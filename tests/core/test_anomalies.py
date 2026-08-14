"""Session 123: anomaly detection for the Observe panel.

The detectors are pure functions in core.anomalies — these tests lock the
exact failure shapes the user reported:
- STALL: "it hung for 108.6s and returned 23 tokens" (Session 115).
- TOKEN_LEAK: "prompt: 5705 on a new chat, close to the previous attempt's
  5653 — context did not reset between chats" (Session 115/117).
"""

from core.anomalies import (
    detect_stall,
    detect_token_leak,
    detect_turn_anomalies,
)


class TestDetectStall:
    def test_108s_with_23_tokens_is_a_stall(self):
        a = detect_stall(latency_ms=108_600, completion_tokens=23)
        assert a is not None
        assert a["kind"] == "stall"
        assert a["severity"] == "high"
        assert a["metrics"]["latency_ms"] == 108_600

    def test_120s_with_43_tokens_is_a_stall(self):
        # The exact second reported failure (120.2s / 43 tokens).
        a = detect_stall(latency_ms=120_200, completion_tokens=43)
        assert a is not None

    def test_slow_but_real_output_is_not_a_stall(self):
        # 65s / 300 tokens ≈ 4.6 tok/s — slow but productive.
        a = detect_stall(latency_ms=65_000, completion_tokens=300)
        assert a is None

    def test_under_latency_threshold_never_stalls(self):
        # 30s / 5 tokens is slow but below the 60s floor — not a stall.
        a = detect_stall(latency_ms=30_000, completion_tokens=5)
        assert a is None

    def test_zero_latency_is_not_a_stall(self):
        assert detect_stall(latency_ms=0, completion_tokens=0) is None


class TestDetectTokenLeak:
    def test_fresh_session_matching_previous_turn_is_a_leak(self):
        # 5705 vs 5653 — within 1%, the exact user-reported shape.
        a = detect_token_leak(
            session_id="session-new-chat",
            context_tokens=5705,
            is_first_turn=True,
            prev_prompt_tokens=5653,
            prev_session_id="session-old-chat",
        )
        assert a is not None
        assert a["kind"] == "token_leak"
        assert a["metrics"]["context_tokens"] == 5705

    def test_small_prompt_on_fresh_session_is_not_a_leak(self):
        a = detect_token_leak(
            session_id="session-new-chat",
            context_tokens=2000,  # system prompt + short message — normal
            is_first_turn=True,
            prev_prompt_tokens=5653,
            prev_session_id="session-old-chat",
        )
        assert a is None

    def test_continuation_of_same_session_is_not_a_leak(self):
        # Same session continuing a conversation — high prompt is expected.
        a = detect_token_leak(
            session_id="session-a",
            context_tokens=5705,
            is_first_turn=False,
            prev_prompt_tokens=5653,
            prev_session_id="session-a",
        )
        assert a is None

    def test_very_different_count_is_not_a_leak(self):
        a = detect_token_leak(
            session_id="session-new-chat",
            context_tokens=9000,  # way off from 5653 — not a carry-over
            is_first_turn=True,
            prev_prompt_tokens=5653,
            prev_session_id="session-old-chat",
        )
        assert a is None

    def test_no_previous_turn_is_not_a_leak(self):
        a = detect_token_leak(
            session_id="session-new-chat",
            context_tokens=5705,
            is_first_turn=True,
            prev_prompt_tokens=None,
            prev_session_id=None,
        )
        assert a is None


class TestDetectTurnAnomalies:
    def test_clean_turn_has_no_anomalies(self):
        out = detect_turn_anomalies(
            session_id="s1",
            latency_ms=2_300,
            completion_tokens=145,
            context_tokens=180,
            is_first_turn=True,
            prev_prompt_tokens=0,
            prev_session_id="",
        )
        assert out == []

    def test_stall_turn_is_flagged(self):
        out = detect_turn_anomalies(
            session_id="s1",
            latency_ms=108_600,
            completion_tokens=23,
            context_tokens=5705,
            is_first_turn=False,
            prev_prompt_tokens=5653,
            prev_session_id="s0",
        )
        kinds = [a["kind"] for a in out]
        assert "stall" in kinds
        assert "token_leak" not in kinds  # not a first turn

    def test_fresh_leak_turn_is_flagged(self):
        out = detect_turn_anomalies(
            session_id="s2",
            latency_ms=2_500,
            completion_tokens=200,
            context_tokens=5705,
            is_first_turn=True,
            prev_prompt_tokens=5653,
            prev_session_id="s1",
        )
        kinds = [a["kind"] for a in out]
        assert "token_leak" in kinds
        assert "stall" not in kinds  # fast turn


class TestEngineWiring:
    """Engine._store_observation must actually EMIT anomaly obs events and
    merge them into the stored observation (the pure detectors are tested
    above; this locks the integration)."""

    @staticmethod
    def _engine(monkeypatch, tmp_path):
        from core.config import settings
        from core.engine import Engine

        db_path = str(tmp_path / "anomalies.db")
        monkeypatch.setenv("LOCALMIND_DB_PATH", db_path)
        monkeypatch.setattr(settings, "localmind_db_path", db_path)
        return Engine()

    def test_store_observation_emits_stall_anomaly(self, monkeypatch, tmp_path):
        from core.obs import ObsCollector

        engine = self._engine(monkeypatch, tmp_path)
        obs = ObsCollector()
        # Seed the request collector with the turn_complete carrying the
        # completion-token count (what _store_observation reads back).
        obs.emit("turn_complete", tokens_approx=23, intent="chat", total_latency_ms=108_600)
        engine._store_observation(
            "session-a",
            obs,
            intent="chat",
            confidence=0.9,
            tools_used="",
            memory_hits=0,
            context_tokens=300,
            latency_ms=108_600,
        )
        anomaly_events = [e for e in obs.history() if e.type == "anomaly"]
        assert len(anomaly_events) == 1
        assert anomaly_events[0].data.get("kind") == "stall"
        stored = engine._last_observation["session-a"]["anomalies"]
        assert stored[0]["kind"] == "stall"
        # Tracker advanced even though detection ran.
        assert engine._last_turn_session_id == "session-a"

    def test_store_observation_emits_token_leak_on_new_chat(self, monkeypatch, tmp_path):
        from core.obs import ObsCollector

        engine = self._engine(monkeypatch, tmp_path)
        # Turn 1: a heavy shell turn in session-a.
        obs1 = ObsCollector()
        obs1.emit("turn_complete", tokens_approx=200, intent="shell", total_latency_ms=2_000)
        engine._store_observation(
            "session-a", obs1, intent="shell", tools_used="", memory_hits=0,
            context_tokens=5653, latency_ms=2_000,
        )
        # Turn 2: a NEW session's first turn with a near-identical count.
        obs2 = ObsCollector()
        obs2.emit("turn_complete", tokens_approx=200, intent="shell", total_latency_ms=2_000)
        engine._store_observation(
            "session-b", obs2, intent="shell", tools_used="", memory_hits=0,
            context_tokens=5705, latency_ms=2_000,
        )
        leak_events = [e for e in obs2.history() if e.type == "anomaly"]
        assert len(leak_events) == 1
        assert leak_events[0].data.get("kind") == "token_leak"

    def test_normal_turn_emits_no_anomaly(self, monkeypatch, tmp_path):
        from core.obs import ObsCollector

        engine = self._engine(monkeypatch, tmp_path)
        obs = ObsCollector()
        obs.emit("turn_complete", tokens_approx=145, intent="chat", total_latency_ms=2_300)
        engine._store_observation(
            "session-a", obs, intent="chat", tools_used="", memory_hits=0,
            context_tokens=180, latency_ms=2_300,
        )
        assert [e for e in obs.history() if e.type == "anomaly"] == []
        assert "anomalies" not in engine._last_observation["session-a"]

    def test_cleanup_session_resets_leak_tracker(self, monkeypatch, tmp_path):
        from core.obs import ObsCollector

        engine = self._engine(monkeypatch, tmp_path)
        obs = ObsCollector()
        obs.emit("turn_complete", tokens_approx=200, intent="chat", total_latency_ms=2_000)
        engine._store_observation(
            "session-a", obs, intent="chat", tools_used="", memory_hits=0,
            context_tokens=5000, latency_ms=2_000,
        )
        assert engine._last_turn_session_id == "session-a"
        engine.cleanup_session("session-a")
        assert engine._last_turn_prompt_tokens == 0
        assert engine._last_turn_session_id == ""
