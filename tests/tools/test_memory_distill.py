"""Memory_op must not persist a raw paste as a single "fact".

Root cause (live session syn-0): "Remember this source" + a pasted 6KB weather
JSON dump stored the ENTIRE blob verbatim as one memory. `_distill_fact` now
reduces a store request to a concise durable fact — pulling the URL out of a
paste ("remember THIS source"), or declining a wall of text and asking for the
specific fact — so junk memories are never created.
"""

from __future__ import annotations

from tools.memory_tool import _distill_fact, _looks_like_dump

_WEATHER_BLOB = (
    "Source: https://wttr.in/Kitengela?format=j1\n\n"
    '{\n "current_condition": [ { "FeelsLikeC": "15", "temp_C": "17", '
    '"humidity": "70", "weatherDesc": [ { "value": "Overcast" } ] } ], '
    '"nearest_area": [ { "areaName": [ { "value": "x" } ] } ] }'
)


class TestLooksLikeDump:
    def test_json_object_is_a_dump(self):
        assert _looks_like_dump('{"a": 1, "b": 2, "c": 3}') is True

    def test_long_text_is_a_dump(self):
        assert _looks_like_dump("word " * 200) is True

    def test_short_prose_is_not_a_dump(self):
        assert _looks_like_dump("I prefer Python and dark mode") is False


class TestDistillFact:
    def test_extracts_url_from_pasted_source_blob(self):
        # The exact reported scenario: keep the source URL, not the 6KB blob.
        fact, note = _distill_fact("Remember this source", _WEATHER_BLOB)
        assert fact == "Source: https://wttr.in/Kitengela?format=j1"
        assert note and "source" in note.lower()

    def test_short_clean_fact_is_stored_as_is(self):
        fact, note = _distill_fact("remember", "I prefer Python")
        assert fact == "I prefer Python"
        assert note is None

    def test_short_fact_with_url_is_untouched(self):
        fact, note = _distill_fact("remember my endpoint", "my API endpoint is https://api.x.io/v1")
        assert fact == "my API endpoint is https://api.x.io/v1"
        assert note is None

    def test_large_blob_without_url_is_declined(self):
        fact, note = _distill_fact("remember this", "garbage " * 200)
        assert fact is None
        assert note and "specific fact" in note.lower()

    def test_multiple_urls_are_deduped_and_labeled(self):
        blob = "x " * 300 + " see https://a.io/x and https://a.io/x and https://b.io/y"
        fact, note = _distill_fact("save these", blob)
        assert fact is not None
        assert fact.startswith("URLs:")
        assert "https://a.io/x" in fact and "https://b.io/y" in fact
        # de-duped: a.io/x appears once
        assert fact.count("https://a.io/x") == 1
