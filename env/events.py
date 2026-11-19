"""Sudden things that happen on Astana roads.

Scheduled events come from a seeded random schedule, so every controller faces the same accident
at the same place and time. Some events also emerge from the traffic itself: when a speeder or an
impaired driver collides with someone, that becomes an accident blocking the lane.

  accident    one or two cars stop dead in a lane for 5-9 min (others squeeze past if they can)
  breakdown   one car stops for 3-7 min
  jaywalker   someone runs across mid-block: cars on that stretch brake hard and wait a few seconds;
              5% of the time a car can't stop in time -> accident
  impaired    an impaired (drunk/high) driver enters: erratic speed, slow reactions, may run reds
  ambulance   an ambulance with a blue-light device crosses the map; others make way (SUMO bluelight)
  snowstorm   winter: speed on every street drops to 65% for 15-25 min
  roadworks   summer: one lane of an avenue closed for 20-40 min

The rates are per simulated hour, multiplied by the season (seasons.py).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from demand.seasons import Season

BASE_RATE = {"accident": 0.5, "breakdown": 0.6, "jaywalker": 3.0, "impaired": 0.6, "ambulance": 0.8,
             "snowstorm": 0.5, "roadworks": 0.5}
LABEL = {"accident": "Accident", "breakdown": "Breakdown", "jaywalker": "Person ran across",
         "impaired": "Impaired driver", "ambulance": "Ambulance", "snowstorm": "Snowstorm",
         "roadworks": "Road works", "crash": "Crash (speeder / impaired)"}


@dataclass
class Event:
    t: float
    kind: str
    edge: str = ""
    pos: float = 0.5           # share of the edge length
    duration: float = 0.0
    started: bool = False
    done: bool = False
    until: float = 0.0
    vehicles: list = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0
    note: str = ""
    tries: int = 0


class Events:
    def __init__(self, season: Season, profile_peds: float, edges: list[str], avenues: list[str],
                 routes: list[tuple[str, str]], seed: int, duration: float, enabled: bool = True,
                 start: float = 0.0):
        self.season, self.edges, self.avenues, self.routes = season, edges, avenues, routes
        self.rng = random.Random(seed * 104729 + 7)
        self.active: list[Event] = []
        self.log: list[Event] = []
        self.counts: dict[str, int] = {}
        self.slowed: dict[str, float] = {}      # vehicle -> time to release
        self.speed_restore: dict[str, float] = {}
        self.queue: list[Event] = []
        self._n = 0
        if enabled:
            self._schedule(profile_peds, start, start + duration)

    def _schedule(self, ped_factor: float, t0: float, t1: float) -> None:
        s = self.season
        mult = {"accident": s.incident, "breakdown": s.incident, "jaywalker": s.jaywalk * ped_factor,
                "impaired": s.impaired / 0.005, "ambulance": 1.0,
                "snowstorm": 1.0 if s.name == "winter" else 0.0,
                "roadworks": 1.0 if s.name == "summer" else 0.0}
        hours = (t1 - t0) / 3600
        for kind, rate in BASE_RATE.items():
            lam = rate * mult[kind] * hours
            n = self._poisson(lam)
            for _ in range(n):
                self.queue.append(self.make(kind, self.rng.uniform(t0 + 60, t1 - 60)))
        self.queue.sort(key=lambda e: e.t)

    def _poisson(self, lam: float) -> int:
        k, p, L = 0, 1.0, pow(2.718281828, -lam)
        while True:
            p *= self.rng.random()
            if p <= L:
                return k
            k += 1

    def make(self, kind: str, t: float) -> Event:
        r = self.rng
        edge = r.choice(self.avenues if kind in ("roadworks", "jaywalker", "accident") and self.avenues
                        else self.edges)
        dur = {"accident": r.uniform(300, 540), "breakdown": r.uniform(180, 420), "jaywalker": r.uniform(4, 7),
               "snowstorm": r.uniform(900, 1500), "roadworks": r.uniform(1200, 2400)}.get(kind, 0.0)
        return Event(t, kind, edge, r.uniform(0.35, 0.8), dur)

    def trigger(self, kind: str, t: float, edge: str | None = None) -> None:
        """Manual trigger (dashboard button)."""
        e = self.make(kind, t)
        if edge:
            e.edge = edge
        self.queue.insert(0, e)

    # ------------------------------------------------------------------------------------------
    def step(self, conn, t: float) -> None:
        while self.queue and self.queue[0].t <= t:
            ev = self.queue.pop(0)
            if self._start(conn, ev, t):
                self.active.append(ev)
                self.log.append(ev)
                self.counts[ev.kind] = self.counts.get(ev.kind, 0) + 1
            elif ev.tries < 12:                       # nobody on that street yet: try again soon
                ev.tries += 1
                ev.t = t + 5
                self.queue.append(ev)
                self.queue.sort(key=lambda e: e.t)
        for ev in list(self.active):
            if t >= ev.until:
                self._end(conn, ev)
                self.active.remove(ev)
        for v, until in list(self.slowed.items()):
            if t >= until:
                try:
                    conn.vehicle.setSpeed(v, -1)
                except Exception:
                    pass
                del self.slowed[v]
        self._crashes(conn, t)

    def _crashes(self, conn, t: float) -> None:
        for c in conn.simulation.getCollisions():
            types = (c.colliderType, c.victimType)
            if not any(x in ("speeder", "impaired") for x in types):
                continue                                # car-car SUMO artefacts are ignored
            if any(c.collider in e.vehicles or c.victim in e.vehicles for e in self.active):
                continue
            try:
                lane = conn.vehicle.getLaneID(c.collider)
            except Exception:
                continue
            if not lane or lane.startswith(":"):
                lane = conn.vehicle.getLaneID(c.victim) if c.victim else lane
            ev = Event(t, "crash", lane.rsplit("_", 1)[0] if lane else "", duration=self.rng.uniform(300, 540))
            ev.vehicles = [v for v in (c.collider, c.victim) if v]
            self._freeze(conn, ev, t)
            self.active.append(ev)
            self.log.append(ev)
            self.counts["crash"] = self.counts.get("crash", 0) + 1

    def _freeze(self, conn, ev: Event, t: float) -> None:
        for v in ev.vehicles:
            try:
                conn.vehicle.setSpeed(v, 0)
                conn.vehicle.setLaneChangeMode(v, 0)
                conn.vehicle.setColor(v, (235, 87, 87, 255))
            except Exception:
                pass
        ev.started, ev.until = True, t + ev.duration
        if ev.vehicles:
            try:
                ev.x, ev.y = conn.vehicle.getPosition(ev.vehicles[0])
            except Exception:
                pass

    def _pick(self, conn, edge: str, frac: float) -> list[str]:
        best, bd = None, 1e9
        for k in range(conn.edge.getLaneNumber(edge)):
            lane = f"{edge}_{k}"
            if "passenger" not in conn.lane.getAllowed(lane) and conn.lane.getAllowed(lane):
                continue
            L = conn.lane.getLength(lane)
            for v in conn.lane.getLastStepVehicleIDs(lane):
                if v in self.slowed or conn.vehicle.getTypeID(v) == "ambulance":
                    continue
                d = abs(conn.vehicle.getLanePosition(v) - frac * L)
                if d < bd and 15 < conn.vehicle.getLanePosition(v) < L - 15:
                    best, bd = v, d
        return [best] if best else []

    def _start(self, conn, ev: Event, t: float) -> bool:
        k = ev.kind
        if k in ("accident", "breakdown"):
            vs = self._pick(conn, ev.edge, ev.pos)
            if not vs:
                return False
            if k == "accident":
                f = conn.vehicle.getFollower(vs[0], 30)
                if f and f[0]:
                    vs.append(f[0])
            ev.vehicles = vs
            self._freeze(conn, ev, t)
            return True
        if k == "jaywalker":
            lane0 = f"{ev.edge}_0"
            L = conn.lane.getLength(lane0)
            p = ev.pos * L
            hit = []
            for i in range(conn.edge.getLaneNumber(ev.edge)):
                for v in conn.lane.getLastStepVehicleIDs(f"{ev.edge}_{i}"):
                    if p - 60 < conn.vehicle.getLanePosition(v) < p:
                        conn.vehicle.setSpeed(v, 0)
                        self.slowed[v] = t + ev.duration
                        hit.append(v)
            if not hit:
                return False
            ev.x, ev.y = conn.simulation.convert2D(ev.edge, p, 0)
            ev.started, ev.until = True, t + ev.duration
            if self.rng.random() < 0.05:              # a car could not stop in time
                crash = Event(t, "accident", ev.edge, ev.pos, self.rng.uniform(300, 540))
                crash.vehicles = hit[:1]
                self._freeze(conn, crash, t)
                crash.note = "after a jaywalker"
                self.active.append(crash)
                self.log.append(crash)
                self.counts["accident"] = self.counts.get("accident", 0) + 1
            return True
        if k in ("impaired", "ambulance"):
            o, d = self.rng.choice(self.routes)
            route = conn.simulation.findRoute(o, d).edges
            if not route:
                return False
            self._n += 1
            rid, vid = f"ev_r{self._n}_{int(t)}", f"{k}_{self._n}"
            conn.route.add(rid, list(route))
            conn.vehicle.add(vid, rid, typeID=k, departLane="best", departSpeed="max")
            ev.vehicles, ev.started, ev.until = [vid], True, t + 1
            ev.x, ev.y = conn.simulation.convert2D(route[0], 1.0, 0)
            return True
        if k == "snowstorm":
            for e in self.edges:
                self.speed_restore.setdefault(e, conn.lane.getMaxSpeed(f"{e}_0"))
                conn.edge.setMaxSpeed(e, self.speed_restore[e] * 0.65)
            ev.started, ev.until = True, t + ev.duration
            return True
        if k == "roadworks":
            n = conn.edge.getLaneNumber(ev.edge)
            if n < 2:
                return False
            lane = f"{ev.edge}_{n - 1}"
            ev.note = lane
            ev.vehicles = list(conn.lane.getDisallowed(lane))     # restore exactly this afterwards
            conn.lane.setDisallowed(lane, ["passenger", "delivery", "bus", "emergency", "pedestrian"])
            ev.x, ev.y = conn.simulation.convert2D(ev.edge, ev.pos * conn.lane.getLength(lane), n - 1)
            ev.started, ev.until = True, t + ev.duration
            return True
        return False

    def _end(self, conn, ev: Event) -> None:
        ev.done = True
        if ev.kind in ("accident", "breakdown", "crash"):
            for v in ev.vehicles:
                try:
                    conn.vehicle.setSpeed(v, -1)
                    conn.vehicle.setLaneChangeMode(v, 1621)
                except Exception:
                    pass
        elif ev.kind == "snowstorm":
            for e, sp in self.speed_restore.items():
                conn.edge.setMaxSpeed(e, sp)
        elif ev.kind == "roadworks" and ev.note:
            conn.lane.setDisallowed(ev.note, ev.vehicles)

    def frozen(self) -> set[str]:
        return {v for e in self.active if e.kind in ("accident", "breakdown", "crash") for v in e.vehicles}

    def blocked_edges(self) -> set[str]:
        return {e.edge for e in self.active if e.kind in ("accident", "breakdown", "crash", "roadworks")}

    def snapshot(self, t: float) -> list[dict]:
        return [{"kind": e.kind, "label": LABEL.get(e.kind, e.kind), "x": round(e.x, 1), "y": round(e.y, 1),
                 "left": round(max(0.0, e.until - t)), "note": e.note} for e in self.active if e.x or e.y]
