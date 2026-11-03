# ruff: noqa: E501 — prompt templates are intentionally long lines.
"""The response-formatting contract — ONE text, every answer surface.

The owner's 2026-11-03 report ("the UI does not format the output in
style eg tables etc its just text") traced to a structural gap: only the
scoped execution-agent registry carried a formatting section, while the
two surfaces that answer ordinary turns — the parent warm-kernel
(the native bootstrap that answers most task turns directly) and the
chat surface — carried none. The model was never asked for markdown on
the turns real users ask for tables, so the (working) frontend renderer
had nothing to render.

This module is the single home of that contract text. All three surface
registries register it byte-identically at the shared
``response_formatting`` slot (405 — AFTER the tool index so the SOCIAL
relevance cut, which drops a contiguous suffix of tool-choosing
guidance, can never drop it from a conversational turn; BEFORE the
style examples so the suffix property holds). The GFM line is the
renderer contract: the frontend renders standard GFM (react-markdown +
remark-gfm), so tables must be standard GFM pipe tables — ASCII ``|``,
a delimiter row — never full-width punctuation lookalikes.
"""

RESPONSE_FORMATTING_TEXT = (
    "RESPONSE FORMATTING:\n"
    "- **Lead with the answer,** then stop — don't bury it. Be concise: one sentence if it answers, never a wall of text.\n"
    "- **Structure it:** tables for data (weather, file lists, comparisons), bullets for steps, bold for key numbers, code blocks for code/commands/paths.\n"
    "- **Tables are standard GFM pipe tables:** ASCII `|` delimiters, a header row, then a `| --- | --- |` delimiter row — never full-width lookalikes (｜ －), never space-aligned pseudo-tables — so any markdown renderer parses them.\n"
    '- **No source citations** — synthesize into a clean, actionable answer ("Yes, bring an umbrella" beats "35% probability of precipitation").\n'
    "- **Match length to the question:** one line + small table for a simple ask; a structured explanation for a deep one."
)
