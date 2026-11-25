# llm-router-log-viz

A small, local dashboard that visualises **Codex routing decisions live** from
`llm-router` logs.

It tails a router log file, extracts the routing decisions and shows them in one window:

- **RAW ROUTER LOG** – the full log stream, terminal style
- **CODEX ROUTING (EXTRACTED)** – only the `Codex routing: ...` lines
- **PHASE TRANSITION DIAGRAM** – graph of transitions between consecutive routing decisions
- **TIMELINE / COUNTERS** – most recent decisions and aggregate counters
- **SESSIONS** – a session strip; an idle period longer than `--session-gap` opens a new session

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
llm-router-log-viz --log ./sample_logs/router_sample.log --host 127.0.0.1 --port 8787
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
| `--log PATH` | required | Log file to tail |
| `--host HOST` | `127.0.0.1` | Bind address |
| `--port PORT` | `8787` | Bind port |
| `--session-gap SEC` | `120` | Idle time that starts a new session |
| `--poll-interval SEC` | `0.5` | How often the log file is polled |
| `--no-follow` | off | Read existing content, then stop |
| `--read-from-end` | off | Ignore existing content, follow new lines only |

## Supported log format

The parser follows the format emitted by `llm-router-plugins`
(`agentic_routing/codex/plugin.py`):

```text
Codex routing: mode=plan source=explicit model=qwen/Qwen3.8-Flash-Next similarity=1.000 class=main reason=explicit_agent_mode evidence=explicit memory=disabled semantic=-
```

Parsing is tolerant: shorter variants work as long as the key fields
(`mode`, `source`, `model`, ...) are present, and unknown fields are ignored.

## Request correlation and sessions

Besides `Codex routing:` lines, the parser reads `POST /v1/...`,
`Selected provider=...` and `Response <status> ... duration_ms=...` lines and merges
them into a single request record (`POST` → decision → provider → `Response`). One
router is assumed to handle one request at a time; a decision that arrives without an
open `POST` starts its own record, so partial logs and fragments still correlate.

Records are exposed under the `requests` key of `/api/state`, and each extracted
routing line shows its response time inline as `dur=`.

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
| `GET /api/stream` | Server-Sent Events: one `full` event, then `delta` events carrying only new lines and recomputed aggregates |

The frontend uses `EventSource` and appends only new lines; if `EventSource` is
unavailable it falls back to polling `/api/state`.

## Project layout

```text
llm-router-log-viz/
  pyproject.toml
  README.md
  sample_logs/
    router_sample.log       # example log for local runs
  src/llm_router_log_viz/
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
  scripts/
    usage_recipes.md        # ready-to-run commands for common cases
```

## Tests

```bash
PYTHONPATH=src pytest -q
```

With the development extra installed (`pip install -e .[dev]`), plain `pytest -q` works too.

## License

MIT — see [LICENSE](LICENSE). Part of the `llm-router` / `llm-router-plugins` ecosystem.
