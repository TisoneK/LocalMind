"""DeepSeek's tool-call markup comes in more than one spelling; every one must be run as a tool call, never shown."""

import pytest
from core.agent.text_tools import (
    _has_minimax_tool_call,
    _parse_minimax_tool_call,
    _strip_minimax_tool_calls,
)

SINGLE = '<｜DSML｜tool_calls><｜DSML｜invoke name="web_fetch"><｜DSML｜parameter name="url" string="true">https://a.example</｜DSML｜parameter></｜DSML｜invoke></｜DSML｜tool_calls>'
DOUBLE = '<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="search_tool_results">\n<｜｜DSML｜｜ parameter name="result_id" string="true">web_fetch-79e5</｜｜DSML｜｜ parameter>\n</｜｜DSML｜｜ invoke>\n</｜｜DSML｜｜ calls>'


@pytest.mark.parametrize("markup,name,arg", [(SINGLE, "web_fetch", "url"), (DOUBLE, "search_tool_results", "result_id")])
def test_every_spelling_is_parsed_as_a_tool_call(markup, name, arg):
    assert _has_minimax_tool_call(markup)
    calls = _parse_minimax_tool_call(markup)
    assert len(calls) == 1 and calls[0][0] == name and arg in calls[0][1]


@pytest.mark.parametrize("markup", [SINGLE, DOUBLE])
def test_none_of_it_survives_into_the_answer(markup):
    cleaned = _strip_minimax_tool_calls("I'll check.\n\n" + markup)
    assert "DSML" not in cleaned and "invoke" not in cleaned and cleaned.strip() == "I'll check."
