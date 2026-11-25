# llm-router-log-viz

Mały, lokalny dashboard do **wizualizacji na żywo decyzji routingu Codexa** na podstawie logów LLM Routera.

Pokazuje w jednym oknie:
- **RAW ROUTER LOG** – pełny strumień logów (widok terminalowy),
- **CODEX ROUTING (EXTRACTED)** – tylko wycięte linie `Codex routing: ...`,
- **PHASE TRANSITION DIAGRAM** – graf przejść między kolejnymi decyzjami routingu,
- **TIMELINE / COUNTERS** – ostatnie zdarzenia i agregaty.

> Uwaga: dashboard wizualizuje **decyzje routingu z logów**, nie wewnętrzny „stan myślenia” modelu.

## Dlaczego ten format

To repo jest przygotowane pod demo „meta”: Codex pracuje, router loguje decyzje, a dashboard pokazuje je live. Możesz je najpierw odpalić w wersji działającej, potem celowo coś zepsuć i naprawiać na żywo.

## Wymagania

- Python 3.10+
- zależności: `fastapi`, `uvicorn` (instalowane przez `pip install -e .`)

## Szybki start

```bash
cd llm-router-log-viz
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
llm-router-log-viz --log ./sample_logs/router_sample.log --host 127.0.0.1 --port 8787
```

Otwórz w przeglądarce: <http://127.0.0.1:8787>

## Podpięcie pod prawdziwy log routera

```bash
llm-router-log-viz --log /ścieżka/do/router.log --host 127.0.0.1 --port 8787
```

Dashboard tylko **czyta** plik logu. Nie modyfikuje logów routera.

## Obsługiwany format linii

Parser jest oparty o realny format z `llm-router-plugins` (`agentic_routing/codex/plugin.py`):

```text
Codex routing: mode=plan source=explicit model=qwen/Qwen3.8-Flash-Next similarity=1.000 class=main reason=explicit_agent_mode evidence=explicit memory=disabled semantic=-
```

Parser jest tolerancyjny: obsługuje też krótsze warianty, o ile są kluczowe pola `mode/source/model/...`.

## Struktura

```text
llm-router-log-viz/
  pyproject.toml
  README.md
  sample_logs/
    router_sample.log
  src/llm_router_log_viz/
    parser.py      # parsowanie linii Codex routing
    state.py       # liczniki, timeline, przejścia
    watcher.py     # tail/follow pliku logu
    server.py      # FastAPI + API + serwowanie frontendu
  web/
    index.html
    style.css      # ciemny styl inspirowany ak-bench
    app.js
  tests/
    test_parser.py
    test_state.py
    test_watcher.py
  scripts/
    demo_commands.md
```

## Testy

```bash
PYTHONPATH=src pytest -q
```

## Jak użyć tego na demo

1. Uruchom dashboard na logu routera.
2. Ułóż okno: Codex po jednej stronie, dashboard po drugiej.
3. Daj Codexowi zadanie, które naturalnie generuje fazy: plan → implement → test → debug → git_review.
4. Obserwuj, jak wpadają surowe logi, wycięte decyzje Codex i przejścia w grafie.

## Proponowane miejsca do celowego "zepsucia" (przed demem)

Wersja v0 jest działająca. Jeśli chcesz zrobić live-fix, sensowne miejsca do popsucia:

- `state.py` – błędne liczenie przejść / pomijanie wybranych trybów.
- `parser.py` – niepoprawne wyciąganie `class`/`mode` dla wybranego przypadku.
- `web/app.js` – brak podświetlenia aktywnej krawędzi lub zły render etykiet.
- `watcher.py` – nie doganianie nowych linii (ostrożnie, łatwo zepsuć cały live).

Najbezpieczniejszy wybór: **zepsuć diagram przejść w `state.py` lub render w `app.js`**, zostawiając raw log i extracted panel działające.

## Licencja / kontekst

Przykładowe narzędzie demo do ekosystemu `llm-router` / `llm-router-plugins`. Styl UI inspirowany paletą ak-bench.
