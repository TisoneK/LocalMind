"""
Tests for the message-derived goal checklist (Session 330, B-2026-08-20-23).

derive_goal_items() is the FIXED denominator for the acceptance gate on the
warm-kernel parent path: the user's request defines the deliverables, so
completion is gated on evidence against THESE items — never on what tools
happened to run (the self-mutating checklist bug the user diagnosed).

Conservative by design: a named file becomes a goal item ONLY when the
message commits to writing it; conversational/abstract requests derive []
(no contract — legacy path unchanged).
"""

from __future__ import annotations

from core.agent.goal_interpreter import (
    _title_for_goal,
    _title_for_sub_goal,
    derive_goal_items,
    derive_goal_tree,
)


def test_goal_tree_matches_flat_checklist_and_adds_ordered_subgoals():
    """Every flat goal becomes a DerivedGoal whose sub-goals
    spell the fastest+safest ordered route (check → prep → write → verify)."""
    tree = derive_goal_tree(
        'In Dev/, create a folder called path-test. Inside it, create two '
        'files: a.txt with "first" and b.txt with "second".'
    )
    flat = derive_goal_items(
        'In Dev/, create a folder called path-test. Inside it, create two '
        'files: a.txt with "first" and b.txt with "second".'
    )
    assert [g.goal for g in tree] == flat
    # The file goal's route spells check → folder prep → write → verify,
    # each feeding the next.
    file_goal = next(g for g in tree if g.goal.startswith("file exists at a.txt"))
    assert file_goal.sub_goals[0].startswith("check whether a.txt")
    assert file_goal.sub_goals[1].startswith("write a.txt")
    assert file_goal.sub_goals[-1].startswith("verify a.txt")
    assert len(file_goal.sub_goals) <= 4


def test_goal_tree_folder_route_checks_before_creating():
    tree = derive_goal_tree("create a folder called path-test")
    folder_goal = tree[0]
    assert folder_goal.goal == "folder created at path-test"
    assert folder_goal.sub_goals[0].startswith("check whether the folder path-test")
    assert "only if it is missing" in folder_goal.sub_goals[1]
    assert folder_goal.sub_goals[-1].startswith("verify the folder path-test")


def test_goal_tree_nested_path_includes_parent_folder_prep():
    tree = derive_goal_tree("create src/utils/helper.py with a helper function")
    assert tree[0].goal == "file exists at src/utils/helper.py with content"
    # A nested path routes through its parent folder before writing.
    assert "create the folder src/utils first" in tree[0].sub_goals[1]


def test_goal_tree_empty_when_flat_is_empty():
    assert derive_goal_tree("hello there") == []
    assert derive_goal_tree("") == []


def test_goal_tree_bounded_like_flat():
    msg = "create " + " and ".join(f"f{i}.txt" for i in range(20))
    tree = derive_goal_tree(msg)
    assert len(tree) <= 6
    assert all(g.sub_goals for g in tree)


def test_path_test_task_derives_fixed_checklist():
    """The user's exact failing task: folder + two files -> 3 fixed items."""
    items = derive_goal_items(
        'In Dev/, create a folder called path-test. Inside it, create two '
        'files: a.txt with "first" and b.txt with "second". Then read both '
        'back and tell me if either one is empty or truncated.'
    )
    assert items == [
        "file exists at a.txt with content",
        "file exists at b.txt with content",
        "folder created at path-test",
    ]


def test_notes_txt_task():
    items = derive_goal_items(
        'Create a folder called test-run in Dev/, write a file inside it '
        'called notes.txt with the text "hello from deepseek", then read the '
        'file back to me.'
    )
    assert items == [
        "file exists at notes.txt with content",
        "folder created at test-run",
    ]


def test_conversational_and_abstract_messages_derive_nothing():
    for msg in (
        "hi how are you",
        "list my dev folder",
        "check git status",
        "run the tests and fix any failures",
        "write me a poem about the sea",
        "open config.json and show me its contents",  # read-only mention
    ):
        assert derive_goal_items(msg) == [], msg


def test_nested_path_file():
    items = derive_goal_items("create src/utils/helper.py with a helper function")
    assert items == ["file exists at src/utils/helper.py with content"]


def test_update_verb_counts_as_write():
    items = derive_goal_items("update README.md to mention the new endpoint")
    assert items == ["file exists at README.md with content"]


def test_quoted_folder_name_kept_whole():
    items = derive_goal_items('create a folder called "my stuff" and a file notes.txt in it')
    # The quoted multi-word name survives whole; the partial unquoted match
    # ("my") is dropped, not the longer name.
    assert items == [
        "file exists at notes.txt with content",
        "folder created at my stuff",
    ]


def test_folder_name_trailing_punctuation_stripped():
    items = derive_goal_items("create a folder called path-test.")
    assert items == ["folder created at path-test"]


def test_empty_and_blank_messages():
    assert derive_goal_items("") == []
    assert derive_goal_items("   ") == []


def test_max_items_bounded():
    msg = "create " + " and ".join(f"f{i}.txt" for i in range(20))
    items = derive_goal_items(msg)
    assert len(items) <= 6
    assert all(item.startswith("file exists at") for item in items)


# ── Session 382 follow-up: workspace-relative goal derivation ───────────────


def test_base_dir_resolves_bare_file_onto_workspace():
    items = derive_goal_items(
        "create a.txt and b.txt",
        base_dir="/ws/sess-1",
    )
    assert items == [
        "file exists at /ws/sess-1/a.txt with content",
        "file exists at /ws/sess-1/b.txt with content",
    ]


def test_base_dir_resolves_folder_onto_workspace():
    items = derive_goal_items(
        "create a folder called path-test",
        base_dir="/ws/sess-1",
    )
    assert items == ["folder created at /ws/sess-1/path-test"]


def test_base_dir_resolves_nested_relative_onto_workspace():
    items = derive_goal_items(
        "create src/utils/helper.py",
        base_dir="/ws/sess-1",
    )
    assert items == ["file exists at /ws/sess-1/src/utils/helper.py with content"]


def test_base_dir_leaves_explicit_absolute_path_verbatim():
    items = derive_goal_items(
        "update /Users/me/README.md",
        base_dir="/ws/sess-1",
    )
    assert items == ["file exists at /Users/me/README.md with content"]


def test_base_dir_none_keeps_legacy_bare_tokens():
    items = derive_goal_items("create a.txt")
    assert items == ["file exists at a.txt with content"]


def test_title_for_goal_is_short_and_verb_led():
    # User sees a short label, not the full path.
    assert _title_for_goal("file exists at /ws/sess-1/path-test/a.txt with content") == "Create a.txt"
    assert _title_for_goal("file exists at a.txt with content") == "Create a.txt"
    assert _title_for_goal("folder created at /ws/sess-1/path-test") == "Create the folder path-test"
    assert _title_for_goal("garbage nonsense") == "garbage nonsense"


def test_title_for_sub_goal_is_short():
    long_check = (
        "check whether /ws/path-test/a.txt already exists (read it if so)"
    )
    assert _title_for_sub_goal(long_check) == "Check current state"
    assert _title_for_sub_goal("write /ws/path-test/a.txt with the full content") == "Write the file"
    assert _title_for_sub_goal("verify /ws/path-test/a.txt exists with the expected content") == "Verify the result"
    assert _title_for_sub_goal("create the folder /ws/path-test first if it is missing") == "Create path-test"


def test_goal_tree_sets_titles():
    tree = derive_goal_tree(
        "create a folder called path-test and a file a.txt in it",
        base_dir="/ws/sess-1",
    )
    assert any(g.title == "Create the folder path-test" for g in tree)
    assert any(g.title == "Create a.txt" for g in tree)


def test_goal_tree_route_uses_workspace_resolved_path():
    tree = derive_goal_tree(
        "In my workspace, create a folder called path-test. Inside it "
        "create a.txt.",
        base_dir="/ws/sess-1",
    )
    a_goal = next(g for g in tree if g.goal.startswith("file exists at"))
    assert a_goal.goal == "file exists at /ws/sess-1/a.txt with content"
    assert a_goal.sub_goals[0].startswith("check whether /ws/sess-1/a.txt")
    # The parent IS the workspace root → no redundant "create the folder"
    # prep step (the harness creates the workspace).
    assert not any("create the folder" in s for s in a_goal.sub_goals)
    assert a_goal.sub_goals[1].startswith("write /ws/sess-1/a.txt")
    folder_goal = next(g for g in tree if g.goal.startswith("folder created at"))
    assert folder_goal.goal == "folder created at /ws/sess-1/path-test"


# ── Reading-prose must never fabricate a creation contract ───────────────────
#
# A long message can PASTE background prose for reading ("read this and
# answer one question"). Words inside that prose are content, not the
# user's instruction. Before the same-sentence rule, a whole-message
# substring match let "every new hire" supply the folder verb for "a
# folder convention that everybody tolerated" — the extractor invented a
# "folder created at …" goal, the model obediently mkdir'd it in its
# session workspace to satisfy the acceptance gate, and the user got a
# fabricated "✓ 1/1 criteria met (folder created at …)" line. The fix:
# word-boundary verbs + verb and artifact committed in the SAME sentence.

_OTT19_STYLE_PROSE = (
    "Please read this background and then answer ONE question at the end. "
    "On the tools side we migrated our document store twice, first to a "
    "self-hosted wiki that nobody liked, then to a folder convention that "
    "everybody tolerated. Each new hire shadows a senior consultant and "
    "presents one insight at the Friday forum. Maria's favorite color is "
    "teal. Question: what is Maria's favorite color?"
)


def test_reading_prose_with_incidental_folder_words_derives_nothing():
    assert derive_goal_items(_OTT19_STYLE_PROSE) == []
    assert derive_goal_items(_OTT19_STYLE_PROSE, base_dir="/ws/sess-1") == []
    assert derive_goal_tree(_OTT19_STYLE_PROSE, base_dir="/ws/sess-1") == []


def test_verbs_do_not_leak_across_sentences():
    # 'new' is a whole word here but nowhere near a folder/file commit;
    # the config.json mention sits in a read-only sentence.
    msg = (
        "Renew my subscription. The config.json file in the old folder "
        "is stale - just tell me what it contains."
    )
    assert derive_goal_items(msg) == []


def test_word_boundary_verb_required_not_substring():
    # 'renew'/'mistakes' must not count as 'new'/'make' commitments.
    assert derive_goal_items("I made some mistakes. Where does data.txt go?") == []
    assert derive_goal_items("Renew everything about notes.txt") == []


def test_same_sentence_commit_with_determiner_still_derives():
    # 'new' as a determiner INSIDE the committing sentence remains a
    # legitimate create-shape ("make the new reports folder called X").
    items = derive_goal_items("make the new reports folder called monthly-data")
    assert items == ["folder created at monthly-data"]


def test_multi_sentence_request_keeps_all_legit_items():
    msg = (
        "Create a folder called project-notes. Inside it, write a summary.md "
        "with the key points."
    )
    items = derive_goal_items(msg, base_dir="/ws/s-1")
    assert items == [
        "file exists at /ws/s-1/summary.md with content",
        "folder created at /ws/s-1/project-notes",
    ]
