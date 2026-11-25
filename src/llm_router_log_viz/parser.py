from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Dict, Optional

CODEX_ROUTING_MARKER = "Codex routing:"

# Common log prefix timestamps: 2026-11-26 09:41:10,123 | INFO | ... or ISO-ish.
_TIMESTAMP_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?)"
)

# Key=value pairs. Values are non-whitespace tokens; we keep it tolerant.
_KV_RE = re.compile(r"(?P<key>[a-zA-Z_]+)=(?P<value>[^\s]+)")

KNOWN_MODES = [
    "plan",
    "implement",
    "review",
    "debug",
    "test",
    "git_review",
    "aux_title",
    "compaction",
]


@dataclass
class RoutingEvent:
    ts: str
    raw: str
    mode: str
    source: str
    model: str
    similarity: Optional[float]
    request_class: str
    reason: str
    evidence: str
    memory: str
    semantic: str
    line_no: int

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["class"] = data.pop("request_class")
        return data


def is_codex_routing_line(line: str) -> bool:
    return CODEX_ROUTING_MARKER in line


def extract_timestamp(line: str) -> str:
    m = _TIMESTAMP_RE.search(line)
    return m.group("ts") if m else ""


def _parse_similarity(value: str) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_codex_routing_line(line: str, line_no: int = 0) -> Optional[RoutingEvent]:
    """Parse a Codex routing log line into a RoutingEvent.

    Tolerant by design: unknown/missing fields get defaults, extra fields ignored.
    Returns None if the line is not a Codex routing decision.
    """
    if not is_codex_routing_line(line):
        return None

    marker_idx = line.index(CODEX_ROUTING_MARKER)
    payload = line[marker_idx + len(CODEX_ROUTING_MARKER) :].strip()
    kv = {m.group("key"): m.group("value") for m in _KV_RE.finditer(payload)}

    mode = kv.get("mode", "unknown")
    source = kv.get("source", "unknown")
    model = kv.get("model", "unknown")
    similarity = _parse_similarity(kv.get("similarity", ""))
    request_class = kv.get("class", "unknown")
    reason = kv.get("reason", "-")
    evidence = kv.get("evidence", "-")
    memory = kv.get("memory", "-")
    semantic = kv.get("semantic", "-")

    return RoutingEvent(
        ts=extract_timestamp(line),
        raw=line.rstrip("\n"),
        mode=mode,
        source=source,
        model=model,
        similarity=similarity,
        request_class=request_class,
        reason=reason,
        evidence=evidence,
        memory=memory,
        semantic=semantic,
        line_no=line_no,
    )


def parse_lines(lines: list[str], start_line_no: int = 1) -> list[RoutingEvent]:
    events: list[RoutingEvent] = []
    for i, line in enumerate(lines, start=start_line_no):
        ev = parse_codex_routing_line(line, line_no=i)
        if ev is not None:
            events.append(ev)
    return events
