"""Session 344 — Presentation Intelligence tests."""
from __future__ import annotations

from core.presentation import (
    PresentationType,
    Tone,
    InfoState,
    ResponseBlock,
    classify_presentation,
    text_block,
    table_block,
    metric_block,
    diagram_block,
    code_block,
    list_block,
    mixed_block,
)


# ── Presentation intent classification ───────────────────────────────────────


class TestPresentationClassification:
    def test_compare_request_returns_table(self):
        p = classify_presentation("Compare TCP and UDP.")
        assert p == PresentationType.TABLE

    def test_vs_returns_table(self):
        p = classify_presentation("RAM vs storage")
        assert p == PresentationType.TABLE

    def test_difference_between_returns_table(self):
        p = classify_presentation("What's the difference between RAM and storage?")
        assert p == PresentationType.TABLE

    def test_architecture_request_returns_diagram(self):
        p = classify_presentation("Show me the LocalMind architecture.")
        assert p == PresentationType.DIAGRAM

    def test_how_does_it_work_returns_diagram(self):
        p = classify_presentation("How does the system work?")
        assert p == PresentationType.DIAGRAM

    def test_steps_request_returns_diagram(self):
        p = classify_presentation("What are the steps to build a plugin?")
        assert p == PresentationType.DIAGRAM

    def test_benchmark_request_returns_chart(self):
        p = classify_presentation("Show the benchmark results.")
        assert p == PresentationType.CHART

    def test_timeline_request_returns_timeline(self):
        p = classify_presentation("Show the timeline of events.")
        assert p == PresentationType.TIMELINE

    def test_code_request_with_code_response_returns_code(self):
        p = classify_presentation("Write Python code for a calculator.", "```python\ndef add(a, b):\n    return a + b\n```")
        assert p == PresentationType.CODE

    def test_list_request_returns_list(self):
        p = classify_presentation("Give me three ideas for a cyber café.")
        assert p == PresentationType.LIST

    def test_markdown_table_in_response_returns_table(self):
        resp = "| Col1 | Col2 |\n|---|---|\n| a | b |"
        p = classify_presentation("show results", resp)
        assert p == PresentationType.TABLE

    def test_plain_explanation_returns_text(self):
        p = classify_presentation("Explain how a car engine works.")
        assert p == PresentationType.TEXT

    def test_definition_returns_text(self):
        p = classify_presentation("What is the capital of Kenya?")
        assert p == PresentationType.TEXT


# ── Block factory helpers ───────────────────────────────────────────────────


class TestBlockFactories:
    def test_text_block(self):
        b = text_block("Hello world")
        assert b.type == PresentationType.TEXT
        assert b.content == "Hello world"

    def test_text_block_with_info_state(self):
        b = text_block("This is confirmed.", InfoState.CONFIRMED)
        assert b.info_state == InfoState.CONFIRMED

    def test_table_block(self):
        b = table_block("Results", ["Test", "Score"], [["CAT1", "PASS"]])
        assert b.type == PresentationType.TABLE
        assert b.title == "Results"
        assert b.columns == ["Test", "Score"]
        assert b.rows == [["CAT1", "PASS"]]

    def test_metric_block(self):
        b = metric_block("2228", "Tests Passed", Tone.SUCCESS)
        assert b.type == PresentationType.METRIC
        assert b.value == "2228"
        assert b.label == "Tests Passed"
        assert b.tone == Tone.SUCCESS

    def test_diagram_block(self):
        nodes = [{"id": "user", "label": "User"}, {"id": "agent", "label": "Agent"}]
        edges = [{"from": "user", "to": "agent"}]
        b = diagram_block("architecture", nodes, edges, title="System Architecture")
        assert b.type == PresentationType.DIAGRAM
        assert b.diagram_type == "architecture"
        assert len(b.nodes) == 2
        assert len(b.edges) == 1
        assert b.title == "System Architecture"

    def test_code_block(self):
        b = code_block("def add(a, b): return a + b", "python")
        assert b.type == PresentationType.CODE
        assert b.content == "def add(a, b): return a + b"
        assert b.metadata == {"language": "python"}

    def test_list_block(self):
        b = list_block(["item1", "item2", "item3"], ordered=True)
        assert b.type == PresentationType.LIST
        assert b.items == ["item1", "item2", "item3"]
        assert b.metadata == {"ordered": True}

    def test_mixed_block(self):
        b1 = text_block("Intro")
        b2 = table_block("Data", ["col"], [["row"]])
        m = mixed_block([b1, b2])
        assert m.type == PresentationType.MIXED
        assert len(m.blocks) == 2


# ── Serialization ────────────────────────────────────────────────────────────


class TestSerialization:
    def test_text_block_to_dict(self):
        b = text_block("Hello")
        d = b.to_dict()
        assert d["type"] == "text"
        assert d["content"] == "Hello"

    def test_table_block_to_dict(self):
        b = table_block("Results", ["A", "B"], [["1", "2"]], Tone.SUCCESS)
        d = b.to_dict()
        assert d["type"] == "table"
        assert d["title"] == "Results"
        assert d["columns"] == ["A", "B"]
        assert d["rows"] == [["1", "2"]]
        assert d["tone"] == "success"

    def test_diagram_block_to_dict(self):
        b = diagram_block(
            "flow",
            [{"id": "a", "label": "Step 1"}],
            [{"from": "a", "to": "b"}],
        )
        d = b.to_dict()
        assert d["type"] == "diagram"
        assert d["diagram_type"] == "flow"
        assert d["nodes"] == [{"id": "a", "label": "Step 1"}]
        assert d["edges"] == [{"from": "a", "to": "b"}]

    def test_mixed_block_to_dict_serializes_nested(self):
        m = mixed_block([text_block("A"), metric_block("100", "count")])
        d = m.to_dict()
        assert d["type"] == "mixed"
        assert len(d["blocks"]) == 2
        assert d["blocks"][0]["type"] == "text"
        assert d["blocks"][1]["type"] == "metric"
