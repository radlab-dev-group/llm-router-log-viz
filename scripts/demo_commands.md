# Demo commands — llm-router-log-viz

## 1. Uruchom dashboard na sample logu
```bash
cd llm-router-log-viz
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
llm-router-log-viz --log ./sample_logs/router_sample.log --host 127.0.0.1 --port 8787
```
Otwórz: http://127.0.0.1:8787

## 2. Uruchom na żywym logu routera
```bash
llm-router-log-viz --log /ścieżka/do/llm-router.log --host 127.0.0.1 --port 8787
```

## 3. Szybka symulacja "live" (drugi terminal)
```bash
cat >> ./sample_logs/router_sample.log << 'LOG'
2026-11-26 09:46:01,000 INFO [llm_router_plugins.routing.codex] Codex routing: mode=implement source=phase model=qwen/Qwen3.8-Flash-Next similarity=1.000 class=main reason=assistant_patch evidence=tool_call memory=hit semantic=-
2026-11-26 09:46:20,000 INFO [llm_router_plugins.routing.codex] Codex routing: mode=test source=phase model=qwen/Qwen3.8-27B similarity=1.000 class=main reason=pytest_command evidence=tool_call memory=hit semantic=-
LOG
```

## 4. Co pokazać na demie
- lewy panel: surowy log routera (wszystko),
- prawy górny: wycięte tylko `Codex routing`,
- lewy dolny: diagram przejść faz (grubość krawędzi = licznik),
- prawy dolny: liczniki i timeline,
- pasek SESSIONS: dopisz linię z przerwą > `--session-gap` → pojawia się chip `S2`,
- LATENCY: p50/p95 per mode i per provider (wymyka się dopiero gdy w logu są linie `Response …`),
- ROUTING INSIGHTS: alerty z reguł — kliknięcie rozwija szczegóły i listę `seq`.

## 5. Szybkie wywołanie alertów (drugi terminal)
Niska pewność routingu + review bez testów:
```bash
cat >> ./sample_logs/router_sample.log << 'LOG'
2026-11-26 09:47:01,000 INFO [llm_router.api] POST /v1/responses model=auto_codex stream=false
2026-11-26 09:47:01,010 INFO [llm_router_plugins.routing.codex] Codex routing: mode=implement source=heuristic model=qwen/Qwen3.8-Flash-Next similarity=0.510 class=main reason=fuzzy_match evidence=heuristic memory=miss semantic=-
2026-11-26 09:47:04,000 INFO [llm_router.api] Response 200 /v1/responses duration_ms=900
2026-11-26 09:47:20,000 INFO [llm_router.api] POST /v1/responses model=auto_codex stream=false
2026-11-26 09:47:20,010 INFO [llm_router_plugins.routing.codex] Codex routing: mode=git_review source=heuristic model=qwen/Qwen3.8-27B similarity=0.990 class=main reason=git_diff evidence=heuristic memory=miss semantic=-
2026-11-26 09:47:23,000 INFO [llm_router.api] Response 200 /v1/responses duration_ms=2400
LOG
```
Powinny pojawić się: `low_similarity`, `git_review_without_test`, `aux_on_large_model` (dla `compaction`/`aux_title` na 27B).

## 6. Miejsca do celowego "zepsucia" przed demo
- `src/llm_router_log_viz/state.py` — policz przejścia inaczej / pomiń `git_review`.
- `src/llm_router_log_viz/parser.py` — przestań wyłapywać `class` albo `debug`.
- `web/app.js` — ukryj/zepsuj render krawędzi.
Po naprawie: restart dashboardu i odśwież przeglądarkę.
