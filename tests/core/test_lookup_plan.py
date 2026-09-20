"""The upfront plan for a request that needs live information."""
from core.agent.lookup_plan import LOOKUP_STEPS, derive_lookup_plan, request_needs_live_lookup


class TestRequestNeedsLiveLookup:
    def test_real_messy_lookup_requests_match(self):
        for q in (
            "whats the weather like in nairobi rn",
            "what's the weather in kitengela",
            "latest arsenal score",
            "who won the match yesterday",
            "current exchange rate for usd to kes",
            "any news on the election today",
            "look up the release date of the new iphone",
            "search the web for the best pizza in westlands",
            "is the airport open right now",
        ):
            assert request_needs_live_lookup(q), q

    def test_local_and_grounded_questions_do_not(self):
        for q in (
            "whts the size of my disk that is empty",
            "how much free disk space do i have",
            "what day is it today",
            "what time is it right now",
            "read the latest file in my downloads folder",
            "show me the latest commit on this branch",
            "delete the logs from today",
            "write a script that prints the weather",
        ):
            assert not request_needs_live_lookup(q), q

    def test_chat_and_short_messages_do_not(self):
        for q in ("hey", "hi there", "thanks", "what can you do", "", "weather"):
            assert not request_needs_live_lookup(q), q


def test_the_plan_is_the_three_lookup_steps_or_nothing():
    assert derive_lookup_plan("whats the weather like in nairobi rn") == list(LOOKUP_STEPS)
    assert len(LOOKUP_STEPS) == 3
    assert derive_lookup_plan("how much free disk space do i have") == []


def test_the_init_safety_net_uses_the_same_steps():
    from core.agent.initialization import ensure_upfront_plan
    from core.models import Intent

    assert ensure_upfront_plan([], Intent.WEB_SEARCH) == list(LOOKUP_STEPS)


def test_finished_tools_complete_the_matching_step():
    from core.agent.lookup_plan import lookup_step_for_tool

    assert lookup_step_for_tool("web_search") == 0
    assert lookup_step_for_tool("web_fetch") == 1
    assert lookup_step_for_tool("browse") == 1
    assert lookup_step_for_tool("shell") is None


def test_the_step_wording_is_true_for_snippets_and_for_a_page():
    # "Read the best source" claimed a page was opened; "Check the sources" holds either way.
    assert LOOKUP_STEPS[1] == "Check the sources"


class TestLookupStepLabel:
    def test_a_search_names_what_is_being_searched(self):
        from core.agent.lookup_plan import lookup_step_label

        assert lookup_step_label("web_search", "nairobi traffic news today") == (
            0, "Search the web for nairobi traffic news today",
        )

    def test_a_page_read_names_the_site(self):
        from core.agent.lookup_plan import lookup_step_label

        assert lookup_step_label("web_fetch", "https://www.wttr.in/Kisumu?format=j1") == (1, "Read wttr.in")
        assert lookup_step_label("web_fetch", "livescore.com/en/football") == (1, "Read livescore.com")

    def test_long_queries_are_cut_and_only_the_first_line_is_used(self):
        from core.agent.lookup_plan import lookup_step_label

        idx, label = lookup_step_label("web_search", "x" * 200 + "\nsecond line")
        assert idx == 0 and len(label) <= len("Search the web for ") + 60 and "second" not in label

    def test_other_tools_and_empty_input_give_nothing(self):
        from core.agent.lookup_plan import lookup_step_label

        assert lookup_step_label("shell", "ls") is None
        assert lookup_step_label("web_search", "  ") is None
        assert lookup_step_label("web_fetch", "") is None


class TestFollowupSteps:
    GOAL = ["file exists at /w/shopping.txt with content"]

    def test_the_live_request_gets_its_edit_and_show_steps(self):
        from core.agent.lookup_plan import derive_followup_steps

        msg = (
            "make a file called shopping.txt with milk, eggs and bread on separate lines, "
            "then add tea to the end of it and show me what's in it"
        )
        assert derive_followup_steps(msg, self.GOAL) == ["Add tea to the file", "Show you the result"]

    def test_read_it_back_and_listing_count_as_showing(self):
        from core.agent.lookup_plan import derive_followup_steps

        steps = derive_followup_steps("create notes.txt with hello then read it back", self.GOAL)
        assert steps == ["Show you the result"]
        assert derive_followup_steps("create a.txt with x and list the folder", self.GOAL) == ["Show you the result"]

    def test_a_plain_create_adds_nothing(self):
        from core.agent.lookup_plan import derive_followup_steps

        assert derive_followup_steps("create notes.txt containing hello", self.GOAL) == []

    def test_no_goals_means_no_extras(self):
        from core.agent.lookup_plan import derive_followup_steps

        assert derive_followup_steps("then add tea to it and show me", []) == []


class TestSequencePlan:
    def test_the_live_shell_request_becomes_three_steps_in_the_users_words(self):
        from core.agent.lookup_plan import derive_sequence_plan

        msg = "run ls in the workspace then try to cat a file called nope.txt and tell me what happened"
        assert derive_sequence_plan(msg) == [
            "Run ls in the workspace",
            "Try to cat a file called nope.txt",
            "Tell you what happened",
        ]

    def test_other_explicit_sequences(self):
        from core.agent.lookup_plan import derive_sequence_plan

        assert derive_sequence_plan("open the log, then count the errors, then show me the top three") == [
            "Open the log", "Count the errors", "Show you the top three",
        ]
        assert derive_sequence_plan("check the disk; after that clean the temp folder") == [
            "Check the disk", "Clean the temp folder",
        ]

    def test_a_single_action_or_plain_chat_is_not_a_sequence(self):
        from core.agent.lookup_plan import derive_sequence_plan

        for q in ("run ls in the workspace", "then", "hey what's up", "tell me a joke and make it short", ""):
            assert derive_sequence_plan(q) == [], q

    def test_it_is_capped_and_never_invents_words(self):
        from core.agent.lookup_plan import derive_sequence_plan

        msg = "do a, then do b, then do c, then do d, then do e, then do f, then do g"
        steps = derive_sequence_plan(msg)
        assert len(steps) == 5
        assert all(s.split()[0] in {"Do"} for s in steps)
