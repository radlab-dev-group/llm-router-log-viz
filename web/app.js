(() => {
  const KNOWN_MODES = ["plan", "implement", "review", "debug", "test", "git_review", "aux_title", "compaction"];
  const NODE_POS = {
    plan:        { x: 110, y: 80 },
    implement:   { x: 330, y: 80 },
    review:      { x: 550, y: 80 },
    debug:       { x: 770, y: 80 },
    aux_title:   { x: 110, y: 250 },
    test:        { x: 330, y: 250 },
    compaction:  { x: 550, y: 250 },
    git_review:  { x: 770, y: 250 },
  };
  const NODE_W = 150;
  const NODE_H = 56;
  const EXTRA_ROW_Y = 400;
  const EXTRA_PER_ROW = 4;
  // Keep in sync with the viewBox shipped in index.html: when the computed
  // height matches it, the SVG attribute is never touched and nothing moves.
  const GRAPH_BASE_HEIGHT = 360;
  const GRAPH_PADDING = 24;
  const GRAPH_KNOWN_BOTTOM = 250;
  const MAX_DOM_LINES = 500;
  const MAX_CLIENT_EVENTS = 500;

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
      const x = a.x, y = a.y - NODE_H / 2;
      return `M ${x - 18} ${y} C ${x - 55} ${y - 55}, ${x + 55} ${y - 55}, ${x + 18} ${y}`;
    }
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const mx = (a.x + b.x) / 2;
    const my = (a.y + b.y) / 2;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const nx = -dy / len;
    const ny = dx / len;
    const bend = Math.min(60, Math.max(20, len * 0.12));
    const cx = mx + nx * bend;
    const cy = my + ny * bend;

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
    if (from === to) return { x: a.x, y: a.y - NODE_H / 2 - 38 };
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const mx = (a.x + b.x) / 2;
    const my = (a.y + b.y) / 2;
    const len = Math.sqrt(dx * dx + dy * dy) || 1;
    const nx = -dy / len;
    const ny = dx / len;
    const bend = Math.min(60, Math.max(20, len * 0.12));
    return { x: mx + nx * (bend * 0.65), y: my + ny * (bend * 0.65) - 2 };
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

  function renderTimeline() {
    const rows = clientEvents.slice(-30).reverse();
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
      const x = pos.x - NODE_W / 2;
      const y = pos.y - NODE_H / 2;
      svg += `
        <g class="graph-node ${active ? "active" : ""}">
          <rect x="${x}" y="${y}" rx="8" ry="8" width="${NODE_W}" height="${NODE_H}"></rect>
          <text x="${pos.x}" y="${pos.y - 4}" text-anchor="middle">${esc(n.id)}</text>
          <text class="count" x="${pos.x}" y="${pos.y + 16}" text-anchor="middle">${n.count || 0} events</text>
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
