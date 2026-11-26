import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from llm_router_log_viz.server import AppContext, create_app, format_sse
from llm_router_log_viz.state import MAX_EVENTS

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


def test_state_endpoint(tmp_path):
    text = "\n".join([POST, ROUTING, PROVIDER, RESPONSE]) + "\n"
    with _client(tmp_path, text) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        state = _wait_for(client=client)
        assert len(state["requests"]) == 1
        assert state["requests"][0]["duration_ms"] == 2666.0
        assert state["requests"][0]["status"] == 200
        assert state["cursor"]["events"] == 1
        assert state["cursor"]["requests"] == 1


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


# ---------------------------------------------------------------------- replay
ROUTING_IMPL = (
    "2026-11-26 09:41:15,102 INFO [llm_router_plugins.routing.codex] Codex routing: "
    "mode=implement source=phase model=qwen/Qwen3.8-Flash-Next similarity=0.97 class=main "
    "reason=phase_transition evidence=plan_done memory=miss semantic=-"
)
BACKEND = (
    "2026-11-26 09:41:15,120 INFO [llm_router_api.endpoints] Request model "
    "qwen/Qwen3.8-Flash-Next with config id: qwen3.8:27b-UD-66:7000 [llama.cpp: http://192.168.100.66:7000]"
)
UPSTREAM = (
    "2026-11-26 09:41:17,660 DEBUG urllib3.connectionpool: "
    "http://192.168.100.66:7000 \"POST /v1/responses HTTP/1.1\" 200 None"
)


def _replay_log() -> str:
    return "\n".join(
        [POST, ROUTING, PROVIDER, BACKEND, UPSTREAM, ROUTING_IMPL, UPSTREAM]
    ) + "\n"


def _wait_events(client, count: int, timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get("/api/events").json()
        if body["total"] >= count:
            return body
        time.sleep(0.05)
    raise AssertionError("events did not populate in time")


def test_events_endpoint_returns_enriched_history(tmp_path):
    log = tmp_path / "router.log"
    log.write_text(_replay_log(), encoding="utf-8")
    app = create_app(str(log), follow=False, read_from_start=True, poll_interval=0.05)
    with TestClient(app) as client:
        body = _wait_events(client, 2)

        assert body["total"] == 2
        assert body["retained"] == 2
        assert body["first_seq"] == 1
        assert body["max_events"] == MAX_EVENTS
        assert [ev["seq"] for ev in body["events"]] == [1, 2]
        assert [ev["mode"] for ev in body["events"]] == ["plan", "implement"]
        first = body["events"][0]
        assert first["host"] == "http://192.168.100.66:7000"
        assert first["status"] == 200
        assert "session" in first and "ts_epoch" in first

        # Paging: the replay client walks forward by seq without refetching.
        assert [ev["seq"] for ev in client.get("/api/events", params={"limit": 1}).json()["events"]] == [1]
        assert [ev["seq"] for ev in client.get("/api/events", params={"after": 1}).json()["events"]] == [2]
        assert client.get("/api/events", params={"after": 99}).json()["events"] == []
