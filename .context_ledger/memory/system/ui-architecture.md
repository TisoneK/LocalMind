# LocalMind UI/UX Architecture — Session 344

**Created:** 2026-08-22
**Goal:** Make the UI the natural expression layer of the agent — not just "prettier screens," but a deliberate backend-to-presentation alignment.

**Core principle:** The model decides the semantic form of the answer. The UI owns its visual implementation.

---

## Phase 1 — Backend/UI Alignment

Every meaningful backend state has a deliberate UI representation.

| Backend capability | User sees it? | When? | Abstraction | Interactive? | Persistent? |
|---|---|---|---|---|---|
| Agent thinking | Collapsible | During processing | "Researching..." / "Analyzing..." | Expandable | No (ephemeral) |
| Tool execution | Action card | During + after | "✓ Found source" / "✓ Retrieved data" | Expandable | No |
| Web search | Activity indicator | During research | "Researching current information" | No | No |
| Browser | Activity indicator | During JS rendering | "Rendering page..." | No | No |
| Memory retrieval | Invisible | Never | (internal) | No | No |
| Memory write | Confirmation | After write | "✓ Remembered: X" | No | No |
| Task creation | Task UI | After plan | Todo list with checkboxes | Yes (mark done) | Yes |
| File analysis | File card | After read | Filename + excerpt | Expandable | No |
| Child agent | Agent workspace | During delegation | Nested run tree | Expandable | No |
| Errors | Recovery card | On failure | Human-readable + "Try again" / "Switch model" | Yes | No |
| Structured output | Native rendering | In response | Table / chart / diagram / code | No | No |

**Presentation Policy:** Not every backend event becomes user-facing UI.
- `memory_op` / `describe_tool` → internal only
- `web_search` / `web_fetch` → "Researching..." activity
- `web_research` → "Researching current information" activity
- `browser` → "Rendering page..." activity
- Memory write → "✓ Remembered" confirmation

---

## Phase 2 — Response Block System

A stable schema for structured response content. The agent produces semantic blocks; the frontend renders them.

### ResponseBlock types

```
ResponseBlock
│
├── TextBlock      — plain text or markdown
├── TableBlock     — structured table with columns + rows
├── CodeBlock      — syntax-highlighted code
├── DiagramBlock   — semantic graph (nodes + edges) → renderer
├── ChartBlock     — data series → chart renderer
├── MetricBlock    — single value + label + tone
├── CardBlock      — compact info card (title + body + metadata)
├── FileBlock      — file reference (name + path + excerpt)
├── ActionBlock    — actionable item (button / link)
├── TimelineBlock  — ordered events with timestamps
├── ComparisonBlock — side-by-side comparison
└── MixedBlock     — composite (multiple blocks in sequence)
```

### Schema (JSON)

```json
{
  "blocks": [
    {
      "type": "text",
      "content": "Here's how the system works."
    },
    {
      "type": "table",
      "title": "Benchmark Results",
      "columns": ["Test", "Result", "Latency"],
      "rows": [
        ["CAT1-1", "PASS", "1.2s"],
        ["CAT1-2", "PASS", "3.3s"]
      ]
    },
    {
      "type": "diagram",
      "diagram_type": "architecture",
      "nodes": [
        {"id": "user", "label": "User"},
        {"id": "parent", "label": "Parent Agent"},
        {"id": "memory", "label": "Memory"}
      ],
      "edges": [
        {"from": "user", "to": "parent"},
        {"from": "parent", "to": "memory"}
      ]
    },
    {
      "type": "metric",
      "value": "2228",
      "label": "Tests Passed",
      "tone": "success"
    }
  ]
}
```

### Semantic tones (colors communicate meaning)

| Tone | Meaning | Visual |
|---|---|---|
| `success` | Confirmed / passed / completed | Green |
| `warning` | Partial / needs attention | Amber |
| `error` | Failed / broken | Red |
| `info` | Neutral information | Blue |
| `neutral` | Default | Gray |
| `primary` | Key highlight | Brand color |
| `accent` | Secondary highlight | Accent color |

### Information state indicators

| State | Visual | Meaning |
|---|---|---|
| ✓ Confirmed | Green checkmark | Data verified from source |
| ~ Inferred | Tilde | Agent inference, not directly sourced |
| ? Needs verification | Question mark | Unverified claim |

---

## Phase 3 — Presentation Intelligence

The agent decides the best presentation format based on the content's nature.

### PresentationIntent classification

| Content pattern | Presentation type | Block type |
|---|---|---|
| Definition | TEXT | TextBlock |
| Steps / process | FLOW | DiagramBlock (flow) |
| Comparison | TABLE | TableBlock / ComparisonBlock |
| Architecture | DIAGRAM | DiagramBlock (architecture) |
| Statistics / metrics | CHART | ChartBlock / MetricBlock |
| Timeline / history | TIMELINE | TimelineBlock |
| Data / records | TABLE | TableBlock |
| Code | CODE | CodeBlock |
| File reference | FILE | FileBlock |
| Single value + label | METRIC | MetricBlock |

### Decision model

```
Answer
   ↓
What is the structure?
   ↓
┌────────┬────────┬────────┐
│ Compare │ Process │ Metrics │
│    ↓      │   ↓      │    ↓    │
│ Table  │ Flow   │ Chart  │
└────────┴────────┴────────┘
```

The agent doesn't decide CSS. It decides the semantic presentation type.

---

## Phase 4 — Visual Language

- Spacing: consistent 4px / 8px / 16px / 24px grid
- Typography: Inter for body, monospace for code, heavier weight for headings
- Surface hierarchy: dark base → elevated card → interactive element
- Semantic colors: success/warning/error/info/neutral/primary/accent
- Status indicators: ✓ / ~ / ? with color coding
- Cards: rounded corners, subtle border, elevated background
- Animations: enter motion (fade + slide), progress indicators (pulsing dots)
- Loading states: skeleton blocks, activity cards, progressive disclosure
- Error states: recovery card with "Try again" / "Switch model" actions

---

## Phase 5 — Agent Workspace UX

- Agent activity: collapsible timeline of actions
- Tasks: live todo list with checkboxes
- Tools: invisible during normal operation, expandable in "Details"
- Memory: invisible, confirmed with subtle "✓ Remembered" toast
- Child agents: nested run tree in Agent Workspace tab
- Artifacts: files / diagrams / tables generated during the turn, attached to the response

---

## Implementation order

1. **Phase 1 + Phase 2 first** — create the backend-to-UI contract and response block system
2. Then Phase 3 (presentation intelligence) — teach the agent to choose the right block type
3. Then Phase 4 (visual language) — implement the rendering components
4. Finally Phase 5 (agent workspace UX) — refine the advanced capabilities

The key is: **don't polish visuals before the contract is stable.**

---

## Theme identity — the palettes are ours (2026-10-26)

The skin adopted in S002 (see the S002 review in `office/reviews/` for provenance)
shipped under a borrowed working title. Per owner direction the identity is
original now; the owner picked the name. Dated historical records keep their
provenance on purpose.

- **`graphite-blue` / "Graphite Blue"** (the default) — flat neutral graphite
  ramp, hairline borders, one blue accent (`#5686fe`). Also the BACKEND default
  (`config.py` SettingsResponse + `_read_appearance`), so a fresh start with no
  settings.json and no localStorage restores Graphite Blue in dark mode.
- **`graphite` / "Graphite Green"** — neutral slate, emerald accent (`#34d399`).
  Id unchanged; label only.
- **Clean break, no compat alias (owner directive):** the retired id is not
  recognised anywhere — frontend `THEME_IDS`, the index.html pre-paint script,
  and the appearance API all reject or ignore it. A choice saved under the
  retired id falls back to the default, which is the same look, so nothing
  visible changes.
- **Latent bug fixed en route:** the backend never accepted the old default id,
  so saving the default palette from Settings always 400'd silently;
  persistence works for every palette now.
- **Verified 2026-10-26 (after the clean break):** frontend vitest green
  (59 files), `tsc -b && vite build` clean, backend `tests/api/test_config_adapter.py`
  green.
- **Owner ruling (2026-10-26/27):** the S002-era published commit messages that
  still carry the borrowed working title stay as-is — no history rewrite, no
  force-push ("not a problem as long as future agents never make that
  mistake"). The enforceable half is recorded in `memory/user/preferences.md`:
  nothing NEW (commits, changelog, ledger text, comments) ever carries the
  retired id again.
