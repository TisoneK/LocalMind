"""User-context perception — collect, fuse, and surface the user's stable context.

The agent answers location/locale-sensitive questions ("what's trending",
local weather, currency, time) from its own assumptions because the machine's
signals are never surfaced in one place: the OS knows the locale, timezone,
region and UI language, but nothing fuses them into a conclusion before the
model plans. The result is the classic failure mode — assume a default region,
hedge across four countries after a correction, or ask for what the machine
already knows.

Three parts live here:

* ``collect_user_signals()`` — best-effort OS reads (stdlib + Windows
  ctypes). Every collector degrades silently; a signal that can't be read is
  simply absent. Deliberately NO network signals (IP/ISP): those are volatile
  and must never become durable defaults.
* ``fuse_user_signals()`` — the DEDUCTION step. Deterministic, no LLM call,
  and trust-tiered: the OS **country setting** (what the user picked when
  setting up the machine) outranks an IANA zone name, which outranks the
  locale *format* tag (defaults to ``en-US`` on English Windows regardless
  of the user's country — verified on a Kenyan machine whose geo setting and
  +03:00 offset both said Kenya while the locale tag said US). A keyboard
  layout is the weakest signal and can only corroborate. The strongest tier
  that yields a country IS the conclusion — lower tiers never override it,
  so the answer is one country, never a candidate list. A contradiction from
  a STRONG tier (country setting vs time zone) is surfaced as a note instead
  of a silent pick; noise-tier contradictions (locale tag) are ignored.
* ``format_user_context()`` — the compact prompt block, with a one-sentence
  deduction contract: commit to converging signals, ask one precise question
  when they genuinely conflict.

The boot hook (server startup) caches the fused conclusion here (same shape
as the system-snapshot cache) so every turn injects it with zero I/O. Only
the STABLE part is collected at all; volatile values are excluded by
construction in the collectors above.
"""

from __future__ import annotations

import logging
import os
import platform
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# The fused user-context CONCLUSION, computed ONCE at boot and held here for
# the hot prompt-assembly path. None until the boot hook sets it. Callers read
# it through ``get_cached_fused`` (the multi-line block for the bootstrap
# prompt) or ``get_cached_fused_inline`` (a one-line summary for the
# per-turn environment context) — both render from the same conclusion.
_CACHED_FUSED: dict | None = None


def set_cached_fused(fused: dict) -> str:
    """Cache the boot-fused conclusion; returns the formatted block (for the
    boot log). Passing an empty dict clears the cache."""
    global _CACHED_FUSED
    _CACHED_FUSED = fused or {}
    return format_user_context(_CACHED_FUSED)


def get_cached_fused_dict() -> dict:
    """The raw fused conclusion (empty dict when unset)."""
    return dict(_CACHED_FUSED or {})


def get_cached_fused() -> str:
    """The boot-fused `User context` block for prompt injection (empty if unset)."""
    return format_user_context(_CACHED_FUSED or {})


def get_cached_fused_inline() -> str:
    """One-line summary for the per-turn environment context (empty if unset)."""
    fused = _CACHED_FUSED or {}
    parts: list[str] = []
    if fused.get("country"):
        iso = fused["country"]
        parts.append(f"{_COUNTRY_NAMES.get(iso, iso)} ({iso})")
    if fused.get("timezone_name"):
        parts.append(str(fused["timezone_name"]))
    if fused.get("language"):
        lang = fused["language"]
        parts.append(_LANGUAGE_NAMES.get(lang, lang))
    return " | ".join(parts)


# ── Windows ctypes plumbing (all best-effort) ────────────────────────────────


def _windows_kernel32():
    if platform.system() != "Windows":
        return None
    try:
        import ctypes

        return ctypes.windll.kernel32
    except Exception:
        return None


def _windows_user32():
    if platform.system() != "Windows":
        return None
    try:
        import ctypes

        return ctypes.windll.user32
    except Exception:
        return None


def _windows_locale_name() -> str | None:
    """BCP-47 user locale, e.g. 'en-KE' (GetUserDefaultLocaleName)."""
    k32 = _windows_kernel32()
    if k32 is None:
        return None
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(85)
        if k32.GetUserDefaultLocaleName(buf, 85):
            return buf.value or None
    except Exception:
        return None
    return None


def _windows_geo_country() -> str | None:
    """ISO-3166 alpha-2 country from the user's OS geo setting
    (GetUserGeoID) — the country the user TOLD the OS, independent of the
    locale format tag."""
    k32 = _windows_kernel32()
    if k32 is None:
        return None
    try:
        import ctypes

        GEOCLASS_NATION = 16  # country classification, per GetGeoInfo docs
        GEO_ISO2 = 4  # request the two-letter ISO name
        geoid = k32.GetUserGeoID(GEOCLASS_NATION)
        if not geoid or geoid == -1:
            return None
        buf = ctypes.create_unicode_buffer(8)
        if k32.GetGeoInfoW(geoid, GEO_ISO2, buf, 8, 0):
            name = (buf.value or "").strip()
            return name.upper() if len(name) == 2 else None
    except Exception:
        return None
    return None


def _windows_ui_language() -> str | None:
    """The UI language as an `en_GB`-style tag (GetUserDefaultUILanguage)."""
    k32 = _windows_kernel32()
    if k32 is None:
        return None
    try:
        import locale

        langid = k32.GetUserDefaultUILanguage()
        return locale.windows_locale.get(langid)
    except Exception:
        return None


def _windows_keyboard_layout() -> str | None:
    """Active keyboard layout's language tag, e.g. 'en_US' (weak signal —
    a bilingual user keeps a layout from another locale for years)."""
    u32 = _windows_user32()
    if u32 is None:
        return None
    try:
        import ctypes
        import locale

        buf = ctypes.create_unicode_buffer(9)
        if u32.GetKeyboardLayoutNameW(buf):
            klid = buf.value or ""
            langid = int(klid[4:], 16) if len(klid) == 8 else 0
            return locale.windows_locale.get(langid)
    except Exception:
        return None
    return None


def _windows_tz_display_name() -> str | None:
    """The Windows time-zone registry key name, e.g. 'E. Africa Standard
    Time' (GetDynamicTimeZoneInformation). Display-only: many countries
    share one Windows zone name, so this never votes for a country."""
    k32 = _windows_kernel32()
    if k32 is None:
        return None
    try:
        import ctypes

        # SYSTEMTIME (unused here, but the struct layout needs its size)
        class _SYSTEMTIME(ctypes.Structure):
            _fields_ = [
                ("wYear", ctypes.c_ushort),
                ("wMonth", ctypes.c_ushort),
                ("wDayOfWeek", ctypes.c_ushort),
                ("wDay", ctypes.c_ushort),
                ("wHour", ctypes.c_ushort),
                ("wMinute", ctypes.c_ushort),
                ("wSecond", ctypes.c_ushort),
                ("wMilliseconds", ctypes.c_ushort),
            ]

        class _DTZI(ctypes.Structure):
            _fields_ = [
                ("Bias", ctypes.c_long),
                ("StandardName", ctypes.c_wchar * 32),
                ("StandardDate", _SYSTEMTIME),
                ("StandardBias", ctypes.c_long),
                ("DaylightName", ctypes.c_wchar * 32),
                ("DaylightDate", _SYSTEMTIME),
                ("DaylightBias", ctypes.c_long),
                ("TimeZoneKeyName", ctypes.c_wchar * 128),
                ("DynamicDaylightTimeDisabled", ctypes.c_bool),
            ]

        info = _DTZI()
        # Returns 0 (unknown) / 1 (standard) / 2 (daylight) — any of them
        # still fills TimeZoneKeyName.
        k32.GetDynamicTimeZoneInformation(ctypes.byref(info))
        name = (info.TimeZoneKeyName or "").strip()
        return name or None
    except Exception:
        return None


def _posix_locale_from_env() -> str | None:
    """LANG/LC_ALL/LC_CTYPE, skipping the C/POSIX default."""
    for var in ("LC_ALL", "LC_CTYPE", "LANG"):
        value = os.environ.get(var, "").strip()
        if value and value.lower() not in ("c", "posix"):
            return value.split(".")[0]  # strip the charset: en_KE.UTF-8 → en_KE
    return None


def _posix_timezone_name() -> str | None:
    """IANA zone name on Linux/macOS (e.g. 'Africa/Nairobi')."""
    try:
        with open("/etc/timezone", encoding="utf-8") as fh:
            name = fh.read().strip()
            if name:
                return name
    except OSError:
        pass
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    try:
        primary = time.tzname[0]
        if primary and primary.upper() not in ("UTC", "GMT"):
            return primary
    except Exception:
        pass
    return None


def _utc_offset() -> str | None:
    """Local UTC offset as '+HHMM', always available where datetime works."""
    try:
        return datetime.now().astimezone().strftime("%z") or None
    except Exception:
        return None


def collect_user_signals() -> dict[str, list[str]]:
    """Gather every user/environment signal the OS exposes. Best-effort and
    never raises; empty/absent keys are dropped. Values are raw — fusion
    (``fuse_user_signals``) interprets them."""
    signals: dict[str, list[str]] = {}

    def add(key: str, *values: str | None) -> None:
        for v in values:
            if v and v not in signals.setdefault(key, []):
                signals[key].append(v)

    on_windows = platform.system() == "Windows"

    # Locale, most-trusted first: the explicit OS locale name, then the
    # environment locale, then the UI language (what the OS UI renders in).
    add("locale", _windows_locale_name(), _posix_locale_from_env(), _windows_ui_language())

    add("region", _windows_geo_country())

    add(
        "timezone",
        None if on_windows else _posix_timezone_name(),
        # Windows names the zone ("E. Africa Standard Time") — kept verbatim
        # for display; it never votes (many countries share one zone name).
        _windows_tz_display_name() if on_windows else None,
    )

    # Primary language tags parsed out of any locale/keyboard tag we saw.
    for raw in signals.get("locale", []):
        if raw and ("-" in raw or "_" in raw):
            add("lang", raw.replace("_", "-").split("-")[0].lower())
    add("lang", *(s for s in signals.get("locale", []) if "-" not in s and "_" not in s and s.isalpha()))

    if (offset := _utc_offset()) and offset != "+0000":
        add("tz_offset", offset)

    add("keyboard", _windows_keyboard_layout())

    return {k: v for k, v in signals.items() if v}


# ── Deterministic fusion — the deduction step ────────────────────────────────

# IANA zone city → ISO country, only where the zone maps to ONE country
# unambiguously. Shared zones simply aren't in the table — an absent mapping
# costs a vote, never a wrong one.
_TZ_COUNTRY: dict[str, str] = {
    "nairobi": "KE", "dar es salaam": "TZ", "kampala": "UG", "addis ababa": "ET",
    "mogadishu": "SO", "djibouti": "DJ", "kigali": "RW", "bujumbura": "BI",
    "lagos": "NG", "accra": "GH", "abidjan": "CI", "dakar": "SN", "casablanca": "MA",
    "algiers": "DZ", "tunis": "TN", "cairo": "EG", "khartoum": "SD", "tripoli": "LY",
    "johannesburg": "ZA", "harare": "ZW", "lusaka": "ZM", "maputo": "MZ",
    "windhoek": "NA", "gaborone": "BW", "monrovia": "LR",
    "london": "GB", "dublin": "IE", "lisbon": "PT", "madrid": "ES", "paris": "FR",
    "brussels": "BE", "amsterdam": "NL", "berlin": "DE", "zurich": "CH", "vienna": "AT",
    "rome": "IT", "stockholm": "SE", "oslo": "NO", "copenhagen": "DK", "helsinki": "FI",
    "warsaw": "PL", "prague": "CZ", "budapest": "HU", "bucharest": "RO", "sofia": "BG",
    "athens": "GR", "moscow": "RU", "kyiv": "UA", "kiev": "UA",
    "dubai": "AE", "riyadh": "SA", "doha": "QA", "kuwait": "KW", "bahrain": "BH",
    "muscat": "OM", "amman": "JO", "beirut": "LB", "baghdad": "IQ", "tehran": "IR",
    "jerusalem": "IL", "karachi": "PK", "kolkata": "IN", "calcutta": "IN",
    "colombo": "LK", "dhaka": "BD", "kathmandu": "NP", "bangkok": "TH",
    "jakarta": "ID", "singapore": "SG", "kuala lumpur": "MY", "manila": "PH",
    "hong kong": "HK", "shanghai": "CN", "taipei": "TW", "seoul": "KR", "tokyo": "JP",
    "sydney": "AU", "melbourne": "AU", "brisbane": "AU", "perth": "AU",
    "auckland": "NZ", "new york": "US", "chicago": "US", "denver": "US",
    "los angeles": "US", "phoenix": "US", "anchorage": "US", "detroit": "US",
    "toronto": "CA", "vancouver": "CA", "halifax": "CA", "edmonton": "CA",
    "winnipeg": "CA", "regina": "CA", "st johns": "CA", "mexico city": "MX",
    "bogota": "CO", "lima": "PE", "santiago": "CL", "sao paulo": "BR",
    "buenos aires": "AR", "caracas": "VE", "guatemala": "GT", "panama": "PA",
    "havana": "CU", "jamaica": "JM", "puerto rico": "PR",
}

_COUNTRY_NAMES: dict[str, str] = {
    "KE": "Kenya", "TZ": "Tanzania", "UG": "Uganda", "ET": "Ethiopia",
    "RW": "Rwanda", "BI": "Burundi", "SO": "Somalia", "DJ": "Djibouti",
    "NG": "Nigeria", "GH": "Ghana", "CI": "Côte d'Ivoire", "SN": "Senegal",
    "MA": "Morocco", "DZ": "Algeria", "TN": "Tunisia", "EG": "Egypt",
    "SD": "Sudan", "LY": "Libya", "ZA": "South Africa", "ZW": "Zimbabwe",
    "ZM": "Zambia", "MZ": "Mozambique", "NA": "Namibia", "BW": "Botswana",
    "LR": "Liberia", "GB": "the United Kingdom", "IE": "Ireland",
    "PT": "Portugal", "ES": "Spain", "FR": "France", "BE": "Belgium",
    "NL": "the Netherlands", "DE": "Germany", "CH": "Switzerland",
    "AT": "Austria", "IT": "Italy", "SE": "Sweden", "NO": "Norway",
    "DK": "Denmark", "FI": "Finland", "PL": "Poland", "CZ": "Czechia",
    "HU": "Hungary", "RO": "Romania", "BG": "Bulgaria", "GR": "Greece",
    "RU": "Russia", "UA": "Ukraine", "AE": "the United Arab Emirates",
    "SA": "Saudi Arabia", "QA": "Qatar", "KW": "Kuwait", "BH": "Bahrain",
    "OM": "Oman", "JO": "Jordan", "LB": "Lebanon", "IQ": "Iraq",
    "IR": "Iran", "IL": "Israel", "PK": "Pakistan", "IN": "India",
    "LK": "Sri Lanka", "BD": "Bangladesh", "NP": "Nepal", "TH": "Thailand",
    "ID": "Indonesia", "SG": "Singapore", "MY": "Malaysia", "PH": "the Philippines",
    "HK": "Hong Kong", "CN": "China", "TW": "Taiwan", "KR": "South Korea",
    "JP": "Japan", "AU": "Australia", "NZ": "New Zealand", "US": "the United States",
    "CA": "Canada", "MX": "Mexico", "CO": "Colombia", "PE": "Peru",
    "CL": "Chile", "BR": "Brazil", "AR": "Argentina", "VE": "Venezuela",
    "GT": "Guatemala", "PA": "Panama", "CU": "Cuba", "JM": "Jamaica",
    "PR": "Puerto Rico",
}

_LANGUAGE_NAMES: dict[str, str] = {
    "en": "English", "sw": "Swahili", "am": "Amharic", "fr": "French",
    "es": "Spanish", "de": "German", "pt": "Portuguese", "it": "Italian",
    "nl": "Dutch", "ar": "Arabic", "zh": "Chinese", "ja": "Japanese",
    "ko": "Korean", "hi": "Hindi", "ru": "Russian", "tr": "Turkish",
    "pl": "Polish", "sv": "Swedish", "da": "Danish", "fi": "Finnish",
    "no": "Norwegian", "nb": "Norwegian", "zu": "Zulu", "xh": "Xhosa",
    "yo": "Yoruba", "ig": "Igbo", "ha": "Hausa", "el": "Greek",
    "cs": "Czech", "ro": "Romanian", "uk": "Ukrainian", "fa": "Persian",
    "he": "Hebrew", "th": "Thai", "id": "Indonesian", "ms": "Malay",
    "vi": "Vietnamese",
}

_GUIDANCE = (
    "Deduce from these facts before acting: when an answer depends on where or "
    "who the user is (trends, news, weather, currency, time, regional "
    "conventions), use the context above directly instead of assuming another "
    "region or hedging across candidates; if the facts here ever conflict with "
    "something the user says, the user wins — ask one precise question, never "
    "list candidate countries."
)


def _parse_region_tag(raw: str) -> str | None:
    """'en_KE' / 'en-KE' → 'KE'; returns None for language-only tags."""
    if not raw:
        return None
    parts = raw.replace("_", "-").split("-")
    if len(parts) >= 2:
        region = parts[-1].upper()
        if len(region) == 2 and region.isalpha():
            return region
    return None


def _parse_language_tag(raw: str) -> str | None:
    if not raw:
        return None
    primary = raw.replace("_", "-").split("-")[0].lower()
    return primary if len(primary) == 2 and primary.isalpha() else None


def _tz_country_votes(timezone_names: list[str]) -> set[str]:
    votes: set[str] = set()
    for name in timezone_names or []:
        if not name or "/" not in name:
            continue  # Windows-style display names never vote (too coarse)
        city = name.split("/")[-1].replace("_", " ").strip().lower()
        if city in _TZ_COUNTRY:
            votes.add(_TZ_COUNTRY[city])
    return votes


def fuse_user_signals(signals: dict[str, list[str]]) -> dict:
    """Fuse raw signals into ONE conclusion. Deterministic, offline, and
    trust-tiered — no LLM call, no candidate lists.

    Tier order (strongest first): the OS country setting, the IANA time-zone
    city, the locale format tag, the keyboard layout. The strongest tier that
    yields a country IS the conclusion; lower tiers can corroborate (raise
    confidence) but never override. Returns ``{"country", "language",
    "timezone_name", "utc_offset", "confidence", "sources"}`` (+ ``"note"``
    on a strong-tier contradiction). ``country`` is an ISO-3166 alpha-2 code
    or None when no tier yields one — an honest unknown, never a guess.
    """
    geo = {r.upper() for r in signals.get("region", []) if r}
    tz_votes = _tz_country_votes(signals.get("timezone", []))
    locale_regions = {r for raw in signals.get("locale", []) if (r := _parse_region_tag(raw))}
    keyboard_regions = {r for raw in signals.get("keyboard", []) if (r := _parse_region_tag(raw))}

    country: str | None = None
    confidence = "none"
    sources: list[str] = []
    note: str | None = None

    if geo:
        # The user's own OS country setting — authoritative by definition.
        country = sorted(geo)[0]
        sources = ["region"]
        confidence = "high"
        if tz_votes & geo:
            sources.append("timezone")
        elif locale_regions & geo:
            sources.append("locale")
        elif keyboard_regions & geo:
            sources.append("keyboard")
        # A strong-tier contradiction is surfaced, never silently resolved;
        # a disagreeing locale FORMAT tag is known noise (en-US default on
        # English Windows regardless of country) and is ignored.
        if tz_votes and not (tz_votes & geo):
            note = (
                "the OS country setting and the time zone disagree — treat the "
                "country setting as authoritative; do not hedge, ask only if a "
                "request truly depends on it"
            )
    elif tz_votes:
        country = sorted(tz_votes)[0]
        sources = ["timezone"]
        if locale_regions & tz_votes:
            sources.append("locale")
        confidence = "high"
    elif locale_regions:
        country = sorted(locale_regions)[0]
        sources = ["locale"]
        if keyboard_regions & locale_regions:
            sources.append("keyboard")
        confidence = "high" if len(sources) >= 2 else "medium"
    elif keyboard_regions:
        country = sorted(keyboard_regions)[0]
        sources = ["keyboard"]
        confidence = "low"

    language = next(iter(signals.get("lang", [])), None)
    timezone_name = next(iter(signals.get("timezone", [])), None)
    utc_offset = next(iter(signals.get("tz_offset", [])), None)

    fused: dict = {
        "country": country,
        "language": language,
        "timezone_name": timezone_name,
        "utc_offset": utc_offset,
        "confidence": confidence,
        "sources": sources,
    }
    if note:
        fused["note"] = note
    return fused


def format_user_context(fused: dict) -> str:
    """Render the fused conclusion as the prompt block. Empty when nothing
    usable was deduced — a block that says nothing must not exist."""
    lines: list[str] = []
    if fused.get("country"):
        iso = fused["country"]
        name = _COUNTRY_NAMES.get(iso, iso)
        lines.append(f"- Location: {name} ({iso})")
    if fused.get("timezone_name") or fused.get("utc_offset"):
        offset = fused.get("utc_offset")
        pretty = f"UTC{offset[:3]}:{offset[3:]}" if offset and len(offset) == 5 else ""
        tz = fused.get("timezone_name") or pretty or "unknown"
        lines.append(f"- Time zone: {tz}{' — ' + pretty if pretty and tz != pretty else ''}")
    if fused.get("language"):
        lang = fused["language"]
        lines.append(f"- Language: {_LANGUAGE_NAMES.get(lang, lang)} ({lang})")
    if fused.get("note"):
        lines.append(f"- Note: {fused['note']}")
    if not lines:
        return ""
    return "\n\n## User context (deduced from this machine's settings)\n" + "\n".join(lines) + "\n" + _GUIDANCE
