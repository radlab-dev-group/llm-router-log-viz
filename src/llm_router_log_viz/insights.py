from __future__ import annotations

import re
from typing import Dict, List, Optional

SIMILARITY_FLOOR = 0.85
FLAP_WINDOW = 4
MEMORY_MISS_RATIO = 0.4
MEMORY_MISS_MIN_EVENTS = 5
LARGE_MODEL_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*B\b", re.IGNORECASE)
LARGE_MODEL_MIN_B = 27.0
AUX_CLASSES = {"aux_title", "compaction", "structural", "title"}


def _sev_rank(severity: str) -> int:
    return {"critical": 0, "warning": 1, "info": 2}.get(severity, 3)


def _model_size_b(model: str) -> Optional[float]:
    match = LARGE_MODEL_RE.search(model or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _is_aux(event: dict) -> bool:
    request_class = (event.get("class") or event.get("request_class") or "").lower()
    mode = (event.get("mode") or "").lower()
    return request_class in AUX_CLASSES or mode in AUX_CLASSES


def _low_similarity(events: List[dict]) -> List[dict]:
    hits = [
        ev
        for ev in events
        if ev.get("similarity") is not None and float(ev["similarity"]) < SIMILARITY_FLOOR
    ]
    if not hits:
        return []
    worst = min(hits, key=lambda ev: float(ev["similarity"]))
    return [
        {
            "id": "low_similarity",
            "severity": "critical" if float(worst["similarity"]) < 0.6 else "warning",
            "title": f"Niska pewność routingu ({len(hits)}×)",
            "detail": (
                f"similarity < {SIMILARITY_FLOOR}; najgorzej: mode={worst.get('mode')} "
                f"similarity={float(worst['similarity']):.3f} "
                f"reason={worst.get('reason', '-')}"
            ),
            "refs": [ev.get("seq") for ev in hits if ev.get("seq") is not None],
            "line_no": worst.get("line_no"),
        }
    ]


def _flapping(events: List[dict]) -> List[dict]:
    by_session: Dict[object, List[dict]] = {}
    for ev in events:
        by_session.setdefault(ev.get("session"), []).append(ev)

    findings = []
    for session_id, session_events in by_session.items():
        modes = [ev.get("mode") for ev in session_events]
        flaps = 0
        refs: List[int] = []
        for i in range(len(modes) - 2):
            window = modes[i : i + FLAP_WINDOW]
            for j in range(len(window) - 2):
                if window[j] and window[j] == window[j + 2] and window[j] != window[j + 1]:
                    flaps += 1
                    refs.extend(
                        ev.get("seq")
                        for ev in session_events[i + j : i + j + 3]
                        if ev.get("seq") is not None
                    )
        if flaps:
            findings.append(
                {
                    "id": f"mode_flapping:{session_id}",
                    "severity": "warning",
                    "title": f"Flapping trybów w sesji {session_id} ({flaps}×)",
                    "detail": "sekwencja A→B→A w krótkim oknie — routing prawdopodobnie oscyluje",
                    "refs": sorted(set(refs)),
                }
            )
    return findings


def _git_review_without_test(events: List[dict]) -> List[dict]:
    by_session: Dict[object, List[dict]] = {}
    for ev in events:
        by_session.setdefault(ev.get("session"), []).append(ev)

    findings = []
    for session_id, session_events in by_session.items():
        offenders = []
        seen_test = False
        for ev in session_events:
            mode = (ev.get("mode") or "").lower()
            if mode == "test":
                seen_test = True
            elif mode == "git_review" and not seen_test:
                offenders.append(ev)
        if offenders:
            findings.append(
                {
                    "id": f"git_review_without_test:{session_id}",
                    "severity": "warning",
                    "title": f"git_review bez wcześniejszego testu (sesja {session_id})",
                    "detail": "review zmian na gałęzi bez testów w tej sesji — ryzyko braku weryfikacji",
                    "refs": [ev.get("seq") for ev in offenders if ev.get("seq") is not None],
                    "line_no": offenders[0].get("line_no"),
                }
            )
    return findings


def _aux_on_large_model(events: List[dict]) -> List[dict]:
    hits = []
    for ev in events:
        if not _is_aux(ev):
            continue
        size = _model_size_b(ev.get("model", ""))
        if size is not None and size >= LARGE_MODEL_MIN_B:
            hits.append((ev, size))
    if not hits:
        return []
    sample = hits[0]
    return [
        {
            "id": "aux_on_large_model",
            "severity": "info",
            "title": f"Request pomocniczy na dużym modelu ({len(hits)}×)",
            "detail": (
                f"mode={sample[0].get('mode')} → {sample[0].get('model')} "
                f"(~{sample[1]:.0f}B); klasy pomocnicze zwykle taniej obsłuży model mniejszy"
            ),
            "refs": [ev.get("seq") for ev, _ in hits if ev.get("seq") is not None],
        }
    ]


def _memory_miss_spike(events: List[dict]) -> List[dict]:
    considered = [ev for ev in events if ev.get("memory") not in (None, "-", "")]
    if len(considered) < MEMORY_MISS_MIN_EVENTS:
        return []
    misses = [ev for ev in considered if str(ev.get("memory")).lower() == "miss"]
    ratio = len(misses) / len(considered)
    if ratio < MEMORY_MISS_RATIO:
        return []
    return [
        {
            "id": "memory_miss_spike",
            "severity": "warning",
            "title": f"Spike pamięci semantycznej: {len(misses)}/{len(considered)} miss",
            "detail": f"udział miss = {ratio:.0%} (próg {MEMORY_MISS_RATIO:.0%}) — decyzje routingu "
            "bezkontekstowe lub świeża sesja",
            "refs": [ev.get("seq") for ev in misses if ev.get("seq") is not None],
        }
    ]


def _data_quality(requests: List[dict]) -> List[dict]:
    no_routing = [r for r in requests if r.get("routing") is None]
    unclosed = [
        r for r in requests if r.get("routing") is not None and r.get("duration_ms") is None and r.get("status") is None
    ]
    findings = []
    if no_routing:
        findings.append(
            {
                "id": "requests_without_routing",
                "severity": "info",
                "title": f"Requesty bez decyzji routingu ({len(no_routing)}×)",
                "detail": "POST bez linii `Codex routing:` — log niekompletny lub ścieżka poza pluginem",
                "refs": [r.get("seq") for r in no_routing if r.get("seq") is not None],
            }
        )
    if unclosed:
        findings.append(
            {
                "id": "unclosed_requests",
                "severity": "info",
                "title": f"Otwarte requesty bez Response ({len(unclosed)}×)",
                "detail": "linia `Response …` nigdy nie spadła — request w toku lub zgubiony w logu",
                "refs": [r.get("seq") for r in unclosed if r.get("seq") is not None],
            }
        )
    return findings


def lint(events: List[dict], requests: List[dict], sessions: Optional[List[dict]] = None) -> List[dict]:
    """Run all routing-lint rules over the current aggregates.

    Pure function of the data handed in; safe to call on every snapshot.
    """
    findings: List[dict] = []
    findings += _low_similarity(events)
    findings += _flapping(events)
    findings += _git_review_without_test(events)
    findings += _aux_on_large_model(events)
    findings += _memory_miss_spike(events)
    findings += _data_quality(requests)
    findings.sort(key=lambda f: (_sev_rank(f["severity"]), -len(f.get("refs") or []), f["id"]))
    return findings
