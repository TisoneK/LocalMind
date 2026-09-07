"""
Session 344 — Presentation Intelligence.

The user's principle:
  > The model decides the semantic form of the answer.
  > The UI owns its visual implementation.

This module classifies the agent's response content into a PresentationIntent
(TABLE, CHART, DIAGRAM, TEXT, etc.) and generates structured ResponseBlocks
that the frontend renders natively — instead of forcing everything through
Markdown.

Architecture:
                    Answer
                       │
                       ▼
              What is the structure?
                       │
      ┌────────────────┼─────────────────┐
      │                │                 │
      ▼                ▼                 ▼
   Compare           Process          Metrics
      │                │                 │
      ▼                ▼                 ▼
    Table            Flow             Chart

The agent doesn't decide CSS. It decides the semantic presentation type.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class PresentationType(Enum):
    """The semantic presentation type the agent should use."""

    TEXT = "text"  # plain text or markdown
    TABLE = "table"  # structured table
    CODE = "code"  # syntax-highlighted code
    DIAGRAM = "diagram"  # semantic graph (nodes + edges)
    CHART = "chart"  # data series → bar/line/pie
    METRIC = "metric"  # single value + label + tone
    CARD = "card"  # compact info card
    FILE = "file"  # file reference
    TIMELINE = "timeline"  # ordered events
    COMPARISON = "comparison"  # side-by-side comparison
    LIST = "list"  # numbered/bulleted list
    MIXED = "mixed"  # composite (multiple blocks)


class Tone(Enum):
    """Semantic tone — communicates meaning, not decoration."""

    SUCCESS = "success"  # confirmed / passed / completed
    WARNING = "warning"  # partial / needs attention
    ERROR = "error"  # failed / broken
    INFO = "info"  # neutral information
    NEUTRAL = "neutral"  # default
    PRIMARY = "primary"  # key highlight
    ACCENT = "accent"  # secondary highlight


class InfoState(Enum):
    """Information state indicator."""

    CONFIRMED = "confirmed"  # ✓ — data verified from source
    INFERRED = "inferred"  # ~ — agent inference
    NEEDS_VERIFICATION = "needs_verification"  # ? — unverified


@dataclass
class ResponseBlock:
    """A single block of structured response content.

    The agent produces these; the frontend renders them.
    The agent decides WHAT to show; the UI decides HOW it looks.
    """

    type: PresentationType
    # Common fields
    content: Optional[str] = None  # for TEXT, CODE
    title: Optional[str] = None  # for TABLE, CHART, CARD
    tone: Optional[Tone] = None  # semantic color
    info_state: Optional[InfoState] = None  # ✓ / ~ / ?

    # Table fields
    columns: Optional[list[str]] = None
    rows: Optional[list[list[str]]] = None

    # Diagram fields
    diagram_type: Optional[str] = None  # "flow" / "architecture" / "sequence" / "hierarchy" / "state" / "relationship"
    nodes: Optional[list[dict]] = None  # [{"id": "...", "label": "..."}]
    edges: Optional[list[dict]] = None  # [{"from": "...", "to": "...", "label": "..."}]

    # Chart fields
    chart_type: Optional[str] = None  # "bar" / "line" / "pie" / "scatter"
    data: Optional[list[dict]] = None  # [{"label": "...", "value": ...}]

    # Metric fields
    value: Optional[str] = None  # "2228"
    label: Optional[str] = None  # "Tests Passed"

    # File fields
    file_name: Optional[str] = None
    file_path: Optional[str] = None
    file_excerpt: Optional[str] = None

    # List fields
    items: Optional[list[str]] = None

    # Timeline fields
    events: Optional[list[dict]] = None  # [{"timestamp": "...", "label": "...", "description": "..."}]

    # Comparison fields
    left: Optional[dict] = None  # {"title": "...", "items": [...]}
    right: Optional[dict] = None  # {"title": "...", "items": [...]}

    # Card fields
    metadata: Optional[dict] = None

    # Mixed block
    blocks: Optional[list["ResponseBlock"]] = None

    def to_dict(self) -> dict:
        """Serialize for SSE/frontend consumption."""
        d: dict[str, Any] = {"type": self.type.value}
        if self.content is not None:
            d["content"] = self.content
        if self.title is not None:
            d["title"] = self.title
        if self.tone is not None:
            d["tone"] = self.tone.value
        if self.info_state is not None:
            d["info_state"] = self.info_state.value
        if self.columns is not None:
            d["columns"] = self.columns
        if self.rows is not None:
            d["rows"] = self.rows
        if self.diagram_type is not None:
            d["diagram_type"] = self.diagram_type
        if self.nodes is not None:
            d["nodes"] = self.nodes
        if self.edges is not None:
            d["edges"] = self.edges
        if self.chart_type is not None:
            d["chart_type"] = self.chart_type
        if self.data is not None:
            d["data"] = self.data
        if self.value is not None:
            d["value"] = self.value
        if self.label is not None:
            d["label"] = self.label
        if self.file_name is not None:
            d["file_name"] = self.file_name
        if self.file_path is not None:
            d["file_path"] = self.file_path
        if self.file_excerpt is not None:
            d["file_excerpt"] = self.file_excerpt
        if self.items is not None:
            d["items"] = self.items
        if self.events is not None:
            d["events"] = self.events
        if self.left is not None:
            d["left"] = self.left
        if self.right is not None:
            d["right"] = self.right
        if self.metadata is not None:
            d["metadata"] = self.metadata
        if self.blocks is not None:
            d["blocks"] = [b.to_dict() for b in self.blocks]
        return d


# ── Presentation Intent Classification ────────────────────────────────────────


def classify_presentation(
    user_message: str,
    response_text: str = "",
) -> PresentationType:
    """Classify the best presentation type for the response.

    The agent's output decision model:
      What is the structure of the answer?

    - Compare → TABLE
    - Process / steps → DIAGRAM (flow)
    - Architecture → DIAGRAM (architecture)
    - Statistics / metrics → CHART / METRIC
    - Timeline → TIMELINE
    - Data / records → TABLE
    - Code → CODE
    - File reference → FILE
    - Definition / explanation → TEXT
    """
    lower_msg = user_message.lower() if user_message else ""

    # Comparison cues
    if any(w in lower_msg for w in ["compare", "vs", "versus", "difference between", "contrast"]):
        return PresentationType.TABLE

    # Architecture cues
    if any(w in lower_msg for w in ["architecture", "diagram", "show me the"]):
        return PresentationType.DIAGRAM

    # Process / steps cues — "how does X work" / "how to" / "steps" / "process"
    if re.search(r"\bhow\s+(?:does|do|is|are)\b.*\bwork\b", lower_msg):
        return PresentationType.DIAGRAM
    if any(w in lower_msg for w in ["steps", "process", "how to", "workflow", "lifecycle", "pipeline"]):
        return PresentationType.DIAGRAM

    # Statistics / metrics cues
    if any(w in lower_msg for w in ["benchmark", "statistics", "score"]):
        return PresentationType.CHART
    # "results" alone is ambiguous — could be a table or chart. Check if
    # the response contains a markdown table first.
    if "results" in lower_msg and "|" not in response_text:
        return PresentationType.CHART

    # Timeline cues
    if any(w in lower_msg for w in ["timeline", "history", "chronology", "what happened"]):
        return PresentationType.TIMELINE

    # Code cues
    if any(w in lower_msg for w in ["code", "function", "class", "script", "program", "python", "javascript"]):
        # Only if the response actually contains code
        if "```" in response_text or re.search(r"\bdef\s+\w+\s*\(", response_text):
            return PresentationType.CODE

    # List cues
    if any(w in lower_msg for w in ["list", "examples", "ideas", "suggestions", "recommend"]):
        return PresentationType.LIST

    # Check response for table-like content
    if "|" in response_text and response_text.count("|") > 4:
        # Markdown table detected
        return PresentationType.TABLE

    # Default: text
    return PresentationType.TEXT


# ── Block factory helpers ───────────────────────────────────────────────────


def text_block(content: str, info_state: Optional[InfoState] = None) -> ResponseBlock:
    """Create a TextBlock."""
    return ResponseBlock(
        type=PresentationType.TEXT,
        content=content,
        info_state=info_state,
    )


def table_block(
    title: str,
    columns: list[str],
    rows: list[list[str]],
    tone: Optional[Tone] = None,
) -> ResponseBlock:
    """Create a TableBlock."""
    return ResponseBlock(
        type=PresentationType.TABLE,
        title=title,
        columns=columns,
        rows=rows,
        tone=tone,
    )


def metric_block(
    value: str,
    label: str,
    tone: Tone = Tone.NEUTRAL,
) -> ResponseBlock:
    """Create a MetricBlock."""
    return ResponseBlock(
        type=PresentationType.METRIC,
        value=value,
        label=label,
        tone=tone,
    )


def diagram_block(
    diagram_type: str,
    nodes: list[dict],
    edges: list[dict],
    title: Optional[str] = None,
) -> ResponseBlock:
    """Create a DiagramBlock (semantic graph → renderer)."""
    return ResponseBlock(
        type=PresentationType.DIAGRAM,
        diagram_type=diagram_type,
        nodes=nodes,
        edges=edges,
        title=title,
    )


def code_block(content: str, language: Optional[str] = None) -> ResponseBlock:
    """Create a CodeBlock."""
    return ResponseBlock(
        type=PresentationType.CODE,
        content=content,
        metadata={"language": language} if language else None,
    )


def list_block(items: list[str], ordered: bool = False) -> ResponseBlock:
    """Create a ListBlock."""
    return ResponseBlock(
        type=PresentationType.LIST,
        items=items,
        metadata={"ordered": ordered},
    )


def mixed_block(blocks: list[ResponseBlock]) -> ResponseBlock:
    """Create a MixedBlock (composite)."""
    return ResponseBlock(
        type=PresentationType.MIXED,
        blocks=blocks,
    )
