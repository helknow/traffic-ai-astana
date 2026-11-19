"""Safety shield: hard rules every learned controller passes through (the toggle turns 2-6 off).

Always on (physics and law, never switchable):
  0. Clearance: walk ends -> 5 s pedestrian clearance -> 3 s yellow -> 2 s all-red. Minimum green 7 s.
Shield rules (on by default, "shield off" lets raw RL decide):
  1. Sensor trouble at the junction -> fixed-time cycling until the cameras recover.
  2. 4-minute backstop: every phase gets a short green within 240 s even if cameras see nobody.
  3. 90 s cap: a vehicle or person actually seen waiting 90 s at a red is served next.
  4. Demand-only switching: green only goes where someone is waiting; empty road -> keep green.
  5. Empty green: if the green road is empty and someone waits elsewhere, move the green on.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ShieldConfig:
    enabled: bool = True
    min_green: float = 7.0
    ped_clear: float = 5.0
    yellow: float = 3.0
    all_red: float = 2.0
    max_red_cap: float = 90.0
    backstop: float = 240.0
    backstop_green: float = 12.0
    fallback_green: float = 30.0


@dataclass
class PhaseDemand:
    vehicles: int = 0
    queued: int = 0
    peds: int = 0
    max_wait: float = 0.0

    @property
    def any(self) -> bool:
        return self.vehicles > 0 or self.peds > 0


@dataclass
class Decision:
    next_phase: int | None = None
    hold: float = 0.0
    reason: str = "keep"


class Shield:
    def __init__(self, cfg: ShieldConfig):
        self.cfg = cfg

    def decide(self, cur: int, elapsed: float, hold: float, since_served: list[float],
               demand: list[PhaseDemand], sensors_ok: bool, choice: int | None) -> Decision:
        cfg, n = self.cfg, len(demand)
        if elapsed < max(cfg.min_green, hold):
            return Decision(reason="min_green")
        if choice is not None and not (0 <= choice < n):
            choice = None                                  # padded action slot: keep
        if not cfg.enabled:
            if choice is not None and choice != cur:
                return Decision(choice, reason="ai")
            return Decision(reason="ai_keep")
        if not sensors_ok:
            if elapsed >= cfg.fallback_green:
                return Decision((cur + 1) % n, hold=cfg.fallback_green, reason="sensor_fallback")
            return Decision(reason="sensor_fallback")
        others = [i for i in range(n) if i != cur]
        overdue = [i for i in others if since_served[i] >= cfg.backstop]
        if overdue:
            return Decision(max(overdue, key=lambda i: since_served[i]), hold=cfg.backstop_green,
                            reason="backstop_4min")
        capped = [i for i in others if demand[i].max_wait >= cfg.max_red_cap]
        if capped:
            return Decision(max(capped, key=lambda i: demand[i].max_wait), reason="max_red_cap")
        if choice is not None and choice != cur and demand[choice].any:
            return Decision(choice, reason="ai")
        waiting = [i for i in others if demand[i].any]
        if not demand[cur].any and waiting:
            return Decision(max(waiting, key=lambda i: (demand[i].max_wait, demand[i].vehicles)),
                            reason="empty_green")
        return Decision(reason="keep" if waiting else "rest_in_green")
