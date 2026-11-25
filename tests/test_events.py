from llm_router_log_viz.events import (
    RouterEventLog,
    parse_router_line,
    parse_ts_epoch,
    percentile,
)


def _lines():
    return [
        "2026-11-26 09:41:10,221 INFO  [llm_router.api] POST /v1/responses model=auto_codex stream=true",
        "2026-11-26 09:41:10,244 INFO  [llm_router_plugins.routing.codex] Codex routing: mode=plan source=explicit model=qwen/Qwen3.8-Flash-Next similarity=1.000 class=main reason=explicit_agent_mode evidence=explicit memory=disabled semantic=-",
        "2026-11-26 09:41:10,301 INFO  [llm_router.lb] Selected provider=lab3-flash-next model=qwen/Qwen3.8-Flash-Next",
        "2026-11-26 09:41:12,887 INFO  [llm_router.api] Response 200 /v1/responses duration_ms=2666",
    ]


def test_parse_router_line_kinds():
    assert parse_router_line(_lines()[0])[0] == "post"
    assert parse_router_line(_lines()[2])[0] == "provider"
    assert parse_router_line(_lines()[3])[0] == "response"
    assert parse_router_line("2026-11-26 09:41:10,244 INFO noise line") is None


def test_correlation_full_request():
    log = RouterEventLog()
    kinds = [log.ingest(line)[0] for line in _lines()]
    assert kinds == ["post", "routing", "provider", "response"]
    assert len(log.requests) == 1
    rec = log.requests[0]
    assert rec.mode == "plan"
    assert rec.provider == "lab3-flash-next"
    assert rec.status == 200
    assert rec.duration_ms == 2666.0
    assert rec.stream is True


def test_non_responses_paths_and_missing_path_are_parsed():
    post, post_payload = parse_router_line(
        "2026-11-26 09:41:10,221 INFO [api] POST /v1/chat/completions model=auto_codex stream=true"
    )
    assert post == "post" and post_payload["model"] == "auto_codex"

    kind, payload = parse_router_line("2026-11-26 09:41:12,887 INFO [api] Response 200 /v1/chat/completions duration_ms=412")
    assert kind == "response" and payload["duration_ms"] == 412.0

    kind, payload = parse_router_line("2026-11-26 09:41:12,887 INFO [api] Response 500 duration_ms=99")
    assert kind == "response" and payload["status"] == 500


def test_post_like_prose_is_not_matched():
    assert parse_router_line("2026-11-26 09:41:10,100 INFO [api] POSTURE check ok") is None


def test_routing_without_post_becomes_standalone_request():
    log = RouterEventLog()
    line = "2026-11-26 09:41:10,244 INFO  Codex routing: mode=debug source=phase model=m similarity=0.9 class=main reason=- evidence=- memory=- semantic=-"
    kind, rec = log.ingest(line)
    assert kind == "routing"
    assert len(log.requests) == 1
    assert rec.routing is not None
    assert rec.duration_ms is None


def test_multiple_requests_close_in_order():
    log = RouterEventLog()
    for line in _lines():
        log.ingest(line)
    assert log.open_request is None
    # second request with provider but no response stays open
    log.ingest("2026-11-26 09:42:03,010 INFO  [llm_router.api] POST /v1/responses model=auto_codex stream=false")
    log.ingest("2026-11-26 09:42:03,031 INFO  Codex routing: mode=implement source=phase model=m similarity=1.0 class=main reason=- evidence=- memory=- semantic=-")
    log.ingest("2026-11-26 09:42:03,090 INFO  [llm_router.lb] Selected provider=lab3-flash-next model=m")
    assert len(log.requests) == 2
    assert log.open_request is not None
    assert log.open_request.mode == "implement"


def test_percentile():
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5
    assert percentile([10.0], 95) == 10.0
    assert percentile([], 95) is None
    values = [float(i) for i in range(1, 21)]
    assert percentile(values, 95) == 19.05


def test_parse_ts_epoch():
    assert parse_ts_epoch("2026-11-26 09:41:10,221") is not None
    assert parse_ts_epoch("2026-11-26T09:41:10.221") is not None
    assert parse_ts_epoch("") is None
    assert parse_ts_epoch("not a timestamp") is None
    a = parse_ts_epoch("2026-11-26 09:41:10,221")
    b = parse_ts_epoch("2026-11-26 09:41:11,221")
    assert b - a == 1.0
