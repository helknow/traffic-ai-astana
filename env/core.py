"""AstanaSim: the 12-light Astana centre in SUMO with cameras, shield, sudden events and metrics.

One step() = 5 simulated seconds. Modes:
  rl            learned controllers decide (any strategy), through the shield
  max_pressure  classic adaptive rule, through the shield
  fixed         SUMO's own 90 s fixed-time plans (the conventional lights in Astana today)
  actuated      SUMO's built-in gap-based actuated control

Reward (partner's formula, with the fixes explained in README "Reward: what we changed"):
  r_t = -( a*Q_t + b*W_t + g*D_t + d*P_t ) / scale  - teleport and blocked-entry penalties
  Q_t queue: halted vehicles on my approaches
  W_t waiting: seconds the vehicles now on my approaches have waited so far, in minutes
      (a level, not a running total, and memory long enough to see long waits)
  D_t delayed: vehicles on my approaches slower than half the speed limit
  P_t pedestrians waiting at my crosswalks
"""
from __future__ import annotations

import os
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from demand.generate import PROFILES, fringe, write_routes  # noqa: E402
from demand.seasons import SEASONS  # noqa: E402

from .controller import Controller  # noqa: E402
from .events import Events  # noqa: E402
from .shield import PhaseDemand, Shield, ShieldConfig  # noqa: E402
from .tls import ADD_FILE, MAX_PHASES, NET_FILE, load  # noqa: E402

DECISION = 5
WARMUP = 300
SEASON_LIST = list(SEASONS)
PER_PHASE = 5
LOCAL_DIM = MAX_PHASES * PER_PHASE + MAX_PHASES + 3 + len(SEASON_LIST) + 1     # 32
NB_SLOTS, PER_NB = 4, 4
NEIGHBOUR_DIM = LOCAL_DIM + NB_SLOTS * PER_NB                                   # 48


@dataclass
class RewardWeights:
    alpha: float = 1.0      # queue
    beta: float = 0.1       # waiting (minutes)
    gamma: float = 0.1      # delayed vehicles
    delta: float = 0.5      # waiting pedestrians (added: the original formula ignored people on foot)
    scale: float = 20.0
    teleport: float = 2.0   # per teleported vehicle, shared by all lights
    backlog: float = 0.01   # per vehicle that cannot even enter the map, shared


def sumo_bin(gui: bool = False) -> str:
    import sumo
    return str(Path(sumo.SUMO_HOME) / "bin" / ("sumo-gui" if gui else "sumo"))


@dataclass
class Camera:
    lanes: set
    ema: float = 0.0
    last_seen: float = 0.0
    fault: str = ""             # "" | dead | blind | flaky
    status: str = "ok"


@dataclass
class Stats:
    queue_samples: list = field(default_factory=list)
    max_wait: float = 0.0
    max_ped_wait: float = 0.0
    teleports: int = 0
    arrived: int = 0
    departed: int = 0
    reasons: dict = field(default_factory=dict)
    ambulance_times: list = field(default_factory=list)


class AstanaSim:
    def __init__(self, profile: str = "midday", season: str = "summer", seed: int = 0, scale: float = 1.0,
                 duration: int = 3600, mode: str = "rl", shield: bool = True, events: bool = True,
                 random_faults: bool = False, backend: str = "libsumo", label: str = "sim",
                 tripinfo: str | None = None, weights: RewardWeights | None = None, gui: bool = False):
        self.profile, self.season = PROFILES[profile], SEASONS[season]
        self.seed, self.scale, self.duration, self.mode = seed, scale, duration, mode
        self.cfg = ShieldConfig(enabled=shield)
        self.shield = Shield(self.cfg)
        self.events_on, self.random_faults = events, random_faults
        self.backend, self.label, self.tripinfo, self.gui = backend, label, tripinfo, gui
        self.w = weights or RewardWeights()
        self.lights = list(load().values())
        self.ids = [L.short for L in self.lights]
        self.rng = random.Random(seed * 7919 + 17)
        self.routes = str(write_routes(profile, season, seed, scale, duration + WARMUP))
        self.conn = None

    # ------------------------------------------------------------------------------------------
    def start(self):
        end = WARMUP + self.duration
        cmd = [sumo_bin(self.gui), "-n", str(NET_FILE), "-r", self.routes, "-a", str(ADD_FILE),
               "--step-length", "1", "--seed", str(self.seed), "--no-step-log", "true", "--no-warnings", "true",
               "--time-to-teleport", "600", "--waiting-time-memory", "1000", "--ignore-route-errors", "true",
               "--collision.action", "warn", "--end", str(end + 1)]
        if self.tripinfo:
            cmd += ["--tripinfo-output", self.tripinfo, "--tripinfo-output.write-unfinished", "true",
                    "--device.emissions.probability", "1"]
        if self.gui:
            cmd += ["--start", "--delay", "20"]
        if self.backend == "libsumo":
            import libsumo
            libsumo.start(cmd)
            self.conn = libsumo
        else:
            import traci
            traci.start(cmd, label=self.label)
            self.conn = traci.getConnection(self.label)
        c = self.conn
        import traci.constants as tc
        self.tc = tc
        self.t = 0.0
        self.stats = Stats()
        self._tele_step, self._backlog = 0, 0
        self.amb_depart: dict[str, float] = {}
        for L in self.lights:      # SUMO activates the LAST loaded program (actuated): force fixed-time
            c.trafficlight.setProgram(L.id, "0")
        for _ in range(WARMUP):                               # everyone starts from the same warm traffic
            c.simulationStep()
        self.t = float(WARMUP)
        self.end = float(end)
        self.ctrl = {L.short: Controller(L, self.cfg, self.t) for L in self.lights}
        self._state_cache: dict[str, str] = {}
        if self.mode == "actuated":
            for L in self.lights:
                c.trafficlight.setProgram(L.id, "actuated")
        elif self.mode in ("rl", "max_pressure"):
            for L in self.lights:
                self._set_state(L)
        # one camera per approach street of each light, plus one crosswalk camera per light
        self.cams: dict[str, Camera] = {}
        self.cam_of_lane: dict[str, str] = {}
        for L in self.lights:
            for ln in L.in_lanes:
                cid = f"{L.short}:{ln.rsplit('_', 1)[0]}"
                self.cams.setdefault(cid, Camera(set())).lanes.add(ln)
                self.cam_of_lane[ln] = cid
            self.cams[f"{L.short}:walk"] = Camera(set(L.crossing_wait))
        if self.random_faults and self.rng.random() < 0.35:
            cid = self.rng.choice(sorted(self.cams))
            t0 = self.t + self.rng.uniform(120, max(121, self.duration - 600))
            self.faults = [(cid, self.rng.choice(["dead", "blind", "flaky"]), t0, t0 + self.rng.uniform(300, 900))]
        else:
            self.faults = []
        # subscriptions: everything we read each decision in one call
        lanes = sorted({ln for L in self.lights for ln in L.in_lanes + L.out_lanes})
        for ln in lanes:
            c.lane.subscribe(ln, [tc.LAST_STEP_VEHICLE_NUMBER, tc.LAST_STEP_VEHICLE_HALTING_NUMBER,
                                  tc.LAST_STEP_VEHICLE_ID_LIST, tc.LAST_STEP_MEAN_SPEED, tc.VAR_MAXSPEED])
        self.lane_max = {ln: c.lane.getMaxSpeed(ln) for ln in lanes}
        src, snk, _ = fringe()
        roads = [e for e in c.edge.getIDList() if not e.startswith(":") and
                 any("passenger" in c.lane.getAllowed(f"{e}_{k}") or not c.lane.getAllowed(f"{e}_{k}")
                     for k in range(c.edge.getLaneNumber(e)))]
        avenues = [e for e in roads if c.edge.getLaneNumber(e) >= 3]
        od = [(o, d) for o, *_ in src for d, *_ in snk if o.lstrip("-").split("#")[0] != d.lstrip("-").split("#")[0]]
        self.events = Events(self.season, self.profile.peds / 1000, roads, avenues, od, self.seed,
                             self.duration, enabled=self.events_on, start=self.t)
        self._sense()
        return self.observations()

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    # ------------------------------------------------------------------------------------------
    def _set_state(self, L):
        st = self.ctrl[L.short].state()
        if self._state_cache.get(L.id) != st:
            self.conn.trafficlight.setRedYellowGreenState(L.id, st)
            self._state_cache[L.id] = st

    def _fault(self, cid: str) -> str:
        for c, kind, t0, t1 in self.faults:
            if c == cid and t0 <= self.t < t1:
                return kind
        return ""

    def _sense(self):
        """Read the truth once, then what the cameras report, for every light."""
        c, tc = self.conn, self.tc
        sub = c.lane.getAllSubscriptionResults()
        self.lane = sub
        self.truth: dict[str, list[PhaseDemand]] = {}
        self.det: dict[str, list[PhaseDemand]] = {}
        self.local: dict[str, dict] = {}
        lane_wait: dict[str, float] = {}
        frozen = self.events.frozen() if hasattr(self, "events") else set()   # known crashes: not "waiting"
        for L in self.lights:
            for ln in L.in_lanes:
                ids = [v for v in sub[ln][tc.LAST_STEP_VEHICLE_ID_LIST] if v not in frozen]
                lane_wait[ln] = c.vehicle.getWaitingTime(ids[-1]) if ids else 0.0
        for cid, cam in self.cams.items():
            cam.fault = self._fault(cid)
        for L in self.lights:
            ped_wait: dict[str, tuple[int, float]] = {}
            for cr, areas in L.crossing_wait.items():
                n, mw = 0, 0.0
                for wa in areas:
                    for p in c.edge.getLastStepPersonIDs(wa):
                        if c.person.getNextEdge(p) == cr and c.person.getSpeed(p) < 0.2:
                            n += 1
                            mw = max(mw, c.person.getWaitingTime(p))
                ped_wait[cr] = (n, mw)
            truth, det = [], []
            walk_cam = self.cams[f"{L.short}:walk"]
            for ph in L.phases:
                d, e = PhaseDemand(), PhaseDemand()
                for ln in ph.lanes:
                    nveh, halt = sub[ln][tc.LAST_STEP_VEHICLE_NUMBER], sub[ln][tc.LAST_STEP_VEHICLE_HALTING_NUMBER]
                    d.vehicles += nveh
                    d.queued += halt
                    d.max_wait = max(d.max_wait, lane_wait[ln])
                    f = self.cams[self.cam_of_lane[ln]].fault
                    if f in ("dead", "blind"):
                        continue
                    keep = 0.4 if f == "flaky" else 1.0
                    e.vehicles += sum(self.rng.random() < keep for _ in range(nveh)) if keep < 1 else nveh
                    e.queued += min(halt, e.vehicles)
                    if self.rng.random() < keep:
                        e.max_wait = max(e.max_wait, lane_wait[ln])
                for cr in ph.crossings:
                    n, mw = ped_wait[cr]
                    d.peds += n
                    d.max_wait = max(d.max_wait, mw)
                    if walk_cam.fault not in ("dead", "blind"):
                        e.peds += n
                        e.max_wait = max(e.max_wait, mw)
                truth.append(d)
                det.append(e)
            self.truth[L.short], self.det[L.short] = truth, det
            # camera health: dead = no heartbeat; silent = nothing for 2 min where traffic is normal
            for cid in [f"{L.short}:{e_}" for e_ in L.in_edges] + [f"{L.short}:walk"]:
                cam = self.cams[cid]
                if cid.endswith(":walk"):
                    seen = sum(ped_wait[cr][0] for cr in L.crossing_wait) if cam.fault not in ("dead", "blind") else 0
                else:
                    seen = 0 if cam.fault in ("dead", "blind") else sum(sub[ln][tc.LAST_STEP_VEHICLE_NUMBER] for ln in cam.lanes)
                if seen:
                    cam.last_seen = self.t
                a = DECISION / 900.0
                cam.ema = (1 - a) * cam.ema + a * seen
                if cam.fault == "dead":
                    cam.status = "dead"
                elif self.t - cam.last_seen > 120 and cam.ema > 1.5:
                    cam.status = "silent"
                else:
                    cam.status = "ok"
            self.local[L.short] = {
                "Q": sum(sub[ln][tc.LAST_STEP_VEHICLE_HALTING_NUMBER] for ln in L.in_lanes),
                "W": sum(c.vehicle.getWaitingTime(v) for ln in L.in_lanes for v in sub[ln][tc.LAST_STEP_VEHICLE_ID_LIST]
                         if sub[ln][tc.LAST_STEP_VEHICLE_HALTING_NUMBER] and v not in frozen) / 60.0,
                "D": sum(sub[ln][tc.LAST_STEP_VEHICLE_NUMBER] for ln in L.in_lanes
                         if sub[ln][tc.LAST_STEP_MEAN_SPEED] < 0.5 * self.lane_max[ln]),
                "P": sum(n for n, _ in ped_wait.values()),
            }
        self.sensors_ok = {L.short: all(self.cams[k].status == "ok" for k in self.cams if k.startswith(L.short + ":"))
                           for L in self.lights}

    # ------------------------------------------------------------------------------------------
    def observations(self) -> dict[str, np.ndarray]:
        out = {}
        blocked = self.events.blocked_edges()
        s_idx = SEASON_LIST.index(self.season.name)
        for L in self.lights:
            v = np.zeros(LOCAL_DIM, np.float32)
            ctl = self.ctrl[L.short]
            for k, d in enumerate(self.det[L.short]):
                v[k * PER_PHASE:(k + 1) * PER_PHASE] = [min(d.queued / 15, 3), min(d.vehicles / 25, 3),
                                                        min(d.max_wait / 120, 3), min(d.peds / 10, 3), 1.0]
            b = MAX_PHASES * PER_PHASE
            v[b + ctl.current] = 1.0
            v[b + MAX_PHASES] = min(ctl.elapsed(self.t) / 60, 4)
            v[b + MAX_PHASES + 1] = 0.0 if ctl.in_green else 1.0
            v[b + MAX_PHASES + 2] = 0.0 if self.sensors_ok[L.short] else 1.0
            v[b + MAX_PHASES + 3 + s_idx] = 1.0
            v[-1] = 1.0 if blocked & set(L.in_edges) else 0.0
            out[L.short] = v
        return out

    def neighbour_obs(self, local: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
        tc = self.tc
        out = {}
        for L in self.lights:
            extra = np.zeros(NB_SLOTS * PER_NB, np.float32)
            for k, nb in enumerate(L.neighbours[:NB_SLOTS]):
                q = self.local[nb]["Q"]
                mw = max((d.max_wait for d in self.det[nb]), default=0.0)
                inflow = sum(self.lane[ln][tc.LAST_STEP_VEHICLE_NUMBER] for ln in L.from_neighbour.get(nb, []))
                extra[k * PER_NB:(k + 1) * PER_NB] = [min(q / 40, 3), min(mw / 120, 3), min(inflow / 20, 3), 1.0]
            out[L.short] = np.concatenate([local[L.short], extra])
        return out

    def rewards(self) -> dict[str, float]:
        w = self.w
        shared = -(w.teleport * self._tele_step + w.backlog * self._backlog) / len(self.lights)
        out = {}
        for L in self.lights:
            m = self.local[L.short]
            r = -(w.alpha * m["Q"] + w.beta * m["W"] + w.gamma * m["D"] + w.delta * m["P"]) / w.scale
            out[L.short] = float(max(-10.0, r + shared))
        return out

    # ------------------------------------------------------------------------------------------
    def _max_pressure(self, L) -> int:
        tc = self.tc
        best, bp = None, -1e9
        for k, (ph, d) in enumerate(zip(L.phases, self.det[L.short])):
            down = sum(self.lane[ln][tc.LAST_STEP_VEHICLE_HALTING_NUMBER] for ln in L.out_lanes
                       if ln in self.lane) / max(1, len(L.phases))
            p = d.queued + 0.5 * d.peds - 0.3 * down
            if p > bp:
                best, bp = k, p
        return best

    def step(self, actions: dict[str, int | None] | None = None):
        """Advance one decision (5 simulated seconds)."""
        it = self.step_iter(actions)
        while True:
            try:
                next(it)
            except StopIteration as stop:
                return stop.value

    def step_iter(self, actions: dict[str, int | None] | None = None):
        """Same as step(), but yields after every simulated second (the dashboard animates them)."""
        c = self.conn
        decisions = {}
        if self.mode in ("rl", "max_pressure"):
            for L in self.lights:
                ctl = self.ctrl[L.short]
                if not ctl.in_green:
                    continue
                choice = actions.get(L.short) if (self.mode == "rl" and actions) else None
                if self.mode == "max_pressure":
                    choice = self._max_pressure(L)
                d = self.shield.decide(ctl.current, ctl.elapsed(self.t), ctl.hold, ctl.since_served(self.t),
                                       self.det[L.short], self.sensors_ok[L.short], choice)
                ctl.apply(d, self.t)
                decisions[L.short] = d
                self.stats.reasons[d.reason] = self.stats.reasons.get(d.reason, 0) + DECISION
                self._set_state(L)
        self._tele_step = 0
        for _ in range(DECISION):
            c.simulationStep()
            self.t += 1
            if self.mode in ("rl", "max_pressure"):
                for L in self.lights:
                    self.ctrl[L.short].tick(self.t)
                    self._set_state(L)
            self.events.step(c, self.t)
            self._tele_step += c.simulation.getStartingTeleportNumber()
            self.stats.arrived += c.simulation.getArrivedNumber()
            self.stats.departed += c.simulation.getDepartedNumber()
            for v in c.simulation.getDepartedIDList():
                if v.startswith("ambulance"):
                    self.amb_depart[v] = self.t
            for v in c.simulation.getArrivedIDList():
                if v in self.amb_depart:
                    self.stats.ambulance_times.append(self.t - self.amb_depart.pop(v))
            yield
        self.stats.teleports += self._tele_step
        self._backlog = len(c.simulation.getPendingVehicles())
        self._sense()
        q = sum(m["Q"] for m in self.local.values())
        self.stats.queue_samples.append(q)
        for L in self.lights:
            for d in self.truth[L.short]:
                self.stats.max_wait = max(self.stats.max_wait, d.max_wait)
        self.last_decisions = decisions
        done = self.t >= self.end
        return self.observations(), self.rewards(), done

    def summary(self) -> dict:
        s = self.stats
        hours = self.duration / 3600
        return {"arrived": s.arrived, "throughput_vph": round(s.arrived / hours, 1),
                "avg_queue": round(float(np.mean(s.queue_samples)) if s.queue_samples else 0.0, 2),
                "max_red_wait_s": round(s.max_wait, 1), "teleports": s.teleports,
                "backlog_end": len(self.conn.simulation.getPendingVehicles()) if self.conn else 0,
                "events": dict(self.events.counts), "reasons": dict(s.reasons),
                "ambulance_s": round(float(np.mean(s.ambulance_times)), 1) if s.ambulance_times else None}
