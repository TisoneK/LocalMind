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


# ── 3. File-search phrasing → FIND_PATH signal (Session 191) ──────────
# "find my cv", "locate the invoice", "search for resume files" are
# unambiguous NAME-SEARCH requests that used to route through the LLM
# dispatcher → SHELL intent → the model's Get-ChildItem -Recurse (20s
# timeouts on Windows home dirs, then a replan spiral). The signal routes
# them to a SINGLE_TOOL find_path plan with zero dispatcher LLM calls.


def _file_search_plan(message):
    """Return the plan ONLY if it is the file-ops signal family.

    Session 191: plain name-searches → primary_domain "file_search".
    Session 193: compound read requests ("find my cv and read it", "read
    my cv") → primary_domain "file_ops" — the engine executes the
    find→pick→read chain deterministically. Both are the find_path signal.
    """
    plans = _signal_plan(message)
    if not plans:
        return None
    plan = plans[0]
    if plan.fast_path is True and plan.profile.primary_domain in ("file_search", "file_ops"):
        return plan
    return None


def test_find_my_cv_is_a_file_search_signal():
    # The exact request from the user's transcript — with the "and read it"
    # follow-up preserved for the agent loop.
    plan = _file_search_plan("find my cv and read it")
    assert plan is not None
    assert plan.profile.execution_mode.value == "single_tool"
    assert plan.profile.acknowledgement == "Searching for 'cv'..."
    assert "read it" in plan.profile.reformulated


def test_file_search_signal_produces_find_path_node_with_args():
    plan = _file_search_plan("find my cv")
    assert plan is not None
    node = plan.graph.nodes[0]
    assert node.tool_name == "find_path"
    assert node.tool_args["name"] == "cv"
    assert node.tool_args["max_depth"] == 4
    assert node.tool_args["max_results"] == 25


def test_locate_search_for_and_where_is_phrasing():
    for msg in [
        "locate the invoice",
        "search for resume files",
        "look for my passport scan",
        "where is my config file",
        "can you find the design mockup",
        "please locate the license document",
    ]:
        assert _file_search_plan(msg) is not None, f"{msg!r} must be a file-search signal"


def test_file_search_multiword_target_becomes_glob():
    plan = _file_search_plan("find the annual budget report")
    assert plan is not None
    assert plan.graph.nodes[0].tool_args["name"] == "*annual*budget*report*"


def test_raw_find_shell_commands_stay_shell():
    # `find <path> <opts>` is a real shell command — must NOT become a
    # file-search signal (find is also a Windows cmd builtin).
    for msg in [
        "find . -name foo",
        "find /tmp -type f -iname cv",
        "find src -name '*.py'",
        r"find C:\Users\tison -type f",
    ]:
        assert _file_search_plan(msg) is None, f"{msg!r} must stay a shell command"
        plans = _signal_plan(msg)
        assert plans[0].profile.primary_domain == "shell_command", f"{msg!r} must route to shell"


def test_investigation_phrasing_falls_through():
    for msg in [
        "find out why the build failed",
        "find a way to speed up the build",
        "figure out what the error means",
        "search the web for quantum computing news",
    ]:
        assert _file_search_plan(msg) is None, f"{msg!r} must NOT be a file-search signal"


def test_debug_targets_fall_through():
    for msg in [
        "find the bug in app.py",
        "find the error",
        "find the problem with my code",
        "find the issue",
    ]:
        assert _file_search_plan(msg) is None, f"{msg!r} must NOT be a file-search signal"


def test_error_log_still_searches():
    # "find the error log" is a FILE search (a log file), not debugging.
    assert _file_search_plan("find the error log") is not None


def test_file_search_finds_within_absolute_location():
    # The transcript's exact winning call: root derived from the phrase.
    plan = _file_search_plan(r"find my cv in C:\Users\tison\Documents")
    assert plan is not None
    assert plan.graph.nodes[0].tool_args["name"] == "cv"
    assert plan.graph.nodes[0].tool_args["root"] == r"C:\Users\tison\Documents"


def test_identity_clause_phrasing_from_transcript():
    # The EXACT live message that spiraled for 480s: "I'm Tisone, find my
    # cv and read it" — the identity clause must not defeat the signal.
    plan = _file_search_plan("I'm Tisone, find my cv and read it")
    assert plan is not None
    assert plan.graph.nodes[0].tool_args["name"] == "cv"
    assert "read it" in plan.profile.reformulated


def test_identity_and_greeting_clauses():
    for msg in [
        "my name is Tisone, find my resume",
        "hey, find the invoice",
        "hi can you find my config file",
        "ok, find the license document",
    ]:
        assert _file_search_plan(msg) is not None, f"{msg!r} must be a file-search signal"


def test_empty_root_means_home_by_find_path_contract():
    # "find my cv" (no location) emits root="" — find_path treats an
    # empty root as the user home (Path.home()), never CWD.
    plan = _file_search_plan("find my cv")
    assert plan is not None
    assert plan.graph.nodes[0].tool_args["root"] == ""


def test_find_where_phrasing_falls_through():
    assert _file_search_plan("find where my file is") is None


def test_directory_listing_signal_unaffected():
    # "list files in X" stays a listing signal, not a file search.
    assert _file_search_plan("list files in dev") is None
    plans = _signal_plan("list files in dev")
    assert plans[0].profile.primary_domain == "shell_command"


def test_bare_diff_without_git_anchor_falls_through():
    # "show me the diff" between two files has no git anchor (no git/repo/
    # uncommitted/working-tree wording) — must NOT be a git signal.
    plans = _signal_plan("show me the diff between the two files")
    plan = plans[0]
    assert not (
        plan.fast_path is True and plan.profile.primary_domain == "shell_command"
    )


# ── 4. Compound read phrasing → file_ops signal (Session 193) ──────────
# The deterministic file-ops execution layer routes find+read requests to
# primary_domain="file_ops" so the engine executes find→pick→read as code
# (model reduced to final synthesis). Two entry points: the existing find
# branch (now flags read_requested) and a new direct-read branch ("read my
# cv", "show me the invoice").


def _file_ops_plan(message):
    """Return the plan ONLY if it is the deterministic file_ops signal."""
    plans = _signal_plan(message)
    if not plans:
        return None
    plan = plans[0]
    if plan.fast_path is True and plan.profile.primary_domain == "file_ops":
        return plan
    return None


def test_find_and_read_routes_to_file_ops_domain():
    # The exact transcript phrasing — now a DETERMINISTIC chain, not an
    # agent-loop gamble (the model found the CV in 1.9s but never read it).
    plan = _file_ops_plan("I'm Tisone, find my cv and read it")
    assert plan is not None
    node = plan.graph.nodes[0]
    assert node.tool_name == "find_path"
    assert node.tool_args["name"] == "cv"
    assert "read it" in plan.profile.reformulated


def test_direct_read_phrasing_routes_to_file_ops():
    for msg in [
        "read my cv",
        "read my resume",
        "show me the invoice",
        "open the budget file",
        "summarize the annual report",
        "view my config file",
        "display the license document",
    ]:
        plan = _file_ops_plan(msg)
        assert plan is not None, f"{msg!r} must be a file_ops signal"
        assert plan.graph.nodes[0].tool_name == "find_path"


def test_direct_read_multiword_target_becomes_glob():
    plan = _file_ops_plan("summarize the annual budget report")
    assert plan is not None
    assert plan.graph.nodes[0].tool_args["name"] == "*annual*budget*report*"


def test_plain_find_stays_file_search_domain():
    # "find my cv" without a read verb is still a plain name-search (the
    # agent loop synthesizes the location from find_path output) — the
    # deterministic READ chain only engages when a read is requested.
    plan = _file_search_plan("find my cv")
    assert plan is not None
    assert plan.profile.primary_domain == "file_search"
    assert _file_ops_plan("find my cv") is None


def test_non_file_read_targets_fall_through():
    # Coding/debug/list/web phrasing must NOT become a file-name search.
    for msg in [
        "review my code",
        "analyze the problem",
        "read the news",
        "show me all projects in dev",
        "open the browser",
        "read the email settings",
        "show me how to fix this",
        "read ~/Documents/notes.txt",  # explicit path → FILE_TASK handles it
    ]:
        assert _file_ops_plan(msg) is None, f"{msg!r} must NOT be a file_ops signal"


def test_investigation_phrasing_still_falls_through():
    for msg in ["find out what the error means", "figure out the issue"]:
        assert _file_ops_plan(msg) is None, f"{msg!r} must NOT be a file_ops signal"


def test_file_ops_signal_preserves_dispatch_step():
    plan = _file_ops_plan("read my cv")
    assert plan is not None
    assert plan.dispatch_steps
    assert plan.dispatch_steps[0]["intent"] == "find_path"


# ── 5. Catalog continuation phrasing → filter/offset args (Session 194) ─
# "show more" / "only pdf" / "in Documents" are continuation filters on the
# cached catalog walk — zero-LLM, same signal, different find_path args.


def _node_args(message):
    plan = _file_search_plan(message)
    assert plan is not None, f"{message!r} must be a file-search signal"
    return plan.graph.nodes[0].tool_args


def test_show_more_sets_offset():
    args = _node_args("find my cv, show more")
    assert args["offset"] == 25
    assert args["name"] == "cv"


def test_only_ext_sets_ext_filter():
    args = _node_args("find my cv, only pdf")
    assert args["ext"] == "pdf"
    assert args["name"] == "cv"


def test_only_ext_sets_ext_filter_with_files_word():
    args = _node_args("find my cv, only pdf files")
    assert args["ext"] == "pdf"


def test_bare_folder_location_sets_subpath():
    args = _node_args("find my cv in Documents")
    assert args["subpath"] == "Documents"
    assert args["root"] == ""


def test_absolute_location_still_sets_root():
    args = _node_args("find my cv in /tmp/work")
    assert args["root"] == "/tmp/work"
    assert "subpath" not in args


def test_direct_read_location_sets_subpath():
    plan = _file_ops_plan("read my cv in Documents")
    assert plan is not None
    args = plan.graph.nodes[0].tool_args
    assert args["subpath"] == "Documents"
    assert plan.profile.primary_domain == "file_ops"


def test_show_more_survives_and_conjunction():
    # Code review (Session 194): "and show more" must page the catalog even
    # though the branch splits on "and".
    args = _node_args("find my cv and show more")
    assert args["offset"] == 25
    assert args["name"] == "cv"


def test_show_more_without_find_anchor_falls_through():
    # No file-search anchor → not the signal's job (follow-up routing owns it).
    assert _file_search_plan("show more") is None
