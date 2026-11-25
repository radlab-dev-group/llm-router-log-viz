from llm_router_log_viz.parser import parse_codex_routing_line
from llm_router_log_viz.state import DashboardState


def _ev(line, n=1):
    return parse_codex_routing_line(line, line_no=n)


def test_state_counts_and_transitions():
    state = DashboardState()
    e1 = _ev("Codex routing: mode=plan source=explicit model=m1 similarity=1.0 class=main reason=- evidence=- memory=- semantic=-", 1)
    e2 = _ev("Codex routing: mode=implement source=phase model=m1 similarity=1.0 class=main reason=- evidence=- memory=- semantic=-", 2)
    e3 = _ev("Codex routing: mode=test source=phase model=m2 similarity=1.0 class=main reason=- evidence=- memory=- semantic=-", 3)
    state.add_event(e1)
    state.add_event(e2)
    state.add_event(e3)

    snap = state.snapshot()
    assert snap["total_events"] == 3
    assert snap["counts"]["mode"]["plan"] == 1
    assert snap["counts"]["mode"]["implement"] == 1
    assert snap["counts"]["mode"]["test"] == 1
    assert {"from": "plan", "to": "implement", "count": 1} in snap["edges"]
    assert {"from": "implement", "to": "test", "count": 1} in snap["edges"]
    assert snap["last_event"]["mode"] == "test"


def test_snapshot_contains_known_nodes():
    state = DashboardState()
    snap = state.snapshot()
    ids = {n["id"] for n in snap["nodes"]}
    for mode in ["plan", "implement", "review", "debug", "test", "git_review", "aux_title", "compaction"]:
        assert mode in ids
