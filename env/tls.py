"""Read the 12 traffic lights from the SUMO network.

For each light we take netconvert's own fixed-time plan (conflict-free by construction) and turn
it into a short list of *action phases*: the green phases a controller may choose between.
Pedestrian-clearance, yellow and all-red phases are not actions: they are generated
automatically whenever the controller moves from one action phase to another.
"""
from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NET_FILE = ROOT / "map" / "astana.net.xml"
ADD_FILE = ROOT / "map" / "astana.add.xml"
JUNCTIONS_FILE = ROOT / "map" / "junctions.json"
MAX_PHASES = 4


@dataclass
class Phase:
    state: str                      # SUMO state string while this phase is green
    lanes: list[str]                # incoming vehicle lanes that get green
    crossings: list[str]            # crosswalks that get the walk signal
    kind: str = "main"              # main | left (short protected turn phase)


@dataclass
class Light:
    id: str                         # SUMO traffic-light id
    short: str                      # J01..J12
    name: str                       # "Abay × Respublika"
    x: float
    y: float
    n_links: int
    phases: list[Phase]
    link_kind: list[str]            # per link index: "veh" | "ped"
    in_lanes: list[str]             # every incoming vehicle lane
    out_lanes: list[str]
    crossing_wait: dict[str, list[str]]   # crossing -> walkingareas where people wait
    crossing_len: dict[str, float]
    in_edges: list[str] = field(default_factory=list)
    neighbours: list[str] = field(default_factory=list)   # short ids, up to 4
    from_neighbour: dict[str, list[str]] = field(default_factory=dict)  # short -> lanes arriving from it

    def transition(self, i: int, j: int) -> list[tuple[str, str]]:
        """Stages between action phase i and j: [(stage, state)], each run for its own duration."""
        a, b = self.phases[i].state, self.phases[j].state
        green = lambda s: s in "Gg"
        stages = []
        ped_end = [k for k in range(self.n_links)
                   if self.link_kind[k] == "ped" and green(a[k]) and not green(b[k])]
        if ped_end:
            s = list(a)
            for k in ped_end:
                s[k] = "r"
            stages.append(("ped_clear", "".join(s)))
        cur = list(stages[-1][1] if stages else a)
        veh_end = [k for k in range(self.n_links)
                   if self.link_kind[k] == "veh" and green(a[k]) and not green(b[k])]
        if veh_end:
            y = list(cur)
            for k in veh_end:
                y[k] = "y"
            stages.append(("yellow", "".join(y)))
        r = list(cur)
        for k in range(self.n_links):
            if green(a[k]) and not green(b[k]):
                r[k] = "r"
        stages.append(("all_red", "".join(r)))
        return stages


def _is_green(state: str) -> bool:
    return any(c in "Gg" for c in state) and "y" not in state


@lru_cache(maxsize=2)
def load(net_file: str = str(NET_FILE)) -> dict[str, Light]:
    root = ET.parse(net_file).getroot()
    meta = {j["id"]: j for j in json.loads(JUNCTIONS_FILE.read_text(encoding="utf-8"))}
    edge_of_lane, lane_len, edge_nodes, crossing_len = {}, {}, {}, {}
    for e in root.iter("edge"):
        if e.get("function") == "crossing":
            for ln in e.iter("lane"):
                crossing_len[e.get("id")] = float(ln.get("length"))
        if e.get("from"):
            edge_nodes[e.get("id")] = (e.get("from"), e.get("to"))
        for ln in e.iter("lane"):
            edge_of_lane[ln.get("id")] = e.get("id")
            lane_len[ln.get("id")] = float(ln.get("length"))

    links: dict[str, dict[int, tuple]] = {}
    walk_ends: dict[str, list[str]] = {}
    for c in root.iter("connection"):
        frm, to = c.get("from"), c.get("to")
        # a crosswalk is used both ways but listed one way: watch both of its ends
        if to in crossing_len and frm.startswith(":"):
            walk_ends.setdefault(to, []).append(frm)
        if frm in crossing_len and to.startswith(":"):
            walk_ends.setdefault(frm, []).append(to)
        if c.get("tl"):
            idx = int(c.get("linkIndex"))
            if to in crossing_len:
                links.setdefault(c.get("tl"), {})[idx] = ("ped", to, None)
            else:
                links.setdefault(c.get("tl"), {})[idx] = (
                    "veh", f"{frm}_{c.get('fromLane')}", f"{to}_{c.get('toLane')}")

    lights: dict[str, Light] = {}
    for tl in root.iter("tlLogic"):
        tid = tl.get("id")
        if tid not in meta:
            continue
        lk = links[tid]
        n = max(lk) + 1
        kinds = [lk[k][0] if k in lk else "veh" for k in range(n)]
        raw = [p.get("state") for p in tl.iter("phase")]
        phases: list[Phase] = []
        prev = None
        for st in raw:
            if not _is_green(st):
                prev = None
                continue
            # a pedestrian-clearance phase: same vehicle greens as the phase before, walk turned off
            if prev is not None and all(st[k] == prev[k] for k in range(n) if kinds[k] == "veh"):
                prev = st
                continue
            prev = st
            lanes = sorted({lk[k][1] for k in range(n) if k in lk and kinds[k] == "veh" and st[k] in "Gg"})
            crs = sorted({lk[k][1] for k in range(n) if k in lk and kinds[k] == "ped" and st[k] in "Gg"})
            n_G = sum(1 for k in range(n) if st[k] == "G" and kinds[k] == "veh")
            phases.append(Phase(st, lanes, crs, "left" if not crs and n_G <= 4 else "main"))
        phases = phases[:MAX_PHASES]
        in_lanes = sorted({v[1] for v in lk.values() if v[0] == "veh"})
        out_lanes = sorted({v[2] for v in lk.values() if v[0] == "veh"})
        crossings = sorted({v[1] for v in lk.values() if v[0] == "ped"})
        m = meta[tid]
        lights[tid] = Light(tid, m["short"], m["name"], m["x"], m["y"], n, phases, kinds, in_lanes,
                            out_lanes, {c: sorted(set(walk_ends.get(c, []))) for c in crossings},
                            {c: crossing_len[c] for c in crossings},
                            in_edges=sorted({edge_of_lane[l] for l in in_lanes}))

    # neighbours: a light whose outgoing lanes lead (within one edge) into my incoming lanes
    out_edge_owner = {}
    for L in lights.values():
        for ln in L.out_lanes:
            out_edge_owner.setdefault(edge_of_lane[ln], set()).add(L.short)
    by_short = {L.short: L for L in lights.values()}
    for L in lights.values():
        frm: dict[str, list[str]] = {}
        for ln in L.in_lanes:
            for owner in out_edge_owner.get(edge_of_lane[ln], ()):
                if owner != L.short:
                    frm.setdefault(owner, []).append(ln)
        # fall back to the nearest lights when two signals are joined by more than one edge
        near = sorted((s for s in by_short if s != L.short),
                      key=lambda s: math.dist((L.x, L.y), (by_short[s].x, by_short[s].y)))
        order = list(frm) + [s for s in near if s not in frm and
                             math.dist((L.x, L.y), (by_short[s].x, by_short[s].y)) < 420]
        L.neighbours = order[:4]
        L.from_neighbour = {s: frm.get(s, []) for s in L.neighbours}
    return dict(sorted(lights.items(), key=lambda kv: kv[1].short))


def lane_lengths(net_file: str = str(NET_FILE)) -> dict[str, float]:
    root = ET.parse(net_file).getroot()
    return {ln.get("id"): float(ln.get("length")) for ln in root.iter("lane")}


if __name__ == "__main__":
    for L in load().values():
        print(L.short, L.name, f"links={L.n_links}", "phases:",
              [(p.kind, len(p.lanes), len(p.crossings)) for p in L.phases], "nb:", L.neighbours)
