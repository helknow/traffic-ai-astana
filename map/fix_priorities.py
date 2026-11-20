"""Fix right-of-way just past the traffic lights.

OSM gives most central streets the same rank, so at a plain (unsignalised) junction a few metres
after a light SUMO sometimes made the main street the minor road. Example: 8 m past J07 the
traffic leaving the light on Zhangeldin had to give way to a 45 m unnamed slip road; every car
from the slip road froze J07's exit and cars stood 5-7 minutes at the stop line even on green.

This raises the rank of the light's exit edge and its straight continuation so they become the
major road there. Traffic-light programs and link indices are checked to be unchanged, so the
trained models stay valid.

    python map/fix_priorities.py
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NET = ROOT / "map" / "astana.net.xml"
PATCH = ROOT / "map" / "priority_patch.edg.xml"
SHORT = 25.0     # metres: a plain junction this close after a light behaves as part of it


def problems(root):
    """(exit edge, continuation edge, node) where the through movement out of a light is minor."""
    edges = {e.get("id"): e for e in root.iter("edge") if not e.get("function")}
    junctions = {j.get("id"): j for j in root.iter("junction")}
    length = {e.get("id"): float(e.find("lane").get("length")) for e in edges.values()}
    out = []
    for c in root.iter("connection"):
        frm, to = c.get("from"), c.get("to")
        if frm not in edges or to not in edges or c.get("dir") != "s" or c.get("state") not in ("m", "="):
            continue
        e = edges[frm]
        node = junctions.get(e.get("to"))
        start = junctions.get(e.get("from"))
        if node is None or start is None or node.get("type") == "traffic_light":
            continue
        if start.get("type") == "traffic_light" and length[frm] < SHORT:
            out.append((frm, to, e.get("to"), int(e.get("priority", -1))))
    return sorted(set(out))


def tls_signature(root):
    progs = [ET.tostring(t) for t in root.iter("tlLogic")]
    links = sorted((c.get("tl"), c.get("linkIndex"), c.get("from"), c.get("to"), c.get("fromLane"), c.get("toLane"))
                   for c in root.iter("connection") if c.get("tl"))
    return progs, links


def main() -> None:
    root = ET.parse(NET).getroot()
    bad = problems(root)
    if not bad:
        print("no minor through movements just past a light")
        return
    lines = ['<edges>']
    for frm, to, node, prio in bad:
        print(f"node {node}: {frm} -> {to} was minor; raising its rank")
        lines += [f'  <edge id="{frm}" priority="{prio + 5}"/>', f'  <edge id="{to}" priority="{prio + 5}"/>']
    lines.append('</edges>')
    PATCH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    import sumo
    netconvert = str(Path(sumo.SUMO_HOME) / "bin" / "netconvert")
    tmp = NET.with_suffix(".tmp.xml")
    subprocess.run([netconvert, "-s", str(NET), "-e", str(PATCH), "-o", str(tmp), "--no-warnings"], check=True)
    new = ET.parse(tmp).getroot()
    if tls_signature(new) != tls_signature(root):
        tmp.unlink()
        sys.exit("traffic-light programs changed; not applying")
    left = problems(new)
    os.replace(tmp, NET)
    print(f"applied: {len(bad)} fixed, {len(left)} left")


if __name__ == "__main__":
    main()
