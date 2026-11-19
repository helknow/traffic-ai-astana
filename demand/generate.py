"""Traffic for the Astana centre: cars, vans, buses, speeders, impaired drivers and pedestrians.

Vehicles enter and leave at the map's edge roads (avenues weigh more than side streets) and SUMO
routes them. Season (see seasons.py) changes how people drive, how many walk, and the share of
speeders and impaired drivers. Same (profile, season, seed) -> identical file, so every controller
is tested on exactly the same traffic.
"""
from __future__ import annotations

import json
import os
import random
import zlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .seasons import SEASONS, Season

ROOT = Path(__file__).resolve().parent.parent
NET = ROOT / "map" / "astana.net.xml"
OUT = ROOT / "demand" / "generated"


@dataclass(frozen=True)
class Profile:
    name: str
    title: str
    vph: int          # vehicles per hour entering the map (before the season multiplier)
    peds: int         # pedestrian trips per hour
    impaired: float   # multiplier on impaired drivers (night: more)
    bias: float       # >0: traffic mostly heads east/north (morning), <0: west/south (evening)


PROFILES = {
    "morning_rush": Profile("morning_rush", "Morning rush", 3600, 900, 0.5, 0.5),
    "midday": Profile("midday", "Midday", 2500, 1100, 0.8, 0.0),
    "evening_rush": Profile("evening_rush", "Evening rush", 3800, 1000, 1.0, -0.5),
    "night": Profile("night", "Night", 700, 150, 4.0, 0.0),
}

MIX = {"car": 0.86, "van": 0.07, "bus": 0.025}   # speeders and impaired come from the season


@lru_cache(maxsize=1)
def fringe():
    """(sources, sinks, sidewalks): map-edge roads in and out, edges people can walk on."""
    import sumolib
    net = sumolib.net.readNet(str(NET))
    cx = sum(n.getCoord()[0] for n in net.getNodes()) / len(net.getNodes())
    cy = sum(n.getCoord()[1] for n in net.getNodes()) / len(net.getNodes())
    src, snk, walk = [], [], []
    for e in net.getEdges():
        if e.getFunction() == "internal":
            continue
        cars = [ln for ln in e.getLanes() if ln.allows("passenger")]
        if any(ln.allows("pedestrian") for ln in e.getLanes()) and e.getLength() > 30:
            walk.append(e.getID())
        if not cars:
            continue
        w = len(cars) * e.getSpeed()
        ins = [i for i in e.getIncoming() if i.getFromNode() != e.getToNode()]     # by real turn links
        outs = [o for o in e.getOutgoing() if o.getToNode() != e.getFromNode()]
        x, y = e.getFromNode().getCoord() if not ins else e.getToNode().getCoord()
        side = ((x - cx) + (y - cy)) / max(1.0, abs(x - cx) + abs(y - cy))   # +1 east/north
        if not ins:
            src.append((e.getID(), w, side))
        if not outs:
            snk.append((e.getID(), w, -side))
    return src, snk, walk


def vtypes(s: Season) -> list[str]:
    base = (f'speedFactor="normc({s.speed:.2f},0.1,0.5,1.4)" decel="{s.decel}" tau="{s.tau}" '
            f'minGap="{s.min_gap}" sigma="{s.sigma}"')
    return [
        f'  <vType id="car" vClass="passenger" length="4.6" {base} color="0.82,0.84,0.88"/>',
        f'  <vType id="van" vClass="delivery" length="6.5" {base} color="0.55,0.58,0.62"/>',
        f'  <vType id="bus" vClass="bus" length="12" personCapacity="80" {base} color="0.89,0.95,0.13"/>',
        # speeders: fast, small gaps, push through the end of yellow
        f'  <vType id="speeder" vClass="passenger" length="4.6" speedFactor="normc({s.speed * 1.35:.2f},0.1,0.8,1.8)" '
        f'decel="{s.decel}" tau="1.0" minGap="2.0" sigma="0.5" lcAssertive="1.5" lcSpeedGain="3" '
        f'jmDriveAfterRedTime="2" color="1,0.55,0.2"/>',
        # impaired (drunk/high): erratic speed, slow reactions, may run a red light
        f'  <vType id="impaired" vClass="passenger" length="4.6" speedFactor="normc({s.speed * 1.1:.2f},0.3,0.5,1.8)" '
        f'decel="{s.decel}" tau="2.2" minGap="{s.min_gap}" sigma="1.0" actionStepLength="1.5" '
        f'jmDriveAfterRedTime="4" lcCooperative="0.1" color="0.75,0.3,1"/>',
        # no SUMO bluelight device: its rescue-lane logic crashed SUMO natively (access violation)
        # mid-training; the ambulance stays a fast emergency vehicle that drives through red lights
        '  <vType id="ambulance" vClass="emergency" guiShape="emergency" length="6.5" speedFactor="1.4" '
        'jmDriveAfterRedTime="300" jmDriveRedSpeed="5.5" color="1,1,1"/>',
        f'  <vType id="ped" vClass="pedestrian" speed="{s.ped_speed}" speedFactor="normc(1,0.15,0.6,1.4)"/>',
    ]


def write_routes(profile: str, season: str, seed: int = 0, scale: float = 1.0,
                 duration: int = 3600) -> Path:
    p, s = PROFILES[profile], SEASONS[season]
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{profile}_{season}_s{seed}_x{scale:.2f}_d{duration}.rou.xml"
    if path.exists():
        return path
    rng = random.Random(zlib.crc32(f"{profile}|{season}|{seed}".encode()))
    src, snk, _ = fringe()
    walk_pairs = json.loads((ROOT / "map" / "walk_pairs.json").read_text())
    speed_share = s.speeders
    imp_share = min(0.05, s.impaired * p.impaired)
    shares = dict(MIX)
    shares["car"] -= speed_share + imp_share
    shares["speeder"], shares["impaired"] = speed_share, imp_share

    total = p.vph * s.demand * scale
    pairs = []
    for o, wo, so in src:
        for d, wd, sd in snk:
            if o.split("_")[0].lstrip("-") == d.split("_")[0].lstrip("-"):
                continue        # same street in and out
            pairs.append((o, d, wo * wd * (1 + p.bias * so) * (1 + p.bias * sd) * rng.uniform(0.6, 1.4)))
    wsum = sum(w for *_, w in pairs)
    entries: list[tuple[float, str]] = []
    for k, (o, d, w) in enumerate(pairs):
        vph = total * w / wsum
        for vt, sh in shares.items():
            prob = vph * sh / 3600
            if prob < 1e-5:
                continue
            entries.append((0, f'  <flow id="f{k}_{vt}" type="{vt}" begin="0" end="{duration}" '
                               f'probability="{prob:.6f}" from="{o}" to="{d}" departLane="best" '
                               f'departSpeed="max"/>'))
    peds = p.peds * s.peds * scale
    n_pf = 40
    for k in range(n_pf):
        a, b = rng.choice(walk_pairs)
        entries.append((0, f'  <personFlow id="p_{k}" type="ped" begin="0" end="{duration}" '
                           f'probability="{peds / n_pf / 3600:.6f}"><walk from="{a}" to="{b}"/></personFlow>'))
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<routes>", *vtypes(s)]
    lines += [e for _, e in sorted(entries, key=lambda x: x[0])]
    lines.append("</routes>")
    # several training workers may build the same file at once: write aside, then swap in atomically
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    os.replace(tmp, path)
    return path


if __name__ == "__main__":
    src, snk, walk = fringe()
    print(len(src), "entries", len(snk), "exits", len(walk), "walkable edges")
    print(write_routes("morning_rush", "winter"))
