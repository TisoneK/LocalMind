# Worklog: Empty Agent Fix — P1–P8 + Router Fix

**Date:** 2025-01 (initial), 2026-05 (router fix update)
**Author:** AI-assisted development
**Status:** P1–P8 complete; router fix v0.4 complete

---

## Problem Statement

LocalMind suffered from the **"Empty Agent" problem**: the infrastructure was solid (Ollama integration, tool dispatch, streaming, Electron shell) but the agent itself felt hollow — no personality, no memory awareness, no depth. Users got generic, mechanical responses indistinguishable from a raw API call.

## Root Causes Identified

1. **Anemic base prompt** — 53-line `base.md` that read like a product spec, not a personality
2. **No memory weaving** — memory facts injected as raw data ("Based on my memory...") instead of being woven into behavior
3. **Single tool dispatch** — adapter dropped parallel tool calls, keeping only the first
4. **No domain expertise** — agent used the same generic prompt for coding, research, and shell tasks
5. **FILE_EDIT missing from skill map** — file edits mapped to no skill file
6. **Intent router blindspots** — natural browsing phrasing ("show me projects in Documents") fell through to CHAT, causing hallucination
7. **CHAT confidence too high** — catch-all CHAT fallback claimed 0.85 confidence, blocking LLM re-evaluation
8. **Dead metrics for agent intents** — `start_request()`/`record_streaming_complete()` only called in CHAT path

## P1: Base Prompt Rewrite

**File:** `core/prompts/base.md`

Expanded from 53 to ~90 lines. Key changes:
- **Identity section**: "thoughtful, capable assistant that lives on the user's hardware" — not a cold API, not pretending to be human
- **Memory framing**: "you treat remembered facts as things you simply know about this person, the way a good colleague would"
- **Ambiguity handling**: New section — state interpretation and proceed, don't ask questions you can answer yourself
- **Mistake recovery**: New section — read error messages before retrying, try different approaches
- **Proactive behavior**: New section — one heads-up per task, not a code review nobody asked for
- **6th value**: "Useful over impressive" — a working one-liner beats a beautifully architected solution that doesn't ship

## P2: Confirmation Gate (Pre-existing)

**File:** `core/agent/constants.py`, `core/agent/loop.py`

Already implemented — destructive operations require `requires_confirmation` flag. No changes needed.

## P3: Memory Weaving

**File:** `core/agent/prompts.py`

Refactored memory injection from "data you're referencing" to "knowledge you have":
- CHAT intent: "What you know about this user" — facts are things you already know, not data you're referencing
- Agent intents: "What you know about this user" — use them to avoid asking for info you already have
- Removed all "Based on my memory..." / "I recall that..." framing — just use the information naturally

## P4: Flywheel Accuracy (Pre-existing)

**File:** `core/flywheel.py`

Already implemented — accuracy tracking per intent, wired into router confidence penalties. No changes needed.

## P5: Multi-Tool Call Support

**File:** `adapters/ollama.py`

Added `MultiToolCallResult` dataclass:
```python
@dataclass
class MultiToolCallResult:
    calls: list[ToolCallResult]
    raw_content: str = ""
    
    @property
    def first(self) -> ToolCallResult:
        """Backward compat — get first tool call."""
        return self.calls[0] if self.calls else ToolCallResult(...)
    
    @property
    def is_parallel(self) -> bool:
        return len(self.calls) > 1
```

**File:** `core/agent/loop.py`

Added parallel dispatch:
```python
if isinstance(result, MultiToolCallResult):
    valid_calls = [tc for tc in result.tool_calls if self._validate_tool_call(tc)]
    if len(valid_calls) > 1:
        tasks = [self._dispatch_single_tool(tc, ...) for tc in valid_calls]
        results = await asyncio.gather(*tasks)
```

Backward compatibility maintained via `MultiToolCallResult.first`.

## P6: Skill Injection + FILE_EDIT Fix

**File:** `core/agent/prompts.py`

Added skill file injection into both planning and execution prompts:
```python
skill_fragment = _load_fragment(_intent_fragment_name(intent))
if skill_fragment:
    skill_section = f"\n## Intent-specific expertise\n{skill_fragment}\n"
```

Planner gets condensed 500-char summary; execution agent gets full skill file.

**File:** `core/context_builder.py`

Added `FILE_EDIT → "debugging"` to the skill map.

## P7: Planner-Execute Split (Pre-existing)

**File:** `core/agent/prompts.py`

Already implemented — `build_planning_prompt()` for plan phase, `build_agent_system_prompt()` for execution phase. No changes needed.

## P8: Sub-Agent Stubs (Pre-existing)

**File:** `core/agent/sub_agent.py`

Already implemented — sub-agent framework stubs. No changes needed.

---

## Router Fix v0.4 (2026-05)

### Problem Discovered

User query "Show me coding projects in Documents/Code" was misclassified as **Code Generation** with 92% confidence. The agent then tried to write code instead of listing files.

### Root Cause Chain

1. **Rule engine blindspot** — SHELL patterns required literal "files/folder/directory" after "show/list". "Show me coding projects" didn't match any pattern → fell through to CHAT
2. **CHAT confidence too high** — CHAT as catch-all got 0.85 confidence, hitting the GREEN threshold (0.75), preventing the LLM from ever re-evaluating
3. **LLM classifier blindspot** — When the LLM did fire (in some code paths), "coding" was a strong CODE_EXEC signal, overriding the actual intent (browsing)
4. **P9 persona amplification** — Wrong intent → wrong persona → wrong behavior cascade

### Fixes Applied

**File:** `core/intent_router.py`
- Added 4 new SHELL patterns for natural browsing phrasing:
  - `"show me projects/repos/items/contents/stuff/code/work/apps"`
  - `"what's in Documents" / "what is on my desktop"`
  - `"open documents/desktop/downloads/home"`
  - `"where is/are/can I find"`
- Added 2 new FILE_TASK patterns for location-aware browsing:
  - `"show me projects in Documents"` (with path context)
  - `"what's in Documents/Desktop/Downloads"`

**File:** `core/intent_classifier.py`
- **CHAT confidence lowered from 0.85 → 0.50** — CHAT is the catch-all fallback, not a confident classification. At 0.50, the router enters AMBER zone and the LLM classifier gets a chance to correct it
- **Classifier system prompt expanded** — added SHELL, FILE_EDIT, SYSINFO intents with explicit browsing/listing guidance and "CRITICAL DISTINCTIONS" section

**File:** `core/intent_router_v2.py`
- **CODE_EXEC confidence guard** — When the LLM returns CODE_EXEC but the message lacks any code-generation verb (write, run, execute, compute, calculate, test, debug, build, generate, implement) AND the rule engine matched SHELL or FILE_TASK, downgrade LLM confidence to 0.50 so the rule engine wins

**File:** `core/semantic_classifier.py`
- Added 20 browsing/listing example sentences to the SHELL semantic cluster ("show me projects in documents", "what's in my documents folder", "browse files", etc.)

**File:** `core/engine.py`
- **Agent-loop metrics fix** — Added `self._metrics.start_request()` before the agent loop entry and `self._metrics.record_streaming_complete()` after response assembly for agent-mode intents. Previously, only the CHAT and FILE_TASK paths tracked streaming metrics, leaving the status bar showing 0 tok/s and 0ms for SHELL, CODE_EXEC, etc.

### Expected Behavior Change

| Query | Before | After |
|-------|--------|-------|
| "Show me coding projects in Documents" | CHAT → hallucinated listing | SHELL → actual `dir`/`ls` command |
| "What's in my Downloads" | CHAT → guessed contents | SHELL → actual directory listing |
| "Browse my desktop" | CHAT → no action | SHELL → actual directory browse |
| "Where is my config file" | CHAT → no action | FILE_TASK → actual file search |
| "List repos in home folder" | CHAT → no action | SHELL → actual directory listing |

---

## Files Modified (All Changes)

| File | P-Level | Change |
|------|---------|--------|
| `core/prompts/base.md` | P1 | Rewritten 53→90 lines |
| `core/prompts/chat.md` | P1 | Tone consistency |
| `core/agent/prompts.py` | P3, P6, P9 | Memory weaving + skill injection + persona map |
| `core/context_builder.py` | P6 | FILE_EDIT → "debugging" skill map |
| `adapters/ollama.py` | P5 | MultiToolCallResult dataclass |
| `core/agent/loop.py` | P5 | Parallel dispatch via asyncio.gather() |
| `core/intent_router.py` | Fix | Broadened SHELL/FILE_TASK patterns |
| `core/intent_classifier.py` | Fix | CHAT confidence 0.85→0.50 + expanded system prompt |
| `core/intent_router_v2.py` | Fix | CODE_EXEC confidence guard |
| `core/semantic_classifier.py` | Fix | Added browsing/listing examples to SHELL |
| `core/engine.py` | Fix | Agent-loop metrics tracking |

## Not Yet Implemented

- **P9**: Expert agents (full implementation — persona map is in place but skill routing is basic)
- **P10**: Reflection/self-evaluation loop
- **P11**: Cross-session memory persistence and recall
- **P12**: Sub-agent framework (delegation and orchestration)
- **Functional testing** of all P1–P8 + router fix changes
