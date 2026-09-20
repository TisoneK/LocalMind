"""Display-only plan rows that come from what the request says (follow-ons and its own sequence).

There is intentionally no canned plan for open-ended lookups: see the module docstring.
"""

from core.agent.lookup_plan import derive_followup_steps, derive_sequence_plan


def test_there_is_no_canned_lookup_plan_any_more():
    import core.agent.lookup_plan as lp

    assert not hasattr(lp, "LOOKUP_STEPS") and not hasattr(lp, "derive_lookup_plan")


class TestFollowupSteps:
    GOAL = ("file exists at /w/shopping.txt with content",)

    def test_the_live_request_gets_its_edit_and_show_steps(self):

        msg = (
            "make a file called shopping.txt with milk, eggs and bread on separate lines, "
            "then add tea to the end of it and show me what's in it"
        )
        assert derive_followup_steps(msg, list(self.GOAL)) == ["Add tea to the file", "Show you the result"]

    def test_read_it_back_and_listing_count_as_showing(self):

        steps = derive_followup_steps("create notes.txt with hello then read it back", self.GOAL)
        assert steps == ["Show you the result"]
        assert derive_followup_steps("create a.txt with x and list the folder", self.GOAL) == ["Show you the result"]

    def test_a_plain_create_adds_nothing(self):

        assert derive_followup_steps("create notes.txt containing hello", self.GOAL) == []

    def test_no_goals_means_no_extras(self):

        assert derive_followup_steps("then add tea to it and show me", []) == []


class TestSequencePlan:
    def test_the_live_shell_request_becomes_three_steps_in_the_users_words(self):

        msg = "run ls in the workspace then try to cat a file called nope.txt and tell me what happened"
        assert derive_sequence_plan(msg) == [
            "Run ls in the workspace",
            "Try to cat a file called nope.txt",
            "Tell you what happened",
        ]

    def test_other_explicit_sequences(self):

        assert derive_sequence_plan("open the log, then count the errors, then show me the top three") == [
            "Open the log", "Count the errors", "Show you the top three",
        ]
        assert derive_sequence_plan("check the disk; after that clean the temp folder") == [
            "Check the disk", "Clean the temp folder",
        ]

    def test_a_single_action_or_plain_chat_is_not_a_sequence(self):

        for q in ("run ls in the workspace", "then", "hey what's up", "tell me a joke and make it short", ""):
            assert derive_sequence_plan(q) == [], q

    def test_it_is_capped_and_never_invents_words(self):

        msg = "do a, then do b, then do c, then do d, then do e, then do f, then do g"
        steps = derive_sequence_plan(msg)
        assert len(steps) == 5
        assert all(s.split()[0] in {"Do"} for s in steps)


def test_a_browser_task_is_named_by_the_site_not_by_its_json():
    from core.agent.loop import _synthetic_todo_text

    label = _synthetic_todo_text("browse", '{"action": "open", "url": "https://www.premierleague.com/en/matches"}')
    assert label == "Open premierleague.com"
    assert _synthetic_todo_text("web_search", "epl scores") == "Search: epl scores"
