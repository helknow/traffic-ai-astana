"""Build the Astana city-centre network from OpenStreetMap with SUMO's own tools.

    python map/build_map.py            # uses the cached OSM extract in map/osm/
    python map/build_map.py --download # fetch a fresh extract first (needs internet)

Steps:
  1. osmGet.py downloads the area around Respublika and Abay avenues (map data (c) OpenStreetMap
     contributors, ODbL).
  2. netconvert turns it into a SUMO network: only real traffic streets, sidewalks and crosswalks
     guessed, junction clusters joined, traffic lights joined per junction, 90 s fixed-time plans.
  3. The network is cut to a 3 x 4 grid of signalised junctions (12 traffic lights):
     Beibitshilik, Auezov and Respublika crossed with Abay, Seifullin, Zhangeldin and Bogenbay.
  4. map/astana.add.xml gets an actuated program for every light ("actuated" baseline), and
     map/junctions.json gets readable names for the dashboard.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
OSM = HERE / "osm" / "astana_bbox.osm.xml"
FULL = HERE / "osm" / "full.net.xml"
NET = HERE / "astana.net.xml"
ADD = HERE / "astana.add.xml"
JUNCTIONS = HERE / "junctions.json"
WALKS = HERE / "walk_pairs.json"

BBOX = "71.415,51.158,71.445,51.178"          # lon/lat, Astana right-bank centre
CUT = "700,1430,1440,2700"                     # network metres: the 3 x 4 grid
CYCLE = 90                                     # fixed-time cycle, seconds

STREETS = {   # Kazakh OSM names -> short Latin names for the dashboard
    "Республика даңғылы": "Respublika", "Абай даңғылы": "Abay", "Мұхтар Әуезов көшесі": "Auezov",
    "Бейбітшілік көшесі": "Beibitshilik", "Сәкен Сейфуллин көшесі": "Seifullin",
    "Әліби Жангелдин көшесі": "Zhangeldin", "Бөгенбай Батыр даңғылы": "Bogenbay",
}
AVENUES = {"Respublika", "Abay", "Bogenbay"}


def sumo_home() -> Path:
    import sumo
    return Path(sumo.SUMO_HOME)


def run(cmd: list[str]) -> None:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode:
        print(res.stdout, res.stderr)
        raise SystemExit(f"failed: {cmd[0]}")


def download() -> None:
    OSM.parent.mkdir(parents=True, exist_ok=True)
    run([sys.executable, str(sumo_home() / "tools" / "osmGet.py"), "-b", BBOX, "-p", "astana",
         "-d", str(OSM.parent)])


def convert() -> None:
    nc = str(sumo_home() / "bin" / "netconvert")
    types = ",".join(f"highway.{t}" for t in ["trunk", "primary", "secondary", "tertiary", "trunk_link",
                                               "primary_link", "secondary_link", "tertiary_link"])
    run([nc, "--osm-files", str(OSM), "-o", str(FULL), "--keep-edges.by-type", types,
         "--remove-edges.isolated", "--keep-edges.components", "1", "--geometry.remove",
         "--roundabouts.guess", "--ramps.guess", "--junctions.join", "--junctions.join-dist", "25",
         "--tls.guess-signals", "--tls.discard-simple", "--tls.join", "--tls.join-dist", "30",
         "--tls.default-type", "static", "--tls.cycle.time", str(CYCLE), "--tls.yellow.time", "3",
         "--tls.allred.time", "2", "--sidewalks.guess", "--sidewalks.guess.max-speed", "30", "--crossings.guess",
         "--no-turnarounds.except-deadend", "--osm.lane-access", "false", "--output.street-names",
         "--proj.utm", "--no-warnings"])
    run([nc, "-s", str(FULL), "-o", str(NET), "--keep-edges.in-boundary", CUT,
         "--remove-edges.isolated", "--keep-edges.components", "1", "--no-warnings"])


def label(names: set[str]) -> tuple[str, str]:
    short = sorted({STREETS.get(n, n) for n in names if n}, key=lambda s: (s not in AVENUES, s))
    return " × ".join(short[:2]), "".join(s[:2].upper() for s in short[:2])


def finish() -> None:
    import sumolib
    net = sumolib.net.readNet(str(NET), withPrograms=True)
    root = ET.parse(NET).getroot()
    junctions, drop = [], []
    for tl in net.getTrafficLights():
        cons = tl.getConnections()
        if len(cons) < 4:                      # a stray signal cut off at the map edge
            drop.append(tl.getID())
            continue
        names = {c[0].getEdge().getName() for c in cons}
        nodes = {c[0].getEdge().getToNode() for c in cons}
        x = sum(n.getCoord()[0] for n in nodes) / len(nodes)
        y = sum(n.getCoord()[1] for n in nodes) / len(nodes)
        name, code = label(names)
        junctions.append({"id": tl.getID(), "name": name, "code": code, "x": round(x, 1), "y": round(y, 1)})
    if drop:   # turn stray signals into plain priority junctions
        nc = str(sumo_home() / "bin" / "netconvert")
        run([nc, "-s", str(NET), "-o", str(NET), "--tls.unset", ",".join(drop), "--no-warnings"])
        root = ET.parse(NET).getroot()
    # reading order: rows north -> south (Abay ... Bogenbay), columns west -> east
    rows, cols = ["Abay", "Seifullin", "Zhangeldin", "Bogenbay"], ["Beibitshilik", "Auezov", "Respublika"]

    def grid(j):
        parts = j["name"].split(" × ")
        return (next((rows.index(p) for p in parts if p in rows), 9),
                next((cols.index(p) for p in parts if p in cols), 9))
    junctions.sort(key=grid)
    for k, j in enumerate(junctions):
        j["short"] = f"J{k + 1:02d}"
    JUNCTIONS.write_text(json.dumps(junctions, ensure_ascii=False, indent=1), encoding="utf-8")

    # actuated copy of every fixed-time program (the classic "smart" baseline SUMO ships with)
    add = ET.Element("additional")
    for tl in root.iter("tlLogic"):
        a = ET.SubElement(add, "tlLogic", id=tl.get("id"), type="actuated", programID="actuated",
                          offset="0")
        ET.SubElement(a, "param", key="max-gap", value="3.0")
        ET.SubElement(a, "param", key="detector-gap", value="2.0")
        for ph in tl.iter("phase"):
            d = float(ph.get("duration"))
            green = any(c in "Gg" for c in ph.get("state")) and "y" not in ph.get("state")
            attrs = {"duration": f"{d:.0f}", "state": ph.get("state")}
            if green and d > 10:
                attrs |= {"minDur": "7", "maxDur": "55"}
            ET.SubElement(a, "phase", **attrs)
    ET.indent(add)
    ADD.write_bytes(ET.tostring(add, encoding="utf-8", xml_declaration=True))
    print(f"{NET.name}: {len(junctions)} traffic lights, dropped {len(drop)} stray")
    for j in junctions:
        print(f"  {j['short']} {j['name']}")
    walk_pairs()


def walk_pairs(n: int = 120) -> None:
    """Sidewalk start/end pairs SUMO can actually route (the OSM sidewalk network has gaps)."""
    import random
    import libsumo
    import sumolib
    net = sumolib.net.readNet(str(NET))
    walk = [e.getID() for e in net.getEdges() if e.getFunction() != "internal" and e.getLength() > 30
            and any(ln.allows("pedestrian") for ln in e.getLanes())]
    libsumo.start([str(sumo_home() / "bin" / "sumo"), "-n", str(NET), "--no-warnings", "--no-step-log"])
    rng, pairs, tries = random.Random(1), [], 0
    while len(pairs) < n and tries < 5000:
        tries += 1
        a, b = rng.sample(walk, 2)
        stages = libsumo.simulation.findIntermodalRoute(a, b, modes="", vType="DEFAULT_PEDTYPE")
        if stages and stages[-1].edges and stages[-1].edges[-1] == b and sum(s.length for s in stages) > 250:
            pairs.append((a, b))
    libsumo.close()
    WALKS.write_text(json.dumps(pairs))
    print(f"{len(pairs)} walkable pedestrian trips found")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true")
    args = ap.parse_args()
    if args.download or not OSM.exists():
        download()
    convert()
    finish()
