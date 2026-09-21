"""The moves the engine may propose. Slice 1 is READ-ONLY by construction.

A move whose tool is not marked ``read_only`` is never executed by the engine —
it is surfaced as ``needs_confirmation`` (ADR-67: refuse only on a verified fact,
and name the confirming step). The catalog is data, not code: adding a tool is
one entry.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_hint: str
    read_only: bool = True


DEFAULT_CATALOG: dict[str, ToolSpec] = {
    s.name: s
    for s in (
        ToolSpec("dir_explorer", "Look inside a local folder (list/tree/stat). Read-only.",
                 '{"operation": "list|tree|stat", "path": "<folder or file>"}'),
        ToolSpec("file_task", "Read the text contents of one local FILE.", '{"path": "<file>"}'),
        ToolSpec("web_search", "Keyword web search; returns links + snippets.", '{"query": "<keywords>"}'),
        ToolSpec("web_fetch", "Fetch and read one web page.", '{"url": "<https url>"}'),
        ToolSpec("sysinfo", "Machine facts: time, OS, CPU, RAM, disk, network.", '{"query": "<what>"}'),
        ToolSpec("calculate", "Evaluate an arithmetic expression exactly.", '{"expression": "<expr>"}'),
    )
}


def render_catalog(catalog: dict[str, ToolSpec]) -> str:
    return "\n".join(f"- {t.name}: {t.description} args={t.args_hint}" for t in catalog.values())
