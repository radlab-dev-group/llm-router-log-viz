from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Dict, Optional

CODEX_ROUTING_MARKER = "Codex routing:"

# Common log prefix timestamps: 2026-11-26 09:41:10,123 | INFO | ... or ISO-ish.
_TIMESTAMP_RE = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?)"
)

# Key=value pairs. A value runs until the next " key=" token, so multi-word
# values survive (e.g. reason=git add). We keep it tolerant.
_KV_RE = re.compile(r"(?P<key>[a-zA-Z_]+)=(?P<value>.*?)(?= [a-zA-Z_]+=|$)")

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
    semantic_target: str = "-"
    semantic_similarity: Optional[float] = None
    runner_up: str = "-"
    runner_similarity: Optional[float] = None
    margin: Optional[float] = None
    semantic_threshold: Optional[float] = None
    line_no: int = 0

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["class"] = data.pop("request_class")
        return data


SEMANTIC_ROUTING_MARKER = "CodexRouting:"


def is_codex_routing_line(line: str) -> bool:
    return CODEX_ROUTING_MARKER in line


_SEMANTIC_TARGET_RE = re.compile(
    r"semantic target=(?P<target>\S+) similarity=(?P<sim>\S+)"
    r"(?: runner_up=(?P<runner>\S+) runner_similarity=(?P<runner_sim>\S+) margin=(?P<margin>\S+))?"
)
_SEMANTIC_BELOW_RE = re.compile(
    r"semantic match '(?P<target>[^']*)' similarity=(?P<sim>\S+) is below threshold (?P<threshold>\S+)"
)


def is_semantic_routing_line(line: str) -> bool:
    return SEMANTIC_ROUTING_MARKER in line


def parse_semantic_routing_line(line: str, line_no: int = 0) -> Optional[Dict]:
    """Parse the ``CodexRouting:`` semantic-classifier line that precedes a
    ``Codex routing:`` decision.

    Two shapes exist in the wild:
      CodexRouting: semantic target=X similarity=S runner_up=Y runner_similarity=R margin=M
      CodexRouting: semantic match 'X' similarity=S is below threshold T
    Returns None if the line is not one of them.
    """
    if not is_semantic_routing_line(line):
        return None

    payload = line[line.index(SEMANTIC_ROUTING_MARKER) + len(SEMANTIC_ROUTING_MARKER):].strip()
    m = _SEMANTIC_TARGET_RE.search(payload)
    if m is not None:
        return {
            "ts": extract_timestamp(line),
            "semantic_target": m.group("target") or "-",
            "semantic_similarity": _parse_similarity(m.group("sim")),
            "runner_up": m.group("runner") or "-",
            "runner_similarity": _parse_similarity(m.group("runner_sim") or "") if m.group("runner_sim") else None,
            "margin": _parse_similarity(m.group("margin") or "") if m.group("margin") else None,
            "semantic_threshold": None,
            "line_no": line_no,
        }

    m = _SEMANTIC_BELOW_RE.search(payload)
    if m is not None:
        return {
            "ts": extract_timestamp(line),
            "semantic_target": m.group("target") or "-",
            "semantic_similarity": _parse_similarity(m.group("sim")),
            "runner_up": "-",
            "runner_similarity": None,
            "margin": None,
            "semantic_threshold": _parse_similarity(m.group("threshold")),
            "line_no": line_no,
        }

    return None


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


def attach_semantic(event: RoutingEvent, semantic: Optional[Dict]) -> RoutingEvent:
    """Attach a parsed ``CodexRouting:`` payload to a routing decision.

    The semantic line is the classifier's raw output; the decision line is what
    was finally routed. Keeping both lets the dashboard show target-vs-final
    mode, margins and threshold rejections.
    """
    if event is None or not semantic:
        return event
    event.semantic_target = semantic.get("semantic_target", "-") or "-"
    event.semantic_similarity = semantic.get("semantic_similarity")
    event.runner_up = semantic.get("runner_up", "-") or "-"
    event.runner_similarity = semantic.get("runner_similarity")
    event.margin = semantic.get("margin")
    event.semantic_threshold = semantic.get("semantic_threshold")
    return event


def parse_lines(lines: list[str], start_line_no: int = 1) -> list[RoutingEvent]:
    events: list[RoutingEvent] = []
    for i, line in enumerate(lines, start=start_line_no):
        ev = parse_codex_routing_line(line, line_no=i)
        if ev is not None:
            events.append(ev)
    return events
