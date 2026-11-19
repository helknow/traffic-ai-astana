"""End-to-end tests in short simulations (each in its own process: libsumo is one per process)."""
from __future__ import annotations

import multiprocessing as mp

import pytest


def _run(fn):
    with mp.get_context("spawn").Pool(1) as pool:
        return pool.apply(fn)


def _fixed_program():
    from env.core import AstanaSim
    sim = AstanaSim("midday", "summer", seed=1, duration=60, mode="fixed", events=False)
    sim.start()
    progs = {sim.conn.trafficlight.getProgram(L.id) for L in sim.lights}
    sim.close()
    sim = AstanaSim("midday", "summer", seed=1, duration=60, mode="actuated", events=False)
    sim.start()
    act = {sim.conn.trafficlight.getProgram(L.id) for L in sim.lights}
    sim.close()
    return progs, act


def test_fixed_timer_really_is_fixed():
    """SUMO activates the last loaded program; the fixed baseline must force program 0."""
    fixed, actuated = _run(_fixed_program)
    assert fixed == {"0"} and actuated == {"actuated"}


def _every_event():
    from env.core import AstanaSim
    sim = AstanaSim("evening_rush", "winter", seed=2, duration=900, mode="rl", events=False, random_faults=True)
    obs = sim.start()
    kinds = ["accident", "breakdown", "jaywalker", "impaired", "ambulance", "snowstorm", "roadworks"]
    rewards = []
    for k, kind in enumerate(kinds * 3):
        sim.events.trigger(kind, sim.t)
        obs, r, done = sim.step({i: k % 4 for i in obs})
        rewards += list(r.values())
    while not done:
        obs, r, done = sim.step({i: 0 for i in obs})
        rewards += list(r.values())
    counts = dict(sim.events.counts)
    # road works restore the lane permissions they took away
    ok = all(sim.conn.lane.getDisallowed(e.note) == e.vehicles for e in sim.events.log if e.kind == "roadworks" and e.done)
    frozen_waiting = [v for v in sim.events.frozen()]
    sim.close()
    return counts, rewards, ok, frozen_waiting


def test_every_event_runs_and_rewards_stay_sane():
    counts, rewards, restored, _ = _run(_every_event)
    assert {"accident", "jaywalker", "ambulance", "snowstorm"} <= set(counts)
    assert all(-10.0 <= r <= 0.0 for r in rewards)
    assert restored


def _identical_traffic():
    from env.core import AstanaSim
    out = []
    for mode in ("fixed", "max_pressure"):
        sim = AstanaSim("morning_rush", "autumn", seed=4, duration=60, mode=mode, events=True)
        sim.start()
        out.append((sim.events.queue and [(e.kind, round(e.t), e.edge) for e in sim.events.queue],
                    sorted(sim.conn.vehicle.getIDList())))
        sim.close()
    return out


def test_every_controller_gets_the_same_traffic_and_events():
    a, b = _run(_identical_traffic)
    assert a == b


@pytest.mark.parametrize("strategy", ["independent", "central", "neighbour"])
def test_strategy_envs_step(strategy):
    import numpy as np

    from env.strategies import make_env
    env = make_env(strategy, n_workers=1, duration=60)
    try:
        o = env.reset()
        assert np.isfinite(o).all()
        env.step_async(np.array([env.action_space.sample() for _ in range(env.num_envs)]))
        o, r, d, _ = env.step_wait()
        assert np.isfinite(o).all() and np.isfinite(r).all()
    finally:
        env.close()
