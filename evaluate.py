"""Compare every controller on the same traffic and the same sudden events.

    python evaluate.py                      # all trained models + baselines, 4 seasons x 4 profiles x 3 seeds
    python evaluate.py --seeds 1 --seasons winter

Seeds 100+ are never used in training. Writes results/summary.json (read by the website) and
results/summary.csv (one row per run).

Metrics (your partner's list, plus the ones that keep the comparison honest):
  avg_wait_s       average waiting time per vehicle (standing still), unfinished trips included
  avg_travel_s     average travel time per vehicle
  avg_queue        average number of halted vehicles at the 12 lights
  throughput_vph   vehicles that finished their trip, per hour
  arrived          vehicles that finished their trip
  time_loss_s      average time lost against free-flow driving
  teleports        vehicles SUMO had to remove from a gridlock
  + backlog_end    vehicles that could not even enter the map by the end (hidden queue)
  + max_red_wait_s longest single standstill at a light (fairness)
  + ped_loss_s     average time lost per pedestrian trip
  + co2_kg, ambulance_s (ambulance crossing time), events (what happened)
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
RES = ROOT / "results"
BASELINES = ["fixed", "actuated", "max_pressure"]
PROFILES = ["morning_rush", "midday", "evening_rush", "night"]
SEASONS = ["winter", "spring", "summer", "autumn"]


def trained_models() -> list[str]:
    return sorted(p.parent.name for p in (RES / "models").glob("*/model.zip"))


class Policy:
    """Loads a trained model and turns observations into one phase per light."""

    def __init__(self, name: str):
        from stable_baselines3 import A2C, DQN, PPO
        meta = json.loads((RES / "models" / name / "training.json").read_text())
        self.strategy, self.shield = meta["strategy"], meta["shield"]
        cls = {"ppo": PPO, "a2c": A2C, "dqn": DQN}[meta["algo"]]
        self.model = cls.load(RES / "models" / name / "model.zip", device="cpu")

    def act(self, sim, obs: dict) -> dict:
        ids = sim.ids
        if self.strategy == "central":
            x = np.concatenate([obs[i] for i in ids])[None]
            a, _ = self.model.predict(x, deterministic=True)
            return dict(zip(ids, (int(v) for v in a[0])))
        if self.strategy == "neighbour":
            obs = sim.neighbour_obs(obs)
        a, _ = self.model.predict(np.stack([obs[i] for i in ids]), deterministic=True)
        return dict(zip(ids, (int(v) for v in a)))


def parse_trips(path: Path, warmup: float) -> dict:
    root = ET.parse(path).getroot()
    occ = {"bus": 25.0, "van": 1.1}
    w, tt, tl, co2, n, pl, np_ = 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0
    for t in root.iter("tripinfo"):
        if float(t.get("depart", -1)) < warmup:
            continue
        n += 1
        w += float(t.get("waitingTime"))
        tt += float(t.get("duration"))
        tl += float(t.get("timeLoss"))
        em = t.find("emissions")
        if em is not None:
            co2 += float(em.get("CO2_abs")) / 1e6
    for p in root.iter("personinfo"):
        if float(p.get("depart", -1)) < warmup:
            continue
        for wk in p.iter("walk"):
            pl += float(wk.get("timeLoss"))
            np_ += 1
    return {"avg_wait_s": w / max(n, 1), "avg_travel_s": tt / max(n, 1), "time_loss_s": tl / max(n, 1),
            "co2_kg": co2, "trips": n, "ped_loss_s": pl / max(np_, 1)}


def _one(job):
    ctrl, profile, season, seed, out_dir = job
    from env.core import WARMUP, AstanaSim
    trip = Path(out_dir) / "trips" / f"{ctrl}_{profile}_{season}_{seed}.xml"
    trip.parent.mkdir(parents=True, exist_ok=True)
    policy, shield, mode = None, True, ctrl
    if ctrl not in BASELINES:
        policy = Policy(ctrl)
        shield, mode = policy.shield, "rl"
    sim = AstanaSim(profile, season, seed=seed, duration=3600, mode=mode, shield=shield, events=True,
                    random_faults=False, tripinfo=str(trip))
    obs = sim.start()
    done = False
    try:
        while not done:
            obs, _, done = sim.step(policy.act(sim, obs) if policy else None)
        s = sim.summary()
    finally:
        sim.close()
    row = {"controller": ctrl, "profile": profile, "season": season, "seed": seed,
           **{k: v for k, v in s.items() if k not in ("events", "reasons")},
           "events": s["events"], "reasons": s["reasons"], **parse_trips(trip, WARMUP)}
    trip.unlink(missing_ok=True)          # 10-50 MB each; the numbers are kept in the summary
    return row


METRICS = ["avg_wait_s", "avg_travel_s", "avg_queue", "throughput_vph", "arrived", "time_loss_s", "teleports",
           "backlog_end", "max_red_wait_s", "ped_loss_s", "co2_kg", "ambulance_s"]


def summarise(rows: list[dict]) -> dict:
    out: dict = {}
    for r in rows:
        key = (r["controller"], r["season"], r["profile"])
        out.setdefault(key, []).append(r)
    res = {}
    for (c, s, p), rs in out.items():
        m = {}
        for k in METRICS:
            vals = [x[k] for x in rs if x.get(k) is not None]
            m[k] = round(float(np.mean(vals)), 2) if vals else None
            m[k + "_sd"] = round(float(np.std(vals)), 2) if len(vals) > 1 else 0.0
        ev: dict = {}
        for x in rs:
            for e, n in x["events"].items():
                ev[e] = ev.get(e, 0) + n / len(rs)
        m["events"] = {e: round(n, 1) for e, n in ev.items()}
        res.setdefault(c, {}).setdefault(s, {})[p] = m
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--seasons", nargs="*", default=SEASONS)
    ap.add_argument("--profiles", nargs="*", default=PROFILES)
    ap.add_argument("--controllers", nargs="*", default=None)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()
    ctrls = args.controllers or BASELINES + trained_models()
    jobs = [(c, p, s, 100 + k, str(RES)) for c in ctrls for s in args.seasons for p in args.profiles
            for k in range(args.seeds)]
    print(f"{len(jobs)} runs: {len(ctrls)} controllers x {len(args.seasons)} seasons x "
          f"{len(args.profiles)} profiles x {args.seeds} seeds", flush=True)
    with mp.get_context("spawn").Pool(min(args.workers, len(jobs))) as pool:
        rows = []
        for k, r in enumerate(pool.imap_unordered(_one, jobs), 1):
            rows.append(r)
            if k % 50 == 0:
                print(f"  {k}/{len(jobs)}", flush=True)
    import pandas as pd
    flat = [{k: v for k, v in r.items() if k not in ("events", "reasons")} for r in rows]
    pd.DataFrame(flat).to_csv(RES / "summary.csv", index=False)
    summary = {"seeds": args.seeds, "seasons": args.seasons, "profiles": args.profiles, "controllers": ctrls,
               "results": summarise(rows)}
    (RES / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    from analysis import analyse
    analyse()


if __name__ == "__main__":
    main()
