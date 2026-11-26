# llm-router-log-viz

A small, local dashboard that visualises **Codex routing decisions live** from
`llm-router` logs.

It tails a router log file, extracts the routing decisions and shows them in one window:

- **RAW ROUTER LOG** – the full log stream, terminal style
- **CODEX ROUTING (EXTRACTED)** – only the `Codex routing: ...` decisions, each enriched
  with the backend host, HTTP status and response time of the request it decided, plus the
  semantic classifier's margin/target from the `CodexRouting: ...` line
- **PHASE TRANSITION DIAGRAM** – graph of transitions between consecutive routing decisions
- **TIMELINE / COUNTERS** – most recent decisions (mode, source, model, backend host, duration)
  and aggregate counters
- **SESSIONS** – a session strip; an idle period longer than `--session-gap` opens a new session
- **REPLAY BAR** – bottom bar for step-by-step playback of the decision history (see below)

The dashboard reads routing **decisions from logs**. It does not expose anything about the
model's internal state.

## Requirements

- Python 3.10+
- `fastapi`, `uvicorn` (installed by `pip install -e .`)

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
llm-router-log-viz --log ./sample_logs/llm-router.log --host 127.0.0.1 --port 8787
```

Open <http://127.0.0.1:8787>.

## Usage

Point it at a real router log:

```bash
llm-router-log-viz --log /path/to/router.log --host 127.0.0.1 --port 8787
```

The dashboard only **reads** the log file; it never writes to it.

| Option | Default | Description |
| --- | --- | --- |
| `--log PATH` | required | Log file to tail (e.g. `./sample_logs/llm-router.log`) |
| `--host HOST` | `127.0.0.1` | Bind address |
| `--port PORT` | `8787` | Bind port |
| `--session-gap SEC` | `120` | Idle time that starts a new session |
| `--max-events N` | `5000` | Routing decisions kept in memory for replay |
| `--poll-interval SEC` | `0.5` | How often the log file is polled |
| `--no-follow` | off | Read existing content, then stop |
| `--read-from-end` | off | Ignore existing content, follow new lines only |

## Step-by-step replay

The bottom **replay bar** plays back the agent's routing decisions one step at
a time. While replaying, every panel (phase transition diagram, counters,
timeline, sessions) is recomputed from the decisions seen *so far*, and the
current decision is highlighted in the CODEX ROUTING panel — so you can watch
the phase diagram grow step by step.

- Start replay with the **REPLAY OFF** pill in the top bar, with `R`, or with
  `▶` in the bar: it fetches the retained history (`GET /api/events`), jumps to
  the first decision and plays it back at a fixed 1 s/step (speed selector
  `0.5×`–`4×`).
- `⏮ ◀ ▶/⏸ ⏭` and the scrubber move through the history; `● LIVE`, `Esc` or
  `R` exits replay and resynchronises the live view from `GET /api/state`.
- Keyboard (outside form controls): `←`/`→` step, `Space` play/pause,
  `Home`/`End` first/last step, `R` toggle replay, `Esc` back to live.
- While replaying, the live stream keeps accumulating in the background: the
  `● LIVE +N` badge counts new decisions, and the RAW log panel is frozen
  (`FROZEN`) with its incoming lines buffered and repainted on exit.
- Header counters describe the **replay position** (not the live total) while
  replaying; the `● LIVE +N` badge is what tells you how far live has moved.

The server retains the last `--max-events` decisions for replay; when the log
holds more, the readout shows `zachowane ostatnie N z M` (retained window).
When playback reaches the end of the retained window it pauses with a
`KONIEC HISTORII (N)` readout; with an empty log the bar shows `brak decyzji do
odtworzenia` and stays idle.

## Full phase-transition graph (demo fixture)

To see the transition diagram completely filled, generate a log that walks
every one of the 8 known modes so all 64 ordered transitions (including
self-loops) appear, in a single session:

```bash
python3 scripts/make_full_graph_log.py            # writes sample_logs/full-graph.log
llm-router-log-viz --log ./sample_logs/full-graph.log
```

The generator emits a de Bruijn sequence over the 8 modes, so each mode node is
non-empty and every `from -> to` edge is present. Flags: `-o PATH`, `--gap S`
(seconds between decisions), `--sessions N` (split the walk into N sessions).
`tests/test_full_graph_log.py` pins the coverage (all nodes > 0, all 64 edges).

## Supported log format## Supported log format

The parser follows the format emitted by `llm-router-plugins`
(`agentic_routing/codex/plugin.py`) and `llm-router`:

```text
Codex routing: mode=plan source=explicit model=qwen/Qwen3.8-Flash-Next similarity=1.000 class=main reason=explicit_agent_mode evidence=explicit memory=disabled semantic=-
```

Parsing is tolerant: shorter variants work as long as the key fields
(`mode`, `source`, `model`, ...) are present, and unknown fields are ignored.
Values may contain spaces (e.g. `reason=python3 -m pytest`); the next `key=`
token delimits the end of a value.

The semantic classifier's raw output is read too, so each decision carries the
margin between the two closest modes:

```text
CodexRouting: semantic target=review similarity=0.5605 runner_up=debug runner_similarity=0.5286 margin=0.0320
```

and the rejected form:

```text
CodexRouting: semantic match 'review' similarity=0.3627 is below threshold 0.4400
```

## Request correlation and sessions

Besides `Codex routing:` lines, the parser reads the actual `llm-router` request
lines and merges them into a single request record
(`[POST]` → decision → `Request model ...` backend → upstream reply):

- `[POST] v1/responses => ['openai', 'lmstudio', ...]` – client request (opens a record)
- `Request model qwen/... with config id: ... [llama.cpp: http://host:port]` – the backend the load
  balancer picked (engine + host, and the true dispatch instant for latency)
- `http://host:port "POST /v1/... HTTP/1.1" 200 None` – the upstream reply logged by urllib3
  (closes the record; status and duration are derived). Health probes (`GET /`, `GET /health`)
  are ignored.
- `Provider request failed: HTTP 400 — ... provider: {"error": {...}}` – the provider error
  (status, `type`, and `n_prompt_tokens`/`n_ctx` for context-overflow failures)

Concurrent requests are supported: when two requests overlap, the upstream reply is
matched to the record whose backend host it came from. The legacy
`POST /v1/... model=...`, `Selected provider=...` and `Response <status> duration_ms=...`
lines are still recognised, so old-style logs and hand-appended demo lines keep working;
a decision that arrives without an open `POST` starts its own record, so partial logs
and fragments still correlate.

Records are exposed under the `requests` key of `/api/state`, and each extracted
routing line shows its response time inline as `dur=`, the backend as `host=`, and the
HTTP status as `http=` (red when >= 400).

Every decision carries a timestamp, and an idle gap longer than `--session-gap`
(default 120 s) opens a new session. Mode transitions are counted **within a session**:
the first decision of a new session never creates an edge from the last decision of the
previous one.

## HTTP API

| Endpoint | Description |
| --- | --- |
| `GET /` | Dashboard |
| `GET /api/health` | Liveness probe |
| `GET /api/state` | Full snapshot: events, raw lines, requests, sessions, graph and counters, plus a cursor |
| `GET /api/events?after=<seq>&limit=<n>` | Retained routing decisions, oldest first (enriched with `host`/`status`/`duration_ms`, `seq`, `session`), for replay; `after` pages forward, `limit` caps page size |
| `GET /api/stream` | Server-Sent Events: one `full` event, then `delta` events carrying only new lines and recomputed aggregates |

The frontend uses `EventSource` and appends only new lines; if `EventSource` is
unavailable it falls back to polling `/api/state`.

## Project layout

```text
llm-router-log-viz/
  pyproject.toml
  README.md
  sample_logs/
    llm-router.log          # example log for local runs (gitignored, drop any router.log here)
    full-graph.log          # generated by scripts/make_full_graph_log.py (gitignored)
  src/llm_router_log_viz/
    __init__.py
    __main__.py             # `python3 -m llm_router_log_viz`
    parser.py               # parse `Codex routing:` lines
    events.py               # correlate POST / decision / provider / Response
    state.py                # sessions, counters, per-session transitions
    watcher.py              # tail / follow the log file
    server.py               # FastAPI app, HTTP API, SSE, static frontend
  web/
    index.html
    style.css
    app.js
  tests/
    test_parser.py
    test_state.py
    test_watcher.py
    test_events.py
    test_sessions.py
    test_server_api.py
    test_full_graph_log.py  # pins the full transition-graph fixture coverage
  scripts/
    usage_recipes.md        # ready-to-run commands for common cases
    make_full_graph_log.py  # generate a log that fills the entire transition diagram
```

## Tests

```bash
PYTHONPATH=src pytest -q
```

With the development extra installed (`pip install -e .[dev]`), plain `pytest -q` works too.

## License

MIT — see [LICENSE](LICENSE). Part of the `llm-router` / `llm-router-plugins` ecosystem.
