"""Scenario definitions for the standing eval harness (B-2026-10-31-23).

Ten audit scenarios (external audit 2026-10-31 §1.7) plus the two absorbed
replay cases (§1.1 perspective/speaker-identity, §1.2 reflective/meta-tools)
and the continuity integration case (the C1/C2/C5 machinery, per the
goal-pursuit investigation's handoff into this row).

Each scenario is provider-agnostic DATA:

- ``turns`` — what the harness fires and what the runner checks. Content
  expectations (``reply_contains``) are pinned in deterministic mode (the
  scripted provider stands in for the model, so the assertions verify the
  pipeline end to end, not model accuracy); on a real provider they are
  recorded as advisory. Exclusions (``reply_excludes``) are defect
  signatures and gate in BOTH modes.
- ``script`` — the deterministic provider's steps, matched per provider
  call, first match wins: ``("classify", mode, ...)`` for the
  pre-init/classify contract (detected by the ``direct|clarify|execute``
  marker), ``("user", substring, text)`` keyed on the LAST user message,
  ``("tool", name, args_json, call_id)`` / ``("after", call_id, ...)`` for
  the loop's tool iterations (matched once, in order, by the minted call
  id the app echoes back in the tool result), ``("any", text)`` fallback.

``{scratch}`` inside texts/args is replaced with the scratch home path at
run time (used to point file tools at seeded files).

A scenario with ``injects_failure=True`` contributes to the recovery-rate
metric: the harness requires the final reply to be present and to carry
``recovery_marker`` (an honest-failure acknowledgment), never a fabricated
success.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TurnSpec:
    """One fired message plus the runner's checks."""

    user: str
    # Content assertions — required in deterministic mode, advisory on a
    # real provider.
    reply_contains: tuple[str, ...] = ()
    # Defect signatures — gate in BOTH modes (a regression is a regression).
    reply_excludes: tuple[str, ...] = ()
    # Tool expectations: these tools must run (any order) and finish done.
    expect_tools: tuple[str, ...] = ()
    # Minimum completed-call count per tool (e.g. {"sysinfo": 2}).
    expect_tool_counts: dict[str, int] = field(default_factory=dict)
    # Tools that must run AND finish FAILED (the honest-failure contract).
    expect_tool_failure: tuple[str, ...] = ()
    # No tool may run at all on this turn.
    expect_no_tools: bool = False
    # Tools that must NOT run on this turn (defect signatures).
    forbid_tools: tuple[str, ...] = ()
    # True: the reply must end asking something; False: it must not.
    expect_question: bool | None = None
    # The path_selected lane the turn must take (e.g. open_question_reply).
    expect_lane: str | None = None
    # Observability event types that must / must not appear on the wire.
    expect_obs: tuple[str, ...] = ()
    forbid_obs: tuple[str, ...] = ()
    # Soft latency budget (ms) — breach is recorded as a finding, never a FAIL.
    max_latency_ms: int | None = None


@dataclass(frozen=True)
class Scenario:
    id: str
    category: str  # the audit §1.7 scenario name (or "absorbed"/"continuity")
    title: str
    description: str
    turns: tuple[TurnSpec, ...]
    script: tuple[tuple, ...]
    # Files seeded into the scratch home before the run: relative -> content.
    seed_files: dict[str, str] = field(default_factory=dict)
    injects_failure: bool = False
    recovery_marker: str = ""


# ─── The ten audit scenarios (§1.7) ────────────────────────────────────

AMBIGUOUS_REQUEST = Scenario(
    id="ambiguous-request",
    category="ambiguous request",
    title="Referent-less request must clarify, not act",
    description=(
        "'fix it' with no referent: the forced-clarify exit is the CORRECT "
        "behavior here (no open question on record, nothing to stand down). "
        "The clarifying question must land as an open-question record."
    ),
    turns=(
        TurnSpec(
            user="fix it",
            expect_question=True,
            expect_no_tools=True,
            expect_obs=("open_question_recorded",),
            # No content pin: the forced-clarify exit's question text is
            # machinery-generated (the scripted clarifying_question feeds
            # the classify decision, not the exit's wording).
        ),
    ),
    script=(
        ("classify", "clarify", "What exactly should I fix — which file or setting is it about?"),
        ("any", "Noted."),
    ),
)

LONG_CONVERSATION = Scenario(
    id="long-conversation",
    category="long conversation",
    title="Context carried across six turns",
    description=(
        "A fact stated in turn 1 must still be answerable in turn 6. On the "
        "deterministic provider this verifies the pipeline carries history "
        "to every call; on a real provider it is a genuine recall probe."
    ),
    turns=(
        TurnSpec(user="Please remember my demo passphrase is 'harbour-light-7'.",
                 reply_contains=("noted",)),
        TurnSpec(user="What can you do here?", reply_contains=("help", "can")),
        TurnSpec(user="Anyway — the demo is on Friday.", reply_contains=("friday", "okay")),
        TurnSpec(user="Let's continue tomorrow.", reply_contains=("tomorrow", "sure")),
        TurnSpec(user="One more thing: the venue changed.", reply_contains=("venue", "noted")),
        TurnSpec(user="What exact demo passphrase did I ask you to remember?",
                 reply_contains=("harbour-light-7",), expect_question=False),
    ),
    script=(
        ("classify", "execute", ""),
        ("user", "passphrase is", "Got it — the demo passphrase is noted for this session."),
        ("user", "What can you do here",
         ("I can help you prepare the demo: read and edit files, run shell "
          "commands, search the web, and inspect this machine.")),
        ("user", "demo is on Friday", "Okay — Friday's demo is on the calendar notes."),
        ("user", "continue tomorrow", "Sure — we continue tomorrow."),
        ("user", "venue changed", "Noted — the venue changed; I'll keep that in mind."),
        ("user", "What exact demo passphrase",
         "You asked me to remember the demo passphrase 'harbour-light-7'."),
        ("any", "Noted."),
    ),
)

PREFERENCE_RECALL = Scenario(
    id="preference-recall",
    category="preference recall",
    title="Stated name/style preference shapes later replies",
    description=(
        "The user states a name and an answer-style preference; a later turn "
        "asks for them back. The preference machinery (memory facts / turn "
        "context) is what makes this real on a live provider."
    ),
    turns=(
        TurnSpec(user="Call me Chips, and I prefer short bullet-point answers.",
                 reply_contains=("Chips",)),
        TurnSpec(user="thanks"),
        TurnSpec(user="What's my name, and what answer style did I ask for?",
                 reply_contains=("Chips", "bullet"), expect_question=False),
    ),
    script=(
        ("classify", "execute", ""),
        ("user", "Call me Chips", "Noted, Chips — short bullet-point answers from here on."),
        ("user", "thanks", "Anytime!"),
        ("user", "What's my name",
         ("You're Chips, and you asked for short bullet-point answers.")),
        ("any", "Noted."),
    ),
)

FILE_ANALYSIS = Scenario(
    id="file-analysis",
    category="file analysis",
    title="Real file read, real summary",
    description=(
        "A file is seeded into the scratch home; the scripted provider calls "
        "file_task with its absolute path. The tool execution is REAL — if "
        "the seed is missing or the read is blocked, the tool fails and the "
        "scenario fails."
    ),
    seed_files={
        "files/notes.md": (
            "# Harbour demo notes\n\n"
            "1. Action item: ship the login fix.\n"
            "2. Action item: rehearse the demo script.\n"
            "3. Action item: send the venue map.\n"
        ),
    },
    turns=(
        TurnSpec(
            user="Read the file {scratch}/files/notes.md and summarize it.",
            expect_tools=("file_task",),
            reply_contains=("three action items",),
            expect_question=False,
        ),
    ),
    script=(
        ("classify", "execute", ""),
        ("tool", "file_task", '{"path": "{scratch}/files/notes.md"}', "call_file_1"),
        ("after", 1,
         "The notes cover three action items; first ships the login fix."),
        ("any", "Noted."),
    ),
)

DEPENDENT_MULTI_STEP = Scenario(
    id="dependent-multi-step",
    category="dependent multi-step",
    title="A tool result feeds the next tool decision",
    description=(
        "Read a file, then compute with what it contained: the second tool "
        "call (calculator) only makes sense after the first (file_task) "
        "returned. Verifies tool results return to the same active "
        "objective within a turn (the in-turn half of the continuity work)."
    ),
    seed_files={
        "files/budget.md": (
            "# Budget\n\nAction items: 3\nCost per item (k): 8\n"
        ),
    },
    turns=(
        TurnSpec(
            user="Read {scratch}/files/budget.md, then compute the total cost in k with the calculator.",
            expect_tools=("file_task", "calculator"),
            reply_contains=("24",),
            expect_question=False,
        ),
    ),
    script=(
        ("classify", "execute", ""),
        ("tool", "file_task", '{"path": "{scratch}/files/budget.md"}', "call_file_1"),
        ("after", 1, ("tool", "calculator", '{"expression": "3*8"}', "call_calc_1")),
        ("after", 2,
         "The budget lists 3 action items at 8k each — the calculator puts the total at 24k."),
        ("any", "Noted."),
    ),
)

FAILED_TOOL = Scenario(
    id="failed-tool",
    category="failed tool",
    title="A failing tool must be reported honestly",
    description=(
        "file_task on a path that does not exist: the tool fails for real. "
        "The turn must still end with an honest answer (the failure "
        "acknowledged, no fabricated success) — this is the recovery-rate "
        "fixture."
    ),
    injects_failure=True,
    recovery_marker="couldn't",
    turns=(
        TurnSpec(
            user="Read {scratch}/files/missing-report.md and summarize it.",
            expect_tool_failure=("file_task",),
            reply_contains=("couldn't",),
            expect_question=False,
        ),
    ),
    script=(
        ("classify", "execute", ""),
        ("tool", "file_task", '{"path": "{scratch}/files/missing-report.md"}', "call_file_1"),
        ("after", 1,
         ("I couldn't read that file — it doesn't exist at that path, so there "
          "is nothing to summarize.")),
        ("any", "Noted."),
    ),
)

CONTRADICTION = Scenario(
    id="contradiction",
    category="contradiction",
    title="A stated fact contradicted later must update",
    description=(
        "The user asserts a location, then contradicts it and asks back. "
        "The reply must carry the corrected fact, not the stale one."
    ),
    turns=(
        TurnSpec(user="I live in Nairobi.", reply_contains=("Nairobi",)),
        TurnSpec(user="Actually I lied — I live in Mombasa. Where do I live?",
                 reply_contains=("Mombasa",), reply_excludes=("you live in Nairobi",),
                 expect_question=False),
    ),
    script=(
        ("classify", "execute", ""),
        ("user", "I live in Nairobi", "Got it — Nairobi it is."),
        ("user", "Where do I live",
         "You live in Mombasa — you corrected the earlier Nairobi note."),
        ("any", "Noted."),
    ),
)

USER_CORRECTION = Scenario(
    id="user-correction",
    category="user correction",
    title="A parameter correction supersedes the earlier value",
    description=(
        "'no — make it 11, not 9': the reply must carry the corrected value "
        "and not repeat the stale one as the answer."
    ),
    turns=(
        TurnSpec(user="Remind me to submit the report at 9.", reply_contains=("9",)),
        TurnSpec(user="no — make it 11, not 9.",
                 reply_contains=("11",), expect_question=False),
    ),
    script=(
        ("classify", "execute", ""),
        ("user", "submit the report at 9", "Noted — 9 it is for the report submission."),
        ("user", "make it 11", "Updated — 11, not 9."),
        ("any", "Noted."),
    ),
)

UNFAMILIAR_PROBLEM = Scenario(
    id="unfamiliar-problem",
    category="unfamiliar problem",
    title="Unknowable locally: honest uncertainty, no guess",
    description=(
        "A question the machine facts cannot answer. The capability-honesty "
        "spine says: say what you don't know, offer the path that could "
        "know — never fabricate."
    ),
    turns=(
        TurnSpec(
            user="What is the exact current population of Mars's smallest moon?",
            reply_contains=("don't have", "can search"),
            expect_question=False,
            expect_no_tools=True,
        ),
    ),
    script=(
        ("classify", "execute", ""),
        ("user", "smallest moon",
         ("I don't have that figure locally, and I won't guess a number. "
          "I can search the web for the current estimate if you want.")),
        ("any", "Noted."),
    ),
)

COMPLEX_OBJECTIVE = Scenario(
    id="complex-objective",
    category="complex objective",
    title="Multi-facet ask, multiple tool cycles, synthesis",
    description=(
        "One objective needing two tool cycles (platform, then CPU count) "
        "and a synthesized final answer — the in-turn multi-cycle engine "
        "under load."
    ),
    turns=(
        TurnSpec(
            user="Inspect this machine with your system-info tool: report the OS platform, then the CPU core count, and summarize both.",
            expect_tools=("sysinfo",),
            expect_tool_counts={"sysinfo": 2},
            reply_contains=("Snapshot", "cores"),
            expect_question=False,
        ),
    ),
    script=(
        ("classify", "execute", ""),
        ("tool", "sysinfo", '{"query": "platform"}', "call_sys_1"),
        ("after", 1, ("tool", "sysinfo", '{"query": "cpu"}', "call_sys_2")),
        ("after", 2,
         ("Snapshot: the platform and CPU count above — this machine "
          "completes the snapshot with both cores listed.")),
        ("any", "Noted."),
    ),
)

# ─── Absorbed replay cases (audit §1.1 / §1.2) ─────────────────────────

PERSPECTIVE_IDENTITY = Scenario(
    id="perspective-identity",
    category="absorbed: audit §1.1",
    title="Speaker-identity polarity holds",
    description=(
        "The audit's failing exchange: the relationship must keep its "
        "polarity (they are the creator; the agent is the created). The "
        "reversed signature is a defect EXCLUSION and gates in both modes."
    ),
    turns=(
        TurnSpec(user="Do you know who built you?",
                 reply_contains=("built",),
                 reply_excludes=("As your creator",)),
        TurnSpec(user="And who am I to you?",
                 reply_contains=("built",),
                 reply_excludes=("As your creator", "I created you"),
                 expect_question=False),
    ),
    script=(
        ("classify", "execute", ""),
        ("user", "who built you", "You built me — you're my creator."),
        ("user", "who am I to you", "You're the person who built and owns me."),
        ("any", "Noted."),
    ),
)

REFLECTIVE_NO_META_TOOLS = Scenario(
    id="reflective-no-meta-tools",
    category="absorbed: audit §1.2",
    title="A reflective turn must not reach for meta-tools",
    description=(
        "'Assess yourself' once produced an elaborate plan and a pointless "
        "get_goal call. The replay case asserts a clean answer with zero "
        "meta-tool traffic."
    ),
    turns=(
        TurnSpec(
            user="Assess yourself as an agent — what are you good at, and where do you struggle?",
            expect_no_tools=True,
            forbid_tools=("get_goal", "update_goal", "todo_write",
                          "delegate", "delegate_parallel", "delegate_inline"),
            reply_contains=("good",),
            expect_question=False,
        ),
    ),
    script=(
        ("classify", "execute", ""),
        ("user", "Assess yourself",
         ("I'm good at grounded, tool-backed work on this machine — reading "
          "files, running commands, keeping the record honest. I struggle "
          "with anything that needs knowledge I don't hold and can't fetch.")),
        ("any", "Noted."),
    ),
)

# ─── Continuity integration (the C1/C2/C5 machinery, scored) ───────────

OFFER_THEN_APPROVAL = Scenario(
    id="offer-then-approval",
    category="continuity integration",
    title="Offer → approval → execution, nothing left owed",
    description=(
        "The C5 offer-is-DONE shape, scored end to end: an offered check "
        "ends the turn as an open-question record; a bare 'yes' must "
        "reroute against that record (lane open_question_reply), survive "
        "the driven clarify (stand-down), actually EXECUTE the offered "
        "tool, and consume the record — the approval becomes work, not "
        "small talk."
    ),
    turns=(
        TurnSpec(
            user="Can you check how many CPU cores this machine has?",
            reply_contains=("want me to run",),
            expect_question=True,
            expect_obs=("open_question_recorded",),
        ),
        TurnSpec(
            user="yes",
            expect_lane="open_question_reply",
            expect_obs=("open_question_consumed",),
            expect_tools=("sysinfo",),
            reply_contains=("cores",),
            reply_excludes=("Just to confirm",),
            expect_question=False,
        ),
    ),
    script=(
        ("classify", "execute", ""),
        ("user", "CPU cores",
         ("I can probe the machine's system info for the exact core count — "
          "want me to run that check?")),
        ("classify", "clarify", "Just to confirm — what would you like me to do?"),
        ("tool", "sysinfo", '{"query": "cpu"}', "call_sys_1"),
        ("after", 1, "This machine reports the core count above — 8 CPU cores in total."),
        ("any", "Noted."),
    ),
)


ALL_SCENARIOS: tuple[Scenario, ...] = (
    AMBIGUOUS_REQUEST,
    LONG_CONVERSATION,
    PREFERENCE_RECALL,
    FILE_ANALYSIS,
    DEPENDENT_MULTI_STEP,
    FAILED_TOOL,
    CONTRADICTION,
    USER_CORRECTION,
    UNFAMILIAR_PROBLEM,
    COMPLEX_OBJECTIVE,
    PERSPECTIVE_IDENTITY,
    REFLECTIVE_NO_META_TOOLS,
    OFFER_THEN_APPROVAL,
)
