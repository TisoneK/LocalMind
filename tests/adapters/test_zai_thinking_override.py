"""The one-shot thinking override (empty-after-reasoning fix).

Ground truth: glm-4.5-flash streams reasoning then 0 content ("thinks but
doesn't act"). The loop's empty-after-reasoning recovery sets
`_one_shot_thinking_off` so the RETRY forces thinking OFF and the model emits
the answer/tool-call directly. The flag must apply once, then clear itself.
"""

from adapters.openai_compat import OpenAICompatAdapter


def _zai_adapter(model="glm-4.5-flash"):
    a = OpenAICompatAdapter.__new__(OpenAICompatAdapter)
    a._provider_key = "zai"
    a._model = model
    return a


def test_one_shot_thinking_off_forces_disabled_then_clears(monkeypatch):
    a = _zai_adapter()
    # Isolate the flag logic from the real model-version/thinking helpers.
    a._zai_thinking_payload = lambda m: {"type": "enabled"}
    a._zai_model_version = lambda m: (4, 5)

    a._one_shot_thinking_off = True
    p1 = {}
    a._add_provider_params(p1)
    assert p1["thinking"] == {"type": "disabled"}, "one-shot must force thinking OFF"
    assert a._one_shot_thinking_off is False, "flag must clear after one use"

    # Next call (flag cleared) reverts to the normal enabled thinking.
    p2 = {}
    a._add_provider_params(p2)
    assert p2["thinking"] == {"type": "enabled"}


def test_no_flag_leaves_thinking_enabled(monkeypatch):
    a = _zai_adapter()
    a._zai_thinking_payload = lambda m: {"type": "enabled"}
    a._zai_model_version = lambda m: (4, 5)
    p = {}
    a._add_provider_params(p)
    assert p["thinking"] == {"type": "enabled"}


def test_one_shot_off_suppresses_reasoning_effort(monkeypatch):
    # A 5.2 model normally gets reasoning_effort; the forced-off retry must not.
    import core.config as cfg

    monkeypatch.setattr(cfg.settings, "localmind_reasoning_effort", "high", raising=False)
    a = _zai_adapter("glm-5.2")
    a._zai_thinking_payload = lambda m: {"type": "enabled"}
    a._zai_model_version = lambda m: (5, 2)
    a._one_shot_thinking_off = True
    p = {}
    a._add_provider_params(p)
    assert p["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in p, "forced-off retry must not also send reasoning_effort"
