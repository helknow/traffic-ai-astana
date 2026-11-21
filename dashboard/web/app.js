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
/* Plain names for everything shown on screen. Recorded races and old result files carry older
   labels, so the page always names things from the id itself. */
const NAME = { independent: "Independent AI", central: "Central AI", neighbour: "Neighbour AI",
  fixed: "Fixed timer (today)", actuated: "Sensor timer", max_pressure: "Simple rule" };
const WHAT = { independent: "each light decides alone", central: "one brain runs all 12 lights",
  neighbour: "each light also hears its neighbours", fixed: "same cycle all day, like Astana now",
  actuated: "green lasts longer while cars keep coming", max_pressure: "green goes to the longest queue, no AI" };
const WHAT_SHORT = { independent: "each light alone", central: "one brain for all lights", neighbour: "lights share info",
  fixed: "like Astana today", actuated: "reacts to sensors", max_pressure: "longest queue first" };
const ALGO = { ppo: "PPO", a2c: "A2C", dqn: "DQN" };
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
function nameOf(id) {
  if (NAME[id]) return NAME[id];
  const p = id.split("_");
  let s = `${NAME[p[0]] || p[0]} · ${ALGO[p[1]] || p[1]}`;
  if (p.includes("noshield")) s += " · safety rules off";
  if (p.includes("long")) s += " · 4× practice";
  return s;
}
const kindOf = (id) => id.split("_")[0];
const EVENT_TEXT = { accident: "Accident", breakdown: "Car broke down", jaywalker: "Person runs across",
  impaired: "Drunk or high driver", ambulance: "Ambulance", snowstorm: "Snowstorm", roadworks: "Road works",
  crash: "Crash (speeding or drunk driver)" };
const REASON = {
  ai: "the AI chose it", ai_keep: "the AI kept it green", keep: "cars are still coming, so it stays green",
  rest_in_green: "nobody is waiting on the other roads, so it stays green", min_green: "every green lasts at least 7 seconds",
  max_red_cap: "someone waited 90 seconds at a red, so it is their turn", backstop_4min: "4-minute rule: every direction gets a turn",
  sensor_fallback: "a camera is broken, so the light runs on a fixed timer", empty_green: "this road was empty, so the green went to people waiting",
  start: "starting up", fixed: "a fixed timer: the same 90-second cycle all day", actuated: "a sensor timer: the green lasts longer while cars keep coming",
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
  const groups = [["Without AI", c => c.kind === "baseline"],
    ["Independent AI: each light decides alone", c => c.kind === "independent"],
    ["Central AI: one brain runs all 12 lights", c => c.kind === "central"],
    ["Neighbour AI: lights also hear their neighbours", c => c.kind === "neighbour"]];
  const opt = (sel) => `<option value="">Nobody</option>` + groups.map(([g, f]) => {
    const items = state.opts.controllers.filter(f);
    return items.length ? `<optgroup label="${g}">${items.map(c => `<option value="${c.id}"${c.id === sel ? " selected" : ""}>${esc(c.label.replace(/^[^·]+· /, c.kind === "baseline" ? "" : ""))}</option>`).join("")}</optgroup>` : "";
  }).join("");
  $("#slots").innerHTML = SLOT_KEYS.map((k, i) => `
    <div class="slot"><span class="key">${k}</span>
      <label class="select"><span class="sr">Racer ${k}</span><select data-slot="${i}">${opt(defs[i] || "")}</select><svg class="icon"><use href="#i-chev"/></svg></label>
    </div>`).join("");
  // full labels inside optgroups read better than the trimmed ones
  $$("#slots select").forEach(sel => $$("option", sel).forEach(o => {
    const c = state.opts.controllers.find(x => x.id === o.value);
    if (c) o.textContent = nameOf(c.id);
  }));
}

function buildEvents() {
  $("#eventButtons").innerHTML = state.opts.events.map(e =>
    `<button class="btn ghost" data-event="${e.id}" disabled><svg class="icon"><use href="#${EVENT_ICON[e.id]}"/></svg>${esc(EVENT_TEXT[e.id] || e.label)}</button>`).join("");
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
    toast(on ? "Safety rules on: the AI can never make anyone wait too long. Press Start to apply." : "Safety rules off: the AI decides alone; only the 7-second minimum green and the safe yellow and red change-over stay. Press Start to apply.");
  });
  $("#eventButtons").addEventListener("click", (e) => {
    const b = e.target.closest("[data-event]");
    if (!b || !state.running) return;
    send({ cmd: "event", kind: b.dataset.event });
    toast(`${b.textContent.trim()}: happening to every system at the same moment`);
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
  if (!controllers.length) { toast("Choose at least one system to race"); return; }
  state.starting = true;
  $("#run").disabled = true;
  $("#run span").textContent = "Starting…";
  state.order = []; state.lastRank.clear(); state.litUntil.clear(); state.frame = null;
  state.selected = 0; state.prevVeh.clear(); state.curVeh.clear();
  const season = state.opts.seasons.find(s => s.id === $("#season").value);
  const profile = state.opts.profiles.find(p => p.id === $("#profile").value);
  $("#scenarioLine").innerHTML = `<b>${esc(season.title)}</b>, ${esc(profile.title.toLowerCase())}: filling the streets with cars…`;
  send({ cmd: "start", controllers, season: season.id, profile: profile.id, seed: 101,
    shield: $("#shield").getAttribute("aria-checked") === "true" });
  send({ cmd: "speed", value: state.speed });
}

function setRunning(on) {
  state.running = on;
  $("#pause").disabled = !on;
  $$("#eventButtons button").forEach(b => b.disabled = !on);
  $("#run").disabled = false;
  $("#run span").textContent = on ? "Start again" : "Start";
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
    $("#scenarioLine").textContent = "The race did not start. Check the server window for the reason, then press Start again.";
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
    if (m.done) { setRunning(false); $("#run span").textContent = "Start again"; toast(STATIC ? "End of the recording. The Results tab has the full comparison." : "The hour is over. The Results tab has the full comparison."); }
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
    const label = nameOf(r.id);
    const name = label.split(" · ")[0];
    const sub = [label.split(" · ").slice(1).join(" · "), WHAT_SHORT[kindOf(r.id)]].filter(Boolean).join(" · ");
    const k1 = r.kpi;
    const gap = k > 0 && bestLoss > 0 ? `<span class="lead">${Math.round(100 * (k1.loss - bestLoss) / bestLoss)}% slower</span>` : `<span class="lead">${r.done ? "finished first" : "best so far"}</span>`;
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
    $("#mapTitle span").textContent = nameOf(sel.id);
    $("#mapDot").style.background = `var(${STRAT_VAR(sel.id)})`;
    $("#snowChip").hidden = !sel.snow;
  }
}

function renderLog(items) {
  const ol = $("#log");
  const run = state.frame.runs[state.selected];
  const auto = (run && run.events) ? run.events.filter(e => !items.some(x => x.kind === e.kind && Math.abs(x.t - state.frame.t) < 3)) : [];
  if (!items.length && !auto.length) return;
  const rows = items.map(x => `<li><span class="t">${clock(x.t)}</span><span class="pill you">${esc(EVENT_TEXT[x.kind] || x.label)}</span><span class="where">${x.street ? esc(x.street) + " · " : ""}${STATIC ? "happened to all four at once" : "caused by you"}</span></li>`);
  const live = auto.map(e => `<li><span class="t">now</span><span class="pill">${esc(EVENT_TEXT[e.kind] || e.label)}</span><span class="where">${e.left ? `cleared in ${Math.ceil(e.left / 60)} min` : "still going on"}${e.note ? " · " + esc(e.note) : ""}</span></li>`);
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
  st.textContent = d.ok ? "" : "camera broken";
  st.className = "status" + (d.ok ? "" : " bad");
  const r = REASON[d.r] || d.r;
  const STAGE = { yellow: "yellow", all_red: "all red for a moment, for safety", ped_clear: "letting people finish crossing" };
  $("#dReason").innerHTML = d.p === null ? `This light runs on <b>${esc(r)}</b>. The numbers below are only measured.` :
    `Green right now because <b>${esc(r)}</b>${d.st && d.st !== "green" ? `. Switching: ${esc(STAGE[d.st] || d.st)}` : ""}.`;
  const maxq = Math.max(8, ...d.q.map((q, k) => q + (d.pd[k] || 0)));
  $("#dPhases").innerHTML = L.phases.map((p, k) => `
    <li class="${d.p === k ? "on" : ""}"><span class="pn">${p.kind === "left" ? "left-turn green" : "green " + (k + 1)}</span>
      <span class="bars" title="cars stopped and people waiting for this green"><i class="q" style="width:${100 * d.q[k] / maxq}%"></i><i class="p" style="width:${100 * (d.pd[k] || 0) / maxq}%"></i></span>
      <span class="nums">${plural(d.q[k], "car", "cars")} · ${plural(d.pd[k] || 0, "person", "people")} · longest wait ${d.w[k]} s</span></li>`).join("");
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
      c.fillText("12 traffic lights in central Astana · press Start", this.w / 2, this.h / 2);
    }
  },
};
function roundRect(c, x, y, w, h, r) { c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); }

/* ---------------- results ---------------- */
const COLS = [
  ["time_loss_s", "Delay per car", "s", 0, "Extra time an average car needs compared with empty roads. The main score."],
  ["avg_wait_s", "Standing still", "s", 0, "How long an average car stands completely still."],
  ["avg_travel_s", "Trip time", "s", 0, "How long an average trip through the centre takes."],
  ["avg_queue", "Cars stopped", "", 1, "Cars stopped at the 12 lights, on average."],
  ["throughput_vph", "Cars through", "/h", 0, "Cars that reached their destination per hour. Higher is better."],
  ["arrived", "Trips finished", "", 0, "Trips finished in the hour. The same number as cars through, because each test lasts one hour."],
  ["teleports", "Stuck cars removed", "", 1, "Cars so stuck in a jam that the simulator had to remove them. A sign of gridlock."],
  ["backlog_end", "Can't get in", "", 0, "Cars still waiting at the edge of the map at the end of the hour because the streets were too full."],
  ["max_red_wait_s", "Longest wait", "s", 0, "The longest any single car stood still at a light in the hour (averaged over the tests)."],
  ["ped_loss_s", "Delay per walker", "s", 0, "Extra time an average person on foot loses, mostly waiting to cross."],
  ["co2_kg", "CO₂", "kg", 0, "Exhaust gas from all cars in the hour. Less stopping means less CO₂."],
  ["ambulance_s", "Ambulance trip", "s", 0, "How long an ambulance needs to cross the centre."],
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
      box.innerHTML = `<h1>Which system works best?</h1><p class="empty-results">No test results yet. Train the AIs (<code>train_all.sh</code>), then run <code>python evaluate.py</code>. This page then shows every number for every system, season by season, with a written answer.</p>${fixesCard()}`;
      return;
    }
    const A = R.analysis, S = R.summary;
    const ctrls = Object.keys(A.overall);
    box.innerHTML = `
      <div><h1>Which system works best?</h1>
      <p class="lede">We tested ${ctrls.length} traffic-light systems on ${S.seasons.length * S.profiles.length * S.seeds} hours of traffic each: ${S.seasons.length} seasons × ${S.profiles.length} times of day × ${S.seeds} different days the AI never saw while learning. Every system got the same accidents, breakdowns, people running across and snowstorms.</p></div>
      <section class="card"><h2>The answer</h2><div class="verdict">${A.verdict.map(v => `<p>${esc(v)}</p>`).join("")}</div></section>
      ${readCard()}
      <section class="card"><h2>All the numbers</h2><p class="sub">Averages over all ${S.seasons.length * S.profiles.length * S.seeds} test hours. Hover a column name to see what it means, click it to sort. The best value in each column is underlined. The last column compares the delay with today's fixed timers.</p>
        <div class="rtable-wrap" id="rtable"></div></section>
      <div class="grid2">
        <section class="card"><h2>Delay per car in each season</h2><p class="sub">The best version of each AI next to the systems without AI. Winter snow and ice is where good control matters most.</p><div id="seasonChart"></div></section>
        <section class="card"><h2>Who wins more often</h2><p class="sub">Out of 16 situations (4 seasons × 4 times of day), how often each AI had less delay than the other.</p><div id="h2h"></div></section>
      </div>
      <div class="grid2">
        <section class="card"><h2>What the safety rules cost</h2><p class="sub">The same AI, trained and tested with the safety rules on and off.</p><div id="shieldT"></div></section>
        <section class="card"><h2>How the AIs learned</h2><p class="sub">Cars stopped during practice, against hours of practice traffic. Going down means the AI is getting better. Every AI got the same amount of practice.</p><div id="trainChart"></div></section>
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
    const head = `<tr><th data-k="name">Traffic-light system</th>${COLS.map(([k, t, , , tip]) => `<th data-k="${k}" title="${esc(tip)}"${k === this.sortKey ? ` aria-sort="${this.sortDir > 0 ? "ascending" : "descending"}"` : ""}>${t}</th>`).join("")}<th title="Delay per car compared with today's fixed timers">vs today</th></tr>`;
    const body = rows.map(c => {
      const o = A.overall[c];
      const vf = A.vs_fixed[c];
      return `<tr><td><div class="cname"><i class="sdot" style="background:var(${STRAT_VAR(c)})"></i>${esc(nameOf(c))}</div></td>${COLS.map(([k, , u, d]) => {
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
    let out = `<svg class="chart" viewBox="0 0 ${W} ${H + 4}" role="img" aria-label="Delay per car in each season">`;
    for (let k = 0; k <= 4; k++) {
      const v = max * k / 4, y = H - B - (H - B - T) * k / 4;
      out += `<line x1="${L}" x2="${W}" y1="${y}" y2="${y}" stroke="#23252a"/><text class="tick" x="${L - 6}" y="${y + 3}" text-anchor="end">${Math.round(v)}</text>`;
    }
    S.seasons.forEach((se, gi) => {
      const x0 = L + gi * gw + (gw - bw * series.length) / 2;
      series.forEach((c, si) => {
        const v = A.per_season[se][c], h = (H - B - T) * v / max;
        out += `<rect x="${x0 + si * bw + 1}" y="${H - B - h}" width="${bw - 2}" height="${h}" rx="2" fill="var(${STRAT_VAR(c)})"><title>${esc(nameOf(c))}: ${v} s</title></rect>`;
      });
      const title = state.opts.seasons.find(s => s.id === se)?.title || se;
      out += `<text x="${L + gi * gw + gw / 2}" y="${H - 8}" text-anchor="middle">${esc(title)}</text>`;
    });
    out += `</svg><div class="legend-row">${series.map(c => `<span><i class="sdot" style="background:var(${STRAT_VAR(c)})"></i>${esc(nameOf(c))}</span>`).join("")}</div>`;
    $("#seasonChart").innerHTML = out;
  },
  h2h(A) {
    const rows = Object.values(A.head_to_head);
    if (!rows.length) { $("#h2h").innerHTML = `<p class="muted">Needs at least two trained AIs.</p>`; return; }
    const name = (s) => NAME[s];
    $("#h2h").innerHTML = `<table class="rtable"><tr><th>Match</th><th>Wins</th><th>Wins</th></tr>${rows.map(r =>
      `<tr><td>${name(r.a)} vs ${name(r.b)}</td><td class="${r.a_wins > r.b_wins ? "best" : ""}">${name(r.a)} ${r.a_wins}</td><td class="${r.b_wins > r.a_wins ? "best" : ""}">${name(r.b)} ${r.b_wins}</td></tr>`).join("")}</table>`;
  },
  shield(A) {
    const s = A.shield;
    if (!Object.keys(s).length) { $("#shieldT").innerHTML = `<p class="muted">Train the <code>--no-shield</code> runs to compare.</p>`; return; }
    const keys = [["time_loss_s", "Delay per car", "s"], ["max_red_wait_s", "Longest wait", "s"], ["ped_loss_s", "Delay per walker", "s"], ["teleports", "Stuck cars removed", ""]];
    const name = (x) => NAME[x];
    $("#shieldT").innerHTML = `<table class="rtable"><tr><th>AI</th>${keys.map(([, t]) => `<th>${t}<br><span class="muted">on / off</span></th>`).join("")}</tr>${Object.entries(s).map(([k, v]) =>
      `<tr><td>${name(k)}</td>${keys.map(([m, , u]) => `<td>${fmt(v.on[m])} / ${fmt(v.off[m])}${u ? `<span class="unit">${u}</span>` : ""}</td>`).join("")}</tr>`).join("")}</table>`;
  },
  train(A) {
    const runs = Object.entries(A.training).filter(([, v]) => v.history && v.history.length);
    if (!runs.length) { $("#trainChart").innerHTML = `<p class="muted">No practice history yet.</p>`; return; }
    const W = 520, H = 240, L = 34, B = 26, T = 10;
    const xmax = Math.max(...runs.flatMap(([, v]) => v.history.map(h => h.sim_hours)));
    const ys = runs.flatMap(([, v]) => v.history.map(h => h.avg_queue));
    const ymin = Math.min(...ys) * 0.95, ymax = Math.max(...ys) * 1.05;
    const X = (x) => L + (W - L - 8) * x / xmax, Y = (y) => H - B - (H - B - T) * (y - ymin) / (ymax - ymin);
    let out = `<svg class="chart" viewBox="0 0 ${W} ${H + 4}" role="img" aria-label="How the AIs learned">`;
    for (let k = 0; k <= 3; k++) { const y = ymin + (ymax - ymin) * k / 3; out += `<line x1="${L}" x2="${W}" y1="${Y(y)}" y2="${Y(y)}" stroke="#23252a"/><text class="tick" x="${L - 6}" y="${Y(y) + 3}" text-anchor="end">${Math.round(y)}</text>`; }
    for (let k = 0; k <= 4; k++) { const x = xmax * k / 4; out += `<text class="tick" x="${X(x)}" y="${H - 8}" text-anchor="middle">${Math.round(x)} h</text>`; }
    for (const [id, v] of runs) {
      const dash = id.includes("a2c") ? "4 3" : id.includes("dqn") ? "1 3" : "";
      out += `<polyline fill="none" stroke="var(${STRAT_VAR(id)})" stroke-width="1.6" ${dash ? `stroke-dasharray="${dash}"` : ""} stroke-linejoin="round" points="${v.history.map(h => `${X(h.sim_hours)},${Y(h.avg_queue)}`).join(" ")}"><title>${esc(nameOf(id))}</title></polyline>`;
    }
    out += `</svg><div class="legend-row"><span><i class="sdot" style="background:var(--s-independent)"></i>Independent AI</span><span><i class="sdot" style="background:var(--s-central)"></i>Central AI</span><span><i class="sdot" style="background:var(--s-neighbour)"></i>Neighbour AI</span><span>line style = learning method: solid PPO, dashed A2C, dotted DQN</span></div>`;
    $("#trainChart").innerHTML = out;
  },
};
const fmt = (v) => v === null || v === undefined ? "–" : (+v).toLocaleString("en-US", { maximumFractionDigits: 0 });

function readCard() {
  return `<section class="card"><h2>How to read this</h2><p class="sub">Three kinds of AI were tested against three systems without AI.</p>
  <ul class="fixes">
    <li><b>Independent AI</b><p>Every traffic light has its own small AI that only sees the cars and people at its own crossing. Idea 1 from the plan.</p></li>
    <li><b>Central AI</b><p>A helper at every light reports what it sees to one big AI, which then sets all 12 lights at once. Idea 2 from the plan.</p></li>
    <li><b>Neighbour AI</b><p>Like the independent AI, but each light also hears a short summary from the lights next to it. We added it to check whether lights should talk to each other.</p></li>
    <li><b>Without AI</b><p><em>Fixed timer</em>: the same cycle all day, like most Astana lights now. <em>Sensor timer</em>: the green lasts longer while cars keep coming. <em>Simple rule</em> (max-pressure): the green always goes to the longest queue.</p></li>
    <li><b>PPO, A2C, DQN</b><p>Three different learning methods. Each AI was trained with each method on the same amount of practice, so we can see which method learns best.</p></li>
    <li><b>Safety rules</b><p>Hard rules the AI cannot break: nobody waits much more than 90 seconds, every road gets a turn at least every 4 minutes, and if a camera breaks the light falls back to a fixed timer.</p></li>
    <li><b>Delay per car</b><p>The main score: how much extra time an average car needs compared with driving on empty roads. Lower is better.</p></li>
  </ul></section>`;
}

function fixesCard() {
  return `<section class="card"><h2>What we changed in the plan, and why</h2><p class="sub">Problems we found while building and testing. Each one would have made the comparison wrong or stopped the training.</p>
  <ul class="fixes">
    <li><b>Waiting time kept growing</b><p>The plan counted all waiting since the start of the hour, so the score got worse with the clock even when the lights did well. Now it counts the waiting of the cars standing at the light right now.</p></li>
    <li><b>Seconds outweighed cars</b><p>Waiting was measured in seconds and the queue in cars, so waiting counted about three times more than it should. Waiting is now in minutes, and the whole score is scaled down so the AI can learn from it.</p></li>
    <li><b>Gridlock looked like success</b><p>When cars get totally stuck, the simulator removes them, and the queue suddenly looks shorter. Now every removed car costs points and is reported.</p></li>
    <li><b>Cars that never got in</b><p>An AI could keep its own queue short by not letting new cars into the centre. Cars waiting at the edge of the map now cost points too.</p></li>
    <li><b>People on foot were missing</b><p>The plan only counted cars. People waiting to cross now count as well, and the safety rules make sure they always get a turn.</p></li>
    <li><b>Two numbers that say the same thing</b><p>"Delayed cars" is almost the same as the queue, and "throughput" is the same number as "arrived cars" in a one-hour test. We kept them, as in the plan, but they add little.</p></li>
    <li><b>A fair race</b><p>Every system got the same traffic and the same accidents, and every AI got the same amount of practice. The central AI gets 12 times fewer examples per decision, so we also gave it 4 times more practice to check whether that was the only problem. It was not.</p></li>
    <li><b>One learning method can't run the central AI</b><p>DQN would have to compare about 16.8 million combinations of the 12 lights every 5 seconds. So DQN was tested only on the independent and neighbour AIs.</p></li>
    <li><b>Bugs in the simulator</b><p>The "fixed timer" was secretly a sensor timer; speeding cars crashed into each other because their safety gap was too small; training workers overwrote each other's files; crashed cars counted as waiting; the ambulance siren feature crashed the simulator. All fixed and tested before training.</p></li>
    <li><b>Found in the results</b><p>Cars stood 5–7 minutes at Zhangeldin × Beibitshilik even on green: the map data made the main street give way to a small side road just after the light. Cars stuck behind a broken-down car also counted as waiting for a green. Both fixed, then everything was tested again.</p></li>
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
    $("#shield").title = "These races were recorded with the safety rules on. To switch them off, run the project on your own computer.";
    const hints = $$(".block-head .hint");
    if (hints[0]) hints[0].textContent = "recorded: the best version of each AI";
    if (hints[1]) hints[1].textContent = "already planned in the recording";
    $("#scenarioLine").innerHTML = `These are recorded races, ${o.replay_minutes} minutes each. Choose a season and a time of day, then press Start.`;
    const empty = $(".log-empty");
    if (empty) empty.textContent = "An accident, a person running across, an ambulance, a drunk driver and a broken-down car happen at set minutes, plus the season's own surprises.";
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
      toast("This online copy plays recorded races. To cause your own problems, run the project on your own computer.");
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
