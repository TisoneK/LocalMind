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
