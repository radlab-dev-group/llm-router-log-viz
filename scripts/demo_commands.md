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
- licznik `req:` w nagłówku: rośnie z każdym skorelowanym `POST`; czas odpowiedzi widać inline jako `dur=` przy wyciętych liniach.

## 5. Miejsca do celowego "zepsucia" przed demo
- `src/llm_router_log_viz/state.py` — policz przejścia inaczej / pomiń `git_review`.
- `src/llm_router_log_viz/parser.py` — przestań wyłapywać `class` albo `debug`.
- `web/app.js` — ukryj/zepsuj render krawędzi.
Po naprawie: restart dashboardu i odśwież przeglądarkę.
