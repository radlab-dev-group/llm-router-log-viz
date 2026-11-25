# Usage recipes

## 1. Run against the sample log

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
llm-router-log-viz --log ./sample_logs/llm-router.log --host 127.0.0.1 --port 8787
```

Open http://127.0.0.1:8787.

## 2. Run against a real router log

```bash
llm-router-log-viz --log /path/to/router.log --host 127.0.0.1 --port 8787
```

Useful flags: `--session-gap <s>`, `--poll-interval <s>`, `--no-follow`, `--read-from-end`.

## 3. Simulate live traffic

Append routing lines to the watched file (second terminal). Each new decision shows up
in the extracted panel, the timeline and the transition diagram:

```bash
cat >> /path/to/router.log << 'LOG'
2026-11-26 09:46:01,000 INFO [llm_router.api] POST /v1/responses model=auto_codex stream=false
2026-11-26 09:46:01,010 INFO [llm_router_plugins.routing.codex] Codex routing: mode=implement source=phase model=qwen/Qwen3.8-Flash-Next similarity=1.000 class=main reason=assistant_patch evidence=tool_call memory=hit semantic=-
2026-11-26 09:46:03,000 INFO [llm_router.api] Response 200 /v1/responses duration_ms=900
LOG
```

Append a line whose timestamp is more than `--session-gap` after the previous one to
open a new session (a new chip appears in the SESSIONS strip).

## 4. Fill the entire phase transition diagram

Handy for eyeballing the graph layout: the generator walks all 8 known modes so
every node is non-empty and all 64 ordered transitions (self-loops included)
appear, inside a single session.

```bash
python3 scripts/make_full_graph_log.py
llm-router-log-viz --log ./sample_logs/full-graph.log --host 127.0.0.1 --port 8787
```

Options: `-o PATH` (output), `--gap S` (seconds between decisions, keep it below
`--session-gap` to stay in one session), `--sessions N` (split the walk).

## 5. Watch the history step by step

```bash
llm-router-log-viz --log ./sample_logs/full-graph.log --no-follow
```

Open the page, then start replay: click the **REPLAY OFF** pill, press `R`, or
hit `▶` in the bottom bar. `←`/`→` step one decision, `Space` play/pause,
`Home`/`End` jump, `R`/`Esc` return to live. The graph, counters, timeline and
sessions are recomputed for the decisions seen so far, and the current decision
is highlighted in the CODEX ROUTING panel.

## What to look for

- **RAW ROUTER LOG** – the full log stream
- **CODEX ROUTING (EXTRACTED)** – only the decisions, with session tag, `source`,
  `class`, `model`, `similarity` and, when available, the response time `dur=`
- **PHASE TRANSITION DIAGRAM** – edge thickness is proportional to the number of
  transitions; the active node and edge are highlighted
- **TIMELINE / COUNTERS** – last 30 decisions and per-mode counters
- **SESSIONS** – one chip per session with request count and the most frequent modes
- **REPLAY BAR** – `⏮ ◀ ▶/⏸ ⏭`, speed `0.5×`–`4×`, scrubber and a `KROK n/N`
  readout; `● LIVE +N` exits replay and reports how many decisions arrived meanwhile
