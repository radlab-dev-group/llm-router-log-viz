from llm_router_log_viz.parser import parse_codex_routing_line
from llm_router_log_viz.state import DashboardState


def _ev(line, n=1):
    return parse_codex_routing_line(line, line_no=n)


def test_single_session_when_dense():
    state = DashboardState(session_gap_s=120.0)
    for i in range(3):
        state.add_event(_ev(
            f"2026-11-26 09:41:{10 + i * 10:02d},000 Codex routing: mode=plan source=explicit model=m similarity=1.0 class=main reason=- evidence=- memory=- semantic=-"
        ))
    assert len(state.sessions) == 1


def test_session_split_on_idle_gap():
    state = DashboardState(session_gap_s=120.0)
    state.add_event(_ev(
        "2026-11-26 09:41:10,000 Codex routing: mode=plan source=explicit model=m similarity=1.0 class=main reason=- evidence=- memory=- semantic=-"
    ))
    # +200s idle -> new session
    state.add_event(_ev(
        "2026-11-26 09:44:50,000 Codex routing: mode=implement source=phase model=m similarity=1.0 class=main reason=- evidence=- memory=- semantic=-"
    ))
    assert len(state.sessions) == 2
    assert state.sessions[0]["requests"] == 1
    assert state.sessions[1]["requests"] == 1


def test_transitions_do_not_cross_sessions():
    state = DashboardState(session_gap_s=120.0)
    state.add_event(_ev(
        "2026-11-26 09:41:10,000 Codex routing: mode=plan source=explicit model=m similarity=1.0 class=main reason=- evidence=- memory=- semantic=-"
    ))
    state.add_event(_ev(
        "2026-11-26 09:41:40,000 Codex routing: mode=implement source=phase model=m similarity=1.0 class=main reason=- evidence=- memory=- semantic=-"
    ))
    # new session after a long gap; its first event must not create an edge
    state.add_event(_ev(
        "2026-11-26 09:45:40,000 Codex routing: mode=debug source=phase model=m similarity=1.0 class=main reason=- evidence=- memory=- semantic=-"
    ))
    snap = state.snapshot()
    edges = {(e["from"], e["to"]) for e in snap["edges"]}
    assert ("plan", "implement") in edges
    assert ("implement", "debug") not in edges


def test_request_inherits_session():
    state = DashboardState(session_gap_s=120.0)
    state.add_request_line(
        "2026-11-26 09:41:10,221 [llm_router.api] POST /v1/responses model=auto_codex stream=false"
    )
    state.add_request_line(
        "2026-11-26 09:41:10,244 Codex routing: mode=plan source=explicit model=m similarity=1.0 class=main reason=- evidence=- memory=- semantic=-"
    )
    assert len(state.requests.requests) == 1
    assert state.requests.requests[0].session == 1
