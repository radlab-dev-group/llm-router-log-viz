from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .parser import RoutingEvent, extract_timestamp, parse_codex_routing_line

# Path is deliberately generic: real routers log /v1/responses, /v1/chat/completions,
# and the path is sometimes absent altogether on the Response line.
_POST_RE = re.compile(r"POST\s+(?P<path>/\S*)?\s*(?P<kv>.*)$")
# Selected provider=lab3-flash-next model=qwen/Qwen3.8-Flash-Next
_PROVIDER_RE = re.compile(r"Selected\s+provider=(?P<provider>[^\s]+)\b(?P<kv>.*)$")
# Response 200 /v1/responses duration_ms=2666
_RESPONSE_RE = re.compile(r"Response\s+(?P<status>\d{3})\s*(?P<path>/\S*)?\s*(?P<kv>.*)$")

_KV_RE = re.compile(r"(?P<key>[a-zA-Z_]+)=(?P<value>[^\s]+)")

_TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S,%f",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S,%f",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
)


def parse_ts_epoch(ts: str) -> Optional[float]:
    """Convert a log timestamp string to epoch seconds. None if unparseable."""
    if not ts:
        return None
    normalized = ts.strip().replace("T", " ")
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(normalized, fmt).timestamp()
        except ValueError:
            continue
    return None


@dataclass
class RequestRecord:
    """One router request: POST -> routing decision -> provider -> Response."""

    seq: int
    ts: str = ""
    ts_epoch: Optional[float] = None
    model: str = "-"
    stream: bool = False
    provider: str = "-"
    routing: Optional[RoutingEvent] = None
    status: Optional[int] = None
    duration_ms: Optional[float] = None
    session: Optional[int] = None

    @property
    def mode(self) -> Optional[str]:
        return self.routing.mode if self.routing else None

    @property
    def is_error(self) -> bool:
        return self.status is not None and self.status >= 400

    def to_dict(self) -> Dict:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "ts_epoch": self.ts_epoch,
            "model": self.model,
            "stream": self.stream,
            "provider": self.provider,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "mode": self.mode,
            "session": self.session,
            "routing": self.routing.to_dict() if self.routing else None,
        }


@dataclass
class RouterEventLog:
    """Correlates router log lines into request records.

    Assumption (true for the sample logs of this ecosystem): a router handles
    one request at a time, so ordering is
      POST        -> open a request
      Codex routing -> attach the routing decision to the open request
      Selected provider -> attach the provider to the open request
      Response     -> close the request
    A routing line seen without an open POST starts a standalone request, so
    hand-appended demo lines and log fragments still correlate correctly.
    """

    requests: List[RequestRecord] = field(default_factory=list)
    open_request: Optional[RequestRecord] = None

    def _next_seq(self) -> int:
        return self.requests[-1].seq + 1 if self.requests else 1

    @property
    def created_total(self) -> int:
        """How many records were ever created.

        Derived from ``seq``, which is assigned monotonically and survives the
        retention trim, so it cannot drift out of sync with the list.
        """
        return self.requests[-1].seq if self.requests else 0

    def add_routing(self, event: RoutingEvent, ts_epoch: Optional[float] = None) -> RequestRecord:
        if self.open_request is not None and self.open_request.routing is None:
            record = self.open_request
            record.routing = event
            if not record.ts:
                record.ts = event.ts
            if record.ts_epoch is None:
                record.ts_epoch = ts_epoch
            return record
        record = RequestRecord(
            seq=self._next_seq(),
            ts=event.ts,
            ts_epoch=ts_epoch,
            model=event.model,
            routing=event,
        )
        self.requests.append(record)
        self.open_request = record
        return record

    def add_post(self, ts: str, ts_epoch: Optional[float], model: str, stream: bool) -> RequestRecord:
        record = RequestRecord(seq=self._next_seq(), ts=ts, ts_epoch=ts_epoch, model=model, stream=stream)
        self.requests.append(record)
        self.open_request = record
        return record

    def add_provider(self, provider: str) -> None:
        if self.open_request is not None and self.open_request.provider == "-":
            self.open_request.provider = provider

    def add_response(
        self,
        ts: str,
        ts_epoch: Optional[float],
        status: Optional[int],
        duration_ms: Optional[float],
    ) -> Optional[RequestRecord]:
        record = self.open_request
        if record is None:
            return None
        if not record.ts:
            record.ts = ts
        if record.ts_epoch is None:
            record.ts_epoch = ts_epoch
        record.status = status
        record.duration_ms = duration_ms
        self.open_request = None
        return record

    def ingest(self, line: str, line_no: int = 0):
        """Feed one raw log line into the correlation model.

        Returns a ``(kind, record)`` tuple when the line touched a request
        record, with kind one of "routing", "post", "provider", "response",
        or ``None`` for lines that carry no router information.
        """
        ts = extract_timestamp(line)
        ts_epoch = parse_ts_epoch(ts)

        routing = parse_codex_routing_line(line, line_no=line_no)
        if routing is not None:
            return "routing", self.add_routing(routing, ts_epoch=ts_epoch)

        parsed = parse_router_line(line)
        if parsed is None:
            return None

        kind, payload = parsed
        if kind == "post":
            return kind, self.add_post(ts, ts_epoch, payload["model"], payload["stream"])
        if kind == "provider":
            self.add_provider(payload["provider"])
            return kind, self.open_request
        if kind == "response":
            record = self.add_response(ts, ts_epoch, payload["status"], payload["duration_ms"])
            return kind, record
        return None


def parse_router_line(line: str):
    """Classify a router support line (POST / provider selection / Response)."""
    match = _POST_RE.search(line)
    if match:
        kv = {x.group("key"): x.group("value") for x in _KV_RE.finditer(match.group("kv"))}
        if not (match.group("path") or kv):
            return None
        return "post", {
            "model": kv.get("model", "-"),
            "stream": kv.get("stream", "false") == "true",
        }

    match = _PROVIDER_RE.search(line)
    if match:
        kv = {x.group("key"): x.group("value") for x in _KV_RE.finditer(match.group("kv"))}
        return "provider", {"provider": match.group("provider"), "model": kv.get("model", "-")}

    match = _RESPONSE_RE.search(line)
    if match:
        kv = {x.group("key"): x.group("value") for x in _KV_RE.finditer(match.group("kv"))}
        duration = None
        raw_duration = kv.get("duration_ms")
        if raw_duration:
            try:
                duration = float(raw_duration)
            except ValueError:
                duration = None
        try:
            status = int(match.group("status"))
        except ValueError:
            status = None
        return "response", {"status": status, "duration_ms": duration}

    return None
