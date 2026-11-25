from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

from .parser import KNOWN_MODES, RoutingEvent


@dataclass
class DashboardState:
    raw_lines: Deque[str] = field(default_factory=lambda: deque(maxlen=400))
    events: Deque[Dict] = field(default_factory=lambda: deque(maxlen=500))
    transitions: Dict[str, Dict[str, int]] = field(default_factory=dict)
    mode_counts: Counter = field(default_factory=Counter)
    source_counts: Counter = field(default_factory=Counter)
    class_counts: Counter = field(default_factory=Counter)
    model_counts: Counter = field(default_factory=Counter)
    total_events: int = 0
    last_mode: Optional[str] = None
    last_event: Optional[Dict] = None

    def add_raw_line(self, line: str) -> None:
        self.raw_lines.append(line.rstrip("\n"))

    def add_event(self, event: RoutingEvent) -> None:
        ev = event.to_dict()
        prev_mode = self.last_mode
        self.events.append(ev)
        self.total_events += 1
        self.mode_counts[event.mode] += 1
        self.source_counts[event.source] += 1
        self.class_counts[event.request_class] += 1
        self.model_counts[event.model] += 1

        if prev_mode is not None:
            self.transitions.setdefault(prev_mode, {})
            self.transitions[prev_mode][event.mode] = (
                self.transitions[prev_mode].get(event.mode, 0) + 1
            )

        self.last_mode = event.mode
        self.last_event = ev

    def snapshot(self) -> Dict:
        # Ensure all known modes appear as nodes for stable UI.
        nodes = []
        seen = set()
        for mode in KNOWN_MODES:
            nodes.append({"id": mode, "count": int(self.mode_counts.get(mode, 0))})
            seen.add(mode)
        for mode, count in self.mode_counts.items():
            if mode not in seen:
                nodes.append({"id": mode, "count": int(count)})

        edges = []
        for src, targets in self.transitions.items():
            for dst, count in targets.items():
                edges.append({"from": src, "to": dst, "count": int(count)})
        edges.sort(key=lambda e: (-e["count"], e["from"], e["to"]))

        return {
            "raw_lines": list(self.raw_lines),
            "events": list(self.events),
            "timeline": list(self.events)[-50:][::-1],
            "nodes": nodes,
            "edges": edges,
            "counts": {
                "mode": dict(self.mode_counts),
                "source": dict(self.source_counts),
                "class": dict(self.class_counts),
                "model": dict(self.model_counts),
            },
            "total_events": self.total_events,
            "last_event": self.last_event,
        }
