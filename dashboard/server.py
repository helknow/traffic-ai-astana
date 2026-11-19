"""Strategy bench server: up to four controllers race the same Astana hour, streamed to the browser.

    python dashboard/server.py            then open http://localhost:8790

Every run gets identical traffic (same profile, season and seed) and identical sudden events:
an event button picks one street and one random state and applies it to every run at once.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import random
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import traci.constants as tc  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from analysis import label as controller_label  # noqa: E402
from demand.generate import PROFILES  # noqa: E402
from demand.seasons import SEASONS  # noqa: E402
from env.core import AstanaSim  # noqa: E402
from env.events import LABEL as EVENT_LABEL  # noqa: E402
from env.tls import NET_FILE, load  # noqa: E402
from evaluate import BASELINES, Policy, trained_models  # noqa: E402

WEB = Path(__file__).resolve().parent / "web"
RES = ROOT / "results"
MAX_RUNS = 4
app = FastAPI()


# ---------------------------------------------------------------------------------------------
def _shape(s: str) -> list[list[float]]:
    return [[round(float(a), 1) for a in pt.split(",")[:2]] for pt in s.split()]


def network_geometry() -> dict:
    root = ET.parse(NET_FILE).getroot()
    bounds = [float(x) for x in root.find("location").get("convBoundary").split(",")]
    lanes, areas, names = [], [], {}
    for e in root.iter("edge"):
        fn = e.get("function", "")
        if fn == "internal":
            continue
        for ln in e.iter("lane"):
            if fn == "walkingarea":
                areas.append(_shape(ln.get("shape")))
                continue
            allow = ln.get("allow", "")
            kind = "crossing" if fn == "crossing" else "sidewalk" if allow == "pedestrian" else "road"
            lanes.append({"id": ln.get("id"), "k": kind, "w": round(float(ln.get("width", 3.2)), 1),
                          "s": _shape(ln.get("shape"))})
            if kind == "road" and e.get("name"):
                L = float(ln.get("length"))
                if L > names.get(e.get("name"), (0,))[0]:
                    names[e.get("name")] = (L, _shape(ln.get("shape")))
    junctions = [{"s": _shape(j.get("shape")), "tl": j.get("type") == "traffic_light"}
                 for j in root.iter("junction") if j.get("type") != "internal" and j.get("shape")]
    lane_shape = {l["id"]: l["s"] for l in lanes}
    lights = []
    for L in load().values():
        heads = []
        for c in root.iter("connection"):
            if c.get("tl") != L.id:
                continue
            i = int(c.get("linkIndex"))
            if L.link_kind[i] == "ped":
                heads.append({"i": i, "ped": 1, "s": lane_shape.get(c.get("to") + "_0", [])})
            else:
                pts = lane_shape.get(f"{c.get('from')}_{c.get('fromLane')}")
                if pts and len(pts) > 1:
                    (x1, y1), (x2, y2) = pts[-2], pts[-1]
                    heads.append({"i": i, "x": x2, "y": y2, "dx": round(x2 - x1, 2), "dy": round(y2 - y1, 2)})
        lights.append({"id": L.short, "name": L.name, "x": L.x, "y": L.y, "heads": heads,
                       "phases": [{"kind": p.kind, "lanes": len(p.lanes), "walk": len(p.crossings)} for p in L.phases]})
    from map.build_map import STREETS
    labels = []
    for n, (_, pts) in names.items():
        if n in STREETS and len(pts) > 1:
            a, b = pts[0], pts[-1]
            labels.append({"text": STREETS[n], "x": (a[0] + b[0]) / 2, "y": (a[1] + b[1]) / 2,
                           "angle": __import__("math").atan2(b[1] - a[1], b[0] - a[0])})
    return {"bounds": bounds, "lanes": lanes, "areas": areas, "junctions": junctions, "lights": lights,
            "labels": labels}


def options() -> dict:
    models = trained_models()
    ctrls = [{"id": c, "label": controller_label(c), "kind": "baseline"} for c in BASELINES]
    for m in models:
        meta = json.loads((RES / "models" / m / "training.json").read_text())
        ctrls.append({"id": m, "label": controller_label(m), "kind": meta["strategy"], "algo": meta["algo"],
                      "shield": meta["shield"]})
    return {"seasons": [{"id": s.name, "title": s.title, "months": s.months, "note": s.note} for s in SEASONS.values()],
            "profiles": [{"id": p.name, "title": p.title} for p in PROFILES.values()],
            "controllers": ctrls,
            "events": [{"id": k, "label": EVENT_LABEL[k]} for k in
                       ["accident", "breakdown", "jaywalker", "impaired", "ambulance", "snowstorm", "roadworks"]]}


GEO: dict | None = None


@app.get("/api/network")
def api_network():
    global GEO
    if GEO is None:
        GEO = network_geometry()
    return JSONResponse(GEO)


@app.get("/api/options")
def api_options():
    return JSONResponse(options())


@app.get("/api/results")
def api_results():
    s, a = RES / "summary.json", RES / "analysis.json"
    if not s.exists():
        return JSONResponse({"available": False})
    out = {"available": True, "summary": json.loads(s.read_text())}
    if a.exists():
        out["analysis"] = json.loads(a.read_text(encoding="utf-8"))
    return JSONResponse(out)


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")


# ---------------------------------------------------------------------------------------------
class Run:
    def __init__(self, ctrl: str, profile: str, season: str, seed: int, shield: bool, label: str):
        self.id = ctrl
        self.policy = None
        mode = ctrl
        if ctrl not in BASELINES:
            self.policy = Policy(ctrl)
            mode = "rl"            # the page's shield switch applies to every learned controller
        self.sim = AstanaSim(profile, season, seed=seed, duration=3600, mode=mode, shield=shield, events=True,
                             backend="traci", label=label)
        self.obs = None
        self.it = None
        self.loss_done = 0.0      # time loss of vehicles that finished
        self.wait_done = 0.0
        self.n_done = 0
        self.last: dict[str, tuple[float, float]] = {}
        self.done = False

    def start(self):
        self.obs = self.sim.start()
        self.sim.conn.simulation.subscribe([tc.VAR_DEPARTED_VEHICLES_IDS, tc.VAR_DEPARTED_PERSONS_IDS])
        c = self.sim.conn
        for v in c.vehicle.getIDList():
            self._sub(v)
        for p in c.person.getIDList():
            c.person.subscribe(p, [tc.VAR_POSITION, tc.VAR_SPEED])

    def _sub(self, v):
        self.sim.conn.vehicle.subscribe(v, [tc.VAR_POSITION, tc.VAR_ANGLE, tc.VAR_SPEED, tc.VAR_TYPE,
                                            tc.VAR_TIMELOSS, tc.VAR_ACCUMULATED_WAITING_TIME])

    def act(self):
        return self.policy.act(self.sim, self.obs) if self.policy else None

    def advance(self):
        if self.done:
            return
        if self.it is None:
            self.it = self.sim.step_iter(self.act())
        try:
            next(self.it)
        except StopIteration as stop:
            self.obs, _, self.done = stop.value
            self.it = None
        c = self.sim.conn
        new = c.simulation.getSubscriptionResults()
        for v in new.get(tc.VAR_DEPARTED_VEHICLES_IDS, ()):
            self._sub(v)
        for p in new.get(tc.VAR_DEPARTED_PERSONS_IDS, ()):
            c.person.subscribe(p, [tc.VAR_POSITION, tc.VAR_SPEED])

    def close(self):
        self.sim.close()


class Live:
    def __init__(self, ctrls: list[str], profile: str, season: str, seed: int, shield: bool):
        self.profile, self.season, self.seed, self.shield = profile, season, seed, shield
        self.runs = [Run(c, profile, season, seed, shield, f"r{k}_{id(self)}") for k, c in enumerate(ctrls[:MAX_RUNS])]
        self.log: list[dict] = []
        self.rng = random.Random(seed * 31 + 5)

    def start(self):
        for r in self.runs:
            r.start()

    def close(self):
        for r in self.runs:
            r.close()

    @property
    def done(self):
        return all(r.done for r in self.runs)

    def advance(self):
        for r in self.runs:
            r.advance()

    def event(self, kind: str):
        """One street, one random state, applied to every run at the same simulated second."""
        lead = self.runs[0].sim
        template = lead.events.make(kind, lead.t)
        state = self.rng.randrange(1 << 30)
        for r in self.runs:
            ev = dataclasses.replace(template, t=r.sim.t, vehicles=[], started=False, done=False, tries=0)
            r.sim.events.rng.seed(state)
            r.sim.events.queue.insert(0, ev)
        self.log.insert(0, {"t": lead.t, "kind": kind, "label": EVENT_LABEL.get(kind, kind),
                            "street": self._street(lead, template.edge)})

    def _street(self, sim, edge):
        try:
            from map.build_map import STREETS
            return STREETS.get(sim.conn.edge.getStreetName(edge), sim.conn.edge.getStreetName(edge)) if edge else ""
        except Exception:
            return ""

    def frame(self, selected: int) -> dict:
        out = {"t": self.runs[0].sim.t, "runs": [], "log": self.log[:30]}
        for k, r in enumerate(self.runs):
            sim, c = r.sim, r.sim.conn
            subs = c.vehicle.getAllSubscriptionResults()
            gone = set(r.last) - set(subs)
            for v in gone:
                loss, wait = r.last.pop(v)
                r.loss_done += loss
                r.wait_done += wait
                r.n_done += 1
            run_loss = run_wait = 0.0
            veh = []
            frozen = sim.events.frozen()
            for v, s in subs.items():
                r.last[v] = (s[tc.VAR_TIMELOSS], s[tc.VAR_ACCUMULATED_WAITING_TIME])
                run_loss += s[tc.VAR_TIMELOSS]
                run_wait += s[tc.VAR_ACCUMULATED_WAITING_TIME]
                if k == selected:
                    x, y = s[tc.VAR_POSITION]
                    t = s[tc.VAR_TYPE]
                    kind = "x" if v in frozen else {"bus": "b", "van": "v", "speeder": "s", "impaired": "i",
                                                    "ambulance": "a"}.get(t, "c")
                    veh.append([v, round(x, 1), round(y, 1), round(s[tc.VAR_ANGLE]), kind, 1 if s[tc.VAR_SPEED] < 0.5 else 0])
            n = max(1, r.n_done + len(subs))
            elapsed_h = max(1e-6, (sim.t - (sim.end - sim.duration)) / 3600)
            st = sim.stats
            item = {"id": r.id, "label": controller_label(r.id), "done": r.done,
                    "kpi": {"loss": round((r.loss_done + run_loss) / n, 1), "wait": round((r.wait_done + run_wait) / n, 1),
                            "queue": round(sum(m["Q"] for m in sim.local.values())),
                            "throughput": round(st.arrived / elapsed_h) if elapsed_h > 0.02 else 0,
                            "arrived": st.arrived, "hidden": getattr(sim, "_backlog", 0),
                            "teleports": st.teleports, "maxWait": round(st.max_wait),
                            "ambulance": round(sum(st.ambulance_times) / len(st.ambulance_times)) if st.ambulance_times else None}}
            if k == selected:
                ppl = [[round(s[tc.VAR_POSITION][0], 1), round(s[tc.VAR_POSITION][1], 1), 1 if s[tc.VAR_SPEED] < 0.2 else 0]
                       for s in c.person.getAllSubscriptionResults().values()]
                lights = {}
                for L in sim.lights:
                    if sim.mode in ("rl", "max_pressure"):
                        ctl = sim.ctrl[L.short]
                        state, phase, stage, reason = ctl.state(), ctl.current, ctl.stage_name(), ctl.reason
                    else:
                        state = c.trafficlight.getRedYellowGreenState(L.id)
                        phase, stage, reason = None, None, sim.mode
                    lights[L.short] = {"s": state, "p": phase, "st": stage, "r": reason,
                                       "q": [d.queued for d in sim.truth[L.short]],
                                       "pd": [d.peds for d in sim.truth[L.short]],
                                       "w": [round(d.max_wait) for d in sim.truth[L.short]],
                                       "ok": sim.sensors_ok[L.short]}
                item |= {"veh": veh, "ppl": ppl, "lights": lights, "events": sim.events.snapshot(sim.t),
                         "snow": any(e.kind == "snowstorm" for e in sim.events.active)}
            out["runs"].append(item)
        return out


@app.websocket("/ws")
async def ws(socket: WebSocket):
    await socket.accept()
    live: Live | None = None
    speed, paused, selected = 4.0, False, 0
    queue: asyncio.Queue = asyncio.Queue()

    async def reader():
        while True:
            await queue.put(json.loads(await socket.receive_text()))

    task = asyncio.create_task(reader())
    try:
        while True:
            while not queue.empty() or live is None or paused or live.done:
                msg = await queue.get()
                cmd = msg.get("cmd")
                if cmd == "start":
                    if live:
                        live.close()
                        live = None
                    ctrls = [c for c in msg.get("controllers", []) if c][:MAX_RUNS] or ["fixed"]
                    await socket.send_text(json.dumps({"type": "starting"}))
                    try:
                        live = Live(ctrls, msg.get("profile", "evening_rush"), msg.get("season", "winter"),
                                    int(msg.get("seed", 101)), bool(msg.get("shield", True)))
                        await asyncio.to_thread(live.start)
                    except Exception as exc:              # bad model file, SUMO refused to start...
                        await socket.send_text(json.dumps({"type": "error", "message": str(exc)[:300]}))
                        live = None
                        continue
                    selected = min(selected, len(live.runs) - 1)
                    paused = False
                    await socket.send_text(json.dumps({"type": "started", "controllers": ctrls}))
                elif cmd == "speed":
                    speed = float(msg.get("value", 4))
                elif cmd == "pause":
                    paused = bool(msg.get("value", not paused))
                elif cmd == "select":
                    selected = int(msg.get("value", 0))
                    if live:
                        await socket.send_text(json.dumps({"type": "frame", **live.frame(selected)}, separators=(",", ":")))
                elif cmd == "event" and live:
                    live.event(msg.get("kind", "accident"))
                elif cmd == "stop" and live:
                    live.close()
                    live = None
                if queue.empty() and live is not None and not paused and not live.done:
                    break
            loop = asyncio.get_running_loop()
            t0 = loop.time()
            await asyncio.to_thread(live.advance)
            frame = await asyncio.to_thread(live.frame, selected)
            frame["type"] = "frame"
            frame["done"] = live.done
            await socket.send_text(json.dumps(frame, separators=(",", ":")))
            await asyncio.sleep(max(0.0, 1.0 / speed - (loop.time() - t0)))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        task.cancel()
        if live:
            live.close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    port = ap.parse_args().port
    print(f"strategy bench on http://localhost:{port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
