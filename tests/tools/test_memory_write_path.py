"""What the memory write path must refuse, must not duplicate, and must verify.

Three live failures drove this file:
- a live value (the machine's public IP / ISP) stored as a durable default;
- the same fact stored several times over, because a write that cannot embed
  appended a new row per statement instead of updating the fact's one row;
- "Done — I've cleaned up your memory entry" reported while the row was still
  there, because the confirmation described the intent, not the store.

So the gates under test are: durability policy at the door (volatile values are
never persisted), one row per fact whatever the wording, and every mutation
confirmation built from a read-back of the state it left behind.
"""
from __future__ import annotations

import hashlib
from unittest.mock import patch

import pytest

from core.memory_intent import MemoryDurability, canonical_key, durability_profile
from tools.memory_tool import memory_op

# ── Durability policy ────────────────────────────────────────────────────────


class TestDurabilityPolicy:
    def test_ipv4_value_is_volatile(self):
        assert durability_profile("my public IP is 41.90.11.7").kind is MemoryDurability.VOLATILE

    def test_network_provider_is_volatile(self):
        d = durability_profile("my ISP is Safaricom broadband")
        assert d.kind is MemoryDurability.VOLATILE
        assert "reconnect" in d.reason

    def test_live_machine_reading_is_volatile(self):
        assert durability_profile("battery level is 84%").kind is MemoryDurability.VOLATILE
        assert durability_profile("free RAM is 3 GB").kind is MemoryDurability.VOLATILE

    def test_momentary_wording_is_volatile(self):
        assert durability_profile("using the shell right now").kind is MemoryDurability.VOLATILE

    def test_url_with_private_ip_is_durable_not_network_identity(self):
        # A remembered endpoint is source knowledge; only the IP *as a value*
        # is volatile. The URL strip is what keeps these apart.
        d = durability_profile("my API endpoint is https://192.168.1.10/v1")
        assert d.kind is MemoryDurability.STABLE_FACT

    def test_preference_wins_over_momentary_wording(self):
        d = durability_profile("I prefer concise answers right now")
        assert d.kind is MemoryDurability.PREFERENCE
        assert d.freshness == "static"

    def test_environment_fact_is_refreshable(self):
        d = durability_profile("I live in Nairobi")
        assert d.kind is MemoryDurability.STABLE_FACT
        assert d.freshness == "boot"
        assert 0.0 < d.confidence < 1.0

    def test_plain_statement_is_a_durable_fact(self):
        d = durability_profile("my project is called Falcon")
        assert d.kind is MemoryDurability.STABLE_FACT
        assert d.freshness == "static"

    def test_verdict_is_deterministic(self):
        text = "my timezone is Africa/Nairobi"
        assert durability_profile(text) == durability_profile(text)


class TestCanonicalKey:
    def test_restated_location_shares_one_identity(self):
        assert canonical_key("I live in Nairobi") == canonical_key("I am based in Nairobi, Kenya")

    def test_timezone_and_name_have_their_own_identities(self):
        keys = {
            canonical_key("my timezone is Africa/Nairobi"),
            canonical_key("call me Tisone"),
            canonical_key("I live in Nairobi"),
        }
        assert len(keys) == 3

    def test_unrelated_facts_do_not_collapse(self):
        # Collapsing two different preferences into one row would lose data, so
        # the fallback identity keeps only the leading content words.
        assert canonical_key("I prefer dark mode") != canonical_key("I prefer concise answers")

    def test_key_is_stable_and_repeatable(self):
        assert canonical_key("Source: https://wttr.in/x") == canonical_key("Source: https://wttr.in/x")


# ── Tool behavior against a recording store ──────────────────────────────────


class _FakeStore:
    """Stands in for VectorStore, recording the mutations the tool performed."""

    def __init__(self, facts=None, *, store_ok=True, read_back=True):
        self.facts = [dict(f) for f in (facts or [])]
        self.store_ok = store_ok
        self.read_back = read_back
        self.store_calls: list[dict] = []
        self.forgotten: list[str] = []

    # read side
    async def list_all_with_metadata(self):
        return [dict(f) for f in self.facts]

    async def count(self):
        return len(self.facts)

    def matching_ids(self, target):
        from storage.vector import _content_signature

        norm = _content_signature(target)
        if not norm:
            return []
        return [
            f["id"]
            for f in self.facts
            if _content_signature(f["fact"]) == norm
            or (len(norm) >= 12 and _content_signature(f["fact"]).startswith(norm))
        ]

    async def get_fact(self, fact_id):
        for f in self.facts:
            if f["id"].startswith(fact_id):
                return dict(f)
        return None

    # write side
    async def forget_by_id(self, fact_id):
        for f in self.facts:
            if f["id"].startswith(fact_id):
                self.facts.remove(f)
                self.forgotten.append(f["id"])
                return True
        return False

    async def find_by_key(self, key):
        if not self.read_back:
            return None
        for f in self.facts:
            if f.get("memory_key") == key:
                return dict(f)
        return None

    async def store(self, fact, session_id, source="user", extra_metadata=None, key=None):
        self.store_calls.append(
            {
                "fact": fact,
                "session_id": session_id,
                "source": source,
                "metadata": dict(extra_metadata or {}),
                "key": key,
            }
        )
        if not self.store_ok:
            return False
        fact_id = "key" + hashlib.sha256(str(key).encode()).hexdigest()[:13]
        self.facts = [f for f in self.facts if f["id"] != fact_id]
        self.facts.append({"id": fact_id, "fact": fact, **(extra_metadata or {})})
        return True

    def fact_id_for_key(self, key):
        return "key" + hashlib.sha256(str(key).encode()).hexdigest()[:13]


def _with_store(fake):
    return patch("storage.vector.VectorStore", return_value=fake), fake


class TestVolatileRefusal:
    @pytest.mark.asyncio
    async def test_public_ip_is_not_persisted(self):
        fake = _FakeStore()
        patcher, _ = _with_store(fake)
        with patcher:
            result = await memory_op("remember my public IP is 41.90.11.7")
        assert fake.store_calls == []
        assert result.success is True
        assert result.metadata.get("declined_reason") == "volatile_fact"
        assert "rather not keep" in result.content
    @pytest.mark.asyncio
    async def test_isp_is_not_persisted(self):
        fake = _FakeStore()
        patcher, _ = _with_store(fake)
        with patcher:
            result = await memory_op("remember that my ISP is Safaricom")
        assert fake.store_calls == []
        assert "volatile_fact" == result.metadata.get("declined_reason")

    @pytest.mark.asyncio
    async def test_durable_part_of_the_statement_is_still_written(self):
        fake = _FakeStore()
        patcher, _ = _with_store(fake)
        with patcher:
            await memory_op("remember I live in Nairobi")
        assert len(fake.store_calls) == 1
        assert fake.store_calls[0]["metadata"]["memory_freshness"] == "boot"


class TestStorePath:
    @pytest.mark.asyncio
    async def test_confirmation_reports_verified_state(self):
        fake = _FakeStore()
        patcher, _ = _with_store(fake)
        with patcher:
            result = await memory_op("remember that I prefer dark mode")
        assert result.content == "Remembered: *I prefer dark mode*"
        assert result.metadata["verified"] is True
        assert result.metadata["stored"] is True
        assert result.metadata["fact_id"]
        assert result.metadata["memory_kind"] == "preference"

    @pytest.mark.asyncio
    async def test_write_is_keyed_and_typed(self):
        fake = _FakeStore()
        patcher, _ = _with_store(fake)
        with patcher:
            await memory_op("remember I live in Nairobi")
        call = fake.store_calls[0]
        assert call["key"] == "subject:location"
        assert call["metadata"]["memory_kind"] == "stable_fact"
        assert call["metadata"]["memory_confidence"]

    @pytest.mark.asyncio
    async def test_write_that_does_not_read_back_is_not_claimed(self):
        fake = _FakeStore(read_back=False)
        patcher, _ = _with_store(fake)
        with patcher:
            result = await memory_op("remember that my project is Falcon")
        assert result.success is False
        assert result.metadata["stored"] is False
        assert "read memory back" in result.content
        assert "Remembered:" not in result.content

    @pytest.mark.asyncio
    async def test_refused_write_is_not_reported_as_success(self):
        # Both the vector path and the plain-text fallback refuse the write.
        fake = _FakeStore(store_ok=False)
        patcher, _ = _with_store(fake)
        with patcher, patch("sqlite3.connect", side_effect=OSError("no store")):
            result = await memory_op("remember that my project is Falcon")
        assert result.success is False
        assert result.metadata["stored"] is False
        assert "Remembered:" not in result.content
        assert "didn't reach memory" in result.content


class TestForgetPath:
    @pytest.mark.asyncio
    async def test_all_matching_facts_are_removed_and_counted(self):
        fake = _FakeStore(
            [
                {"id": "aaaaaaaaaaaaaaa1", "fact": "I prefer dark mode"},
                # Same fact, differently punctuated — still one thing to remove.
                {"id": "aaaaaaaaaaaaaaa2", "fact": "i prefer dark mode."},
                {"id": "bbbbbbbbbbbbbbb1", "fact": "I prefer Python"},
            ]
        )
        patcher, _ = _with_store(fake)
        with patcher:
            result = await memory_op("forget that I prefer dark mode")
        assert len(fake.forgotten) == 2
        assert result.metadata["removed"] == 2
        assert "(2 matching facts)" in result.content
        assert len(fake.facts) == 1

    @pytest.mark.asyncio
    async def test_fact_can_be_addressed_by_its_listed_id(self):
        fake = _FakeStore(
            [
                {"id": "3f2a91cd00000001", "fact": "I prefer dark mode"},
                {"id": "9e1b77aa00000002", "fact": "I prefer Python"},
            ]
        )
        patcher, _ = _with_store(fake)
        with patcher:
            result = await memory_op("forget #3f2a91cd")
        assert fake.forgotten == ["3f2a91cd00000001"]
        assert result.metadata["removed"] == 1
        assert "Removed from memory" in result.content

    @pytest.mark.asyncio
    async def test_full_id_without_the_hash_marker_resolves(self):
        fake = _FakeStore([{"id": "3f2a91cd00000001", "fact": "I prefer dark mode"}])
        patcher, _ = _with_store(fake)
        with patcher:
            result = await memory_op("forget 3f2a91cd00000001")
        assert fake.forgotten == ["3f2a91cd00000001"]
        assert result.metadata["removed"] == 1

    @pytest.mark.asyncio
    async def test_miss_is_reported_as_a_miss(self):
        fake = _FakeStore([{"id": "c" * 16, "fact": "I prefer Python"}])
        patcher, _ = _with_store(fake)
        with patcher:
            result = await memory_op("forget my favourite colour")
        assert result.metadata["removed"] == 0
        assert "Removed from memory" not in result.content
        assert "Nothing in memory matches" in result.content

    @pytest.mark.asyncio
    async def test_removal_that_does_not_take_is_not_claimed(self):
        class _StubbornStore(_FakeStore):
            async def forget_by_id(self, fact_id):
                return False

        fake = _StubbornStore([{"id": "d" * 16, "fact": "I prefer dark mode"}])
        patcher, _ = _with_store(fake)
        with patcher:
            result = await memory_op("forget that I prefer dark mode")
        assert result.success is False
        assert result.metadata["removed"] == 0
        assert "still in memory" in result.content


class TestBareOperationWord:
    """The schema advertises an operation enum, so the dispatcher hands the tool
    the operation word alone ("list", no content). Observed live: the model
    called memory_op with operation=list, "list" missed the listing pattern,
    and the store path persisted the word "list" as a fact — a junk memory and
    a garbled listing in one call."""

    _FACT = {
        "id": "3f2a91cd11223344",
        "fact": "I prefer dark mode",
        "memory_type": "user_preference",
        "importance": "0.8",
    }

    @pytest.mark.asyncio
    async def test_bare_list_lists_and_never_stores(self):
        fake = _FakeStore([self._FACT])
        patcher, _ = _with_store(fake)
        with patcher:
            result = await memory_op("list")
        assert fake.store_calls == []
        assert "#3f2a91cd" in result.content
        assert result.metadata["fact_count"] == 1

    @pytest.mark.asyncio
    async def test_bare_list_with_a_colon_lists(self):
        fake = _FakeStore([self._FACT])
        patcher, _ = _with_store(fake)
        with patcher:
            result = await memory_op("list:")
        assert fake.store_calls == []
        assert "Stored memory" in result.content

    @pytest.mark.asyncio
    async def test_bare_list_on_empty_store_says_so(self):
        fake = _FakeStore()
        patcher, _ = _with_store(fake)
        with patcher:
            result = await memory_op("list")
        assert fake.store_calls == []
        assert "No facts stored" in result.content

    @pytest.mark.asyncio
    async def test_bare_recall_does_not_store(self):
        fake = _FakeStore([self._FACT])
        patcher, _ = _with_store(fake)
        with patcher:
            result = await memory_op("recall")
        assert fake.store_calls == []
        assert "dark mode" in result.content

    @pytest.mark.asyncio
    async def test_bare_forget_asks_which_fact(self):
        fake = _FakeStore([self._FACT])
        patcher, _ = _with_store(fake)
        with patcher:
            result = await memory_op("forget")
        assert fake.store_calls == []
        assert fake.forgotten == []
        assert "Which fact" in result.content

    @pytest.mark.asyncio
    async def test_bare_store_asks_for_the_fact(self):
        fake = _FakeStore()
        patcher, _ = _with_store(fake)
        with patcher:
            result = await memory_op("store")
        assert fake.store_calls == []
        assert "What should I remember" in result.content

    @pytest.mark.asyncio
    async def test_a_sentence_starting_with_list_is_not_a_memory_listing(self):
        fake = _FakeStore([self._FACT])
        patcher, _ = _with_store(fake)
        with patcher:
            result = await memory_op("list my project files")
        assert "Stored memory" not in result.content


class TestListPath:
    @pytest.mark.asyncio
    async def test_list_exposes_short_ids(self):
        fake = _FakeStore(
            [
                {
                    "id": "3f2a91cd11223344",
                    "fact": "I prefer dark mode",
                    "memory_type": "user_preference",
                    "importance": "0.8",
                }
            ]
        )
        patcher, _ = _with_store(fake)
        with patcher:
            result = await memory_op("what do you know about me")
        assert "#3f2a91cd" in result.content
        assert result.metadata["fact_ids"] == ["3f2a91cd11223344"]
