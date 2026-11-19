"""Turn results/summary.json into a comparison and a plain-language verdict (results/analysis.json).

    python analysis.py

The main score is time lost per vehicle against free-flow driving (lower is better). It captures
waiting at lights and crawling in queues in one number. Every scenario (season x time of day)
counts equally. The hidden queue (cars that could not even enter the map) is checked separately,
because a controller can look good by keeping cars out of the map.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

RES = Path(__file__).resolve().parent / "results"
LABEL = {"independent": "Independent agents", "central": "Central brain with sub-agents",
         "neighbour": "Neighbour-aware agents", "fixed": "Fixed timer (today)", "actuated": "Actuated (SUMO)",
         "max_pressure": "Max-pressure (classic)"}
ALGO = {"ppo": "PPO", "a2c": "A2C", "dqn": "DQN"}
KEYS = ["time_loss_s", "avg_wait_s", "avg_travel_s", "avg_queue", "throughput_vph", "arrived", "teleports",
        "backlog_end", "max_red_wait_s", "ped_loss_s", "co2_kg", "ambulance_s"]


def label(c: str) -> str:
    if c in LABEL:
        return LABEL[c]
    parts = c.split("_")
    s = LABEL[parts[0]] + f" · {ALGO[parts[1]]}"
    if "noshield" in parts:
        s += " · shield off"
    if "long" in parts:
        s += " · 4× training"
    return s


def overall(res: dict, c: str) -> dict:
    cells = [m for s in res[c].values() for m in s.values()]
    return {k: round(float(np.mean([m[k] for m in cells if m.get(k) is not None])), 2)
            if any(m.get(k) is not None for m in cells) else None for k in KEYS}


def analyse() -> dict:
    data = json.loads((RES / "summary.json").read_text())
    res = data["results"]
    ctrls = list(res)
    ov = {c: overall(res, c) for c in ctrls}
    fixed = ov.get("fixed")
    ranking = sorted(ctrls, key=lambda c: ov[c]["time_loss_s"])
    strategies = {}
    for s in ("independent", "central", "neighbour"):
        runs = [c for c in ctrls if c.startswith(s + "_") and "noshield" not in c and "long" not in c]
        if runs:
            best = min(runs, key=lambda c: ov[c]["time_loss_s"])
            strategies[s] = {"best": best, "runs": {c: ov[c] for c in runs}}
    # head to head per scenario, best algorithm of each strategy
    cells = [(se, p) for se in data["seasons"] for p in data["profiles"]]
    h2h = {}
    for a in strategies:
        for b in strategies:
            if a < b:
                ca, cb = strategies[a]["best"], strategies[b]["best"]
                wins = sum(res[ca][se][p]["time_loss_s"] < res[cb][se][p]["time_loss_s"] for se, p in cells)
                h2h[f"{a}|{b}"] = {"a": a, "b": b, "a_wins": wins, "b_wins": len(cells) - wins}
    per_season = {}
    for se in data["seasons"]:
        per_season[se] = {c: round(float(np.mean([res[c][se][p]["time_loss_s"] for p in data["profiles"]])), 1)
                          for c in ctrls}
    shield = {}
    for s in strategies:
        on, off = f"{s}_ppo", f"{s}_ppo_noshield"
        if on in ov and off in ov:
            shield[s] = {"on": ov[on], "off": ov[off]}

    def vs_fixed(c, k="time_loss_s"):
        return round(100 * (ov[c][k] - fixed[k]) / fixed[k], 1) if fixed and fixed[k] else None

    verdict = []
    if strategies:
        order = sorted(strategies, key=lambda s: ov[strategies[s]["best"]]["time_loss_s"])
        top, top_c = order[0], strategies[order[0]]["best"]
        verdict.append(f"Best strategy: {LABEL[top]} ({label(top_c)}): {ov[top_c]['time_loss_s']:.0f} s lost per "
                       f"vehicle on average, {vs_fixed(top_c):+.0f}% against today's fixed timers.")
        for s in order[1:]:
            c = strategies[s]["best"]
            gap = 100 * (ov[c]["time_loss_s"] - ov[top_c]["time_loss_s"]) / ov[top_c]["time_loss_s"]
            verdict.append(f"{LABEL[s]} ({label(c)}): {ov[c]['time_loss_s']:.0f} s, {gap:+.0f}% vs the best "
                           f"strategy, {vs_fixed(c):+.0f}% vs fixed timers.")
        if "independent" in strategies and "central" in strategies:
            ci, cc = strategies["independent"]["best"], strategies["central"]["best"]
            k = h2h.get("central|independent")
            if k:
                verdict.append(f"Your two strategies head to head: central wins {k['a_wins']} of {len(cells)} "
                               f"scenarios, independent wins {k['b_wins']}.")
        mp_ = ov.get("max_pressure")
        if mp_:
            beat = [s for s in strategies if ov[strategies[s]["best"]]["time_loss_s"] < mp_["time_loss_s"]]
            verdict.append("Against the best classic rule (max-pressure, no learning): " +
                           (", ".join(LABEL[s] for s in beat) + " beat it." if beat else
                            "no RL strategy beats it yet on this budget."))
    out = {"labels": {c: label(c) for c in ctrls}, "overall": ov, "ranking": ranking, "strategies": strategies,
           "head_to_head": h2h, "per_season": per_season, "shield": shield, "verdict": verdict,
           "vs_fixed": {c: vs_fixed(c) for c in ctrls}, "training": training_info()}
    (RES / "analysis.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    for line in verdict:
        print("-", line)
    return out


def training_info() -> dict:
    info = {}
    for p in (RES / "models").glob("*/training.json"):
        m = json.loads(p.read_text())
        info[p.parent.name] = {"minutes": m["minutes"], "sim_hours": m["sim_hours"], "history": m["history"]}
    return info


if __name__ == "__main__":
    analyse()
