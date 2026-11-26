#!/usr/bin/env python3
"""Generate a router log whose phase transition diagram is completely filled.

The log is a de Bruijn sequence over the 8 known routing modes, so every
ordered pair of modes (all 64 transitions, including self-loops) occurs at
least once. Every decision sits in a single session (1 s apart, below the
default --session-gap of 120 s) and carries a full request lifecycle, so the
CODEX panel shows host=/http=/dur= as well.

Usage:
    python3 scripts/make_full_graph_log.py                 # writes sample_logs/full-graph.log
    python3 scripts/make_full_graph_log.py -o /tmp/full.log
    python3 scripts/make_full_graph_log.py --gap 3.0       # seconds between decisions
    python3 scripts/make_full_graph_log.py --sessions 2    # split into N sessions
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

MODES = ["plan", "implement", "review", "debug", "test", "git_review", "aux_title", "compaction"]
HOSTS = ["http://192.168.100.66:7000", "http://192.168.100.79:7000", "http://192.168.100.12:8000"]


def de_bruijn_sequence(k: int, n: int) -> list[int]:
    """Cyclic de Bruijn sequence B(k, n): every length-n word appears exactly once.

    Canonical recursive construction (Fredricksen-Mayston); the returned list has
    length k**n and must be read cyclically.
    """
    a = [0] * (k * n)
    sequence: list[int] = []

    def db(t: int, prefix_len: int) -> None:
        if t > n:
            if n % prefix_len == 0:
                sequence.extend(a[1 : prefix_len + 1])
        else:
            a[t] = a[t - prefix_len]
            db(t + 1, prefix_len)
            for j in range(a[t - prefix_len] + 1, k):
                a[t] = j
                db(t + 1, t)

    db(1, 1)
    return sequence


def mode_sequence(n_modes: int = len(MODES)) -> list[str]:
    """Modes to emit so that every ordered pair appears as a consecutive transition.

    A de Bruijn cycle B(k, 2) over k symbols lists all k**n consecutive pairs.
    We emit the cycle plus its first (n-1) symbols again so the *linear* log also
    contains every pair, including the wrap-around pair of the cycle.
    """
    cycle = de_bruijn_sequence(n_modes, 2)
    # Repeat the first symbol so the wrap-around pair is present in a linear log.
    linear = cycle + cycle[: 2 - 1]
    return [MODES[sym] for sym in linear]


def _ts(base: datetime, offset_s: float) -> str:
    stamp = base + timedelta(seconds=offset_s)
    return stamp.strftime("%Y-%m-%d %H:%M:%S,") + f"{stamp.microsecond // 1000:03d}"


def build_log_lines(
    gap_s: float = 1.0,
    n_sessions: int = 1,
    base: datetime = datetime(2026, 11, 26, 9, 0, 0),
    session_gap_s: float = 120.0,
) -> list[str]:
    """One request lifecycle per decision: POST -> routing -> backend -> reply."""
    modes = mode_sequence()
    lines: list[str] = []
    offset = 0.0
    for i, mode in enumerate(modes):
        if i > 0 and i % (len(modes) // n_sessions) == 0:
            offset += session_gap_s + 5  # idle gap opens a new session
        ts = _ts(base, offset)
        host = HOSTS[i % len(HOSTS)]
        dur = 300 + (i * 37) % 2400
        lines.append(f"{ts} INFO [llm_router.api] POST /v1/responses model=auto_codex stream=false")
        lines.append(
            f"{_ts(base, offset + 0.01)} INFO [llm_router_plugins.routing.codex] "
            f"Codex routing: mode={mode} source=phase model=qwen/Qwen3.8-Flash-Next "
            f"similarity=0.90 class=main reason=transition evidence=phase memory=miss semantic=-"
        )
        lines.append(
            f"{_ts(base, offset + 0.02)} INFO [llm_router_api.endpoints] Request model "
            f"qwen/Qwen3.8-Flash-Next with config id: qwen3.8:27b-{i % 100}:{i % 1000} "
            f"[llama.cpp: {host}]"
        )
        lines.append(
            f"{_ts(base, offset + 0.03 + dur / 1000.0)} DEBUG urllib3.connectionpool: "
            f'{host} "POST /v1/responses HTTP/1.1" 200 None'
        )
        offset += gap_s
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--out", default="sample_logs/full-graph.log", help="Output log path")
    parser.add_argument("--gap", type=float, default=1.0, help="Seconds between decisions (default: 1.0)")
    parser.add_argument("--sessions", type=int, default=1, help="Number of sessions to split into (default: 1)")
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = build_log_lines(gap_s=args.gap, n_sessions=args.sessions)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    n_modes = len(MODES)
    print(f"wrote {out} ({len(lines)} lines, {len(mode_sequence())} decisions)")
    print(f"modes: {n_modes} | expected transitions covered: {n_modes * n_modes} (all ordered pairs)")


if __name__ == "__main__":
    main()
