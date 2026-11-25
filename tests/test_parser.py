from llm_router_log_viz.parser import (
    is_codex_routing_line,
    is_semantic_routing_line,
    parse_codex_routing_line,
    parse_lines,
    parse_semantic_routing_line,
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


def test_multivalue_reason_is_kept_whole():
    line = (
        "2026-11-25 23:05:16,439 INFO x: Codex routing: mode=test source=phase "
        "model=qwen/Qwen3.8-27B similarity=1.000 class=main reason=python3 -m pytest "
        "evidence=command memory=hit semantic=-"
    )
    ev = parse_codex_routing_line(line)
    assert ev.reason == "python3 -m pytest"
    assert ev.evidence == "command"
    assert ev.memory == "hit"


def test_semantic_target_line_parses():
    line = (
        "2026-11-25 22:54:48,854 INFO x: CodexRouting: semantic target=review "
        "similarity=0.5605 runner_up=debug runner_similarity=0.5286 margin=0.0320"
    )
    sem = parse_semantic_routing_line(line)
    assert sem["semantic_target"] == "review"
    assert sem["semantic_similarity"] == 0.5605
    assert sem["runner_up"] == "debug"
    assert sem["runner_similarity"] == 0.5286
    assert sem["margin"] == 0.0320
    assert sem["semantic_threshold"] is None


def test_semantic_below_threshold_line_parses():
    line = "2026-11-25 22:55:23,765 INFO x: CodexRouting: semantic match 'review' similarity=0.3627 is below threshold 0.4400"
    sem = parse_semantic_routing_line(line)
    assert sem["semantic_target"] == "review"
    assert sem["semantic_similarity"] == 0.3627
    assert sem["semantic_threshold"] == 0.44
    assert sem["margin"] is None


def test_semantic_line_is_not_a_decision():
    line = "CodexRouting: semantic target=review similarity=0.5 runner_up=debug runner_similarity=0.4 margin=0.1"
    assert parse_codex_routing_line(line) is None
    assert is_codex_routing_line(line) is False
    assert is_semantic_routing_line(line) is True
