(() => {
  const KNOWN_MODES = ["plan", "implement", "review", "debug", "test", "git_review", "aux_title", "compaction"];
  const NODE_POS = {
    plan:        { x: 110, y: 95 },
    implement:   { x: 330, y: 95 },
    test:        { x: 550, y: 95 },
    git_review:  { x: 770, y: 95 },
    aux_title:   { x: 110, y: 260 },
    debug:       { x: 330, y: 260 },
    review:      { x: 550, y: 260 },
    compaction:  { x: 770, y: 260 },
  };
  const NODE_W = 150;
  const NODE_H = 56;
  const EXTRA_ROW_Y = 410;
  const EXTRA_PER_ROW = 4;
  // Keep in sync with the viewBox shipped in index.html: when the computed
  // height matches it, the SVG attribute is never touched and nothing moves.
  const GRAPH_BASE_HEIGHT = 360;
  const GRAPH_PADDING = 24;
  const GRAPH_KNOWN_BOTTOM = 260;
  const MAX_DOM_LINES = 500;
  const MAX_CLIENT_EVENTS = 5000;

  const rawLogEl = document.getElementById("raw-log");
  const codexLogEl = document.getElementById("codex-log");
  const timelineBodyEl = document.getElementById("timeline-body");
  const countersEl = document.getElementById("counters");
  const graphEl = document.getElementById("phase-graph");
  const livePill = document.getElementById("live-pill");
  const liveText = document.getElementById("live-text");
  const logPathEl = document.getElementById("log-path");
  const eventCountEl = document.getElementById("event-count");
  const lastModeEl = document.getElementById("last-mode");
  const reqCountEl = document.getElementById("req-count");
  const rawAuto = document.getElementById("raw-autoscroll");
  const codexAuto = document.getElementById("codex-autoscroll");
  const sessionStripEl = document.getElementById("session-strip");
  const replayBarEl = document.getElementById("replay-bar");
  const replayPill = document.getElementById("replay-pill");
  const replayPillText = document.getElementById("replay-text");
  const rpFirst = document.getElementById("rp-first");
  const rpPrev = document.getElementById("rp-prev");
  const rpPlay = document.getElementById("rp-play");
  const rpNext = document.getElementById("rp-next");
  const rpLast = document.getElementById("rp-last");
  const rpSpeed = document.getElementById("rp-speed");
  const rpRange = document.getElementById("rp-range");
  const rpStep = document.getElementById("rp-step");
  const rpNote = document.getElementById("rp-note");
  const rpCurrent = document.getElementById("rp-current");
  const rpExit = document.getElementById("rp-exit");
  const rpExitBadge = document.getElementById("rp-exit-badge");
  const rawPanelEl = document.querySelector(".panel-raw");

  // Client-side mirror of routing events: keeps deltas cheap (append, no refetch).
  let clientEvents = [];
  let layout = Object.assign({}, NODE_POS);
  let appliedGraphHeight = (() => {
    const parts = (graphEl.getAttribute("viewBox") || "").split(/\s+/);
    const h = parseInt(parts[3], 10);
    return Number.isFinite(h) ? h : GRAPH_BASE_HEIGHT;
  })();

  function applyViewBox(height) {
    if (height === appliedGraphHeight) return;
    appliedGraphHeight = height;
    graphEl.setAttribute("viewBox", `0 0 920 ${height}`);
  }

  function esc(s) {
    return String(s)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function modeClass(mode) {
    const m = KNOWN_MODES.includes(mode) ? mode : "unknown";
    return `mode-${m}`;
  }

  function fmtMs(ms) {
    if (ms == null) return "—";
    if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`;
    return `${Math.round(ms)}ms`;
  }

  function shortTs(ts) {
    if (!ts) return "—";
    const idx = ts.indexOf(" ");
    return idx > 0 ? ts.slice(idx + 1) : ts;
  }

  // ------------------------------------------------------------------ layout
  // Extra (unknown) modes are appended in arrival order and never re-sorted,
  // so placing a new mode cannot re-flow the nodes that are already placed.
  let extraSlots = 0;

  function computeLayout(nodes) {
    for (const node of nodes || []) {
      if (layout[node.id]) continue;
      const row = Math.floor(extraSlots / EXTRA_PER_ROW);
      const col = extraSlots % EXTRA_PER_ROW;
      extraSlots += 1;
      layout[node.id] = { x: 110 + col * 220, y: EXTRA_ROW_Y + row * 120 };
    }
    return layout;
  }

  function graphViewHeight() {
    let maxY = GRAPH_KNOWN_BOTTOM;
    for (const id of Object.keys(layout)) maxY = Math.max(maxY, layout[id].y);
    return Math.max(GRAPH_BASE_HEIGHT, maxY + NODE_H / 2 + GRAPH_PADDING);
  }

  function nodeCenter(mode) {
    const p = layout[mode];
    return p ? { x: p.x, y: p.y } : { x: 460, y: 170 };
  }

  function edgePath(from, to) {
    const a = nodeCenter(from);
    const b = nodeCenter(to);
    if (from === to) {
      const isBottom = a.y > 180;
      const x = a.x;
      if (isBottom) {
        const y = a.y + NODE_H / 2;
        return `M ${x + 18} ${y} C ${x + 50} ${y + 48}, ${x - 50} ${y + 48}, ${x - 18} ${y}`;
      }
      const y = a.y - NODE_H / 2;
      return `M ${x - 18} ${y} C ${x - 50} ${y - 48}, ${x + 50} ${y - 48}, ${x + 18} ${y}`;
    }
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const mx = (a.x + b.x) / 2;
    const my = (a.y + b.y) / 2;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const nx = -dy / len;
    const ny = dx / len;

    let bend = Math.min(50, Math.max(22, len * 0.12));
    let flipNormal = false;
    if (Math.abs(dx) > 300 && Math.abs(dy) < 60) {
      // Long horizontal returns across columns: curve smoothly through the middle gap
      bend = 80;
      if (dx < 0) flipNormal = true; // curve downward into the spacious middle corridor
    }
    const effNy = flipNormal ? -ny : ny;
    const effNx = flipNormal ? -nx : nx;
    const cx = mx + effNx * bend;
    const cy = my + effNy * bend;

    const trim = 75;
    const ux = dx / len, uy = dy / len;
    const sx = a.x + ux * trim;
    const sy = a.y + uy * 35;
    const ex = b.x - ux * trim;
    const ey = b.y - uy * 35;
    return `M ${sx} ${sy} Q ${cx} ${cy} ${ex} ${ey}`;
  }

  function edgeLabelPos(from, to) {
    const a = nodeCenter(from);
    const b = nodeCenter(to);
    if (from === to) {
      const isBottom = a.y > 180;
      return { x: a.x, y: isBottom ? a.y + NODE_H / 2 + 34 : a.y - NODE_H / 2 - 28 };
    }
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const mx = (a.x + b.x) / 2;
    const my = (a.y + b.y) / 2;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const nx = -dy / len;
    const ny = dx / len;

    let bend = Math.min(50, Math.max(22, len * 0.12));
    let flipNormal = false;
    if (Math.abs(dx) > 300 && Math.abs(dy) < 60) {
      bend = 80;
      if (dx < 0) flipNormal = true;
    }
    const effNy = flipNormal ? -ny : ny;
    const effNx = flipNormal ? -nx : nx;
    return { x: mx + effNx * (bend * 0.65), y: my + effNy * (bend * 0.65) - 2 };
  }

  // ------------------------------------------------------------------- lines
  function rawLineHtml(line) {
    const isCodex = line.includes("Codex routing:");
    return `<div class="log-line ${isCodex ? "codex" : ""}">${esc(line)}</div>`;
  }

  function eventLineHtml(ev) {
    const ts = ev.ts ? `<span class="ts">${esc(ev.ts)}</span> ` : "";
    const mode = `<span class="badge ${modeClass(ev.mode)}">${esc(ev.mode)}</span>`;
    const session = ev.session ? `<span class="session-tag">S${esc(ev.session)}</span> ` : "";
    const latency = ev.duration_ms != null
      ? ` <span class="kv"><span class="k">dur</span>=<span class="v">${fmtMs(ev.duration_ms)}</span></span>`
      : "";
    const status = ev.status != null
      ? ` <span class="kv"><span class="k">http</span>=<span class="v ${ev.status >= 400 ? "err" : ""}">${ev.status}</span></span>`
      : "";
    const host = ev.host
      ? ` <span class="kv"><span class="k">host</span>=<span class="v">${esc(ev.host.replace(/^https?:\/\//, ""))}</span></span>`
      : "";
    const rest = [
      `<span class="kv"><span class="k">source</span>=<span class="v src">${esc(ev.source)}</span></span>`,
      `<span class="kv"><span class="k">class</span>=<span class="v cls">${esc(ev.class || ev.request_class || "-")}</span></span>`,
      `<span class="kv"><span class="k">model</span>=<span class="v model">${esc(ev.model)}</span></span>`,
      `<span class="kv"><span class="k">sim</span>=<span class="v">${ev.similarity == null ? "-" : Number(ev.similarity).toFixed(3)}</span></span>`,
    ].join(" ");
    return `<div class="log-line codex">${session}${ts}${mode} ${rest}${host}${status}${latency}</div>`;
  }

  function trimDom(el) {
    while (el.childElementCount > MAX_DOM_LINES) el.removeChild(el.firstElementChild);
  }

  function appendRaw(lines) {
    if (!lines.length) return;
    rawLogEl.insertAdjacentHTML("beforeend", lines.map(rawLineHtml).join(""));
    trimDom(rawLogEl);
    if (rawAuto.checked) rawLogEl.scrollTop = rawLogEl.scrollHeight;
  }

  function appendCodex(events) {
    if (!events.length) return;
    codexLogEl.insertAdjacentHTML("beforeend", events.map(eventLineHtml).join(""));
    trimDom(codexLogEl);
    if (codexAuto.checked) codexLogEl.scrollTop = codexLogEl.scrollHeight;
  }

  function resetContainers() {
    rawLogEl.innerHTML = "";
    codexLogEl.innerHTML = "";
  }

  // --------------------------------------------------------------- renderers
  function renderCounters(state) {
    const counts = (state.counts && state.counts.mode) || {};
    const order = [...KNOWN_MODES, ...Object.keys(counts).filter(k => !KNOWN_MODES.includes(k))];
    countersEl.innerHTML = order.map(mode => {
      const n = counts[mode] || 0;
      return `<div class="counter"><strong>${esc(mode)}</strong><span class="n">${n}</span></div>`;
    }).join("") + `<div class="counter"><strong>total</strong><span class="n">${state.total_events || 0}</span></div>`;
  }

  function renderTimeline(events) {
    const source = events && events.length ? events : clientEvents;
    const rows = source.slice(-30).reverse();
    timelineBodyEl.innerHTML = rows.map(ev => `
      <tr>
        <td>${esc(shortTs(ev.ts))}</td>
        <td><span class="badge ${modeClass(ev.mode)}">${esc(ev.mode)}</span></td>
        <td>${esc(ev.source || "-")}</td>
        <td class="model-cell" title="${esc(ev.model || "-")}">${esc(ev.model || "-")}</td>
        <td class="host-cell" title="${esc(ev.host || "-")}">${esc((ev.host || "-").replace(/^https?:\/\//, ""))}</td>
        <td class="${ev.duration_ms != null ? "" : "muted"}">${ev.duration_ms != null ? fmtMs(ev.duration_ms) : "—"}</td>
      </tr>
    `).join("");
  }

  function renderGraph(state) {
    const nodes = state.nodes || [];
    const edges = state.edges || [];
    computeLayout(nodes);
    applyViewBox(graphViewHeight());

    const last = state.last_event;
    const lastMode = last ? last.mode : null;
    const prevMode = clientEvents.length >= 2 ? clientEvents[clientEvents.length - 2].mode : null;
    const maxCount = edges.length ? edges[0].count : 1;

    let svg = `
      <defs>
        <marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth">
          <path d="M0,0 L0,6 L9,3 z" fill="#35506a" />
        </marker>
        <marker id="arrow-active" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto" markerUnits="strokeWidth">
          <path d="M0,0 L0,6 L9,3 z" fill="#00e59b" />
        </marker>
      </defs>
    `;

    for (const e of edges) {
      const active = prevMode && lastMode && e.from === prevMode && e.to === lastMode;
      const width = (0.9 + 2.6 * (e.count / maxCount)).toFixed(2);
      const path = edgePath(e.from, e.to);
      const lp = edgeLabelPos(e.from, e.to);
      svg += `<path class="graph-edge ${active ? "active" : ""}" style="stroke-width:${width}" d="${path}" marker-end="url(#${active ? "arrow-active" : "arrow"})"></path>`;
      svg += `<text class="edge-label ${active ? "active" : ""}" x="${lp.x}" y="${lp.y}" text-anchor="middle">${e.count}</text>`;
    }

    for (const n of nodes) {
      const pos = layout[n.id] || { x: 460, y: 170 };
      const active = lastMode === n.id;
      const count = n.count || 0;
      const x = pos.x - NODE_W / 2;
      const y = pos.y - NODE_H / 2;
      svg += `
        <g class="graph-node mode-${esc(n.id)} ${active ? "active" : ""} ${count === 0 ? "empty" : ""}">
          <rect x="${x}" y="${y}" rx="8" ry="8" width="${NODE_W}" height="${NODE_H}"></rect>
          <text class="node-title" x="${pos.x}" y="${pos.y - 4}" text-anchor="middle">${esc(n.id)}</text>
          <text class="count" x="${pos.x}" y="${pos.y + 16}" text-anchor="middle">${count} events</text>
        </g>
      `;
    }

    graphEl.innerHTML = svg;
  }

  function renderSessions(state) {
    const sessions = state.sessions || [];
    if (!sessions.length) return;
    const activeId = sessions.length ? sessions[sessions.length - 1].id : null;
    const chips = sessions.slice(-12).map(s => {
      const modes = Object.entries(s.modes || {})
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([m, n]) => `${m}:${n}`)
        .join(" ");
      return `<button class="session-chip ${s.id === activeId ? "active" : ""}" title="${esc(s.start_ts)} → ${esc(s.end_ts)}">
        <span class="sid">S${s.id}</span>
        <span class="sreq">${s.requests} req</span>
        <span class="smodes">${esc(modes)}</span>
      </button>`;
    });
    sessionStripEl.innerHTML = `<span class="session-strip-label">SESSIONS</span>${chips.join("")}` +
      (sessions.length > 12 ? `<span class="muted">+${sessions.length - 12}</span>` : "");
  }

  // ------------------------------------------------------------------ render
  let lastState = null;

  function applyHeader(state) {
    logPathEl.textContent = state.log_path || logPathEl.textContent || "—";
    eventCountEl.textContent = String(state.total_events || 0);
    lastModeEl.textContent = state.last_event ? state.last_event.mode : "—";
    const cursor = state.cursor || {};
    reqCountEl.textContent = String(cursor.requests != null ? cursor.requests : (state.requests || []).length);
  }

  function renderFull(state) {
    lastState = state;
    clientEvents = (state.events || []).slice(-MAX_CLIENT_EVENTS);
    replay.pendingRaw = [];
    resetContainers();
    applyHeader(state);
    appendRaw(state.raw_lines || []);
    appendCodex(clientEvents);
    renderCounters(state);
    renderTimeline();
    renderGraph(state);
    renderSessions(state);
  }

  function renderDelta(delta) {
    lastState = Object.assign({}, lastState || {}, delta);
    if (replay.active) {
      // Stay frozen: accumulate history for the replay, buffer the raw stream,
      // and surface how much has piled up behind the scrubber.
      if (delta.events && delta.events.length) {
        for (const ev of delta.events) {
          const exists = replay.events.some((x) => x.seq === ev.seq);
          if (!exists) replay.events.push(ev);
          replay.pendingSinceReplay += 1;
        }
        replay.events.sort((a, b) => (a.seq || 0) - (b.seq || 0));
        replay.total = delta.cursor ? (delta.cursor.events || replay.total) : replay.total;
        if (rpRange.max !== "1") {
          rpRange.max = String(replay.events.length);
          rpStep.textContent = `KROK ${replay.index + 1}/${replay.events.length}`;
        }
      }
      if (delta.raw_lines && delta.raw_lines.length) replay.pendingRaw.push(...delta.raw_lines);
      updateExitBadge();
      return;
    }
    if (delta.events && delta.events.length) {
      clientEvents = clientEvents.concat(delta.events).slice(-MAX_CLIENT_EVENTS);
    }
    applyHeader(lastState);
    appendRaw(delta.raw_lines || []);
    appendCodex(delta.events || []);
    renderCounters(lastState);
    renderTimeline();
    renderGraph(lastState);
    renderSessions(lastState);
  }

  // ------------------------------------------------------------------ replay
  // Step-by-step playback of routing decisions. The live stream keeps feeding
  // clientEvents in the background; replay renders any prefix of a *dedicated*
  // history list (fetched from /api/events) so it can cover the whole retained
  // window even when the live DOM mirror has already been trimmed.
  const REPLAY_BASE_INTERVAL_MS = 1000;

  const replay = {
    active: false,
    playing: false,
    speed: 1,
    index: -1,
    events: [],
    total: 0,
    pendingRaw: [],
    pendingSinceReplay: 0,
    timer: null,
  };

  function replayStepCount() {
    return replay.events.length;
  }

  // Recompute the dashboard views (graph, counters, sessions) for a prefix of
  // the history. The shape mirrors what the server's aggregates() produces so
  // the existing renderers can be reused unchanged.
  function derivePrefix(slice) {
    const counts = { mode: {}, source: {}, class: {}, model: {} };
    const sessions = [];
    const sessionById = {};

    for (const ev of slice) {
      counts.mode[ev.mode] = (counts.mode[ev.mode] || 0) + 1;
      if (ev.source) counts.source[ev.source] = (counts.source[ev.source] || 0) + 1;
      const cls = ev.class || ev.request_class || "-";
      counts.class[cls] = (counts.class[cls] || 0) + 1;
      if (ev.model) counts.model[ev.model] = (counts.model[ev.model] || 0) + 1;

      let sess = sessionById[ev.session];
      if (!sess) {
        sess = { id: ev.session, requests: 0, modes: {}, start_ts: "", end_ts: "" };
        sessionById[ev.session] = sess;
        sessions.push(sess);
      }
      sess.requests += 1;
      sess.modes[ev.mode] = (sess.modes[ev.mode] || 0) + 1;
      if (ev.ts && !sess.start_ts) sess.start_ts = ev.ts;
      if (ev.ts) sess.end_ts = ev.ts;
    }

    // Transitions: consecutive decisions within the same session only; the
    // first decision of a session never produces an edge (mirrors the server).
    const matrix = {};
    let prev = null;
    for (const ev of slice) {
      if (prev && prev.session === ev.session) {
        const row = matrix[prev.mode] || (matrix[prev.mode] = {});
        row[ev.mode] = (row[ev.mode] || 0) + 1;
      }
      prev = ev;
    }
    const edges = [];
    for (const from of Object.keys(matrix)) {
      for (const to of Object.keys(matrix[from])) {
        edges.push({ from, to, count: matrix[from][to] });
      }
    }
    edges.sort((a, b) => (b.count - a.count) || (a.from < b.from ? -1 : a.from > b.from ? 1 : (a.to < b.to ? -1 : a.to > b.to ? 1 : 0)));

    const nodes = [];
    const seen = new Set();
    for (const mode of KNOWN_MODES) {
      nodes.push({ id: mode, count: counts.mode[mode] || 0 });
      seen.add(mode);
    }
    for (const mode of Object.keys(counts.mode)) {
      if (!seen.has(mode)) nodes.push({ id: mode, count: counts.mode[mode] });
    }

    const last_event = slice.length ? slice[slice.length - 1] : null;
    return {
      nodes,
      edges,
      counts,
      total_events: slice.length,
      last_event,
      sessions: sessions.map((s) => ({
        id: s.id, requests: s.requests, modes: s.modes,
        start_ts: s.start_ts, end_ts: s.end_ts,
      })),
    };
  }

  function replayCurrentSummary(ev) {
    if (!ev) return "";
    const ts = ev.ts ? `<span class="ts">${esc(shortTs(ev.ts))}</span>` : "";
    const mode = `<span class="badge ${modeClass(ev.mode)}">${esc(ev.mode)}</span>`;
    const kv = (k, v) => `<span class="kv"><span class="k">${k}</span>=${esc(v)}</span>`;
    return ts + " " + mode + " " +
      kv("source", ev.source || "-") + " " +
      kv("model", (ev.model || "-").replace(/^.*\//, "")) +
      (ev.host ? " " + kv("host", String(ev.host).replace(/^https?:\/\//, "")) : "");
  }

  function renderReplayStep(fullRebuild) {
    const n = replayStepCount();
    if (!n) return;
    replay.index = Math.max(0, Math.min(n - 1, replay.index));
    const slice = replay.events.slice(0, replay.index + 1);
    const derived = derivePrefix(slice);

    if (fullRebuild) {
      renderCodexPrefix(replay.index);
    } else {
      // Advance by exactly one: append the new line and drop the highlight.
      const ev = replay.events[replay.index];
      appendCodex([ev]);
      const cur = codexLogEl.querySelector(".log-line.replay-current");
      if (cur) cur.classList.remove("replay-current");
    }
    const lastLine = codexLogEl.querySelector(".log-line:last-child");
    if (lastLine) {
      lastLine.classList.add("replay-current");
      lastLine.scrollIntoView({ block: "nearest" });
    }

    renderCounters(derived);
    renderTimeline(slice);
    renderGraph(derived);
    renderSessions(derived);
    applyHeader(derived);

    rpRange.max = String(n);
    rpRange.value = String(replay.index + 1);
    rpStep.textContent = `KROK ${replay.index + 1}/${n}`;
    const trimmed = replay.total > replay.events.length;
    rpNote.textContent = trimmed ? `zachowane ostatnie ${replay.events.length} z ${replay.total}` : "";
    rpCurrent.innerHTML = replayCurrentSummary(replay.events[replay.index]);

    rpFirst.disabled = replay.index <= 0;
    rpPrev.disabled = replay.index <= 0;
    rpNext.disabled = replay.index >= n - 1;
    rpLast.disabled = replay.index >= n - 1;
  }

  function renderCodexPrefix(index) {
    const slice = replay.events.slice(0, index + 1).slice(-MAX_DOM_LINES);
    codexLogEl.innerHTML = slice.map(eventLineHtml).join("");
    if (codexAuto.checked) codexLogEl.scrollTop = codexLogEl.scrollHeight;
  }

  function setReplayPill(on) {
    replayPill.classList.toggle("replay-on", on);
    replayPillText.textContent = on ? "REPLAY" : "REPLAY OFF";
  }

  const rpStepControls = [rpFirst, rpPrev, rpNext, rpLast, rpRange];

  function setReplayControlsEnabled(enabled) {
    for (const el of rpStepControls) el.disabled = !enabled;
  }

  function setPlaying(playing) {
    replay.playing = playing;
    rpPlay.classList.toggle("playing", playing);
    rpPlay.innerHTML = playing ? "&#9646;&#9646;" : "&#9654;";
    if (replay.timer) { clearTimeout(replay.timer); replay.timer = null; }
    if (playing) scheduleNextReplayStep();
  }

  function scheduleNextReplayStep() {
    const n = replayStepCount();
    if (replay.index >= n - 1) {
      // Reached the end of the retained history: pause, but keep the timer
      // slot clear so new live events (which extend replay.events) can resume.
      setPlaying(false);
      rpStep.textContent = `KONIEC HISTORII (${n})`;
      return;
    }
    const delay = REPLAY_BASE_INTERVAL_MS / replay.speed;
    replay.timer = setTimeout(() => {
      if (!replay.playing) return;
      replay.index += 1;
      renderReplayStep(false);
      if (replay.playing) scheduleNextReplayStep();
    }, delay);
  }

  function startReplay() {
    if (replay.active) return;
    fetch("/api/events", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((body) => {
        const events = body.events || [];
        if (!events.length) {
          rpNote.textContent = "brak decyzji do odtworzenia";
          return;
        }
        replay.active = true;
        replay.events = events;
        replay.total = body.total || 0;
        replay.index = 0;
        replay.pendingRaw = [];
        replay.pendingSinceReplay = 0;
        replay.speed = parseFloat(rpSpeed.value) || 1;
        replayBarEl.classList.add("active");
        setReplayPill(true);
        setReplayControlsEnabled(true);
        rawPanelEl.classList.add("frozen");
        rpExitBadge.textContent = "";
        renderReplayStep(true);
        setPlaying(replay.events.length > 1);
      })
      .catch(() => { /* keep the live view; user can retry */ });
  }

  function stopReplay() {
    if (!replay.active) return;
    const bufferedRaw = replay.pendingRaw;
    replay.active = false;
    setPlaying(false);
    replay.events = [];
    replay.total = 0;
    replay.index = -1;
    replay.pendingRaw = [];
    replay.pendingSinceReplay = 0;
    replayBarEl.classList.remove("active");
    setReplayPill(false);
    setReplayControlsEnabled(false);
    rawPanelEl.classList.remove("frozen");
    rpCurrent.innerHTML = "";
    rpStep.textContent = "brak kroków";
    rpNote.textContent = "";
    rpRange.max = "1";
    rpRange.value = "1";
    rpExitBadge.textContent = "";
    const cur = codexLogEl.querySelector(".log-line.replay-current");
    if (cur) cur.classList.remove("replay-current");
    if (bufferedRaw.length) appendRaw(bufferedRaw);
    // Resynchronise everything from the server instead of stitching partial state.
    fetch("/api/state", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(renderFull)
      .catch(() => {});
  }

  function toggleReplay() {
    if (replay.active) stopReplay();
    else startReplay();
  }

  function stepReplay(delta) {
    if (!replay.active) return;
    const n = replayStepCount();
    replay.index = Math.max(0, Math.min(n - 1, replay.index + delta));
    renderReplayStep(delta === 1);
  }

  function jumpReplay(to) {
    if (!replay.active) return;
    const n = replayStepCount();
    replay.index = Math.max(0, Math.min(n - 1, to));
    renderReplayStep(true);
  }

  function updateExitBadge() {
    rpExitBadge.textContent = replay.pendingSinceReplay > 0 ? `+${replay.pendingSinceReplay}` : "";
  }

  rpFirst.addEventListener("click", () => jumpReplay(0));
  rpPrev.addEventListener("click", () => stepReplay(-1));
  rpNext.addEventListener("click", () => stepReplay(1));
  rpLast.addEventListener("click", () => jumpReplay(replayStepCount() - 1));
  rpPlay.addEventListener("click", () => {
    if (!replay.active) startReplay();
    else setPlaying(!replay.playing);
  });
  rpExit.addEventListener("click", stopReplay);
  replayPill.addEventListener("click", toggleReplay);
  rpSpeed.addEventListener("change", () => {
    replay.speed = parseFloat(rpSpeed.value) || 1;
    if (replay.playing) scheduleNextReplayStep();
  });
  rpRange.addEventListener("input", () => jumpReplay(parseInt(rpRange.value, 10) - 1));
  setReplayControlsEnabled(false);

  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, select, textarea, button")) return;
    if (!replay.active) {
      if (e.key === "r" || e.key === "R") { startReplay(); e.preventDefault(); }
      return;
    }
    if (e.key === "r" || e.key === "R") { stopReplay(); e.preventDefault(); }
    if (e.key === "ArrowLeft") { stepReplay(-1); e.preventDefault(); }
    else if (e.key === "ArrowRight") { stepReplay(1); e.preventDefault(); }
    else if (e.key === " ") { setPlaying(!replay.playing); e.preventDefault(); }
    else if (e.key === "Home") { jumpReplay(0); e.preventDefault(); }
    else if (e.key === "End") { jumpReplay(replayStepCount() - 1); e.preventDefault(); }
    else if (e.key === "Escape") { stopReplay(); }
  });

  // ---------------------------------------------------------------- streaming
  function setLive(ok) {
    livePill.classList.toggle("offline", !ok);
    liveText.textContent = ok ? "LIVE" : "OFFLINE";
  }

  function connect() {
    if (typeof EventSource === "undefined") {
      legacyPoll();
      return;
    }
    const source = new EventSource("/api/stream");
    source.addEventListener("full", (e) => { setLive(true); renderFull(JSON.parse(e.data)); });
    source.addEventListener("delta", (e) => { setLive(true); renderDelta(JSON.parse(e.data)); });
    source.onerror = () => setLive(false);
  }

  async function legacyPoll() {
    try {
      const res = await fetch("/api/state", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setLive(true);
      renderFull(await res.json());
    } catch (err) {
      setLive(false);
    }
    setTimeout(legacyPoll, 1000);
  }

  connect();
})();
