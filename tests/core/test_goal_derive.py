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

from core.agent.goal_interpreter import derive_goal_items, derive_goal_tree


def test_goal_tree_matches_flat_checklist_and_adds_ordered_subgoals():
    """B-2026-08-23-8: every flat goal becomes a DerivedGoal whose sub-goals
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
    assert "create the folder src first" in tree[0].sub_goals[1]


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
