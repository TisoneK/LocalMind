"""
Session 33 regression test: the engine fallback must NOT call _obs.drain()
(destructive) — it must use _obs.all() (read-only).

The bug: Session 32's engine fallback called _obs.drain() to check for
agent_loop_done with hit_limit=True. But drain() CLEARS the event list,
and the SSE bridge at chat.py:129 ALSO calls drain() to forward events
to the frontend. The fallback's drain() stole the events (including
tool_status=done) before the SSE bridge could forward them, so the
frontend's "Running command" spinner never cleared.

This test verifies the engine fallback uses _obs.all() (read-only), not
_obs.drain() (destructive).
"""

from __future__ import annotations

from pathlib import Path


def test_engine_fallback_does_not_call_obs_drain():
    """The engine fallback source must NOT call _obs.drain() in actual code
    — it must use _obs.all() (read-only). drain() steals events from the
    SSE bridge."""

    runtime_path = (
        Path(__file__).resolve().parent.parent.parent
        / "backend" / "src" / "core" / "agent_runtime.py"
    )
    source = runtime_path.read_text()

    # The parent runtime inspects collector history without consuming the
    # event stream; the SSE route remains the only destructive consumer.
    assert "collector.history()" in source

    # Check that _obs.drain() does NOT appear as actual CODE (only in comments).
    # Strip comments and check the remaining code.
    # Remove Python comments (lines starting with #, or inline # comments)
    code_lines = []
    for line in source.splitlines():
        # Remove inline comments (simple approach — doesn't handle strings
        # with # but good enough for this check)
        if '#' in line:
            line = line[:line.index('#')]
        code_lines.append(line)
    code_only = '\n'.join(code_lines)

    assert ".drain(" not in code_only, (
        "The parent runtime must not consume the observation stream; "
        "the SSE bridge owns draining."
    )


def test_obs_all_does_not_clear_events():
    """_obs.all() must return a COPY of the events list — it must NOT
    clear the original list. This is what makes it safe to use in the
    engine fallback without stealing events from the SSE bridge."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend" / "src"))
    from core.obs import ObsCollector

    obs = ObsCollector()
    obs.emit("test_event", value=1)
    obs.emit("agent_loop_done", hit_limit=True, iterations=3)

    # all() should return the events WITHOUT clearing
    events_copy = obs.all()
    assert len(events_copy) == 2, f"all() should return 2 events, got {len(events_copy)}"

    # The original list must still have the events
    events_after_all = obs.all()
    assert len(events_after_all) == 2, (
        "all() must NOT clear the events list — the SSE bridge needs to "
        "drain() them later to forward to the frontend."
    )

    # drain() SHOULD clear (that's its job)
    drained = obs.drain()
    assert len(drained) == 2, "drain() should return the 2 events"
    assert len(obs.all()) == 0, "drain() should clear the list"
