from llm_router_log_viz.parser import (
    is_codex_routing_line,
    parse_codex_routing_line,
    parse_lines,
)


def test_parse_real_codex_routing_line():
    line = (
        "2026-11-26 09:41:10,244 INFO [codex] Codex routing: "
        "mode=plan source=explicit model=qwen/Qwen3.8-Flash-Next similarity=1.000 "
        "class=main reason=explicit_agent_mode evidence=explicit memory=disabled semantic=-"
    )
    ev = parse_codex_routing_line(line, line_no=7)
    assert ev is not None
    assert ev.mode == "plan"
    assert ev.source == "explicit"
    assert ev.model == "qwen/Qwen3.8-Flash-Next"
    assert ev.similarity == 1.0
    assert ev.request_class == "main"
    assert ev.reason == "explicit_agent_mode"
    assert ev.evidence == "explicit"
    assert ev.memory == "disabled"
    assert ev.semantic == "-"
    assert ev.line_no == 7
    assert ev.ts.startswith("2026-11-26")


def test_parse_shorter_line_is_tolerant():
    line = "Codex routing: mode=test source=phase model=qwen/Qwen3.8-27B similarity=0.920 class=main"
    ev = parse_codex_routing_line(line)
    assert ev is not None
    assert ev.mode == "test"
    assert ev.source == "phase"
    assert ev.request_class == "main"
    assert ev.reason == "-"


def test_non_codex_line_returns_none():
    assert parse_codex_routing_line("2026-11-26 INFO server started") is None
    assert is_codex_routing_line("POST /v1/responses") is False


def test_parse_lines_filters_only_routing_events():
    lines = [
        "INFO start",
        "Codex routing: mode=plan source=explicit model=m similarity=1.000 class=main reason=- evidence=- memory=- semantic=-",
        "INFO middle",
        "Codex routing: mode=test source=phase model=m similarity=1.000 class=main reason=- evidence=- memory=- semantic=-",
    ]
    events = parse_lines(lines)
    assert len(events) == 2
    assert [e.mode for e in events] == ["plan", "test"]
