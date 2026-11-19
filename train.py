"""Train one RL strategy with one algorithm.

    python train.py --strategy independent --algo ppo
    python train.py --strategy central --algo a2c --sim-hours 400
    python train.py --strategy neighbour --algo dqn --no-shield

Every run gets the same budget in *simulated hours of traffic*, so strategies are compared fairly:
independent/neighbour collect 12 training samples per decision (one per light), central collects
one (a joint decision for all 12). DQN cannot choose 12 lights at once (no MultiDiscrete support),
so it is trained for independent and neighbour only.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from stable_baselines3 import A2C, DQN, PPO
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.vec_env import VecMonitor

from env.core import DECISION
from env.strategies import N_LIGHTS, STRATEGIES, SubAgentExtractor, make_env

ROOT = Path(__file__).resolve().parent


def run_name(strategy: str, algo: str, shield: bool, tag: str = "") -> str:
    return f"{strategy}_{algo}" + ("" if shield else "_noshield") + (f"_{tag}" if tag else "")


class Progress(BaseCallback):
    def __init__(self, env, per_step_hours: float, every_hours: float = 20.0):
        super().__init__()
        self.env, self.per, self.every = env, per_step_hours, every_hours
        self.next, self.t0, self.history = every_hours, time.time(), []

    def _on_step(self) -> bool:
        hours = self.num_timesteps * self.per
        if hours >= self.next:
            self.next += self.every
            eps = self.env.episodes[-24:]
            if eps:
                row = {"sim_hours": round(hours), "minutes": round((time.time() - self.t0) / 60, 1),
                       "avg_queue": round(float(np.mean([e["avg_queue"] for e in eps])), 1),
                       "throughput_vph": round(float(np.mean([e["throughput_vph"] for e in eps])), 0),
                       "max_red_wait_s": round(float(np.mean([e["max_red_wait_s"] for e in eps])), 0)}
                self.history.append(row)
                print(json.dumps(row), flush=True)
        return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", choices=STRATEGIES, required=True)
    ap.add_argument("--algo", choices=["ppo", "a2c", "dqn"], default="ppo")
    ap.add_argument("--sim-hours", type=float, default=400)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--duration", type=int, default=1800, help="episode length, simulated seconds")
    ap.add_argument("--no-shield", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--tag", default="", help="suffix for the run name, e.g. long")
    args = ap.parse_args()
    if args.algo == "dqn" and args.strategy == "central":
        raise SystemExit("DQN cannot pick a phase for 12 lights at once (4^12 joint actions); use ppo or a2c.")

    shield = not args.no_shield
    name = run_name(args.strategy, args.algo, shield, args.tag)
    out = ROOT / "results" / "models" / name
    out.mkdir(parents=True, exist_ok=True)
    env = make_env(args.strategy, n_workers=args.workers, duration=args.duration, seed=args.seed, shield=shield)
    venv = VecMonitor(env)
    rows_per_step = N_LIGHTS if args.strategy != "central" else 1
    per_step_hours = DECISION / 3600 / rows_per_step       # simulated hours per counted timestep
    total = int(args.sim_hours / per_step_hours)

    central = args.strategy == "central"
    pk = {"features_extractor_class": SubAgentExtractor, "net_arch": dict(pi=[256], vf=[256])} if central \
        else {"net_arch": [128, 128]}
    if args.algo == "ppo":
        model = PPO("MlpPolicy", venv, n_steps=256 if central else 128, batch_size=256 if central else 2048,
                    n_epochs=10 if central else 6, learning_rate=3e-4, gamma=0.95, gae_lambda=0.9,
                    ent_coef=0.01, clip_range=0.2, policy_kwargs=pk, device="cpu", seed=args.seed, verbose=0)
    elif args.algo == "a2c":
        model = A2C("MlpPolicy", venv, n_steps=16 if central else 8, learning_rate=7e-4, gamma=0.95,
                    gae_lambda=0.9, ent_coef=0.01, policy_kwargs=pk, device="cpu", seed=args.seed, verbose=0)
    else:
        model = DQN("MlpPolicy", venv, learning_rate=5e-4, buffer_size=300_000, learning_starts=20_000,
                    batch_size=256, gamma=0.95, train_freq=1, gradient_steps=4, target_update_interval=2_000,
                    exploration_fraction=0.25, exploration_final_eps=0.03, policy_kwargs={"net_arch": [128, 128]},
                    device="cpu", seed=args.seed, verbose=0)
    cb = Progress(env, per_step_hours, every_hours=max(10.0, args.sim_hours / 25))
    t0 = time.time()
    try:
        model.learn(total_timesteps=total, callback=cb)
    finally:
        model.save(out / "model")
        meta = {"strategy": args.strategy, "algo": args.algo, "shield": shield, "tag": args.tag, "sim_hours": args.sim_hours,
                "timesteps": total, "minutes": round((time.time() - t0) / 60, 1), "history": cb.history,
                "worker_restarts": env.restarts}
        (out / "training.json").write_text(json.dumps(meta, indent=1))
        venv.close()
    print(f"saved {out / 'model.zip'} in {meta['minutes']} min")


if __name__ == "__main__":
    main()
