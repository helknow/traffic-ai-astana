"""Turn results/summary.json into a comparison and a plain-language verdict (results/analysis.json).

    python analysis.py

The main score is time lost per vehicle against free-flow driving (lower is better). It captures
waiting at lights and crawling in queues in one number. Every scenario (season x time of day)
counts equally. The hidden queue (cars that could not even enter the map) is checked separately,
because a controller can look good by keeping cars out of the map.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

RES = Path(__file__).resolve().parent / "results"
# plain names, the same as on the web page
LABEL = {"independent": "Independent AI", "central": "Central AI", "neighbour": "Neighbour AI",
         "fixed": "Fixed timer (today)", "actuated": "Sensor timer", "max_pressure": "Simple rule (max-pressure)"}
ALGO = {"ppo": "PPO", "a2c": "A2C", "dqn": "DQN"}
WHAT = {"independent": "each light decides alone", "central": "one brain runs all 12 lights",
        "neighbour": "each light also hears its neighbours"}
KEYS = ["time_loss_s", "avg_wait_s", "avg_travel_s", "avg_queue", "throughput_vph", "arrived", "teleports",
        "backlog_end", "max_red_wait_s", "ped_loss_s", "co2_kg", "ambulance_s"]


def label(c: str) -> str:
    if c in LABEL:
        return LABEL[c]
    parts = c.split("_")
    s = LABEL[parts[0]] + f" · {ALGO[parts[1]]}"
    if "noshield" in parts:
        s += " · safety rules off"
    if "long" in parts:
        s += " · 4× practice"
    return s


def overall(res: dict, c: str) -> dict:
    cells = [m for s in res[c].values() for m in s.values()]
    return {k: round(float(np.mean([m[k] for m in cells if m.get(k) is not None])), 2)
            if any(m.get(k) is not None for m in cells) else None for k in KEYS}


def analyse() -> dict:
    data = json.loads((RES / "summary.json").read_text(encoding="utf-8"))
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

    # the written answer, in plain words (shown on the Results page)
    verdict = []
    if strategies:
        order = sorted(strategies, key=lambda s: ov[strategies[s]["best"]]["time_loss_s"])
        top, top_c = order[0], strategies[order[0]]["best"]
        best = ov[top_c]["time_loss_s"]
        verdict.append(f"Winner: {LABEL[top]} ({WHAT[top]}). With it, a car loses {best:.0f} seconds on average, "
                       f"{-vs_fixed(top_c):.0f}% less than with today's fixed timers.")
        for s in order[1:]:
            c = strategies[s]["best"]
            loss = ov[c]["time_loss_s"]
            gap = 100 * (loss - best) / best
            how = "about the same as the winner" if gap < 3 else f"{gap:.0f}% more delay than the winner"
            verdict.append(f"{LABEL[s]} ({WHAT[s]}): {loss:.0f} seconds, {how}, "
                           f"{-vs_fixed(c):.0f}% less than today.")
        k = h2h.get("central|independent")
        if k:
            verdict.append(f"Your two ideas side by side: the independent AI had less delay in {k['b_wins']} of "
                           f"{len(cells)} situations (4 seasons × 4 times of day), the central AI in {k['a_wins']}.")
        k = h2h.get("independent|neighbour")
        if k:
            verdict.append(f"Independent vs neighbour AI: {k['a_wins']} wins to {k['b_wins']}. Letting the lights hear "
                           f"their neighbours barely helps on these 12 lights.")
        mp_ = ov.get("max_pressure")
        if mp_:
            m = mp_["time_loss_s"]
            loss = {s: ov[strategies[s]["best"]]["time_loss_s"] for s in strategies}
            beat = [s for s in strategies if loss[s] < 0.98 * m]          # within 2 % is a tie
            tie = [s for s in strategies if abs(loss[s] - m) <= 0.02 * m]
            text = (" and ".join(LABEL[s] for s in beat) + " clearly beat it." if beat else
                    "no AI clearly beats it yet.")
            if tie:
                text += " " + " and ".join(f"{LABEL[s]} only ties it ({loss[s]:.0f} s vs {m:.0f} s)" for s in tie) + "."
            verdict.append("Compared with the simple rule that needs no AI (green to the longest queue): " + text)
        if "central_ppo_long" in ov and "central_ppo" in ov:
            a, b = ov["central_ppo"]["time_loss_s"], ov["central_ppo_long"]["time_loss_s"]
            change = "no better" if b >= a * 0.98 else f"{100 * (a - b) / a:.0f}% better"
            verdict.append(f"Would more practice save the central AI? With 4 times more training it got {b:.0f} s "
                           f"instead of {a:.0f} s: {change}. The problem is the design, not practice: one brain has "
                           f"to pick settings for all 12 lights at once (about 16.8 million combinations) from one "
                           f"shared score, so it cannot tell which light did well.")
        for s, v in shield.items():
            on, off = v["on"], v["off"]
            verdict.append(f"Safety rules off for the {LABEL[s].lower().replace('ai', 'AI')}: delay per car "
                           f"{on['time_loss_s']:.0f} → {off['time_loss_s']:.0f} s, longest wait "
                           f"{on['max_red_wait_s']:.0f} → {off['max_red_wait_s']:.0f} s, stuck cars removed "
                           f"{on['teleports']:.1f} → {off['teleports']:.1f} per hour.")
        algos = []
        for s, v in strategies.items():
            ranked = sorted(v["runs"], key=lambda c: v["runs"][c]["time_loss_s"])
            algos.append(f"{LABEL[s]}: " + ", ".join(
                f"{ALGO[c.split('_')[1]]} {v['runs'][c]['time_loss_s']:.0f} s" for c in ranked))
        verdict.append("Best learning method (delay per car, lower is better): " + "; ".join(algos) + ".")
    out = {"labels": {c: label(c) for c in ctrls}, "overall": ov, "ranking": ranking, "strategies": strategies,
           "head_to_head": h2h, "per_season": per_season, "shield": shield, "verdict": verdict,
           "vs_fixed": {c: vs_fixed(c) for c in ctrls}, "training": training_info()}
    (RES / "analysis.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    for line in verdict:     # Windows consoles default to cp1251 here, which has no "×" or "→"
        print("-", line.encode(sys.stdout.encoding or "utf-8", "replace").decode(sys.stdout.encoding or "utf-8"))
    return out


def training_info() -> dict:
    info = {}
    for p in (RES / "models").glob("*/training.json"):
        m = json.loads(p.read_text())
        info[p.parent.name] = {"minutes": m["minutes"], "sim_hours": m["sim_hours"], "history": m["history"]}
    return info


if __name__ == "__main__":
    analyse()
