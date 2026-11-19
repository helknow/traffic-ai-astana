"""The three RL strategies as Stable-Baselines3 vector environments.

  independent  (your strategy 1) each light is its own agent and sees ONLY its own approaches.
               One "env" per light; reward = its own reward.
  central      (your strategy 2) a sub-agent at every light encodes its own traffic and sends
               it to ONE main model, which sets all 12 lights at once. One "env" per simulation;
               action = a phase for every light; reward = average of all lights.
  neighbour    (our suggested middle ground) each light is still its own agent, but it also hears
               a short summary from its up-to-4 neighbours (their queue, longest wait, cars on the
               way to me), and its reward includes half of its neighbours' reward.

All three use the same simulator, traffic, seasons and sudden events; each worker process runs
one SUMO (libsumo).
"""
from __future__ import annotations

import multiprocessing as mp
import random

import numpy as np
import torch
from gymnasium import spaces
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor
from stable_baselines3.common.vec_env import VecEnv

from .core import LOCAL_DIM, NEIGHBOUR_DIM
from .tls import MAX_PHASES, load

STRATEGIES = ("independent", "central", "neighbour")
N_LIGHTS = len(load())
TRAIN_PROFILES = {"morning_rush": 3, "evening_rush": 3, "midday": 3, "night": 1}
SEASONS = ["winter", "spring", "summer", "autumn"]


def _worker(remote, wid: int, duration: int, base_seed: int, shield: bool):
    import faulthandler
    import traceback
    from pathlib import Path
    from .core import AstanaSim
    log_dir = Path(__file__).resolve().parent.parent / "results" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    crash_log = open(log_dir / f"worker{wid}_native.log", "a")
    faulthandler.enable(file=crash_log)              # native crashes (SUMO) leave a stack here
    rng = random.Random(base_seed * 1000 + wid)
    sim = None
    episode = {}

    def new_episode():
        nonlocal sim
        if sim is not None:
            sim.close()
        names, weights = zip(*TRAIN_PROFILES.items())
        episode.update(profile=rng.choices(names, weights)[0], season=rng.choice(SEASONS),
                       seed=rng.randrange(30), scale=rng.choice([0.85, 1.0, 1.15]))
        sim = AstanaSim(episode["profile"], episode["season"], seed=episode["seed"], scale=episode["scale"],
                        duration=duration, mode="rl", shield=shield, events=True, random_faults=True)
        crash_log.write(f"--- episode {episode}\n")
        crash_log.flush()
        return pack(sim, sim.start())

    def pack(s, local):
        nb = s.neighbour_obs(local)
        return (np.stack([local[i] for i in s.ids]), np.stack([nb[i] for i in s.ids]))

    try:
        while True:
            cmd, data = remote.recv()
            if cmd == "reset":
                remote.send(new_episode())
            elif cmd == "step":
                n_ev = len(sim.events.log)
                obs, rew, done = sim.step({i: int(a) for i, a in zip(sim.ids, data)})
                for e in sim.events.log[n_ev:]:          # breadcrumbs for a native crash
                    crash_log.write(f"t={sim.t:.0f} event {e.kind} edge={e.edge} veh={e.vehicles} {e.note}\n")
                    crash_log.flush()
                o = pack(sim, obs)
                r = np.array([rew[i] for i in sim.ids], np.float32)
                info = {}
                if done:
                    info = {"terminal": o, "summary": sim.summary(), "season": sim.season.name,
                            "profile": sim.profile.name}
                    o = new_episode()
                remote.send((o, r, done, info))
            elif cmd == "close":
                break
    except Exception:
        with open(log_dir / "worker_errors.log", "a") as f:
            f.write(f"worker {wid} episode {episode} t={getattr(sim, 't', None)}\n{traceback.format_exc()}\n")
        raise
    finally:
        if sim is not None:
            sim.close()
        remote.close()


class _Base(VecEnv):
    def __init__(self, n_workers: int, duration: int, seed: int, shield: bool, n_envs: int, obs_space, act_space):
        self.n_workers = n_workers
        self._args = (duration, seed, shield)
        self.ctx = mp.get_context("spawn")
        self.remotes, self.procs = [None] * n_workers, [None] * n_workers
        self.restarts = 0
        self.dead: set[int] = set()
        for w in range(n_workers):
            self._spawn(w, w)
        super().__init__(n_envs, obs_space, act_space)
        self.episodes: list[dict] = []
        nb = [L.neighbours for L in load().values()]
        ids = [L.short for L in load().values()]
        self.nb_idx = [[ids.index(n) for n in ns] for ns in nb]

    def _spawn(self, slot: int, wid: int) -> None:
        duration, seed, shield = self._args
        a, b = self.ctx.Pipe()
        p = self.ctx.Process(target=_worker, args=(b, wid, duration, seed, shield), daemon=True)
        p.start()
        b.close()
        self.remotes[slot], self.procs[slot] = a, p

    def _send(self, slot: int, msg) -> None:
        try:
            self.remotes[slot].send(msg)
        except (BrokenPipeError, EOFError, ConnectionResetError, OSError):
            self.dead.add(slot)

    def _recv(self, slot: int):
        """Receive from a worker; if SUMO killed it, start a fresh one and end that episode."""
        try:
            if slot in self.dead:
                raise EOFError
            return self.remotes[slot].recv()
        except (EOFError, BrokenPipeError, ConnectionResetError, OSError):
            self.dead.discard(slot)
            self.restarts += 1
            print(f"worker {slot} died (SUMO crash); restarting it (restart #{self.restarts})", flush=True)
            self._spawn(slot, 100 * self.restarts + slot)      # new seed stream for the replacement
            self.remotes[slot].send(("reset", None))
            o = self.remotes[slot].recv()
            n = len(o[0])
            return o, np.zeros(n, np.float32), True, {"terminal": o, "summary": None, "season": "", "profile": ""}

    def _gather(self):
        out = [self._recv(k) for k in range(self.n_workers)]
        for o, rw, d, info in out:
            if d and info.get("summary") is None:
                continue
            if d:
                self.episodes.append({"season": info["season"], "profile": info["profile"], **info["summary"]})
        return out

    def reset(self):
        for r in self.remotes:
            r.send(("reset", None))
        return self._obs([r.recv() for r in self.remotes])

    def close(self):
        for r in self.remotes:
            try:
                r.send(("close", None))
            except Exception:
                pass
        for p in self.procs:
            p.join(10)

    def get_attr(self, attr_name, indices=None):
        return [None] * self.num_envs

    def set_attr(self, attr_name, value, indices=None):
        pass

    def env_method(self, method_name, *args, indices=None, **kwargs):
        return [None] * self.num_envs

    def env_is_wrapped(self, wrapper_class, indices=None):
        return [False] * self.num_envs

    def seed(self, seed=None):
        return [None] * self.num_envs


class PerLightEnv(_Base):
    """independent / neighbour: every light of every simulation is one env row."""

    def __init__(self, strategy: str, n_workers: int = 12, duration: int = 1800, seed: int = 0, shield: bool = True):
        self.strategy = strategy
        dim = LOCAL_DIM if strategy == "independent" else NEIGHBOUR_DIM
        super().__init__(n_workers, duration, seed, shield, n_workers * N_LIGHTS,
                         spaces.Box(0.0, 4.0, (dim,), np.float32), spaces.Discrete(MAX_PHASES))

    def _obs(self, packs):
        k = 0 if self.strategy == "independent" else 1
        return np.concatenate([p[k] for p in packs])

    def _mix(self, r):
        if self.strategy == "independent":
            return r
        return np.array([r[i] + 0.5 * (np.mean(r[nb]) if nb else 0.0) for i, nb in enumerate(self.nb_idx)],
                        np.float32)

    def step_async(self, actions):
        acts = np.asarray(actions).reshape(self.n_workers, N_LIGHTS)
        for k, a in enumerate(acts):
            self._send(k, ("step", a))

    def step_wait(self):
        out = self._gather()
        obs = self._obs([o for o, *_ in out])
        rews = np.concatenate([self._mix(rw) for _, rw, _, _ in out])
        dones = np.repeat([d for _, _, d, _ in out], N_LIGHTS)
        infos = []
        k = 0 if self.strategy == "independent" else 1
        for _, _, d, info in out:
            if d:
                infos += [{"terminal_observation": info["terminal"][k][i]} for i in range(N_LIGHTS)]
            else:
                infos += [{} for _ in range(N_LIGHTS)]
        return obs, rews, dones, infos


class CentralEnv(_Base):
    """central: one env row per simulation; the action sets every light."""

    def __init__(self, n_workers: int = 12, duration: int = 1800, seed: int = 0, shield: bool = True):
        super().__init__(n_workers, duration, seed, shield, n_workers,
                         spaces.Box(0.0, 4.0, (N_LIGHTS * LOCAL_DIM,), np.float32),
                         spaces.MultiDiscrete([MAX_PHASES] * N_LIGHTS))

    def _obs(self, packs):
        return np.stack([p[0].reshape(-1) for p in packs])

    def step_async(self, actions):
        for k, a in enumerate(np.asarray(actions)):
            self._send(k, ("step", a))

    def step_wait(self):
        out = self._gather()
        obs = self._obs([o for o, *_ in out])
        rews = np.array([float(np.mean(rw)) for _, rw, _, _ in out], np.float32)
        dones = np.array([d for _, _, d, _ in out])
        infos = [{"terminal_observation": info["terminal"][0].reshape(-1)} if d else {} for _, _, d, info in out]
        return obs, rews, dones, infos


class SubAgentExtractor(BaseFeaturesExtractor):
    """Strategy 2's network: the same small 'sub-agent' encoder runs at every light, then the
    main model reads all 12 encodings together (their order tells it which light is which)."""

    def __init__(self, observation_space, per_light: int = LOCAL_DIM, code: int = 32, hidden: int = 256):
        super().__init__(observation_space, features_dim=hidden)
        self.n, self.per = observation_space.shape[0] // per_light, per_light
        self.sub = torch.nn.Sequential(torch.nn.Linear(per_light, 64), torch.nn.ReLU(),
                                       torch.nn.Linear(64, code), torch.nn.ReLU())
        self.main = torch.nn.Sequential(torch.nn.Linear(self.n * code, hidden), torch.nn.ReLU())

    def forward(self, obs):
        b = obs.shape[0]
        codes = self.sub(obs.view(b * self.n, self.per)).view(b, -1)
        return self.main(codes)


def make_env(strategy: str, **kw):
    if strategy == "central":
        return CentralEnv(**kw)
    return PerLightEnv(strategy, **kw)
