from llm_router_log_viz.events import (
    RouterEventLog,
    parse_router_line,
    parse_ts_epoch,
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


def test_parse_ts_epoch():
    assert parse_ts_epoch("2026-11-26 09:41:10,221") is not None
    assert parse_ts_epoch("2026-11-26T09:41:10.221") is not None
    assert parse_ts_epoch("") is None
    assert parse_ts_epoch("not a timestamp") is None
    a = parse_ts_epoch("2026-11-26 09:41:10,221")
    b = parse_ts_epoch("2026-11-26 09:41:11,221")
    assert b - a == 1.0


# ---------------------------------------------------------------- real format
def _real_lines():
    """One request in the actual llm-router log format (no Response line)."""
    return [
        "2026-11-25 23:05:16,423 DEBUG llm_router_api.auth.middleware: Auth OK: key=key-34909890 endpoint=POST:/v1/responses model=auto_codex",
        "2026-11-25 23:05:16,423 DEBUG llm_router_api.endpoints.endpoint_i: [POST] v1/responses => ['openai', 'lmstudio', 'vllm', 'llama.cpp', 'anthropic', 'azure_openai']",
        "2026-11-25 23:05:16,439 INFO llm_router_api.endpoints.endpoint_i: Codex routing: mode=test source=phase model=qwen/Qwen3.8-27B similarity=1.000 class=main reason=python3 -m pytest evidence=command memory=hit semantic=-",
        "2026-11-25 23:05:16,441 DEBUG llm_router_api.core.lb.provider_strategy_facade: [keep-alive] _is_host_free current_model='qwen/Qwen3.8-27B' requested_model='qwen/Qwen3.8-27B' host=http://192.168.100.66:7000",
        "2026-11-25 23:05:16,441 DEBUG llm_router_api.endpoints.endpoint_i: Request model qwen/Qwen3.8-27B with config id: qwen3.8:27b-UD-Q8_K_XL-66:7000 [llama.cpp: http://192.168.100.66:7000]",
        "2026-11-25 23:05:19,001 DEBUG urllib3.connectionpool: http://192.168.100.66:7000 \"POST /v1/responses HTTP/1.1\" 200 None",
    ]


def test_real_format_correlates_one_request():
    log = RouterEventLog()
    kinds = []
    for line in _real_lines():
        result = log.ingest(line)
        if result is not None:
            kinds.append(result[0])
    # Auth OK lines are not correlated into request records.
    assert kinds == ["endpoint", "routing", "backend", "response"]
    rec = log.requests[0]
    assert rec.endpoint == "POST v1/responses"
    assert rec.mode == "test"
    assert rec.host == "http://192.168.100.66:7000"
    assert rec.engine == "llama.cpp"
    assert rec.config_id == "qwen3.8:27b-UD-Q8_K_XL-66:7000"
    assert rec.status == 200
    assert rec.duration_ms == 2560.0
    assert log.open_request is None


def test_urllib3_post_is_not_a_new_request():
    # The upstream reply mentions "POST /v1/responses" too; it must close, not open.
    line = "2026-11-25 23:05:19,001 DEBUG urllib3.connectionpool: http://192.168.100.66:7000 \"POST /v1/responses HTTP/1.1\" 200 None"
    kind, payload = parse_router_line(line)
    assert kind == "response"
    assert payload["status"] == 200
    assert payload["duration_ms"] is None


def test_urllib3_get_health_is_ignored():
    line = "2026-11-25 23:05:19,001 DEBUG urllib3.connectionpool: http://192.168.100.66:7000 \"GET /health HTTP/1.1\" 200 15"
    assert parse_router_line(line) is None


def test_registered_endpoint_is_not_a_request():
    line = "2026-11-25 22:29:33,914 INFO llm_router_api.register.register: Registered endpoint POST /api/rewrite_query (RewriteQuery)"
    assert parse_router_line(line) is None


def test_provider_failure_attaches_error_detail():
    log = RouterEventLog()
    log.ingest("2026-11-25 22:51:08,805 DEBUG llm_router_api.endpoints.endpoint_i: [POST] /v1/chat/completions => ['openai', 'lmstudio', 'vllm', 'llama.cpp', 'anthropic', 'azure_openai']")
    log.ingest("2026-11-25 22:51:08,808 DEBUG llm_router_api.endpoints.endpoint_i: Request model google/gemma-4-12b-it-playground with config id: gemma4_12b-vllm-79-llmrouter_api:7000 [vllm: http://192.168.100.79:7000]")
    log.ingest("2026-11-25 22:51:09,015 DEBUG urllib3.connectionpool: http://192.168.100.79:7000 \"POST /v1/chat/completions HTTP/1.1\" 400 199")
    log.ingest(
        "2026-11-25 22:51:09,017 ERROR llm_router_api.endpoints.endpoint_i: "
        "Provider request failed: HTTP 400 \u2014 400 Bad Request for url \u2014 "
        "provider: {\"error\":{\"code\":400,\"message\":\"request (24090 tokens) exceeds the available "
        "context size (21504 tokens), try increasing it\",\"type\":\"exceed_context_size_error\","
        "\"n_prompt_tokens\":24090,\"n_ctx\":21504}}"
    )
    rec = log.requests[0]
    assert rec.status == 400
    assert rec.error_type == "exceed_context_size_error"
    assert rec.prompt_tokens == 24090
    assert rec.ctx_tokens == 21504
    assert rec.host == "http://192.168.100.79:7000"


def test_semantic_detail_attaches_to_decision():
    log = RouterEventLog()
    lines = [
        "2026-11-25 22:30:04,978 INFO x: CodexRouting: semantic target=review similarity=0.4592 runner_up=test runner_similarity=0.4521 margin=0.0071",
        "2026-11-25 22:30:04,978 INFO x: Codex routing: mode=review source=semantic model=qwen/Qwen3.8-Flash-Next similarity=0.459 class=main reason=- evidence=- memory=miss semantic=accepted",
    ]
    for line in lines:
        log.ingest(line)
    rec = log.requests[0]
    assert rec.routing.semantic_target == "review"
    assert rec.routing.margin == 0.0071
    assert rec.routing.runner_up == "test"


def test_rejected_semantic_merges_both_lines():
    log = RouterEventLog()
    lines = [
        "2026-11-25 22:36:38,565 INFO x: CodexRouting: semantic target=review similarity=0.3789 runner_up=implement runner_similarity=0.3691 margin=0.0098",
        "2026-11-25 22:36:38,565 INFO x: CodexRouting: semantic match 'review' similarity=0.3789 is below threshold 0.4400",
        "2026-11-25 22:36:38,567 INFO x: Codex routing: mode=implement source=fallback model=qwen/Qwen3.8-Flash-Next similarity=0.369 class=main reason=no layer answered evidence=- memory=miss semantic=below threshold",
    ]
    for line in lines:
        log.ingest(line)
    rec = log.requests[0]
    assert rec.routing.semantic_target == "review"
    assert rec.routing.margin == 0.0098
    assert rec.routing.semantic_threshold == 0.44
    assert rec.mode == "implement"


def test_concurrent_requests_correlate_by_completion_order():
    # Two requests overlap; replies come back in completion order.
    lines = [
        "2026-11-25 22:53:06,474 DEBUG x: [POST] v1/responses => ['openai']",
        "2026-11-25 22:53:06,475 INFO x: Codex routing: mode=plan source=collaboration_mode model=qwen/Qwen3.8-Flash-Next similarity=1.000 class=main reason=- evidence=- memory=- semantic=-",
        "2026-11-25 22:53:06,479 DEBUG x: Request model qwen/Qwen3.8-Flash-Next with config id: qwen3.8:flash-next-UD-IQ4_XL-70:7000 [llama.cpp: http://192.168.100.70:7000]",
        "2026-11-25 22:53:06,539 DEBUG x: [POST] v1/responses => ['openai']",
        "2026-11-25 22:53:06,540 INFO x: Codex routing: mode=aux_title source=class model=qwen/Qwen3.8-27B similarity=1.000 class=aux_title reason=- evidence=- memory=- semantic=-",
        "2026-11-25 22:53:06,541 DEBUG x: Request model qwen/Qwen3.8-27B with config id: qwen3.8:27b-UD-Q8_K_XL-66:7000 [llama.cpp: http://192.168.100.66:7000]",
        "2026-11-25 22:53:09,000 DEBUG x: http://192.168.100.70:7000 \"POST /v1/responses HTTP/1.1\" 200 None",
        "2026-11-25 22:53:10,000 DEBUG x: http://192.168.100.66:7000 \"POST /v1/responses HTTP/1.1\" 200 None",
    ]
    log = RouterEventLog()
    for line in lines:
        log.ingest(line)
    assert len(log.requests) == 2
    first, second = log.requests
    assert first.mode == "plan" and first.status == 200
    assert second.mode == "aux_title" and second.status == 200
    assert log.open_request is None


def test_get_models_does_not_steal_correlation_slot():
    lines = [
        "2026-11-25 22:50:27,897 DEBUG x: [GET] v1/models => ['openai', 'lmstudio']",
        "2026-11-25 22:50:32,252 DEBUG x: [POST] v1/responses => ['openai']",
        "2026-11-25 22:50:32,300 INFO x: Codex routing: mode=plan source=phase model=m similarity=1.0 class=main reason=- evidence=- memory=- semantic=-",
    ]
    log = RouterEventLog()
    for line in lines:
        log.ingest(line)
    assert len(log.requests) == 2
    assert log.requests[1].mode == "plan"
