"""The State Explorer page and its live SSE stream (experimental, read-only engine — ADR-71)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.routes import state_engine as route
from core.state_engine import Evaluation, Move, Observation
from core.state_engine.llm import parse_json
from core.state_engine.search import StateEngine


class _Proposer:
    async def propose(self, state, n, avoid):
        return [Move("dir_explorer", {"operation": "list", "path": "/x"}, "look")]


class _Executor:
    async def run(self, move):
        return Observation(move, True, "a.txt b.txt")


class _Evaluator:
    async def evaluate(self, state, outcomes):
        return [Evaluation(1.0, True, "2 files", "settled") for _ in outcomes]


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(route, "_provider_and_model", lambda: ("stub", "stub-model"))
    monkeypatch.setattr(
        route, "_make_engine",
        lambda budget: StateEngine(
            None, executor=_Executor(), proposer=_Proposer(), evaluator=_Evaluator(), budget=budget
        ),
    )
    return TestClient(create_app())


def _events(resp):
    return [json.loads(line[5:]) for line in resp.text.split("\n\n") if line.startswith("data:")]


def test_page_is_served_and_is_the_explorer(client):
    r = client.get("/state-explorer")
    assert r.status_code == 200 and "STATE EXPLORER" in r.text and "/api/state-engine/run" in r.text
    assert "/Users/" not in r.text  # the shipped sample runs carry no home path


def test_info_reports_provider_and_read_only_tools(client):
    body = client.get("/api/state-engine/info").json()
    assert body["read_only"] is True and (body["provider"], body["model"]) == ("stub", "stub-model")
    assert {"dir_explorer", "file_task"} <= {t["name"] for t in body["tools"]}
    assert not {"shell", "file_write", "code_exec"} & {t["name"] for t in body["tools"]}


def test_run_streams_meta_then_engine_events_ending_settled(client):
    r = client.post("/api/state-engine/run", json={"goal": "list the folder", "max_depth": 3})
    assert r.headers["content-type"].startswith("text/event-stream")
    ev = _events(r)
    assert ev[0]["kind"] == "meta" and ev[0]["budget"]["max_depth"] == 3 and ev[0]["model"] == "stub-model"
    assert [e["kind"] for e in ev[1:]][0] == "state" and ev[-1]["kind"] == "done" and ev[-1]["answer"] == "2 files"


def test_a_failing_engine_is_reported_not_a_dropped_stream(client, monkeypatch):
    def boom(budget):
        raise RuntimeError("provider unreachable")

    monkeypatch.setattr(route, "_make_engine", boom)
    ev = _events(client.post("/api/state-engine/run", json={"goal": "anything here"}))
    assert ev[-1]["kind"] == "stopped" and ev[-1]["settled"] is False and "provider unreachable" in ev[-1]["reason"]


@pytest.mark.parametrize(
    "body", [{"goal": ""}, {"goal": "ab"}, {"goal": "x" * 2001}, {"goal": "okay goal", "max_depth": 99}]
)
def test_bad_requests_are_rejected(client, body):
    assert client.post("/api/state-engine/run", json=body).status_code == 422


def test_windows_paths_survive_json_parsing():
    raw = r'{"moves":[{"tool":"dir_explorer","args":{"path":"C:\Users\bao\notes\temp\new"}}]}'
    assert parse_json(raw)["moves"][0]["args"]["path"] == "C:\\Users\\bao\\notes\\temp\\new"
    assert parse_json(r'{"p":"C:\\Users\\bao"}')["p"] == "C:\\Users\\bao"  # already escaped: untouched
    assert parse_json(r'{"a":"line1\nline2"}')["a"] == "line1\nline2"  # ordinary escapes still work
