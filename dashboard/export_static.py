"""Build a static copy of the race board (for Vercel or any static host).

SUMO cannot run on a static host, so this records races ahead of time: the same four controllers
drive the same Astana traffic with the same scripted events, and the page plays them back with the
live page's own board, map and results.

    python dashboard/export_static.py                 # writes site/
    python dashboard/export_static.py --minutes 4 --only winter_evening_rush   # quick test
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dashboard"))

import server  # noqa: E402
from env.core import WARMUP  # noqa: E402

SITE = ROOT / "site"
SCENARIOS = [(s, p) for s in ("winter", "spring", "summer", "autumn") for p in ("morning_rush", "evening_rush")]
KINDS = "cbvsiax"          # car, bus, van, speeder, impaired, ambulance, crashed
KPI = ["loss", "wait", "queue", "throughput", "arrived", "hidden", "teleports", "maxWait", "ambulance"]
# scripted "button presses", minutes after the warm-up: the same for every controller
SCRIPT = [(2, "accident"), (5, "jaywalker"), (7, "ambulance"), (9, "impaired"), (11, "breakdown")]
SEASON_EXTRA = {"winter": (3, "snowstorm"), "summer": (3, "roadworks")}


def controllers() -> list[str]:
    """Best algorithm of each strategy (from the evaluation if there is one) + today's fixed timers."""
    a = ROOT / "results" / "analysis.json"
    models = server.trained_models()
    out = []
    if a.exists():
        best = json.loads(a.read_text(encoding="utf-8")).get("strategies", {})
        out = [best[s]["best"] for s in ("neighbour", "independent", "central") if s in best and best[s]["best"] in models]
    if not out:
        out = [m for m in ("neighbour_ppo", "independent_ppo", "central_ppo") if m in models]
    return out[:3] + ["fixed"]


def record(season: str, profile: str, ctrls: list[str], minutes: float, dt: int) -> dict:
    live = server.Live(ctrls, profile, season, seed=101, shield=True)
    live.start()
    script = sorted(SCRIPT + ([SEASON_EXTRA[season]] if season in SEASON_EXTRA else []))
    end = WARMUP + minutes * 60
    frames, last_lights, last_log = [], [{} for _ in ctrls], None
    t0 = time.time()
    try:
        while not live.done and live.runs[0].sim.t < end:
            live.advance()
            t = live.runs[0].sim.t
            while script and t >= WARMUP + script[0][0] * 60:
                live.event(script.pop(0)[1])
            if round(t) % dt or (frames and frames[-1]["t"] == round(t)):
                continue
            f = live.frame(-1)
            item = {"t": round(t), "r": []}
            if f["log"] != last_log:
                item["log"] = last_log = f["log"]
            for k, run in enumerate(f["runs"]):
                veh = []
                for v in run["veh"]:
                    veh += [_vid(v[0]), round(v[1]), round(v[2]), v[3], KINDS.index(v[4]) * 2 + v[5]]
                ppl = []
                for p in run["ppl"]:
                    ppl += [round(p[0]), round(p[1]), p[2]]
                lights = {i: d for i, d in run["lights"].items() if last_lights[k].get(i) != d}
                last_lights[k].update(lights)
                r = {"k": [run["kpi"][x] for x in KPI], "v": veh, "p": ppl}
                if lights:
                    r["l"] = lights
                if run["events"]:
                    r["e"] = run["events"]
                if run["snow"]:
                    r["s"] = 1
                if run["done"]:
                    r["d"] = 1
                item["r"].append(r)
            frames.append(item)
    finally:
        live.close()
    print(f"  {season} {profile}: {len(frames)} frames in {time.time() - t0:.0f} s", flush=True)
    return {"season": season, "profile": profile, "dt": dt, "kpi": KPI, "kinds": KINDS,
            "controllers": [{"id": c, "label": server.controller_label(c)} for c in ctrls], "frames": frames}


_IDS: dict[str, int] = {}


def _vid(v: str) -> int:
    return _IDS.setdefault(v, len(_IDS))


def build(minutes: float, dt: int, only: str | None, ctrls: list[str]) -> None:
    data = SITE / "data"
    (data / "replays").mkdir(parents=True, exist_ok=True)
    web = ROOT / "dashboard" / "web"
    shutil.copy(web / "app.js", SITE / "app.js")
    shutil.copy(web / "app.css", SITE / "app.css")
    html = (web / "index.html").read_text(encoding="utf-8")
    html = html.replace('href="/static/app.css"', 'href="app.css"').replace(
        '<script src="/static/app.js"></script>', '<script>window.BENCH_STATIC = true;</script>\n<script src="app.js"></script>')
    (SITE / "index.html").write_text(html, encoding="utf-8")

    dump = lambda p, o: p.write_text(json.dumps(o, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")  # noqa: E731
    dump(data / "network.json", server.network_geometry())
    opts = server.options()
    opts["controllers"] = [c for c in opts["controllers"] if c["id"] in ctrls]
    res = server.api_results()
    dump(data / "results.json", json.loads(res.body))
    scen = [x for x in SCENARIOS if not only or f"{x[0]}_{x[1]}" == only]
    opts["replays"] = [{"season": s, "profile": p, "file": f"replays/{s}_{p}.json"} for s, p in scen]
    opts["replay_minutes"] = minutes
    opts["replay_controllers"] = ctrls
    dump(data / "options.json", opts)
    for s, p in scen:
        _IDS.clear()
        dump(data / "replays" / f"{s}_{p}.json", record(s, p, ctrls, minutes, dt))
    (SITE / "vercel.json").write_text(json.dumps({"headers": [{"source": "/data/(.*)", "headers": [
        {"key": "Cache-Control", "value": "public, max-age=3600"}]}]}, indent=2))
    size = sum(f.stat().st_size for f in SITE.rglob("*") if f.is_file()) / 1e6
    print(f"site/ written: {size:.1f} MB", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=12)
    ap.add_argument("--dt", type=int, default=2, help="seconds between recorded frames")
    ap.add_argument("--only", help="one scenario, e.g. winter_evening_rush")
    ap.add_argument("--controllers", nargs="*")
    a = ap.parse_args()
    build(a.minutes, a.dt, a.only, a.controllers or controllers())
