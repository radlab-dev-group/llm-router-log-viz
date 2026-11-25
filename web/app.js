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
  const rawAuto = document.getElementById("raw-autoscroll");
  const codexAuto = document.getElementById("codex-autoscroll");

  let lastRawCount = -1;
  let lastEventCount = -1;

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

  function formatEventLine(ev) {
    const ts = ev.ts ? `<span class="ts">${esc(ev.ts)}</span> ` : "";
    const mode = `<span class="badge ${modeClass(ev.mode)}">${esc(ev.mode)}</span>`;
    const rest = [
      `<span class="kv"><span class="k">source</span>=<span class="v src">${esc(ev.source)}</span></span>`,
      `<span class="kv"><span class="k">class</span>=<span class="v cls">${esc(ev.class || ev.request_class || "-")}</span></span>`,
      `<span class="kv"><span class="k">model</span>=<span class="v model">${esc(ev.model)}</span></span>`,
      `<span class="kv"><span class="k">sim</span>=<span class="v">${ev.similarity == null ? "-" : Number(ev.similarity).toFixed(3)}</span></span>`,
    ].join(" ");
    return `<div class="log-line codex">${ts}${mode} ${rest}</div>`;
  }

  function renderRaw(rawLines) {
    if (rawLines.length === lastRawCount) return;
    lastRawCount = rawLines.length;
    rawLogEl.innerHTML = rawLines.map(line => {
      const isCodex = line.includes("Codex routing:");
      const cls = isCodex ? "log-line codex" : "log-line";
      return `<div class="${cls}">${esc(line)}</div>`;
    }).join("");
    if (rawAuto.checked) rawLogEl.scrollTop = rawLogEl.scrollHeight;
  }

  function renderCodex(events) {
    if (events.length === lastEventCount) return;
    lastEventCount = events.length;
    codexLogEl.innerHTML = events.map(formatEventLine).join("");
    if (codexAuto.checked) codexLogEl.scrollTop = codexLogEl.scrollHeight;
  }

  function renderCounters(state) {
    const counts = (state.counts && state.counts.mode) || {};
    const order = [...KNOWN_MODES, ...Object.keys(counts).filter(k => !KNOWN_MODES.includes(k))];
    countersEl.innerHTML = order.map(mode => {
      const n = counts[mode] || 0;
      return `<div class="counter"><strong>${esc(mode)}</strong><span class="n">${n}</span></div>`;
    }).join("") + `<div class="counter"><strong>total</strong><span class="n">${state.total_events || 0}</span></div>`;
  }

  function renderTimeline(state) {
    const rows = (state.timeline || []).slice(0, 30);
    timelineBodyEl.innerHTML = rows.map(ev => `
      <tr>
        <td>${esc(ev.ts || "—")}</td>
        <td><span class="badge ${modeClass(ev.mode)}">${esc(ev.mode)}</span></td>
        <td>${esc(ev.source || "-")}</td>
        <td>${esc(ev.class || ev.request_class || "-")}</td>
        <td class="model-cell" title="${esc(ev.model || "-")}">${esc(ev.model || "-")}</td>
      </tr>
    `).join("");
  }

  function nodeCenter(mode) {
    const p = NODE_POS[mode];
    if (!p) return { x: 460, y: 170 };
    return { x: p.x, y: p.y };
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

    // shorten endpoints to rectangle edge-ish
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

  function renderGraph(state) {
    const nodes = state.nodes || [];
    const edges = state.edges || [];
    const last = state.last_event;
    const lastMode = last ? last.mode : null;
    const prevMode = state.events && state.events.length >= 2 ? state.events[state.events.length - 2].mode : null;

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
      const path = edgePath(e.from, e.to);
      const lp = edgeLabelPos(e.from, e.to);
      svg += `<path class="graph-edge ${active ? "active" : ""}" d="${path}" marker-end="url(#${active ? "arrow-active" : "arrow"})"></path>`;
      svg += `<text class="edge-label ${active ? "active" : ""}" x="${lp.x}" y="${lp.y}" text-anchor="middle">${e.count}</text>`;
    }

    for (const n of nodes) {
      const pos = NODE_POS[n.id] || { x: 460, y: 170 };
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

  function render(state) {
    logPathEl.textContent = state.log_path || "—";
    eventCountEl.textContent = String(state.total_events || 0);
    lastModeEl.textContent = state.last_event ? state.last_event.mode : "—";

    renderRaw(state.raw_lines || []);
    renderCodex(state.events || []);
    renderCounters(state);
    renderTimeline(state);
    renderGraph(state);
  }

  async function poll() {
    try {
      const res = await fetch("/api/state", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const state = await res.json();
      livePill.classList.remove("offline");
      liveText.textContent = "LIVE";
      render(state);
    } catch (e) {
      livePill.classList.add("offline");
      liveText.textContent = "OFFLINE";
    }
  }

  poll();
  setInterval(poll, 1000);
})();
