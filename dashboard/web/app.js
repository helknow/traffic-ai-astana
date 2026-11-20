"use strict";
/* Astana strategy bench: race board + live map + results. Plain JS, no build step. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const STRAT_VAR = (id) => {
  const k = id.split("_")[0];
  if (k === "independent" || k === "central" || k === "neighbour") return `--s-${k}`;
  return `--s-${id}`;
};
const SLOT_KEYS = ["A", "B", "C", "D"];
const REASON = {
  ai: "the AI chose this phase", ai_keep: "the AI kept this phase", keep: "keeping green: people still coming",
  rest_in_green: "resting in green: nobody waiting elsewhere", min_green: "minimum green (7 s) still running",
  max_red_cap: "90 s cap: someone waited 90 s at a red", backstop_4min: "4-minute backstop: every direction gets a turn",
  sensor_fallback: "camera trouble: fixed-time cycling", empty_green: "green road empty, handed to waiting traffic",
  start: "starting up", fixed: "SUMO fixed-time plan (90 s cycle)", actuated: "SUMO actuated: gap-based extension",
};
const EVENT_ICON = { accident: "i-crash", breakdown: "i-wrench", jaywalker: "i-walk", impaired: "i-swerve",
  ambulance: "i-siren", snowstorm: "i-snow", roadworks: "i-cone" };

/* The hosted copy (Vercel) has no simulator: it plays races recorded by dashboard/export_static.py. */
const STATIC = !!window.BENCH_STATIC;
const API = STATIC ? { options: "data/options.json", network: "data/network.json", results: "data/results.json" }
  : { options: "/api/options", network: "/api/network", results: "/api/results" };

const state = {
  opts: null, geo: null, ws: null, outbox: [], running: false, starting: false, paused: false,
  selected: 0, frame: null, prevVeh: new Map(), curVeh: new Map(), frameAt: 0, frameGap: 250,
  order: [], lastRank: new Map(), litUntil: new Map(), light: null, results: null, speed: 4,
};

/* ---------------- startup ---------------- */
async function init() {
  const [opts, geo] = await Promise.all([fetch(API.options).then(r => r.json()), fetch(API.network).then(r => r.json())]);
  state.opts = opts; state.geo = geo;
  fillSelect($("#season"), opts.seasons.map(s => [s.id, `${s.title} · ${s.months}`]), "winter");
  fillSelect($("#profile"), opts.profiles.map(p => [p.id, p.title]), "evening_rush");
  buildSlots();
  buildEvents();
  map.init(geo);
  wire();
  if (STATIC) replay.init(); else connect();
}

function fillSelect(sel, items, value) {
  sel.innerHTML = items.map(([v, t]) => `<option value="${v}">${esc(t)}</option>`).join("");
  if (value && items.some(([v]) => v === value)) sel.value = value;
}
const esc = (s) => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function defaultControllers() {
  const c = state.opts.controllers;
  const pick = (strategy) => {
    const runs = c.filter(x => x.kind === strategy && x.shield && !x.id.includes("long"));
    return (runs.find(x => x.algo === "ppo") || runs[0] || {}).id;
  };
  const out = [pick("neighbour"), pick("independent"), pick("central"), "fixed"].filter(Boolean);
  for (const b of ["max_pressure", "actuated", "fixed"]) if (out.length < 4 && !out.includes(b)) out.push(b);
  return out.slice(0, 4);
}

function buildSlots() {
  const defs = defaultControllers();
  const groups = [["Today and classic", c => c.kind === "baseline"],
    ["Independent agents", c => c.kind === "independent"], ["Central brain + sub-agents", c => c.kind === "central"],
    ["Neighbour-aware agents", c => c.kind === "neighbour"]];
  const opt = (sel) => `<option value="">Empty slot</option>` + groups.map(([g, f]) => {
    const items = state.opts.controllers.filter(f);
    return items.length ? `<optgroup label="${g}">${items.map(c => `<option value="${c.id}"${c.id === sel ? " selected" : ""}>${esc(c.label.replace(/^[^·]+· /, c.kind === "baseline" ? "" : ""))}</option>`).join("")}</optgroup>` : "";
  }).join("");
  $("#slots").innerHTML = SLOT_KEYS.map((k, i) => `
    <div class="slot"><span class="key">${k}</span>
      <label class="select"><span class="sr">Controller ${k}</span><select data-slot="${i}">${opt(defs[i] || "")}</select><svg class="icon"><use href="#i-chev"/></svg></label>
    </div>`).join("");
  // full labels inside optgroups read better than the trimmed ones
  $$("#slots select").forEach(sel => $$("option", sel).forEach(o => {
    const c = state.opts.controllers.find(x => x.id === o.value);
    if (c) o.textContent = c.label.replace(" with sub-agents", "").replace(" agents", "");
  }));
}

function buildEvents() {
  $("#eventButtons").innerHTML = state.opts.events.map(e =>
    `<button class="btn ghost" data-event="${e.id}" disabled><svg class="icon"><use href="#${EVENT_ICON[e.id]}"/></svg>${esc(e.label)}</button>`).join("");
}

function wire() {
  $$(".tab").forEach(t => t.addEventListener("click", () => setView(t.dataset.view)));
  $("#run").addEventListener("click", start);
  $("#pause").addEventListener("click", () => {
    state.paused = !state.paused;
    send({ cmd: "pause", value: state.paused });
    $("#pause").innerHTML = `<svg class="icon${state.paused ? " fill" : ""}"><use href="#${state.paused ? "i-play" : "i-pause"}"/></svg>`;
    $("#pause").setAttribute("aria-label", state.paused ? "Resume" : "Pause");
  });
  $$("#speed button").forEach(b => b.addEventListener("click", () => {
    $$("#speed button").forEach(x => x.setAttribute("aria-checked", x === b));
    state.speed = +b.dataset.v;
    state.frameGap = Math.max(16, 1000 / state.speed);
    send({ cmd: "speed", value: state.speed });
  }));
  $("#shield").addEventListener("click", () => {
    const on = $("#shield").getAttribute("aria-checked") !== "true";
    $("#shield").setAttribute("aria-checked", on);
    toast(on ? "Shield on for the learned controllers. Press Run to apply." : "Shield off: raw RL decides (only minimum green and clearance stay). Press Run to apply.");
  });
  $("#eventButtons").addEventListener("click", (e) => {
    const b = e.target.closest("[data-event]");
    if (!b || !state.running) return;
    send({ cmd: "event", kind: b.dataset.event });
    toast(`${b.textContent.trim()}: sent to every controller at the same second`);
  });
  $("#board").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-i]");
    if (tr) select(+tr.dataset.i);
  });
  $("#board").addEventListener("keydown", (e) => {
    const tr = e.target.closest("tr[data-i]");
    if (tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); select(+tr.dataset.i); }
  });
  $("#fit").addEventListener("click", () => map.fit());
}

function select(i) {
  state.selected = i;
  state.prevVeh.clear(); state.curVeh.clear();
  send({ cmd: "select", value: i });
  renderBoard();
}

function setView(v) {
  $$(".tab").forEach(t => t.setAttribute("aria-selected", t.dataset.view === v));
  $("#race").hidden = v !== "race";
  $("#raceControls").style.visibility = v === "race" ? "visible" : "hidden";
  $("#results").hidden = v !== "results";
  if (v === "results") results.load();
  else map.resize();
}

/* ---------------- socket ---------------- */
function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`);
  state.ws = ws;
  ws.onopen = () => { state.outbox.splice(0).forEach(m => ws.send(JSON.stringify(m))); };
  ws.onmessage = (ev) => onMessage(JSON.parse(ev.data));
  ws.onclose = () => { state.running = false; setRunning(false); setTimeout(connect, 1500); };
}
function send(m) {
  if (STATIC) { replay.handle(m); return; }
  if (state.ws && state.ws.readyState === 1) state.ws.send(JSON.stringify(m)); else state.outbox.push(m);
}

function start() {
  const controllers = $$("#slots select").map(s => s.value).filter(Boolean);
  if (!controllers.length) { toast("Pick at least one controller"); return; }
  state.starting = true;
  $("#run").disabled = true;
  $("#run span").textContent = "Starting…";
  state.order = []; state.lastRank.clear(); state.litUntil.clear(); state.frame = null;
  state.selected = 0; state.prevVeh.clear(); state.curVeh.clear();
  const season = state.opts.seasons.find(s => s.id === $("#season").value);
  const profile = state.opts.profiles.find(p => p.id === $("#profile").value);
  $("#scenarioLine").innerHTML = `<b>${esc(season.title)}</b>, ${esc(profile.title.toLowerCase())}, warming up the streets…`;
  send({ cmd: "start", controllers, season: season.id, profile: profile.id, seed: 101,
    shield: $("#shield").getAttribute("aria-checked") === "true" });
  send({ cmd: "speed", value: state.speed });
}

function setRunning(on) {
  state.running = on;
  $("#pause").disabled = !on;
  $$("#eventButtons button").forEach(b => b.disabled = !on);
  $("#run").disabled = false;
  $("#run span").textContent = on ? "Restart" : "Run";
}

function onMessage(m) {
  if (m.type === "started") {
    state.starting = false; setRunning(true);
    const season = state.opts.seasons.find(s => s.id === $("#season").value);
    const profile = state.opts.profiles.find(p => p.id === $("#profile").value);
    $("#scenarioLine").innerHTML = `<b>${esc(season.title)}</b>, ${esc(profile.title.toLowerCase())} · ${esc(season.note.split(":")[0])}`;
  } else if (m.type === "error") {
    state.starting = false; setRunning(false);
    toast(`Could not start: ${m.message}`);
    $("#scenarioLine").textContent = "The simulation did not start. Check the server window for details.";
  } else if (m.type === "frame") {
    const now = performance.now();
    if (state.frame) state.frameGap = Math.min(1200, Math.max(16, now - state.frameAt));
    state.frameAt = now;
    state.frame = m;
    ingestVehicles(m);
    $("#clock").textContent = clock(m.t);
    renderBoard();
    renderLog(m.log);
    renderDetail();
    if (m.done) { setRunning(false); $("#run span").textContent = "Run again"; toast(STATIC ? "End of the recording. The Results tab has the full comparison." : "The hour is over. Results tab has the averaged comparison."); }
  }
}

function clock(t) {
  const base = { morning_rush: 7.5, midday: 12.5, evening_rush: 17.5, night: 23 }[$("#profile").value] ?? 8;
  const mins = Math.max(0, Math.round((t - 300) / 60));
  const total = Math.round(base * 60) + mins;
  return `${String(Math.floor(total / 60) % 24).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

function ingestVehicles(m) {
  const run = m.runs[state.selected];
  if (!run || !run.veh) return;
  state.prevVeh = state.curVeh;
  const cur = new Map();
  for (const v of run.veh) cur.set(v[0], v);
  state.curVeh = cur;
}

/* ---------------- board ---------------- */
function renderBoard() {
  const f = state.frame;
  const tbody = $("#board");
  $(".board-wrap").classList.toggle("has-rows", !!f);
  if (!f) { tbody.innerHTML = ""; return; }
  const runs = f.runs.map((r, i) => ({ ...r, i }));
  const ranked = [...runs].sort((a, b) => a.kpi.loss - b.kpi.loss || a.i - b.i);
  const bestLoss = ranked[0].kpi.loss;
  const now = performance.now();
  const rankOf = new Map(ranked.map((r, k) => [r.i, k]));
  // rows that moved stay lit for 4 s
  for (const [i, k] of rankOf) {
    const prev = state.lastRank.get(i);
    if (prev !== undefined && prev !== k) state.litUntil.set(i, { until: now + 4000, dir: k < prev ? "up" : "down", by: Math.abs(prev - k) });
  }
  // FLIP: remember positions, rebuild in the new order, animate from the old place
  const before = new Map($$("tr[data-i]", tbody).map(tr => [+tr.dataset.i, tr.getBoundingClientRect().top]));
  const rows = new Map($$("tr[data-i]", tbody).map(tr => [+tr.dataset.i, tr]));
  ranked.forEach((r, k) => {
    let tr = rows.get(r.i);
    if (!tr) { tr = document.createElement("tr"); tr.dataset.i = r.i; tr.tabIndex = 0; }
    const lit = state.litUntil.get(r.i);
    const isLit = lit && lit.until > now;
    tr.className = isLit ? "lit" : "";
    tr.setAttribute("aria-selected", r.i === state.selected);
    const kind = (state.opts.controllers.find(c => c.id === r.id) || {}).kind || "baseline";
    const parts = r.label.split(" · ");
    const name = kind === "baseline" ? r.label : parts[0].replace(" agents", "").replace(" with sub-agents", "");
    const sub = kind === "baseline" ? (r.id === "fixed" ? "Astana today" : "classic rule") : parts.slice(1).join(" · ");
    const k1 = r.kpi;
    const gap = k > 0 && bestLoss > 0 ? `<span class="lead">+${Math.round(100 * (k1.loss - bestLoss) / bestLoss)}%</span>` : `<span class="lead">${r.done ? "finished" : "leading"}</span>`;
    tr.innerHTML = `
      <td><span class="rank${isLit ? " " + lit.dir : ""}">${k + 1}${isLit ? `<svg class="icon"><use href="#i-${lit.dir}"/></svg>` : ""}</span></td>
      <td><div class="cname"><i class="sdot" style="background:var(${STRAT_VAR(r.id)})"></i><div><b>${esc(name)}</b><small>${esc(SLOT_KEYS[r.i])} · ${esc(sub)}</small></div></div></td>
      <td class="num"><span class="val">${k1.loss.toFixed(0)}<span class="unit">s</span></span>${gap}</td>
      <td class="num"><span class="val dim">${k1.wait.toFixed(0)}<span class="unit">s</span></span></td>
      <td class="num"><span class="val">${k1.queue}</span></td>
      <td class="num"><span class="val dim">${k1.throughput ? k1.throughput.toLocaleString("en-US") : "–"}<span class="unit">/h</span></span></td>
      <td class="num"><span class="val${k1.hidden ? "" : " dim"}">${k1.hidden}</span></td>`;
    tbody.appendChild(tr);
  });
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduce) $$("tr[data-i]", tbody).forEach(tr => {
    const old = before.get(+tr.dataset.i);
    if (old === undefined) return;
    const dy = old - tr.getBoundingClientRect().top;
    if (Math.abs(dy) < 1) return;
    tr.animate([{ transform: `translateY(${dy}px)` }, { transform: "translateY(0)" }], { duration: 520, easing: "cubic-bezier(.16,1,.3,1)" });
  });
  state.lastRank = rankOf;
  const sel = runs[state.selected];
  if (sel) {
    $("#mapTitle span").textContent = sel.label;
    $("#mapDot").style.background = `var(${STRAT_VAR(sel.id)})`;
    $("#snowChip").hidden = !sel.snow;
  }
}

function renderLog(items) {
  const ol = $("#log");
  const run = state.frame.runs[state.selected];
  const auto = (run && run.events) ? run.events.filter(e => !items.some(x => x.kind === e.kind && Math.abs(x.t - state.frame.t) < 3)) : [];
  if (!items.length && !auto.length) return;
  const rows = items.map(x => `<li><span class="t">${clock(x.t)}</span><span class="pill you">${esc(x.label)}</span><span class="where">${x.street ? esc(x.street) + " · " : ""}${STATIC ? "scripted, all four at once" : "thrown in by you"}</span></li>`);
  const live = auto.map(e => `<li><span class="t">now</span><span class="pill">${esc(e.label)}</span><span class="where">${e.left ? `clears in ${Math.ceil(e.left / 60)} min` : "under way"}${e.note ? " · " + esc(e.note) : ""}</span></li>`);
  ol.innerHTML = live.concat(rows).join("");
}

/* ---------------- light detail ---------------- */
function renderDetail() {
  const f = state.frame;
  if (!f || !state.light) return;
  const run = f.runs[state.selected];
  const L = state.geo.lights.find(l => l.id === state.light);
  const d = run && run.lights && run.lights[state.light];
  if (!L || !d) return;
  $("#dName").textContent = L.name;
  $("#dId").textContent = L.id;
  const st = $("#dStatus");
  st.textContent = d.ok ? "" : "camera trouble";
  st.className = "status" + (d.ok ? "" : " bad");
  const r = REASON[d.r] || d.r;
  $("#dReason").innerHTML = d.p === null ? `Run by <b>${esc(r)}</b>. Phases and queues are measured, not controlled.` :
    `Now: <b>${esc(r)}</b>${d.st && d.st !== "green" ? ` · changing (${esc(d.st.replace("_", " "))})` : ""}.`;
  const maxq = Math.max(8, ...d.q.map((q, k) => q + (d.pd[k] || 0)));
  $("#dPhases").innerHTML = L.phases.map((p, k) => `
    <li class="${d.p === k ? "on" : ""}"><span class="pn">${p.kind === "left" ? "left turn" : "phase " + (k + 1)}</span>
      <span class="bars" title="cars queued and people waiting"><i class="q" style="width:${100 * d.q[k] / maxq}%"></i><i class="p" style="width:${100 * (d.pd[k] || 0) / maxq}%"></i></span>
      <span class="nums">${d.q[k]} cars · ${d.pd[k] || 0} ppl · ${d.w[k]}s</span></li>`).join("");
}

/* ---------------- map ---------------- */
const map = {
  cv: null, ctx: null, geo: null, s: 1, ox: 0, oy: 0, dpr: 1, w: 0, h: 0, moved: false, drag: null,
  init(geo) {
    this.geo = geo;
    this.cv = $("#map"); this.ctx = this.cv.getContext("2d");
    new ResizeObserver(() => this.resize()).observe(this.cv);
    this.cv.addEventListener("wheel", (e) => {
      e.preventDefault();
      const k = Math.exp(-e.deltaY * 0.0015);
      const r = this.cv.getBoundingClientRect();
      const mx = e.clientX - r.left, my = e.clientY - r.top;
      this.ox = mx - (mx - this.ox) * k; this.oy = my - (my - this.oy) * k; this.s *= k; this.moved = true;
    }, { passive: false });
    this.cv.addEventListener("pointerdown", (e) => { this.drag = { x: e.clientX, y: e.clientY, ox: this.ox, oy: this.oy, m: 0 }; this.cv.setPointerCapture(e.pointerId); });
    this.cv.addEventListener("pointermove", (e) => {
      if (!this.drag) return;
      const dx = e.clientX - this.drag.x, dy = e.clientY - this.drag.y;
      this.drag.m = Math.max(this.drag.m, Math.abs(dx) + Math.abs(dy));
      this.ox = this.drag.ox + dx; this.oy = this.drag.oy + dy; this.moved = true;
    });
    this.cv.addEventListener("pointerup", (e) => {
      const click = this.drag && this.drag.m < 4;
      this.drag = null;
      if (click) this.pick(e);
    });
    requestAnimationFrame(() => this.loop());
  },
  resize() {
    const r = this.cv.getBoundingClientRect();
    if (!r.width || !r.height) return;
    this.dpr = window.devicePixelRatio || 1;
    this.w = r.width; this.h = r.height;
    this.cv.width = r.width * this.dpr; this.cv.height = r.height * this.dpr;
    if (!this.moved) this.fit();
  },
  fit() {
    const xs = this.geo.lights.map(l => l.x), ys = this.geo.lights.map(l => l.y);
    const pad = 160;
    const x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad, y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
    this.s = Math.min(this.w / (x1 - x0), this.h / (y1 - y0));
    this.ox = (this.w - (x1 - x0) * this.s) / 2 - x0 * this.s;
    this.oy = (this.h - (y1 - y0) * this.s) / 2 + y1 * this.s;
    this.moved = false;
  },
  X(x) { return this.ox + x * this.s; },
  Y(y) { return this.oy - y * this.s; },
  pick(e) {
    const r = this.cv.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    let best = null, bd = 28;
    for (const L of this.geo.lights) {
      const d = Math.hypot(this.X(L.x) - mx, this.Y(L.y) - my);
      if (d < bd) { bd = d; best = L.id; }
    }
    if (best) { state.light = best; renderDetail(); }
  },
  poly(pts) {
    const c = this.ctx;
    c.beginPath();
    pts.forEach(([x, y], i) => i ? c.lineTo(this.X(x), this.Y(y)) : c.moveTo(this.X(x), this.Y(y)));
  },
  loop() {
    requestAnimationFrame(() => this.loop());
    if (!this.w || $("#race").hidden) return;
    const c = this.ctx, s = this.s;
    c.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    c.fillStyle = "#08090a"; c.fillRect(0, 0, this.w, this.h);
    c.lineCap = "butt"; c.lineJoin = "round";
    c.fillStyle = "#131416";
    for (const a of this.geo.areas) { this.poly(a); c.closePath(); c.fill(); }
    for (const kind of ["sidewalk", "road"]) {
      c.strokeStyle = kind === "road" ? "#222428" : "#141517";
      for (const l of this.geo.lanes) {
        if (l.k !== kind) continue;
        c.lineWidth = Math.max(1, l.w * s);
        this.poly(l.s); c.stroke();
      }
    }
    c.fillStyle = "#222428";
    for (const j of this.geo.junctions) { if (j.s.length > 2) { this.poly(j.s); c.closePath(); c.fill(); } }
    // lane dividers when zoomed in
    if (s > 1.4) {
      c.strokeStyle = "rgba(255,255,255,.05)"; c.lineWidth = 1; c.setLineDash([3 * s, 6 * s]);
      for (const l of this.geo.lanes) if (l.k === "road") { this.poly(l.s); c.stroke(); }
      c.setLineDash([]);
    }
    const f = state.frame, run = f && f.runs[state.selected];
    const lights = run && run.lights;
    // crossings, coloured by their walk signal
    for (const L of this.geo.lights) {
      const st = lights && lights[L.id] ? lights[L.id].s : "";
      for (const h of L.heads) {
        if (!h.ped || h.s.length < 2) continue;
        const ch = st[h.i];
        c.strokeStyle = ch === "G" || ch === "g" ? "rgba(39,166,68,.38)" : "rgba(255,255,255,.07)";
        c.lineWidth = Math.max(1.5, 3.2 * s);
        c.setLineDash([Math.max(1, .6 * s), Math.max(1, .6 * s)]);
        this.poly(h.s); c.stroke(); c.setLineDash([]);
      }
    }
    // street names
    c.font = "400 11px 'JetBrains Mono', monospace"; c.fillStyle = "rgba(138,143,152,.55)"; c.textAlign = "center"; c.textBaseline = "middle";
    for (const lb of this.geo.labels) {
      let a = -lb.angle; if (a > Math.PI / 2) a -= Math.PI; if (a < -Math.PI / 2) a += Math.PI;
      c.save(); c.translate(this.X(lb.x), this.Y(lb.y)); c.rotate(a); c.fillText(lb.text, 0, -Math.max(9, 7 * s)); c.restore();
    }
    // vehicles, interpolated between frames
    const t = Math.min(1, (performance.now() - state.frameAt) / state.frameGap);
    const VL = 4.6, VW = 1.9;
    for (const [id, v] of state.curVeh) {
      const p = state.prevVeh.get(id);
      let x = v[1], y = v[2], ang = v[3];
      if (p && Math.hypot(p[1] - x, p[2] - y) < 40) {
        x = p[1] + (x - p[1]) * t; y = p[2] + (y - p[2]) * t;
        let da = ((v[3] - p[3] + 540) % 360) - 180; ang = p[3] + da * t;
      }
      const kind = v[4], halted = v[5];
      const len = kind === "b" ? 12 : kind === "v" ? 6.5 : kind === "a" ? 6.5 : VL;
      c.save(); c.translate(this.X(x), this.Y(y)); c.rotate(ang * Math.PI / 180);
      const w = Math.max(2, VW * s), l = Math.max(3, len * s);
      if (kind === "b") { c.strokeStyle = "#d0d6e0"; c.lineWidth = 1.2; c.strokeRect(-w / 2, 0, w, l); }
      else {
        c.fillStyle = kind === "x" ? "#eb5757" : kind === "s" || kind === "i" ? "#ff9f6b" : kind === "a" ? "#ffffff" :
          kind === "v" ? "#62666d" : halted ? "#ffffff" : "#8a8f98";
        c.fillRect(-w / 2, 0, w, l);
        if (kind === "a" && Math.floor(performance.now() / 250) % 2) { c.strokeStyle = "#02b8cc"; c.lineWidth = 1.5; c.strokeRect(-w / 2 - 1.5, -1.5, w + 3, l + 3); }
      }
      c.restore();
    }
    if (run && run.ppl) {
      c.fillStyle = "#02b8cc";
      const r = Math.max(1.4, 0.7 * s);
      for (const p of run.ppl) { c.beginPath(); c.arc(this.X(p[0]), this.Y(p[1]), r, 0, 6.283); c.fill(); }
    }
    // stop lines
    for (const L of this.geo.lights) {
      const st = lights && lights[L.id] ? lights[L.id].s : "";
      for (const h of L.heads) {
        if (h.ped) continue;
        const ch = st[h.i] || "r";
        c.strokeStyle = ch === "G" || ch === "g" ? "#27a644" : ch === "y" ? "#f2b33d" : "#ff3b2f";
        const n = Math.hypot(h.dx, h.dy) || 1, ux = h.dx / n, uy = h.dy / n;
        const half = 1.6 * Math.max(1, s * 0.9);
        c.lineWidth = Math.max(1.5, 1.2 * s);
        c.beginPath();
        c.moveTo(this.X(h.x) - uy * half, this.Y(h.y) - ux * half);
        c.lineTo(this.X(h.x) + uy * half, this.Y(h.y) + ux * half);
        c.stroke();
      }
    }
    // light labels
    c.font = "500 11px 'JetBrains Mono', monospace"; c.textAlign = "left"; c.textBaseline = "alphabetic";
    for (const L of this.geo.lights) {
      const x = this.X(L.x), y = this.Y(L.y);
      if (state.light === L.id) { c.strokeStyle = "rgba(255,255,255,.4)"; c.lineWidth = 1; c.beginPath(); c.arc(x, y, Math.max(18, 22 * s), 0, 6.283); c.stroke(); }
      const ok = !lights || !lights[L.id] || lights[L.id].ok;
      c.fillStyle = ok ? "rgba(208,214,224,.8)" : "#ffb4b4";
      c.fillText(L.id, x + Math.max(14, 16 * s), y - Math.max(10, 12 * s));
    }
    // events
    if (run && run.events) for (const e of run.events) {
      const x = this.X(e.x), y = this.Y(e.y);
      c.strokeStyle = "#eb5757"; c.lineWidth = 1.5;
      c.beginPath(); c.arc(x, y, 10 + 3 * Math.sin(performance.now() / 300), 0, 6.283); c.stroke();
      c.font = "400 11px Inter, sans-serif";
      const label = e.label + (e.left > 5 ? ` · ${Math.ceil(e.left / 60)} min` : "");
      const tw = c.measureText(label).width;
      c.fillStyle = "rgba(235,87,87,.16)"; roundRect(c, x + 14, y - 22, tw + 14, 18, 9); c.fill();
      c.fillStyle = "#ffb4b4"; c.fillText(label, x + 21, y - 9);
    }
    if (!f) {
      c.fillStyle = "rgba(8,9,10,.55)"; c.fillRect(0, 0, this.w, this.h);
      c.fillStyle = "#8a8f98"; c.font = "400 13px Inter, sans-serif"; c.textAlign = "center";
      c.fillText("12 traffic lights, central Astana · press Run to start the hour", this.w / 2, this.h / 2);
    }
  },
};
function roundRect(c, x, y, w, h, r) { c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); }

/* ---------------- results ---------------- */
const COLS = [
  ["time_loss_s", "Time lost", "s", 0], ["avg_wait_s", "Waiting", "s", 0], ["avg_travel_s", "Travel time", "s", 0],
  ["avg_queue", "Queue", "", 1], ["throughput_vph", "Throughput", "/h", 0], ["arrived", "Arrived", "", 0],
  ["teleports", "Teleports", "", 1], ["backlog_end", "Hidden queue", "", 0], ["max_red_wait_s", "Longest standstill", "s", 0],
  ["ped_loss_s", "Pedestrian loss", "s", 0], ["co2_kg", "CO₂", "kg", 0], ["ambulance_s", "Ambulance crossing", "s", 0],
];
const HIGHER_BETTER = new Set(["throughput_vph", "arrived"]);

const results = {
  sortKey: "time_loss_s", sortDir: 1,
  async load() {
    const box = $("#resultsBody");
    if (!state.results) {
      box.innerHTML = `<p class="empty-results">Loading results…</p>`;
      state.results = await fetch(API.results).then(r => r.json()).catch(() => ({ available: false }));
    }
    this.render();
  },
  render() {
    const R = state.results, box = $("#resultsBody");
    if (!R.available || !R.analysis) {
      box.innerHTML = `<h1>Strategy comparison</h1><p class="empty-results">No evaluation yet. Train the strategies (<code>train_all.sh</code>) and run <code>python evaluate.py</code>; this page then shows every metric for every controller, season by season, with the written verdict.</p>${fixesCard()}`;
      return;
    }
    const A = R.analysis, S = R.summary;
    const ctrls = Object.keys(A.overall);
    box.innerHTML = `
      <div><h1>Which strategy should we build on?</h1>
      <p class="lede">${ctrls.length} controllers, each driven through ${S.seasons.length} seasons × ${S.profiles.length} times of day × ${S.seeds} days of traffic the AI never trained on, with the same accidents, breakdowns, jaywalkers and snowstorms for every controller.</p></div>
      <section class="card"><h2>Verdict</h2><div class="verdict">${A.verdict.map(v => `<p>${esc(v)}</p>`).join("")}</div></section>
      <section class="card"><h2>Every metric, every controller</h2><p class="sub">Averaged over all scenarios. Click a column to sort. The best value per column is underlined; the last column compares time lost with today's fixed timers.</p>
        <div class="rtable-wrap" id="rtable"></div></section>
      <div class="grid2">
        <section class="card"><h2>Time lost by season</h2><p class="sub">Best run of each strategy against the classic controllers. Winter's snow and ice is where control matters most.</p><div id="seasonChart"></div></section>
        <section class="card"><h2>Head to head</h2><p class="sub">Scenarios won on time lost (16 = 4 seasons × 4 times of day), best algorithm of each strategy.</p><div id="h2h"></div></section>
      </div>
      <div class="grid2">
        <section class="card"><h2>What the shield costs</h2><p class="sub">Same strategy and algorithm (PPO), trained and tested with the safety shield on and off.</p><div id="shieldT"></div></section>
        <section class="card"><h2>Learning curves</h2><p class="sub">Average queue during training against simulated hours of traffic, every strategy on the same budget.</p><div id="trainChart"></div></section>
      </div>
      ${fixesCard()}`;
    this.table(A); this.seasonChart(A, S); this.h2h(A); this.shield(A); this.train(A);
  },
  table(A) {
    const ctrls = Object.keys(A.overall);
    const rows = [...ctrls].sort((a, b) => {
      const x = A.overall[a][this.sortKey], y = A.overall[b][this.sortKey];
      if (x === null) return 1; if (y === null) return -1;
      return (x - y) * this.sortDir;
    });
    const best = {};
    for (const [k] of COLS) {
      const vals = ctrls.map(c => A.overall[c][k]).filter(v => v !== null && v !== undefined);
      if (vals.length) best[k] = HIGHER_BETTER.has(k) ? Math.max(...vals) : Math.min(...vals);
    }
    const head = `<tr><th data-k="name">Controller</th>${COLS.map(([k, t]) => `<th data-k="${k}"${k === this.sortKey ? ` aria-sort="${this.sortDir > 0 ? "ascending" : "descending"}"` : ""}>${t}</th>`).join("")}<th>vs fixed</th></tr>`;
    const body = rows.map(c => {
      const o = A.overall[c];
      const vf = A.vs_fixed[c];
      return `<tr><td><div class="cname"><i class="sdot" style="background:var(${STRAT_VAR(c)})"></i>${esc(A.labels[c])}</div></td>${COLS.map(([k, , u, d]) => {
        const v = o[k];
        if (v === null || v === undefined) return `<td class="muted">–</td>`;
        return `<td class="${v === best[k] ? "best" : ""}">${(+v).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d })}${u ? `<span class="unit">${u}</span>` : ""}</td>`;
      }).join("")}<td class="${vf < 0 ? "gain" : "loss"}">${c === "fixed" ? "–" : (vf > 0 ? "+" : "") + vf + "%"}</td></tr>`;
    }).join("");
    $("#rtable").innerHTML = `<table class="rtable">${head}${body}</table>`;
    $$("#rtable th[data-k]").forEach(th => th.addEventListener("click", () => {
      const k = th.dataset.k; if (k === "name") return;
      this.sortDir = this.sortKey === k ? -this.sortDir : (HIGHER_BETTER.has(k) ? -1 : 1);
      this.sortKey = k; this.table(A);
    }));
  },
  seasonChart(A, S) {
    const series = [...Object.values(A.strategies).map(s => s.best), "max_pressure", "actuated", "fixed"].filter(c => A.per_season[S.seasons[0]][c] !== undefined);
    const W = 600, H = 250, L = 38, B = 28, T = 10;
    const max = Math.max(...S.seasons.flatMap(se => series.map(c => A.per_season[se][c]))) * 1.08;
    const gw = (W - L) / S.seasons.length, bw = Math.min(18, (gw - 18) / series.length);
    let out = `<svg class="chart" viewBox="0 0 ${W} ${H + 4}" role="img" aria-label="Time lost per vehicle by season">`;
    for (let k = 0; k <= 4; k++) {
      const v = max * k / 4, y = H - B - (H - B - T) * k / 4;
      out += `<line x1="${L}" x2="${W}" y1="${y}" y2="${y}" stroke="#23252a"/><text class="tick" x="${L - 6}" y="${y + 3}" text-anchor="end">${Math.round(v)}</text>`;
    }
    S.seasons.forEach((se, gi) => {
      const x0 = L + gi * gw + (gw - bw * series.length) / 2;
      series.forEach((c, si) => {
        const v = A.per_season[se][c], h = (H - B - T) * v / max;
        out += `<rect x="${x0 + si * bw + 1}" y="${H - B - h}" width="${bw - 2}" height="${h}" rx="2" fill="var(${STRAT_VAR(c)})"><title>${esc(A.labels[c])}: ${v} s</title></rect>`;
      });
      const title = state.opts.seasons.find(s => s.id === se)?.title || se;
      out += `<text x="${L + gi * gw + gw / 2}" y="${H - 8}" text-anchor="middle">${esc(title)}</text>`;
    });
    out += `</svg><div class="legend-row">${series.map(c => `<span><i class="sdot" style="background:var(${STRAT_VAR(c)})"></i>${esc(A.labels[c])}</span>`).join("")}</div>`;
    $("#seasonChart").innerHTML = out;
  },
  h2h(A) {
    const rows = Object.values(A.head_to_head);
    if (!rows.length) { $("#h2h").innerHTML = `<p class="muted">Needs at least two trained strategies.</p>`; return; }
    const name = (s) => ({ independent: "Independent", central: "Central brain", neighbour: "Neighbour-aware" })[s];
    $("#h2h").innerHTML = `<table class="rtable"><tr><th>Match</th><th>Wins</th><th>Wins</th></tr>${rows.map(r =>
      `<tr><td>${name(r.a)} vs ${name(r.b)}</td><td class="${r.a_wins > r.b_wins ? "best" : ""}">${name(r.a)} ${r.a_wins}</td><td class="${r.b_wins > r.a_wins ? "best" : ""}">${name(r.b)} ${r.b_wins}</td></tr>`).join("")}</table>`;
  },
  shield(A) {
    const s = A.shield;
    if (!Object.keys(s).length) { $("#shieldT").innerHTML = `<p class="muted">Train the <code>--no-shield</code> runs to compare.</p>`; return; }
    const keys = [["time_loss_s", "Time lost", "s"], ["max_red_wait_s", "Longest standstill", "s"], ["ped_loss_s", "Pedestrian loss", "s"], ["teleports", "Teleports", ""]];
    const name = (x) => ({ independent: "Independent", central: "Central brain", neighbour: "Neighbour-aware" })[x];
    $("#shieldT").innerHTML = `<table class="rtable"><tr><th>Strategy</th>${keys.map(([, t]) => `<th>${t} on / off</th>`).join("")}</tr>${Object.entries(s).map(([k, v]) =>
      `<tr><td>${name(k)}</td>${keys.map(([m, , u]) => `<td>${fmt(v.on[m])} / ${fmt(v.off[m])}${u ? `<span class="unit">${u}</span>` : ""}</td>`).join("")}</tr>`).join("")}</table>`;
  },
  train(A) {
    const runs = Object.entries(A.training).filter(([, v]) => v.history && v.history.length);
    if (!runs.length) { $("#trainChart").innerHTML = `<p class="muted">No training history yet.</p>`; return; }
    const W = 520, H = 240, L = 34, B = 26, T = 10;
    const xmax = Math.max(...runs.flatMap(([, v]) => v.history.map(h => h.sim_hours)));
    const ys = runs.flatMap(([, v]) => v.history.map(h => h.avg_queue));
    const ymin = Math.min(...ys) * 0.95, ymax = Math.max(...ys) * 1.05;
    const X = (x) => L + (W - L - 8) * x / xmax, Y = (y) => H - B - (H - B - T) * (y - ymin) / (ymax - ymin);
    let out = `<svg class="chart" viewBox="0 0 ${W} ${H + 4}" role="img" aria-label="Training curves">`;
    for (let k = 0; k <= 3; k++) { const y = ymin + (ymax - ymin) * k / 3; out += `<line x1="${L}" x2="${W}" y1="${Y(y)}" y2="${Y(y)}" stroke="#23252a"/><text class="tick" x="${L - 6}" y="${Y(y) + 3}" text-anchor="end">${Math.round(y)}</text>`; }
    for (let k = 0; k <= 4; k++) { const x = xmax * k / 4; out += `<text class="tick" x="${X(x)}" y="${H - 8}" text-anchor="middle">${Math.round(x)} h</text>`; }
    for (const [id, v] of runs) {
      const dash = id.includes("a2c") ? "4 3" : id.includes("dqn") ? "1 3" : "";
      out += `<polyline fill="none" stroke="var(${STRAT_VAR(id)})" stroke-width="1.6" ${dash ? `stroke-dasharray="${dash}"` : ""} stroke-linejoin="round" points="${v.history.map(h => `${X(h.sim_hours)},${Y(h.avg_queue)}`).join(" ")}"><title>${esc(A.labels[id] || id)}</title></polyline>`;
    }
    out += `</svg><div class="legend-row"><span><i class="sdot" style="background:var(--s-independent)"></i>Independent</span><span><i class="sdot" style="background:var(--s-central)"></i>Central brain</span><span><i class="sdot" style="background:var(--s-neighbour)"></i>Neighbour-aware</span><span>solid PPO · dashed A2C · dotted DQN</span></div>`;
    $("#trainChart").innerHTML = out;
  },
};
const fmt = (v) => v === null || v === undefined ? "–" : (+v).toLocaleString("en-US", { maximumFractionDigits: 0 });

function fixesCard() {
  return `<section class="card"><h2>What we changed in the plan, and why</h2><p class="sub">Problems found while building and testing. Each would have made the comparison wrong or the training fail.</p>
  <ul class="fixes">
    <li><b>“Accumulated” waiting time</b><p>A running total of waiting since the start only ever grows, so the reward drifts with the clock instead of the lights' choices. We use the waiting of the cars standing at the light <em>now</em>, with SUMO's waiting memory raised from 100 s to 1000 s so long waits stay visible.</p></li>
    <li><b>Units out of balance</b><p>Queue counts cars, waiting counts seconds: with β = 0.1 the waiting term still outweighed the queue about 3 to 1 in rush hour. Waiting is now in minutes, and the total is scaled so rewards stay in a range PPO handles.</p></li>
    <li><b>Teleports looked like success</b><p>When SUMO removes a gridlocked car, it stops counting in queue and waiting, so a controller could “win” by causing gridlock. Each teleport is now a penalty, and teleports are reported.</p></li>
    <li><b>Cars that never got in</b><p>A controller that blocks the map's entrances shrinks its own queue while cars pile up outside. That hidden queue is now a reward penalty and a reported metric.</p></li>
    <li><b>Pedestrians were invisible</b><p>The formula only counted vehicles. People waiting at crosswalks are added (δ = 0.5), and the safety shield keeps them from being starved.</p></li>
    <li><b>D overlaps Q</b><p>“Delayed vehicles” is almost the same signal as the queue. Kept at γ = 0.1 as your partner wrote, but it adds little; dropping it is a safe simplification.</p></li>
    <li><b>Throughput = arrived</b><p>Two names for one number over a fixed hour. Both are shown, but they always agree.</p></li>
    <li><b>Fair comparison</b><p>Same traffic, same events and new seeds for every controller, and every strategy gets the same budget of simulated hours. The central brain collects 1 training sample per decision against 12 for the per-light agents, so we also trained it with 4× the budget to see whether it just needs more data.</p></li>
    <li><b>DQN and the central brain</b><p>A central DQN would have to score 4¹² ≈ 16.8 million joint actions. It cannot, so DQN runs for the per-light strategies only; PPO and A2C run for all three.</p></li>
    <li><b>Bugs found in the simulator</b><p>SUMO activated the last-loaded (actuated) plan, so the “fixed timer” was secretly actuated; speeders with a 0.8 s gap crashed and got teleported; parallel training workers raced on the same traffic file; crashed cars counted as “waiting”, which pulled the 90 s rule toward blocked roads; SUMO's ambulance blue-light device crashed the simulator mid-training. All fixed and re-tested before training.</p></li>
    <li><b>Found in the results</b><p>The first evaluation showed cars standing 5–7 minutes at J07 even on green. The OSM import had made Zhangeldin give way to a 45 m slip road 8 m past the light, so the light's exit kept freezing; two such spots now give the main street right of way. Cars stuck behind a broken-down car also counted as waiting for the light, sending the 90 s rule's green to a lane nobody could drive on. Both fixed, then everything was evaluated again.</p></li>
  </ul></section>`;
}

/* ---------------- recorded races (hosted copy) ---------------- */
const replay = {
  files: new Map(), data: null, i: 0, timer: null, speed: 4, paused: false, lights: [], log: [],
  init() {
    const o = state.opts, have = o.replays || [];
    const seasons = [...new Set(have.map(r => r.season))];
    fillSelect($("#season"), o.seasons.filter(s => seasons.includes(s.id)).map(s => [s.id, `${s.title} · ${s.months}`]), "winter");
    const profiles = () => {
      const ids = have.filter(r => r.season === $("#season").value).map(r => r.profile);
      fillSelect($("#profile"), o.profiles.filter(p => ids.includes(p.id)).map(p => [p.id, p.title]), $("#profile").value || "evening_rush");
    };
    profiles();
    $("#season").addEventListener("change", profiles);
    $$("#slots select").forEach((s, i) => { s.value = (o.replay_controllers || [])[i] || ""; s.disabled = true; });
    $("#shield").disabled = true;
    $("#shield").title = "Recorded with the safety shield on. Run the project locally to switch it off.";
    const hints = $$(".block-head .hint");
    if (hints[0]) hints[0].textContent = "recorded: best run of each strategy";
    if (hints[1]) hints[1].textContent = "scripted in the recording";
    $("#scenarioLine").innerHTML = `Recorded races, ${o.replay_minutes} minutes each. Pick a season and a time of day, then press Run.`;
    const empty = $(".log-empty");
    if (empty) empty.textContent = "An accident, a person running across, an ambulance, an impaired driver and a breakdown are thrown in at fixed minutes; the season's own events appear too.";
  },
  async handle(m) {
    if (m.cmd === "start") {
      clearTimeout(this.timer);
      const r = (state.opts.replays || []).find(x => x.season === m.season && x.profile === m.profile);
      if (!r) { onMessage({ type: "error", message: "no recording for this season and time of day" }); return; }
      try {
        if (!this.files.has(r.file)) this.files.set(r.file, await fetch("data/" + r.file).then(x => x.json()));
      } catch (e) { onMessage({ type: "error", message: "could not load the recording" }); return; }
      this.data = this.files.get(r.file);
      this.i = 0; this.paused = false;
      this.lights = this.data.controllers.map(() => ({}));
      this.log = [];
      onMessage({ type: "started", controllers: this.data.controllers.map(c => c.id) });
      this.tick();
    } else if (m.cmd === "speed") {
      this.speed = +m.value || 4;
    } else if (m.cmd === "pause") {
      this.paused = !!m.value;
      clearTimeout(this.timer);
      if (!this.paused) this.tick();
    } else if (m.cmd === "select" && this.data && this.i > 0) {
      onMessage(this.frame(this.i - 1));
    } else if (m.cmd === "event") {
      toast("This hosted copy plays recorded races. Run the project locally to throw your own events.");
    }
  },
  tick() {
    if (this.paused || !this.data || this.i >= this.data.frames.length) return;
    const f = this.data.frames[this.i];
    f.r.forEach((r, k) => { if (r.l) Object.assign(this.lights[k], r.l); });
    if (f.log) this.log = f.log;
    onMessage(this.frame(this.i));
    this.i += 1;
    if (this.i < this.data.frames.length) this.timer = setTimeout(() => this.tick(), 1000 * this.data.dt / this.speed);
  },
  frame(i) {
    const D = this.data, f = D.frames[i], last = i === D.frames.length - 1;
    const runs = f.r.map((r, k) => {
      const kpi = {};
      D.kpi.forEach((name, j) => { kpi[name] = r.k[j]; });
      const c = D.controllers[k];
      const item = { id: c.id, label: c.label, done: !!r.d || last, kpi };
      if (k === state.selected) {
        const veh = [], ppl = [];
        for (let j = 0; j < r.v.length; j += 5) veh.push([r.v[j], r.v[j + 1], r.v[j + 2], r.v[j + 3], D.kinds[r.v[j + 4] >> 1], r.v[j + 4] & 1]);
        for (let j = 0; j < r.p.length; j += 3) ppl.push([r.p[j], r.p[j + 1], r.p[j + 2]]);
        Object.assign(item, { veh, ppl, lights: this.lights[k], events: r.e || [], snow: !!r.s });
      }
      return item;
    });
    return { type: "frame", t: f.t, log: this.log, runs, done: last };
  },
};

/* ---------------- misc ---------------- */
let toastTimer;
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("on");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("on"), 3200);
}

window.__bench = state;
init().catch(err => { console.error(err); toast("Could not load the map: is the server running?"); });
