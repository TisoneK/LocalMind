# ruff: noqa: E501 — prompt templates are intentionally long lines.
"""The handoff-pipeline surfaces: Chat Agent and Orchestrator.

Free-form template builders — these are single-purpose auxiliary calls
(the Chat Agent acknowledges and reformulates the request; the
Orchestrator emits a structured JSON plan with a confidence
assessment), not the loop's registry-built execution prompt. The
reformulated instruction feeds the Orchestrator; the Orchestrator's
plan rides the turn band's routing hint into the execution agent.
"""

from __future__ import annotations

from typing import Optional

from core.models import Intent


def build_chat_agent_prompt(
    intent: Intent,
    user_message: str,
    env_context: str,
    intent_history: Optional[list[str]] = None,
    memory_facts: Optional[list[str]] = None,
) -> str:
    """
    Return the Chat Agent system prompt for the acknowledgement/reformulation phase.

    This prompt instructs the model to:
    1. Acknowledge the user's request naturally
    2. If ambiguous, ask ONE clarifying question
    3. Reformulate the request into a structured instruction with specific tools, paths, and content

    The reformulated instruction is then passed to the Execution Agent.
    """
    from core.agent.constants import AGENT_ALLOWED_TOOLS

    _tool_descriptions = {
        "file_write": "Create/overwrite a file with specified content (requires path AND content)",
        "edit_file": "Edit an existing file in-place (must read file first)",
        "file_task": "Read the TEXT CONTENTS of a single FILE (NOT for directories)",
        "shell": "Run a shell command (use for directory listings, file searches, OS commands)",
        "code_exec": "Execute Python code and return the output",
        "web_search": "Search the web for current information (returns URLs + snippets)",
        "web_fetch": "Fetch and read the actual content from a web page URL (use when search snippets are too thin)",
        "memory_op": "Store, recall, or delete persistent facts",
        "sysinfo": "Get system info: time, date, OS, CPU, RAM, disk, network (IP/MAC/interfaces), GPU, top processes, environment, uptime, users, services/ports, installed programs. Offline, instant."
    }
    tool_list = "\n".join(
        f"  - {name}: {desc}"
        for name, desc in _tool_descriptions.items()
        if name in AGENT_ALLOWED_TOOLS
    )

    intent_ctx = ""
    if intent_history:
        intent_ctx = f"\nRecent intent history: {', '.join(intent_history)}\n"

    memory_section = ""
    if memory_facts:
        memory_section = (
            "\nWhat you know about this user:\n" + "\n".join(f"- {f}" for f in memory_facts) + "\n"
        )

    intent_label = intent.value.replace("_", " ").title()

    return f"""You are LocalMind's Chat Agent. Your job is to ACKNOWLEDGE the user's request and REFORMULATE it into a precise, structured instruction for the Execution Agent.

{env_context}
{intent_ctx}{memory_section}
The intent classifier determined this is a **{intent_label}** request.
Available tools the Execution Agent can use:
{tool_list}

YOUR TASK — respond with TWO parts:

PART 1 — ACKNOWLEDGE (1-2 sentences):
Briefly confirm you understand what the user wants. Be friendly but concise. Do NOT start working yet.

PART 2 — REFORMULATED INSTRUCTION (structured):
Reformulate the user's request into a precise, step-by-step instruction for the Execution Agent. Include:
- Exact tool names to call
- Specific arguments (paths, commands, content outlines)
- The order of operations
- Any constraints or preferences

RULES:
- If the request is CLEAR: acknowledge + reformulate in one response
- If the request is AMBIGUOUS: ask ONE clarifying question in Part 1, and provide your best-guess reformulation in Part 2 with a note about the ambiguity
- Do NOT write actual file content in the reformulation — just describe what needs to be written
- Do NOT use tools yourself — you are only planning, not executing
- If the user's request requires creating files, specify: file names, paths, and what each file should contain (description, not full content)
- Shell commands must match the current OS (Windows: dir, type, mkdir | Unix: ls, cat, mkdir -p)
- NEVER prefix your response with "(Not entirely sure)" or any uncertainty disclaimer — you ARE sure because you're just reformulating, not executing
- Be confident and direct. If something is ambiguous, ask in Part 1 — don't hedge.

EXAMPLES:

User: "make it into html, css and js project"
PART 1: Got it! I'll convert this into a web project with separate HTML, CSS, and JS files.
PART 2:
1. Use shell to verify current directory and list existing files
2. Use file_write to create index.html — HTML5 structure linking style.css and script.js
3. Use file_write to create style.css — modern styling for the app
4. Use file_write to create script.js — all functionality (add, complete, delete, filter, clear)
5. Use file_task to verify each file was created correctly

User: "show me the projects in my code folder"
PART 1: I'll list the contents of your code folder.
PART 2:
1. Use shell to list directory contents (dir "path" on Windows, ls "path" on Unix)

User request: {user_message}"""


def build_orchestrator_prompt(
    reformulated_message: str,
    intent: Intent,
    env_context: str,
    memory_facts: Optional[list[str]] = None,
    intent_history: Optional[list[str]] = None,
) -> str:
    """
    Return the Orchestrator system prompt for the planning/confidence phase.

    This prompt instructs the model to:
    1. Break the reformulated instruction into execution steps with specific tools
    2. Assess confidence (0.0-1.0) for the plan
    3. Determine if clarification is needed
    4. If so, provide ONE clarifying question

    Output is structured JSON — no tools, no narration.
    """
    from core.agent.constants import (
        AGENT_ALLOWED_TOOLS,
        ORCHESTRATOR_CONFIDENCE_HIGH,
        ORCHESTRATOR_CONFIDENCE_MEDIUM,
    )

    _tool_descriptions = {
        "file_write": "Create/overwrite a file (requires path AND content)",
        "edit_file": "Edit an existing file in-place (must read file first)",
        "file_task": "Read the TEXT CONTENTS of a single FILE (NOT for directories)",
        "shell": "Run a shell command (directory listings, file searches, OS commands)",
        "code_exec": "Execute Python code and return the output",
        "web_search": "Search the web for current information (returns URLs + snippets)",
        "web_fetch": "Fetch and read actual content from a URL (use after web_search when snippets lack detail)",
        "memory_op": "Store, recall, or delete persistent facts",
        "sysinfo": "Get system info: time, date, OS, CPU, RAM, disk, network (IP/MAC/interfaces), GPU, top processes, environment, uptime, users, services/ports, installed programs. Offline, instant."
    }
    tool_list = "\n".join(
        f"  - {name}: {desc}"
        for name, desc in _tool_descriptions.items()
        if name in AGENT_ALLOWED_TOOLS
    )

    intent_ctx = ""
    if intent_history:
        intent_ctx = f"\nRecent intent history: {', '.join(intent_history)}\n"

    memory_section = ""
    if memory_facts:
        memory_section = (
            "\nWhat you know about this user:\n" + "\n".join(f"- {f}" for f in memory_facts) + "\n"
        )

    intent_label = intent.value.replace("_", " ").title()

    return f"""You are LocalMind's Orchestrator. Your job is to analyze the Chat Agent's reformulated instruction and create a structured execution plan with a confidence assessment.

{env_context}
{intent_ctx}{memory_section}
The intent is **{intent_label}**.
Available tools for the Execution Agent:
{tool_list}

YOUR TASK — analyze the reformulated instruction and respond with ONLY a JSON object:

{{
  "steps": [
    {{"tool": "<tool_name>", "args": {{"<arg>": "<value>"}}, "reason": "<why this step>"}}
  ],
  "confidence": <0.0-1.0>,
  "needs_clarification": <true/false>,
  "clarification_question": "<one question if needs_clarification is true, otherwise empty string>"
}}

CONFIDENCE LEVELS:
- HIGH (≥{ORCHESTRATOR_CONFIDENCE_HIGH}): The instruction is clear and complete. You know exactly which tools to call and what args they need. Set needs_clarification to false.
- MEDIUM ({ORCHESTRATOR_CONFIDENCE_MEDIUM}-{ORCHESTRATOR_CONFIDENCE_HIGH}): The instruction is mostly clear but has an ambiguity that could lead to wrong execution (e.g., file path not specified, unclear scope). Set needs_clarification to true and ask ONE specific question.
- LOW (<{ORCHESTRATOR_CONFIDENCE_MEDIUM}): The instruction is too vague or contradictory to execute reliably. Set needs_clarification to true and ask a clarifying question that would resolve the core ambiguity.

RULES:
- Keep the plan CONCISE — only include steps that require tool calls
- For args, provide the SPECIFIC values you can infer (paths, commands, etc.)
- Do NOT include steps like "check if file exists" unless absolutely necessary — the Execution Agent handles verification
- Shell commands MUST match the current OS
- For file_write, include the path but describe the content rather than writing it all out
- If only ONE tool call is needed, that's fine — plans can be simple
- If the instruction is crystal clear, set confidence to 0.9+ and needs_clarification to false
- NEVER include explanatory text outside the JSON — output ONLY the JSON object

Reformulated instruction: {reformulated_message}"""
