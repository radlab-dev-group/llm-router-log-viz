"""The full-graph fixture: every mode node and every transition is exercised.

The generator lives in `scripts/` so the demo log stays reproducible without
being committed (`*.log` is gitignored). These tests pin its coverage, which is
also the acceptance case for "the whole phase transition diagram is filled".
"""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "scripts" / "make_full_graph_log.py"


def _generator():
    spec = importlib.util.spec_from_file_location("make_full_graph_log", SPEC_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _log_text() -> str:
    return "\n".join(_generator().build_log_lines()) + "\n"


def test_mode_sequence_covers_every_ordered_pair():
    module = _generator()
    modes = module.MODES
    sequence = module.mode_sequence()
    pairs = {(sequence[i], sequence[i + 1]) for i in range(len(sequence) - 1)}

    assert set(sequence) == set(modes)
    assert len(pairs) == len(modes) ** 2
    expected = {(a, b) for a in modes for b in modes}
    assert pairs == expected


def test_full_graph_fills_every_node_and_edge(tmp_path):
    log = tmp_path / "full-graph.log"
    log.write_text(_log_text(), encoding="utf-8")
    app = _app(log)
    with TestClient(app) as client:
        state = _wait_for(client, lambda s: s["total_events"] > 0)

    counts = {n["id"]: n["count"] for n in state["nodes"]}
    assert set(counts) >= set(_generator().MODES)
    assert all(counts[mode] > 0 for mode in _generator().MODES)

    edges = {(e["from"], e["to"]) for e in state["edges"]}
    assert edges == {(a, b) for a in _generator().MODES for b in _generator().MODES}


def test_full_graph_history_is_replayable(tmp_path):
    log = tmp_path / "full-graph.log"
    log.write_text(_log_text(), encoding="utf-8")
    app = _app(log)
    with TestClient(app) as client:
        state = _wait_for(client, lambda s: s["total_events"] > 0)
        history = client.get("/api/events").json()
        # One session holds the whole walk: decision timestamps are 1 s apart,
        # well under the 120 s default session gap.
        assert len(state["sessions"]) == 1

    assert history["total"] == len(history["events"])
    assert [ev["seq"] for ev in history["events"]] == list(range(1, history["total"] + 1))
    assert all(ev["mode"] in _generator().MODES for ev in history["events"])
    assert all(ev.get("host") and ev.get("duration_ms") for ev in history["events"])


def _app(log: Path):
    from llm_router_log_viz.server import create_app

    return create_app(str(log), follow=False, read_from_start=True, poll_interval=0.05)


def _wait_for(client, predicate, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get("/api/state").json()
        if predicate(state):
            return state
        time.sleep(0.05)
    raise AssertionError("state did not satisfy the predicate in time")
