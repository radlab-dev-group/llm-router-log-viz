from __future__ import annotations

import argparse
import threading
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .parser import parse_codex_routing_line
from .state import DashboardState
from .watcher import LogWatcher


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
    def __init__(self, log_path: str, follow: bool = True, read_from_start: bool = True):
        self.log_path = str(Path(log_path).resolve())
        self.follow = follow
        self.read_from_start = read_from_start
        self.state = DashboardState()
        self.lock = threading.Lock()
        self.watcher: Optional[LogWatcher] = None

    def handle_line(self, line: str, line_no: int) -> None:
        with self.lock:
            self.state.add_raw_line(line)
            event = parse_codex_routing_line(line, line_no=line_no)
            if event is not None:
                self.state.add_event(event)

    def start(self) -> None:
        self.watcher = LogWatcher(
            self.log_path,
            on_line=self.handle_line,
            poll_interval=0.5,
            read_from_start=self.read_from_start,
        )
        self.watcher.start()
        if not self.follow:
            # Give initial read a moment, then stop following.
            # For demo simplicity, follow=False means read current content only.
            # We still start watcher to read existing file; it will be stopped shortly.
            def _stop_later() -> None:
                import time

                time.sleep(1.0)
                if self.watcher:
                    self.watcher.stop()

            threading.Thread(target=_stop_later, daemon=True).start()

    def stop(self) -> None:
        if self.watcher:
            self.watcher.stop()

    def snapshot(self):
        with self.lock:
            snap = self.state.snapshot()
        snap["log_path"] = self.log_path
        snap["follow"] = self.follow
        return snap


def create_app(log_path: str, follow: bool = True, read_from_start: bool = True) -> FastAPI:
    web_dir = find_web_dir()
    ctx = AppContext(log_path=log_path, follow=follow, read_from_start=read_from_start)
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
    return p


def main(argv: Optional[list[str]] = None) -> None:
    args = build_arg_parser().parse_args(argv)
    app = create_app(
        log_path=args.log,
        follow=not args.no_follow,
        read_from_start=not args.read_from_end,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
