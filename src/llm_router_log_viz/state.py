from __future__ import annotations

from collections import Counter, deque
from typing import Dict, List, Optional

from .events import RouterEventLog, parse_ts_epoch
from .parser import KNOWN_MODES, RoutingEvent

MAX_RAW_LINES = 400
MAX_EVENTS = 500
MAX_REQUESTS = 2000
SESSION_GAP_S = 120.0
BUCKET_S = 30


class DashboardState:
    """Aggregates routing events, correlated requests and sessions.

    ``snapshot()`` keeps every key the v0 dashboard consumed and adds
    ``requests`` / ``sessions``.
    """

    def __init__(self, session_gap_s: float = SESSION_GAP_S) -> None:
        self.session_gap_s = float(session_gap_s)
        self.raw_lines: deque = deque(maxlen=MAX_RAW_LINES)
        self.events: List[dict] = []
        self.requests = RouterEventLog()
        self.transition_log: List[dict] = []
        self.mode_counts: Counter = Counter()
        self.source_counts: Counter = Counter()
        self.class_counts: Counter = Counter()
        self.model_counts: Counter = Counter()
        self.total_events = 0
        self.last_mode: Optional[str] = None
        self.last_event: Optional[dict] = None
        self.sessions: List[dict] = []
        self._last_routing_epoch: Optional[float] = None

    # ----------------------------------------------------------------- raw
    def add_raw_line(self, line: str) -> None:
        self.raw_lines.append(line.rstrip("\n"))

    # ------------------------------------------------------------ sessions
    def _open_new_session(self, epoch: Optional[float]) -> dict:
        session = {
            "id": len(self.sessions) + 1,
            "requests": 0,
            "modes": Counter(),
            "start_ts": "",
            "start_epoch": epoch,
            "end_ts": "",
            "end_epoch": epoch,
        }
        self.sessions.append(session)
        return session

    def _assign_session(self, epoch: Optional[float], ts: str) -> dict:
        if not self.sessions:
            session = self._open_new_session(epoch)
        elif (
            epoch is not None
            and self._last_routing_epoch is not None
            and epoch - self._last_routing_epoch > self.session_gap_s
        ):
            session = self._open_new_session(epoch)
        else:
            session = self.sessions[-1]
        if epoch is not None:
            if session["start_epoch"] is None:
                session["start_epoch"] = epoch
            session["end_epoch"] = epoch
            session["end_ts"] = ts
        if not session["start_ts"] and ts:
            session["start_ts"] = ts
        self._last_routing_epoch = epoch
        return session

    # -------------------------------------------------------------- events
    def add_event(self, event: RoutingEvent) -> dict:
        ts_epoch = parse_ts_epoch(event.ts)
        session = self._assign_session(ts_epoch, event.ts)
        session["requests"] += 1
        session["modes"][event.mode] += 1

        ev = event.to_dict()
        ev["session"] = session["id"]
        ev["ts_epoch"] = ts_epoch
        ev["seq"] = self.total_events + 1
        self.events.append(ev)
        if len(self.events) > MAX_EVENTS:
            self.events.pop(0)

        self.total_events += 1
        self.mode_counts[event.mode] += 1
        self.source_counts[event.source] += 1
        self.class_counts[event.request_class] += 1
        self.model_counts[event.model] += 1

        # Transitions are only meaningful inside one session: a new session
        # must not inherit the previous session's last mode.
        if self.last_mode is not None and session["id"] == getattr(self, "_last_session_id", None):
            self.transition_log.append(
                {
                    "from": self.last_mode,
                    "to": event.mode,
                    "session": session["id"],
                    "seq": self.total_events,
                    "ts": event.ts,
                }
            )
        self.last_mode = event.mode
        self._last_session_id = session["id"]
        self.last_event = ev
        return ev

    def add_request_line(self, line: str, line_no: int = 0) -> Optional[str]:
        """Correlate one raw line; routing lines also feed :meth:`add_event`."""
        result = self.requests.ingest(line, line_no=line_no)
        if result is None:
            return None
        kind, record = result
        if kind == "routing" and record is not None and record.routing is not None:
            ev = self.add_event(record.routing)
            record.session = ev["session"]
        elif record is not None and self.sessions:
            record.session = self.sessions[-1]["id"]
        if len(self.requests.requests) > MAX_REQUESTS:
            self.requests.requests.pop(0)
        return kind

    # --------------------------------------------------------- transitions
    def _transition_matrix(self, session_id: Optional[int] = None) -> Dict[str, Dict[str, int]]:
        matrix: Dict[str, Dict[str, int]] = {}
        for entry in self.transition_log:
            if session_id is not None and entry.get("session") != session_id:
                continue
            row = matrix.setdefault(entry["from"], {})
            row[entry["to"]] = row.get(entry["to"], 0) + 1
        return matrix

    def _nodes(self) -> List[dict]:
        nodes = []
        seen = set()
        for mode in KNOWN_MODES:
            nodes.append({"id": mode, "count": int(self.mode_counts.get(mode, 0))})
            seen.add(mode)
        for mode, count in self.mode_counts.items():
            if mode not in seen:
                nodes.append({"id": mode, "count": int(count)})
        return nodes

    def _edges(self, session_id: Optional[int] = None) -> List[dict]:
        edges = []
        for src, targets in self._transition_matrix(session_id).items():
            for dst, count in targets.items():
                edges.append({"from": src, "to": dst, "count": int(count)})
        edges.sort(key=lambda e: (-e["count"], e["from"], e["to"]))
        return edges

    def _sessions_view(self) -> List[dict]:
        return [
            {
                "id": s["id"],
                "requests": s["requests"],
                "modes": dict(s["modes"]),
                "start_ts": s["start_ts"],
                "end_ts": s["end_ts"],
            }
            for s in self.sessions
        ]

    def aggregates(self) -> dict:
        """Derived views recomputed on demand: graph and counters."""
        return {
            "nodes": self._nodes(),
            "edges": self._edges(),
            "counts": {
                "mode": dict(self.mode_counts),
                "source": dict(self.source_counts),
                "class": dict(self.class_counts),
                "model": dict(self.model_counts),
            },
            "total_events": self.total_events,
            "last_event": self.last_event,
            "sessions": self._sessions_view(),
        }

    def snapshot(self) -> dict:
        return {
            "raw_lines": list(self.raw_lines),
            "events": list(self.events),
            "timeline": list(self.events)[-50:][::-1],
            "requests": [r.to_dict() for r in self.requests.requests],
            "session_gap_s": self.session_gap_s,
            **self.aggregates(),
        }
