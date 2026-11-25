from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .parser import (
    RoutingEvent,
    attach_semantic,
    extract_timestamp,
    parse_codex_routing_line,
    parse_semantic_routing_line,
)

# Path is deliberately generic: real routers log /v1/responses, /v1/chat/completions,
# and the path is sometimes absent altogether on the Response line.
_POST_RE = re.compile(r"POST\s+(?P<path>/\S*)?\s*(?P<kv>.*)$")
# Selected provider=lab3-flash-next model=qwen/Qwen3.8-Flash-Next
_PROVIDER_RE = re.compile(r"Selected\s+provider=(?P<provider>[^\s]+)\b(?P<kv>.*)$")
# Response 200 /v1/responses duration_ms=2666
_RESPONSE_RE = re.compile(r"Response\s+(?P<status>\d{3})\s*(?P<path>/\S*)?\s*(?P<kv>.*)$")

# Real llm-router logs announce the client request as
#   [POST] v1/responses => ['openai', 'lmstudio', ...]
#   [GET] v1/models => ['openai', ...]
_ENDPOINT_RE = re.compile(r"\[(?P<method>GET|POST|PUT|PATCH|DELETE)\]\s+(?P<path>\S+)\s*=>\s*(?P<candidates>\[[^]]*\])")
# The backend the load balancer picked:
#   Request model qwen/X with config id: qwen3.8:27b-...-66:7000 [llama.cpp: http://192.168.100.66:7000]
_BACKEND_RE = re.compile(
    r"Request model (?P<model>\S+) with config id: (?P<config_id>\S+)\s*\[(?P<engine>[^:\]]+):\s*(?P<host>[^\]\s]+)\]"
)
# The upstream reply, logged by urllib3. GETs are health probes, not client traffic.
#   http://192.168.100.66:7000 "POST /v1/responses HTTP/1.1" 200 None
_UPSTREAM_RE = re.compile(
    r"(?P<url>https?://\S+)\s+\"(?P<method>GET|POST|PUT|PATCH|DELETE)\s+(?P<path>\S+)\s+HTTP/[\d.]+\"\s+(?P<status>\d{3})\s+(?P<size>\S+)\s*$"
)
#   Provider request failed: HTTP 400 — 400 Bad Request for url — provider: {"error": {...}}
_FAILED_RE = re.compile(r"Provider request failed:\s*HTTP\s*(?P<status>\d{3})\s*(?P<detail>.*)$")
_ERROR_JSON_RE = re.compile(r"provider:\s*(?P<json>\{.*\})\s*$")

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


def _candidates(raw: str) -> List[str]:
    if not raw:
        return []
    return [c for c in re.findall(r"'([^']*)'", raw)]


def _error_detail(detail: str) -> Dict:
    """Pull the provider error body out of a ``Provider request failed`` line.

    The body is JSON but can be truncated by the log formatter, so fall back to
    the few fields the dashboard cares about.
    """
    out = {"error_type": "-", "error_message": "-", "prompt_tokens": None, "ctx_tokens": None}
    match = _ERROR_JSON_RE.search(detail)
    if match is None:
        text = detail.strip(" —\t")
        if text:
            out["error_message"] = text
        return out

    blob = match.group("json")
    payload = None
    try:
        payload = json.loads(blob)
    except ValueError:
        payload = None

    error = payload.get("error", payload) if isinstance(payload, dict) else {}
    message = (error.get("message") or "").strip() if isinstance(error, dict) else ""
    error_type = (error.get("type") or "").strip() if isinstance(error, dict) else ""

    if not message:
        message_match = re.search(r'"message"\s*:\s*"(.*?)"', blob)
        message = message_match.group(1) if message_match else ""
    if not error_type:
        type_match = re.search(r'"type"\s*:\s*"([^"]*)"', blob)
        error_type = type_match.group(1) if type_match else ""

    out["error_type"] = error_type or "-"
    out["error_message"] = message or "-"
    out["prompt_tokens"] = _int_field(blob, error, "n_prompt_tokens")
    out["ctx_tokens"] = _int_field(blob, error, "n_ctx")
    return out


def _int_field(blob: str, error: Dict, key: str) -> Optional[int]:
    value = error.get(key) if isinstance(error, dict) else None
    if isinstance(value, int):
        return value
    match = re.search(rf'"\s*{key}"\s*:\s*(\d+)', blob)
    return int(match.group(1)) if match else None


@dataclass
class RequestRecord:
    """One router request: POST -> routing decision -> backend -> upstream reply."""

    seq: int
    ts: str = ""
    ts_epoch: Optional[float] = None
    model: str = "-"
    stream: bool = False
    provider: str = "-"
    endpoint: str = "-"
    candidates: List[str] = field(default_factory=list)
    config_id: str = "-"
    engine: str = "-"
    host: str = "-"
    backend_ts: str = ""
    backend_ts_epoch: Optional[float] = None
    routing: Optional[RoutingEvent] = None
    status: Optional[int] = None
    duration_ms: Optional[float] = None
    error_type: str = "-"
    error_message: str = "-"
    prompt_tokens: Optional[int] = None
    ctx_tokens: Optional[int] = None
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
            "endpoint": self.endpoint,
            "candidates": list(self.candidates),
            "config_id": self.config_id,
            "engine": self.engine,
            "host": self.host,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "prompt_tokens": self.prompt_tokens,
            "ctx_tokens": self.ctx_tokens,
            "mode": self.mode,
            "session": self.session,
            "routing": self.routing.to_dict() if self.routing else None,
        }


@dataclass
class RouterEventLog:
    """Correlates router log lines into request records.

    Assumption (true for the sample logs of this ecosystem): a router handles
    one request at a time, so ordering is
      [POST] / POST          -> open a request
      CodexRouting           -> pending semantic detail for the next decision
      Codex routing          -> attach the routing decision to the open request
      Selected provider      -> attach the provider to the open request
      Request model ...      -> attach the chosen backend (config id / engine / host)
      Provider request failed-> attach the provider error (never closes)
      "POST ... HTTP/1.1" 400 -> close the request (urllib3 upstream reply)
      Response 200 ...       -> close the request (explicit response line)
    A routing line seen without an open POST starts a standalone request, so
    hand-appended demo lines and log fragments still correlate correctly.
    Health probes (upstream GETs) never open or close a request.
    """

    requests: List[RequestRecord] = field(default_factory=list)
    open_request: Optional[RequestRecord] = None
    pending_semantic: Optional[Dict] = None
    pending_decisions: List[RoutingEvent] = field(default_factory=list)

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
        event = attach_semantic(event, self.pending_semantic)
        self.pending_semantic = None

        if self.open_request is not None and self.open_request.routing is None:
            record = self.open_request
            record.routing = event
            if not record.ts:
                record.ts = event.ts
            if record.ts_epoch is None:
                record.ts_epoch = ts_epoch
            return record

        # No open request slot. If earlier decisions are queued (their
        # responses were still in flight), fill the oldest one: its reply is
        # the next one that will come back.
        if self.pending_decisions:
            record = self.pending_decisions.pop(0)
            record.routing = event
            if not record.ts:
                record.ts = event.ts
            if record.ts_epoch is None:
                record.ts_epoch = ts_epoch
            if record.provider == "-":
                record.provider = "-"
            self.open_request = record
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
        if self.open_request is not None and self.open_request.routing is None:
            # The previous request already decided but its reply is still in
            # flight; a new client request arrived. Park the previous decision
            # so the next decision can fill it once a slot frees up.
            self.pending_decisions.append(self.open_request)
        self.open_request = record
        return record

    def add_endpoint(
        self,
        ts: str,
        ts_epoch: Optional[float],
        method: str,
        path: str,
        candidates: List[str],
    ) -> Optional[RequestRecord]:
        """Register a client request announced as ``[POST] v1/responses => [...]``.

        Only methods that go to a backend (POST and friends) open a record for
        correlation. ``GET /v1/models`` is served by the router itself and has
        no upstream reply, so recording it must not steal the correlation slot
        from a POST that follows it.
        """
        record = RequestRecord(
            seq=self._next_seq(),
            ts=ts,
            ts_epoch=ts_epoch,
            endpoint=f"{method} {path}",
            candidates=candidates,
        )
        self.requests.append(record)
        if method == "GET":
            return record
        if self.open_request is not None and self.open_request.routing is None:
            self.pending_decisions.append(self.open_request)
        self.open_request = record
        return record

    def add_provider(self, provider: str) -> None:
        if self.open_request is not None and self.open_request.provider == "-":
            self.open_request.provider = provider

    def add_backend(
        self,
        model: str,
        config_id: str,
        engine: str,
        host: str,
        ts: str = "",
        ts_epoch: Optional[float] = None,
    ) -> Optional[RequestRecord]:
        record = self.open_request
        if record is None:
            return None
        record.config_id = config_id
        record.engine = engine
        record.host = host
        if not record.backend_ts:
            record.backend_ts = ts
        if record.backend_ts_epoch is None:
            record.backend_ts_epoch = ts_epoch
        if record.provider == "-":
            record.provider = config_id
        # The load balancer resolves the trigger model (auto_codex) to a real one.
        if record.model in ("-", "auto_codex") and model:
            record.model = model
        return record

    def add_error(
        self,
        ts: str,
        ts_epoch: Optional[float],
        status: Optional[int],
        detail: Dict,
    ) -> Optional[RequestRecord]:
        """Attach a provider error to the open request.

        The urllib3 upstream reply can arrive *before* the ``Provider request
        failed`` line, having already closed the record. In that case we attach
        to the just-closed request when it matches (same status), so the error
        details are never lost.
        """
        record = self.open_request
        if record is None and self.requests:
            last = self.requests[-1]
            if last.status == status:
                record = last
        if record is None:
            return None
        if not record.ts:
            record.ts = ts
        if record.ts_epoch is None:
            record.ts_epoch = ts_epoch
        if status is not None:
            record.status = status
        record.error_type = detail.get("error_type", "-") or "-"
        record.error_message = detail.get("error_message", "-") or "-"
        record.prompt_tokens = detail.get("prompt_tokens")
        record.ctx_tokens = detail.get("ctx_tokens")
        return record

    def add_response(
        self,
        ts: str,
        ts_epoch: Optional[float],
        status: Optional[int],
        duration_ms: Optional[float] = None,
        url: Optional[str] = None,
    ) -> Optional[RequestRecord]:
        record = self._match_response(url)
        if record is None:
            return None
        if not record.ts:
            record.ts = ts
        if record.ts_epoch is None:
            record.ts_epoch = ts_epoch
        record.status = status
        # Elapsed time is measured from the moment the request actually went
        # out (backend selection), not from the client request line.
        base_epoch = record.backend_ts_epoch if record.backend_ts_epoch is not None else record.ts_epoch
        if duration_ms is None and base_epoch is not None and ts_epoch is not None:
            duration_ms = round(max(0.0, (ts_epoch - base_epoch) * 1000.0), 1)
        record.duration_ms = duration_ms
        self.open_request = None
        return record

    def _match_response(self, url: Optional[str]) -> Optional[RequestRecord]:
        """Pick the open record an upstream reply belongs to.

        With concurrent requests, the reply names the backend host it came
        from; match that against the record's chosen host before falling back
        to the most recently opened request.
        """
        candidates = [self.open_request] if self.open_request else []
        candidates.extend(self.requests)
        if url:
            for record in reversed(candidates):
                if record.status is None and record.host == url:
                    self.open_request = record
                    return record
        for record in reversed(candidates):
            if record.status is None:
                self.open_request = record
                return record
        return None

    def add_semantic(self, semantic: Dict) -> None:
        """Buffer a ``CodexRouting:`` detail line for the next decision.

        A rejected match logs two lines (the target and the below-threshold
        note), so both are merged into one pending detail.
        """
        pending = self.pending_semantic or {}
        for key, value in semantic.items():
            if value is None or value == "-":
                continue
            pending[key] = value
        self.pending_semantic = pending

    def ingest(self, line: str, line_no: int = 0):
        """Feed one raw log line into the correlation model.

        Returns a ``(kind, record)`` tuple when the line touched a request
        record, with kind one of "routing", "post", "endpoint", "provider",
        "backend", "error", "response", "semantic", or ``None`` for lines that
        carry no router information.
        """
        ts = extract_timestamp(line)
        ts_epoch = parse_ts_epoch(ts)

        semantic = parse_semantic_routing_line(line, line_no=line_no)
        if semantic is not None:
            self.add_semantic(semantic)
            return "semantic", self.open_request

        routing = parse_codex_routing_line(line, line_no=line_no)
        if routing is not None:
            return "routing", self.add_routing(routing, ts_epoch=ts_epoch)

        parsed = parse_router_line(line)
        if parsed is None:
            return None

        kind, payload = parsed
        if kind == "post":
            return kind, self.add_post(ts, ts_epoch, payload["model"], payload["stream"])
        if kind == "endpoint":
            return kind, self.add_endpoint(
                ts, ts_epoch, payload["method"], payload["path"], payload["candidates"]
            )
        if kind == "provider":
            self.add_provider(payload["provider"])
            return kind, self.open_request
        if kind == "backend":
            return kind, self.add_backend(
                payload["model"],
                payload["config_id"],
                payload["engine"],
                payload["host"],
                ts=ts,
                ts_epoch=ts_epoch,
            )
        if kind == "error":
            record = self.add_error(ts, ts_epoch, payload["status"], payload["detail"])
            return kind, record
        if kind == "response":
            record = self.add_response(
                ts, ts_epoch, payload["status"], payload["duration_ms"], url=payload.get("url")
            )
            return kind, record
        return None


# Startup bookkeeping ("Registered endpoint POST /api/x (Handler)") is not
# request traffic; it must not open request records.
_REGISTER_RE = re.compile(r"llm_router_api\.register\.")


def parse_router_line(line: str):
    """Classify a router support line.

    Recognised kinds: ``endpoint`` (``[POST] v1/responses => [...]``),
    ``backend`` (``Request model ... with config id: ...``), ``error``
    (``Provider request failed``), ``upstream``/``response`` (the reply that
    closes a request), ``provider`` (provider selection) and the legacy bare
    ``POST /v1/...`` request line.
    """
    if _REGISTER_RE.search(line):
        return None
    # The upstream reply must win over the generic POST matcher: urllib3 logs
    # the very same "POST /v1/responses" text for the call to the backend.
    match = _UPSTREAM_RE.search(line)
    if match is not None:
        if match.group("method") == "GET":
            # Health probes (GET / , GET /health) are not client traffic.
            return None
        try:
            status = int(match.group("status"))
        except ValueError:
            status = None
        return "response", {
            "status": status,
            "duration_ms": None,
            "url": match.group("url"),
            "path": match.group("path"),
            "size": match.group("size"),
        }

    match = _ENDPOINT_RE.search(line)
    if match:
        return "endpoint", {
            "method": match.group("method"),
            "path": match.group("path"),
            "candidates": _candidates(match.group("candidates")),
        }

    match = _BACKEND_RE.search(line)
    if match:
        return "backend", {
            "model": match.group("model"),
            "config_id": match.group("config_id"),
            "engine": match.group("engine"),
            "host": match.group("host"),
        }

    match = _FAILED_RE.search(line)
    if match:
        try:
            status = int(match.group("status"))
        except ValueError:
            status = None
        return "error", {
            "status": status,
            "detail": _error_detail(match.group("detail")),
        }

    match = _POST_RE.search(line)
    if match:
        # A request line always names a routable path (starts with "/").
        # Startup lines like "Registered endpoint POST /api/x (Handler)" are
        # not requests and must not open records.
        if not (match.group("path") or "").startswith("/"):
            return None
        kv = {x.group("key"): x.group("value") for x in _KV_RE.finditer(match.group("kv"))}
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
