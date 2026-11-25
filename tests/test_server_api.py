import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from llm_router_log_viz.server import AppContext, create_app, format_sse

ROUTING = (
    "2026-11-26 09:41:10,244 INFO [llm_router_plugins.routing.codex] Codex routing: "
    "mode=plan source=explicit model=qwen/Qwen3.8-Flash-Next similarity=1.000 class=main "
    "reason=explicit_agent_mode evidence=explicit memory=disabled semantic=-"
)
POST = "2026-11-26 09:41:10,221 INFO [llm_router.api] POST /v1/responses model=auto_codex stream=false"
PROVIDER = "2026-11-26 09:41:10,301 INFO [llm_router.lb] Selected provider=lab3-flash-next model=qwen/Qwen3.8-Flash-Next"
RESPONSE = "2026-11-26 09:41:12,887 INFO [llm_router.api] Response 200 /v1/responses duration_ms=2666"


def _client(tmp_path: Path, log_text: str = "") -> TestClient:
    log = tmp_path / "router.log"
    log.write_text(log_text, encoding="utf-8")
    app = create_app(str(log), follow=True, read_from_start=True, poll_interval=0.05)
    return TestClient(app)


def _wait_for(tmp_path=None, client=None, timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get("/api/state").json()
        if state["total_events"] > 0:
            return state
        time.sleep(0.05)
    raise AssertionError("state did not populate in time")


def test_state_metrics_and_insights_endpoints(tmp_path):
    text = "\n".join([POST, ROUTING, PROVIDER, RESPONSE]) + "\n"
    with _client(tmp_path, text) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        state = _wait_for(client=client)
        assert state["metrics"]["completed_requests"] == 1
        assert state["metrics"]["latency_by_mode"]["plan"]["p50_ms"] == 2666.0
        assert len(state["requests"]) == 1
        assert isinstance(state["insights"], list)
        assert state["cursor"]["events"] == 1

        metrics = client.get("/api/metrics").json()
        assert metrics["total_requests"] == 1

        insights = client.get("/api/insights").json()
        assert "insights" in insights


def test_index_and_static_are_served(tmp_path):
    with _client(tmp_path, "") as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "LLM Router Log Viz" in response.text


def test_format_sse_envelope():
    payload = format_sse("delta", {"a": 1})
    assert payload.startswith("event: delta\n")
    assert '"a": 1' in payload
    assert payload.endswith("\n\n")


def _context(tmp_path: Path) -> AppContext:
    log = tmp_path / "router.log"
    log.write_text("", encoding="utf-8")
    ctx = AppContext(str(log), follow=True, read_from_start=True, poll_interval=0.05)
    ctx.start()
    return ctx


def test_wait_for_update_returns_delta_with_new_records(tmp_path):
    ctx = _context(tmp_path)
    try:
        cursor = ctx.cursor()
        assert cursor["version"] == 0

        for line in (POST, ROUTING, PROVIDER, RESPONSE):
            ctx.handle_line(line, line_no=1)

        delta = ctx.wait_for_update(cursor, timeout=2.0)
        assert delta is not None
        assert delta["kind"] == "delta"
        assert [ev["mode"] for ev in delta["events"]] == ["plan"]
        assert [r["mode"] for r in delta["requests"]] == ["plan"]
        assert delta["requests"][0]["duration_ms"] == 2666.0
        assert delta["cursor"]["events"] == 1
        assert delta["metrics"]["completed_requests"] == 1

        # A cursor already at HEAD times out instead of replaying old data.
        assert ctx.wait_for_update(delta["cursor"], timeout=0.2) is None
    finally:
        ctx.stop()


def test_delta_only_carries_new_raw_lines(tmp_path):
    ctx = _context(tmp_path)
    try:
        ctx.handle_line(POST, line_no=1)
        cursor = ctx.cursor()
        ctx.handle_line(ROUTING, line_no=2)
        delta = ctx.wait_for_update(cursor, timeout=2.0)
        assert delta["raw_lines"] == [ROUTING]
        assert len(delta["nodes"]) >= 8
    finally:
        ctx.stop()


def test_watcher_stops_itself_when_not_following(tmp_path):
    log = tmp_path / "router.log"
    log.write_text(f"{POST}\n{ROUTING}\n{PROVIDER}\n{RESPONSE}\n", encoding="utf-8")
    ctx = AppContext(str(log), follow=False, read_from_start=True, poll_interval=0.05)
    ctx.start()
    assert ctx.watcher.initial_read_done.wait(timeout=3.0)
    # The follow=False watcher terminates on its own; no guessed sleep needed.
    ctx.watcher._thread.join(timeout=2.0)
    assert not ctx.watcher._thread.is_alive()
    assert ctx.state.total_events == 1
    ctx.stop()
