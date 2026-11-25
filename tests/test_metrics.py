from llm_router_log_viz.state import DashboardState


def _feed(state, lines):
    for line in lines:
        state.add_request_line(line)


def test_latency_summary_by_mode():
    state = DashboardState()
    _feed(state, [
        "2026-11-26 09:41:10,221 [a] POST /v1/responses model=auto_codex stream=false",
        "2026-11-26 09:41:10,244 Codex routing: mode=plan source=explicit model=m1 similarity=1.0 class=main reason=- evidence=- memory=- semantic=-",
        "2026-11-26 09:41:10,301 [b] Selected provider=lab3-flash-next model=m1",
        "2026-11-26 09:41:12,887 [a] Response 200 /v1/responses duration_ms=1000",
        "2026-11-26 09:42:10,221 [a] POST /v1/responses model=auto_codex stream=true",
        "2026-11-26 09:42:10,244 Codex routing: mode=implement source=phase model=m1 similarity=1.0 class=main reason=- evidence=- memory=- semantic=-",
        "2026-11-26 09:42:10,301 [b] Selected provider=lab3-flash-next model=m1",
        "2026-11-26 09:42:25,887 [a] Response 200 /v1/responses duration_ms=5000",
    ])
    metrics = state.metrics()
    assert metrics["total_requests"] == 2
    assert metrics["completed_requests"] == 2
    assert metrics["latency"]["p50_ms"] == 3000.0
    assert metrics["latency_by_mode"]["plan"]["p50_ms"] == 1000.0
    assert metrics["latency_by_mode"]["implement"]["p50_ms"] == 5000.0
    assert metrics["latency_by_provider"]["lab3-flash-next"]["count"] == 2


def test_error_rate():
    state = DashboardState()
    _feed(state, [
        "2026-11-26 09:41:10,221 [a] POST /v1/responses model=auto_codex stream=false",
        "2026-11-26 09:41:10,244 Codex routing: mode=plan source=explicit model=m1 similarity=1.0 class=main reason=- evidence=- memory=- semantic=-",
        "2026-11-26 09:41:12,887 [a] Response 500 /v1/responses duration_ms=100",
    ])
    metrics = state.metrics()
    assert metrics["errors"] == 1
    assert metrics["error_rate"] == 1.0


def test_time_series_buckets():
    state = DashboardState()
    _feed(state, [
        "2026-11-26 09:41:10,221 [a] POST /v1/responses model=auto_codex stream=false",
        "2026-11-26 09:41:10,244 Codex routing: mode=plan source=explicit model=m1 similarity=1.0 class=main reason=- evidence=- memory=- semantic=-",
        "2026-11-26 09:41:12,887 [a] Response 200 /v1/responses duration_ms=1000",
        "2026-11-26 09:42:10,221 [a] POST /v1/responses model=auto_codex stream=false",
        "2026-11-26 09:42:10,244 Codex routing: mode=test source=phase model=m1 similarity=1.0 class=main reason=- evidence=- memory=- semantic=-",
        "2026-11-26 09:42:12,887 [a] Response 200 /v1/responses duration_ms=2000",
    ])
    series = state.metrics()["time_series"]
    # 30s buckets over a ~62s span -> three buckets, the middle one empty
    assert len(series) == 3
    assert series[0]["requests"] == 1
    assert series[0]["avg_ms"] == 1000.0
    assert series[1]["requests"] == 0
    assert series[1]["avg_ms"] is None
    assert series[2]["requests"] == 1
    assert series[2]["avg_ms"] == 2000.0
