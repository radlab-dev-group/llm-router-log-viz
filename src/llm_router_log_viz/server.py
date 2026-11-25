from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path
from typing import Dict, Optional

import anyio
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .state import DashboardState
from .watcher import LogWatcher

SSE_KEEPALIVE_S = 15.0


def find_web_dir() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "web",  # repo_root/web when src layout
        here.parents[1] / "web",
        Path.cwd() / "web",
    ]
    for c in candidates:
        if c.exists() and (c / "index.html").exists():
            return c
    raise FileNotFoundError(
        "Could not locate web/ directory. Run from repo root or install package properly."
    )


class AppContext:
    """Owns the watched log, the aggregate state and the update notifications.

    Deltas are addressed by a monotonically growing ``version``; every connected
    SSE client keeps its own cursor on the server side, so a browser tab that
    lags behind simply receives the window of lines it missed (or a full
    snapshot when it fell behind the retention window).
    """

    def __init__(
        self,
        log_path: str,
        follow: bool = True,
        read_from_start: bool = True,
        session_gap_s: float = 120.0,
        poll_interval: float = 0.5,
    ) -> None:
        self.log_path = str(Path(log_path).resolve())
        self.follow = follow
        self.read_from_start = read_from_start
        self.session_gap_s = session_gap_s
        self.poll_interval = poll_interval
        self.state = DashboardState(session_gap_s=session_gap_s)
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.version = 0
        self.raw_total = 0
        self.watcher: Optional[LogWatcher] = None

    # ------------------------------------------------------------ ingestion
    def handle_line(self, line: str, line_no: int) -> None:
        with self.condition:
            self.state.add_raw_line(line)
            self.raw_total += 1
            self.state.add_request_line(line, line_no=line_no)
            self.version += 1
            self.condition.notify_all()

    # -------------------------------------------------------------- cursors
    def cursor(self) -> Dict:
        with self.lock:
            return self._cursor_locked()

    def _cursor_locked(self) -> Dict:
        return {
            "version": self.version,
            "raw": self.raw_total,
            "events": self.state.total_events,
            "requests": self.state.requests.created_total,
        }

    def _delta_locked(self, since: Dict) -> Dict:
        raw_lines = list(self.state.raw_lines)
        events = self.state.events
        requests = self.state.requests.requests

        new_raw_count = self.raw_total - since.get("raw", 0)
        new_event_count = self.state.total_events - since.get("events", 0)
        new_request_count = self.state.requests.created_total - since.get("requests", 0)

        def window(items, count):
            if count <= 0:
                return []
            if count >= len(items):
                return list(items)
            return list(items[-count:])

        delta = self.state.aggregates()
        delta.update(
            {
                "kind": "delta",
                "cursor": self._cursor_locked(),
                "raw_lines": window(raw_lines, new_raw_count),
                "events": window(events, new_event_count),
                "requests": [r.to_dict() for r in window(requests, new_request_count)],
            }
        )
        return delta

    def wait_for_update(self, since: Dict, timeout: float = SSE_KEEPALIVE_S):
        deadline = time.monotonic() + timeout
        with self.condition:
            while self.version == since.get("version", -1):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self.condition.wait(remaining)
            return self._delta_locked(since)

    def snapshot(self) -> Dict:
        with self.lock:
            snap = self.state.snapshot()
            snap["cursor"] = self._cursor_locked()
        snap["log_path"] = self.log_path
        snap["follow"] = self.follow
        snap["session_gap_s"] = self.session_gap_s
        return snap

    def metrics(self) -> Dict:
        with self.lock:
            return self.state.metrics()

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self.watcher = LogWatcher(
            self.log_path,
            on_line=self.handle_line,
            poll_interval=self.poll_interval,
            read_from_start=self.read_from_start,
            follow=self.follow,
        )
        self.watcher.start()

    def stop(self) -> None:
        if self.watcher:
            self.watcher.stop()
        with self.condition:
            self.condition.notify_all()


def format_sse(event: str, data: Dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_app(
    log_path: str,
    follow: bool = True,
    read_from_start: bool = True,
    session_gap_s: float = 120.0,
    poll_interval: float = 0.5,
) -> FastAPI:
    web_dir = find_web_dir()
    ctx = AppContext(
        log_path=log_path,
        follow=follow,
        read_from_start=read_from_start,
        session_gap_s=session_gap_s,
        poll_interval=poll_interval,
    )
    app = FastAPI(title="LLM Router Log Viz")
    app.state.ctx = ctx

    @app.on_event("startup")
    async def _startup() -> None:
        ctx.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        ctx.stop()

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/state")
    async def state():
        return ctx.snapshot()

    @app.get("/api/metrics")
    async def metrics():
        return ctx.metrics()

    @app.get("/api/stream")
    async def stream(request: Request):
        async def generate():
            cursor = ctx.cursor()
            yield format_sse("full", ctx.snapshot())
            while True:
                if await request.is_disconnected():
                    break
                delta = await anyio.to_thread.run_sync(ctx.wait_for_update, cursor, SSE_KEEPALIVE_S)
                if delta is None:
                    yield ": keepalive\n\n"
                    continue
                yield format_sse("delta", delta)
                cursor = delta["cursor"]

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/")
    async def index():
        return FileResponse(web_dir / "index.html")

    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    return app


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Live dashboard for LLM Router Codex routing logs")
    p.add_argument("--log", required=True, help="Path to router log file to watch")
    p.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=8787, help="Port to bind (default: 8787)")
    p.add_argument("--no-follow", action="store_true", help="Read existing log content but do not follow")
    p.add_argument("--read-from-end", action="store_true", help="Start reading only new lines")
    p.add_argument(
        "--session-gap",
        type=float,
        default=120.0,
        help="Idle time (seconds) that starts a new session (default: 120)",
    )
    p.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Log poll interval in seconds (default: 0.5)",
    )
    return p


def main(argv: Optional[list[str]] = None) -> None:
    args = build_arg_parser().parse_args(argv)
    app = create_app(
        log_path=args.log,
        follow=not args.no_follow,
        read_from_start=not args.read_from_end,
        session_gap_s=args.session_gap,
        poll_interval=args.poll_interval,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
