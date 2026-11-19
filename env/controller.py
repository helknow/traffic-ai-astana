"""Signal stage machine for one light: green -> (ped clearance) -> yellow -> all-red -> next green."""
from __future__ import annotations

from .shield import Decision, ShieldConfig
from .tls import Light


class Controller:
    def __init__(self, light: Light, cfg: ShieldConfig, t: float = 0.0):
        self.L, self.cfg = light, cfg
        self.current = 0
        self.green_start = t
        self.hold = 0.0
        self.stages: list[tuple[str, str, float]] = []    # pending (name, state, until)
        self.next: int | None = None
        self.last_served = [t] * len(light.phases)
        self.reason = "start"
        self.switches = 0

    @property
    def in_green(self) -> bool:
        return not self.stages

    def elapsed(self, t: float) -> float:
        return t - self.green_start if self.in_green else 0.0

    def since_served(self, t: float) -> list[float]:
        return [0.0 if (i == self.current and self.in_green) else t - s for i, s in enumerate(self.last_served)]

    def apply(self, d: Decision, t: float) -> None:
        if not self.in_green:
            return
        self.reason = d.reason
        if d.next_phase is None or d.next_phase == self.current:
            return
        dur = {"ped_clear": self.cfg.ped_clear, "yellow": self.cfg.yellow, "all_red": self.cfg.all_red}
        until = t
        self.stages = []
        for name, st in self.L.transition(self.current, d.next_phase):
            until += dur[name]
            self.stages.append((name, st, until))
        self.next, self.hold = d.next_phase, d.hold

    def tick(self, t: float) -> bool:
        """Advance to time t. Returns True when the SUMO state string changed."""
        if self.in_green:
            self.last_served[self.current] = t
            return False
        changed = False
        while self.stages and t >= self.stages[0][2]:
            self.stages.pop(0)
            changed = True
        if not self.stages:
            self.current, self.next = self.next, None
            self.green_start = t
            self.last_served[self.current] = t
            self.switches += 1
        return changed

    def state(self) -> str:
        return self.stages[0][1] if self.stages else self.L.phases[self.current].state

    def stage_name(self) -> str:
        return self.stages[0][0] if self.stages else "green"
