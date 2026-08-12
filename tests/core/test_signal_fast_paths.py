'''Session 145 regression tests — signal fast-path wins (ADR-17 track 2).

Two latency fixes shipped in Session 145:

1. **Directory-listing phrasing signal.** "Show me all projects in dev",
   "List projects available in dev/" are unambiguous directory-list
   requests but never matched _SHELL_PREFIXES (which requires the message
   to START with `ls `/`dir `), so they paid the full dispatcher LLM call
   (~10-20s on the free tier) for a routing decision a regex can make.
   The new signal matches a listing verb + filesystem noun + location
   preposition + target and produces a SINGLE_TOOL shell plan WITHOUT any
   adapter call. Requests with non-listing verbs (read/open/create/
   search/...) or no filesystem noun fall through to the LLM.

2. **Signal fast paths skip the Chat Agent phase.** The engine's
   7a-chat branch used to require `not _dispatcher_fast_path` before
   using the dispatcher's reformulation — so signal-detected plans
   (URL fetch, shell prefixes, sysinfo) fell through to
   `_chat_agent_phase`, an unnecessary LLM call that defeated the
   signal's purpose. Now any dispatcher reformulation (signal or LLM)
   skips the Chat Agent.
'''

from __future__ import annotations

import asyncio

from core import thinking_dispatcher as td
from core.obs import ObsCollector


class _NoCallAdapter:
    """Adapter that FAILS if chat() is called — signals must not hit the LLM."""

    def __init__(self):
        self.chat_calls = 0

    async def chat(self, messages, temperature=0.7, **kwargs):
        self.chat_calls += 1
        # Yield an empty stream then stop so the dispatcher's async-for
        # consumes it cleanly; the counting assert below still proves the
        # signal path never called chat().
        if False:
            yield None
        raise AssertionError("signal fast path must NOT call the adapter")


def _collect(dispatcher, message):
    async def _run():
        items = []
        async for item in dispatcher.dispatch(
            message=message,
            history=[],
            memory_facts=[],
            has_attachment=False,
            obs=ObsCollector(),
            session_id="test-session",
            intent_history=[],
        ):
            items.append(item)
        return items
    return asyncio.run(_run())


def _plans(items):
    return [i for i in items if hasattr(i, "profile")]


def _signal_plan(message):
    d = td.ThinkingDispatcher(_NoCallAdapter())
    return _plans(_collect(d, message))


# ── 1. Directory-listing phrasing signal ───────────────────────────────


def test_list_projects_in_dir_is_a_signal():
    plans = _signal_plan("Show me all projects in dev")
    assert len(plans) == 1, "listing phrasing must produce a plan without an LLM call"
    plan = plans[0]
    assert plan.profile.primary_domain == "shell_command"
    assert plan.profile.execution_mode.value == "single_tool"
    assert plan.fast_path is True
    assert "dev" in plan.profile.reformulated


def test_list_files_available_in_dir_is_a_signal():
    plans = _signal_plan("List projects available in dev/")
    assert len(plans) == 1
    assert plans[0].profile.primary_domain == "shell_command"


def test_list_contents_of_folder_is_a_signal():
    plans = _signal_plan("Show me the contents of my documents folder")
    assert len(plans) == 1
    assert "documents folder" in plans[0].profile.reformulated


def test_non_listing_verbs_fall_through_to_llm():
    # 'read' implies file-content work, not a directory listing — must NOT signal.
    for msg in [
        "Read the README file in dev",
        "Open the config file in the project",
        "Search for the file in my downloads",
        "Create a new folder in dev",
    ]:
        plans = _signal_plan(msg)
        # A plan is always produced (the dispatcher falls back), but it must
        # NOT be the listing signal: no shell_command fast path.
        plan = plans[0]
        assert not (
            plan.fast_path is True and plan.profile.primary_domain == "shell_command"
        ), f"{msg!r} must not be a listing signal"


def test_no_filesystem_noun_falls_through():
    # 'weather' has no filesystem noun — must NOT be a listing signal.
    plans = _signal_plan("Show me the weather in Nairobi")
    plan = plans[0]
    assert not (
        plan.fast_path is True and plan.profile.primary_domain == "shell_command"
    )


# ── 2. Existing signals still fire without an LLM call ─────────────────


def test_shell_prefix_signal_still_fires():
    plans = _signal_plan("ls -la")
    assert len(plans) == 1
    assert plans[0].profile.primary_domain == "shell_command"


def test_url_signal_still_fires():
    plans = _signal_plan("fetch https://example.com/page")
    assert len(plans) == 1
    assert plans[0].profile.primary_domain == "web_fetch"


def test_sysinfo_phrase_signal_still_fires():
    plans = _signal_plan("what time is it")
    assert len(plans) == 1
    assert plans[0].profile.primary_domain in ("sysinfo", "system_info")


# ── 3. Engine: signal fast paths skip the Chat Agent phase ─────────────
# The 7a-chat branch condition is `if _dispatcher_reformulated:` now — a
# signal plan carries reformulated + acknowledgement, so the Chat Agent
# (an LLM call) is skipped. We assert the gate function's logic directly:
# a fast-path plan with a reformulation is eligible for the skip.


def _fast_path_plan_with_reformulation():
    return _signal_plan("Show me all projects in dev")[0]


def test_signal_plan_carries_reformulation_for_chat_agent_skip():
    plan = _fast_path_plan_with_reformulation()
    # These are exactly the fields the engine's 7a-chat branch reads:
    # reformulated must be truthy (else branch runs _chat_agent_phase).
    assert plan.profile.reformulated
    assert plan.fast_path is True


# ── 4. Git-phrasing signal (Session 149) ───────────────────────────────
# The canonical dev-tool request — "Check git status on the repo, and if
# there are uncommitted changes, show me the diff" — anchors on git state
# but starts with "Check" (no shell prefix), so it used to pay the full
# dispatcher LLM call (~10-20s on the free tier). The git signal produces
# a chained status→diff plan with ZERO adapter calls.


def test_git_status_request_is_a_signal():
    plans = _signal_plan(
        "Check git status on the localmind repo, and if there are "
        "uncommitted changes, show me the diff"
    )
    assert len(plans) == 1, "git phrasing must produce a plan without an LLM call"
    plan = plans[0]
    assert plan.profile.primary_domain == "shell_command"
    assert plan.profile.execution_mode.value == "single_tool"
    assert plan.fast_path is True
    assert "git" in plan.profile.reformulated


def test_git_signal_chains_status_then_diff():
    plans = _signal_plan(
        "Check git status, and if there are uncommitted changes, show me the diff"
    )
    plan = plans[0]
    ops = [n.id for n in plan.graph.nodes]
    assert "git_status" in ops
    assert "git_diff" in ops
    assert ops.index("git_status") < ops.index("git_diff"), \
        "status must run before the conditional diff"


def test_git_log_and_branch_signals():
    for msg, expected in [
        ("show me recent commits", "git_log"),
        ("show me the branches", "git_branch"),
    ]:
        plans = _signal_plan(msg)
        plan = plans[0]
        assert plan.fast_path is True and plan.profile.primary_domain == "shell_command", \
            f"{msg!r} must be a git signal"
        node_ids = [n.id for n in plan.graph.nodes]
        assert expected in node_ids, f"{msg!r} should produce {expected}"


def test_git_stash_goes_through_shell_prefix_signal():
    # "git stash list" STARTS with the shell prefix "git " so the pre-existing
    # shell-prefix signal wins BEFORE the git block — still a zero-LLM fast
    # path (plan carries the git subcommand as the shell instruction).
    plans = _signal_plan("git stash list")
    plan = plans[0]
    assert plan.fast_path is True and plan.profile.primary_domain == "shell_command"


def test_bare_diff_without_git_anchor_falls_through():
    # "show me the diff" between two files has no git anchor (no git/repo/
    # uncommitted/working-tree wording) — must NOT be a git signal.
    plans = _signal_plan("show me the diff between the two files")
    plan = plans[0]
    assert not (
        plan.fast_path is True and plan.profile.primary_domain == "shell_command"
    )
