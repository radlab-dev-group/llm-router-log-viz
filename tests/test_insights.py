from llm_router_log_viz.state import DashboardState


def _state_with(lines, gap=120.0):
    state = DashboardState(session_gap_s=gap)
    for line in lines:
        state.add_request_line(line)
    return state


def test_low_similarity_alert():
    state = _state_with([
        "2026-11-26 09:41:10,221 [a] POST /v1/responses model=auto_codex stream=false",
        "2026-11-26 09:41:10,244 Codex routing: mode=implement source=heuristic model=m similarity=0.55 class=main reason=guess evidence=heuristic memory=- semantic=-",
        "2026-11-26 09:41:12,887 [a] Response 200 /v1/responses duration_ms=1000",
    ])
    ids = [i["id"] for i in state.insights()]
    assert "low_similarity" in ids
    item = next(i for i in state.insights() if i["id"] == "low_similarity")
    assert item["severity"] == "critical"


def test_git_review_without_test():
    state = _state_with([
        "2026-11-26 09:41:10,221 [a] POST /v1/responses model=auto_codex stream=false",
        "2026-11-26 09:41:10,244 Codex routing: mode=plan source=explicit model=m similarity=1.0 class=main reason=- evidence=- memory=- semantic=-",
        "2026-11-26 09:41:12,887 [a] Response 200 /v1/responses duration_ms=1000",
        "2026-11-26 09:42:10,221 [a] POST /v1/responses model=auto_codex stream=false",
        "2026-11-26 09:42:10,244 Codex routing: mode=git_review source=heuristic model=m similarity=1.0 class=main reason=- evidence=- memory=- semantic=-",
        "2026-11-26 09:42:12,887 [a] Response 200 /v1/responses duration_ms=1000",
    ])
    ids = [i["id"] for i in state.insights()]
    assert any(i.startswith("git_review_without_test") for i in ids)


def test_memory_miss_spike():
    lines = []
    for i in range(6):
        base = f"2026-11-26 09:41:{10 + i * 5:02d},221 [a] POST /v1/responses model=auto_codex stream=false"
        lines.append(base)
        lines.append(f"2026-11-26 09:41:{10 + i * 5:02d},244 Codex routing: mode=implement source=phase model=m similarity=1.0 class=main reason=- evidence=- memory=miss semantic=-")
        lines.append(f"2026-11-26 09:41:{12 + i * 5:02d},887 [a] Response 200 /v1/responses duration_ms=100")
    state = _state_with(lines)
    ids = [i["id"] for i in state.insights()]
    assert "memory_miss_spike" in ids


def test_clean_run_has_no_critical():
    state = _state_with([
        "2026-11-26 09:41:10,221 [a] POST /v1/responses model=auto_codex stream=false",
        "2026-11-26 09:41:10,244 Codex routing: mode=plan source=explicit model=m similarity=1.0 class=main reason=- evidence=- memory=hit semantic=-",
        "2026-11-26 09:41:12,887 [a] Response 200 /v1/responses duration_ms=1000",
    ])
    assert all(i["severity"] != "critical" for i in state.insights())
