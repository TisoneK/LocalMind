# ruff: noqa: E501 — prompt templates are intentionally long lines.
"""The planning-phase prompt (build_planning_prompt).

A SEPARATE planning LLM call (no tools) that runs before the main
agent loop: understand what the user wants, determine which tools are
needed and in what order, pre-fill the required arguments. The output
is injected into the execution-phase prompt (the turn band's
execution_plan section) so the model knows exactly what to do.
"""

from __future__ import annotations

from typing import Optional

from core.agent.tool_schemas import render_tool_list
from core.models import Intent


def build_planning_prompt(
    intent: Intent,
    user_message: str,
    available_tools: list[dict],
    env_context: str,
    intent_history: Optional[list[str]] = None,
    tool_defs: Optional[list[dict]] = None,
) -> str:
    """
    Return the planning-phase system prompt.

    This prompt is used for a SEPARATE planning LLM call (no tools)
    that runs before the main agent loop. The model is asked to:
    1. Understand what the user wants
    2. Determine which tools are needed and in what order
    3. Pre-fill the required arguments for each step

    The planning output is then injected into the execution-phase
    system prompt so the model knows exactly what to do.
    """
    from core.agent.constants import AGENT_ALLOWED_TOOLS

    # When the scoped tool DEFS are provided, the in-prompt tool list
    # is rendered from the SAME source as the native `tools` param (one source
    # of truth). Fall back to the metadata list for backward-compat callers.
    if tool_defs is not None:
        agent_tool_list = "\n".join(render_tool_list(tool_defs))
    else:
        agent_tool_list = "\n".join(
            f"  - {t['intent']}: {t['description']}"
            for t in available_tools
            if t["intent"] in AGENT_ALLOWED_TOOLS
        )

    intent_ctx = ""
    if intent_history:
        intent_ctx = (
            f"\nRecent intent history (most recent last): {', '.join(intent_history)}\n"
            "Use this as a prior when interpreting follow-up messages.\n"
        )

    # Intent-specific planning templates
    intent_templates = {
        Intent.FILE_WRITE: """
FILE_WRITE WORKFLOW — follow this template:
0. If you don't know the exact target folder (e.g. "desktop"), inspect it with dir_explorer (operation=list) first to confirm the path — then write there
1. Identify the file path from the user's request (or infer a sensible default)
2. Determine the complete file content — write it ALL, no placeholders
3. Call file_write ONCE with both 'path' and 'content' filled
4. Do NOT call file_write multiple times for the same file

IMPORTANT: Only use file_write for CREATING NEW files. If the file already exists
and you only need to modify parts of it, use the edit_file tool instead. edit_file
is preferred for modifications because:
- It shows the user exactly what changed (diff view with green/red highlighting)
- It creates automatic backups (.bak files)
- It's faster and uses fewer tokens than rewriting entire files
- The action log accurately reflects "Edited lines 42-51" instead of "Wrote file.js" """,
        Intent.FILE_EDIT: """
FILE_EDIT WORKFLOW — follow this template:
1. Call file_task to READ the file first — you MUST see its current content
2. Identify what needs to change (search text, line numbers, etc.)
3. Call edit_file with the correct action (replace, insert, append, etc.)
4. Do NOT use file_write to overwrite the entire file for small changes

PREFERRED: Always prefer edit_file over file_write for existing files. edit_file
shows the user a surgical diff (green additions, red deletions) rather than
rewriting the entire file. This is more efficient, saves tokens, and gives
the user a clear view of exactly what changed. Use file_write ONLY when creating
a brand-new file that doesn't exist yet. """,
        Intent.CODE_EXEC: """
CODE_EXEC WORKFLOW — follow this template:
1. Understand what computation the user needs
2. Write the complete Python code
3. Call code_exec with the full code
4. Check the output for errors — if there are errors, fix and retry""",
        Intent.MEMORY_OP: """
MEMORY_OP WORKFLOW — follow this template:
1. Determine if the user wants to store, recall, or forget a fact
2. Call memory_op with the correct operation and content""",
        Intent.SHELL: """
SHELL WORKFLOW — follow this template:
0. CHECK THE OS from environment context: Windows (PowerShell) or Unix (bash)? This determines EVERY command.
1. Understand what the user wants to do on their computer (list files, run a command, check disk, etc.)
2. Write the command in the CORRECT OS syntax:
   - Windows/PowerShell: Get-ChildItem, New-Item -ItemType Directory -Force, Get-Content, Select-String
   - Unix/bash: ls, mkdir -p, cat, grep, find
   NEVER use "mkdir -p" on Windows or "ls" on Windows — they WILL fail.
3. Call the shell tool with the OS-correct command
4. Report the EXACT output from the tool — NEVER fabricate or add items that weren't in the output
5. If listing a directory, report ONLY the names the tool returned — do NOT add "typical" folders
6. If the user asked you to CREATE a file: listing the folder is step ONE — then call file_write with the full path + complete content. Do NOT stop after listing.""",
        Intent.FILE_TASK: """
FILE_TASK WORKFLOW — follow this template:
1. If the user gave a FILE path: call file_task with that exact path — read it immediately
2. If the user gave a DIRECTORY/FOLDER path: call dir_explorer (operation=list) to inspect it first, identify the target file, then call file_task to read it — do NOT stop after listing
3. If the path is ambiguous (could be file or folder): try file_task first; if it fails, use dir_explorer to list and find the file, then read it
4. NEVER guess file names — use ONLY names that appear in the tool output
5. If you found the file the user asked for, READ IT — do not ask "which one?" when the answer is obvious (e.g., the only CV in a folder)
6. COMPLETE THE TASK: If the user asked you to READ a file and you found it, you MUST call file_task to read it. Do NOT stop after just listing the directory.

CRITICAL FOLLOW-THROUGH RULE:
- When a task requires MULTIPLE steps (e.g., list directory → find file → read file), you MUST complete ALL steps before giving a final answer.
- NEVER stop after a partial step and ask the user to confirm. If you listed a directory and found the obvious target file, READ IT.
- Example: User says "Read my CV 'C:\\Users\\tison\\Documents'" → Step 1: shell dir "C:\\Users\\tison\\Documents" → Step 2: Identify CV-TisoneKironget.pdf → Step 3: file_task "C:\\Users\\tison\\Documents\\CV-TisoneKironget.pdf" → Report contents. DO NOT stop at Step 2.""",
        Intent.WEB_SEARCH: """
WEB_SEARCH WORKFLOW — follow this template:
1. Formulate a SPECIFIC search query (NOT the raw user message — extract the key facts)
   - Bad: "What's the weather like in Cheptais now?" (too verbose, returns irrelevant results)
   - Good: "weather Cheptais Bungoma Kenya current conditions" (specific, location-focused)
   - Include region/country for ambiguous place names
2. Call web_search with the formulated query
3. Check the search results — do the snippets contain the specific data the user needs?
   - If YES (snippets have the answer): synthesize the answer from the snippets, cite sources
   - If NO (snippets are link-only without the actual data): call web_fetch on the most relevant URL
4. When using web_fetch, extract the specific facts the user asked for from the page content
5. NEVER fabricate specific numbers (temperature, prices, etc.) that weren't in the search results or fetched pages
6. If no results are found for the specific location, try a broader search (e.g., nearby major city)

CRITICAL: When search returns "No results found" or empty results:
- Do NOT fabricate data from your training knowledge
- Do NOT guess based on "memory fragments" or what seems typical
- TELL THE USER: "I couldn't find search results for [query]. The search providers may be temporarily unavailable."
- You may suggest: "You could try searching for a nearby larger city, or check again later."
- NEVER present guessed information as if it came from a search""",
        Intent.WEB_FETCH: """
WEB_FETCH WORKFLOW — follow this template:
1. Call web_fetch with the URL from a web_search result
2. Extract the specific facts the user needs from the page content
3. Report exactly what the page says — do NOT add information from your training data
4. If the page content doesn't contain the answer, say so clearly""",
        Intent.DIR_EXPLORER: """
DIR_EXPLORER WORKFLOW — follow this template (read-only folder inspection):
1. Pick the operation that answers the ask: 'what's in this folder?' → list;
   'sketch the project structure' → tree (depth 2 default, max 4);
   'does this path exist / how big is it?' → stat
2. Call dir_explorer ONCE with the resolved path — do NOT dump file contents
   (that is file_task) and do NOT hunt by name (that is system_search)
3. Report ONLY the names the tool returned — NEVER add "typical" entries
4. If the result says PARTIAL / truncated / depth-limited, SAY SO and offer
   to go deeper on a narrower path""",
    }

    template = intent_templates.get(intent, "")

    # Inject intent-specific skill expertise (condensed — planner must be brief)
    from core.context_builder import _intent_fragment_name, _load_fragment

    skill_fragment = _load_fragment(_intent_fragment_name(intent))
    skill_hint = ""
    if skill_fragment:
        # Trim to first 500 chars for planner — it just needs the philosophy,
        # not the full detailed rules (those go to the execution agent).
        _truncated_skill = skill_fragment[:500]
        if len(skill_fragment) > 500:
            _truncated_skill += "..."
        skill_hint = f"\nDomain expertise for this task:\n{_truncated_skill}\n"

    return f"""You are a task planner for LocalMind, a local AI assistant. Your job is to analyze the user's request and create a concise execution plan.

{env_context}

Available tools:
{agent_tool_list}
{intent_ctx}
{template}
{skill_hint}

CRITICAL RULES:
- Think step by step before deciding on tools
- For file operations: ALWAYS determine the complete path and content BEFORE planning to call file_write
- For code execution: write the complete code in your plan, no placeholders
- Shell commands must match the current OS (Windows: mkdir, dir, type | Unix: mkdir -p, ls, cat)
- If a task needs only ONE tool call, say so — no need for multi-step plans
- For any MULTI-STEP task, call todo_write FIRST with the whole checklist, then call it again as you go — mark the current step in_progress and finished steps completed. This drives the user's live Todos panel; keep it in sync so they see real progress.

REASONING DEPTH (CRITICAL — don't just state your next action, REASON):
- What do I already know from context that's relevant? (date, user preferences, prior conversation)
- What am I uncertain about? What assumptions am I making?
- What could go wrong with the source data? (stale pages, placeholder content, future dates presented as current)
- How will I verify the results are correct before reporting them?
- Example BAD thinking: "I'll search the web for today's World Cup fixtures"
- Example GOOD thinking: "User wants today's World Cup games. Today is {env_context.split("Current date: ")[1].split(chr(10))[0] if "Current date: " in env_context else "unknown"}. I'll search for fixtures on that specific date. After getting results, I'll check if the source's date matches today — if a page shows a future date or placeholder teams, that's not today's data."

Respond with a concise plan in this format:

UNDERSTANDING: [what the user ACTUALLY needs — interpret their intent. "Should I carry an umbrella?" → "User needs rain probability for their location today"]
WHAT I KNOW: [relevant facts from context — current date, user location if known, prior conversation]
WHAT I'LL VERIFY: [what could be wrong with the data and how I'll check]
STEPS:
1. [goal-level step: what you're achieving AND the exact command/args that achieves it]
2. [next step, or "Done" if single step]
ARGS_PRECHECK: [verify all required args are known]

SESSION 122 STEP QUALITY RULES (CRITICAL):
- Plan at the GOAL level, not a 1:1 mirror of tool calls. Each step is a goal
  the user cares about, with the command that achieves it embedded.
- Include CONDITIONAL branches as separate steps: "If X, then step Y; otherwise
  step Z" — e.g. "Check git status --short. If output is non-empty, run git diff".
- The LAST step must be reporting the result to the user ("Return combined
  result to the user").
- FORBIDDEN filler steps — never write steps that only say "verify the result",
  "analyze the output", "run the command", "capture the output", "report the
  results" without naming the actual tool, path, or command.
- Every step that runs a tool must contain the literal command/args, e.g.
  "Run `git status --short` in the repo root" — never "Run the shell action".

Example for "Check git status and if there are uncommitted changes show me the diff":
1. Locate repo root — resolve the working directory and confirm it's a git repo.
2. Run `git status --short` in the repo root.
3. Parse the output — empty → done (no uncommitted changes). Non-empty → proceed.
4. If changes exist, run `git diff` to show what changed.
5. Return the combined result (files changed + diff, or "no uncommitted changes").

Keep the plan brief — 3-10 lines max. No code blocks, no markdown.

CRITICAL: The search query in your plan should be the OPTIMAL query for getting the data the user needs — NOT their literal question. "Should I carry an umbrella in Kitengela?" → search "Kitengela weather today rain", NOT "should I carry an umbrella in Kitengela".

User request: {user_message}"""
