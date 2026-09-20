from core.text_join import needs_paragraph_break as need


def test_prose_from_a_later_iteration_gets_a_break_after_a_tool_ran():
    assert need(["so let me install it and retry."], "I found the file", tools_now=2, tools_at_last_text=1)


def test_no_break_within_one_iteration_or_when_whitespace_already_separates():
    assert not need(["retry."], "I found", tools_now=1, tools_at_last_text=1)  # no tool between
    assert not need(["retry.\n\n"], "I found", tools_now=2, tools_at_last_text=1)  # already separated
    assert not need(["retry. "], "I found", tools_now=2, tools_at_last_text=1)
    assert not need(["retry."], " I found", tools_now=2, tools_at_last_text=1)  # new text leads with space
    assert not need([], "first words", tools_now=2, tools_at_last_text=0)  # nothing before
