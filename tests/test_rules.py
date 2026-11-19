"""Fast tests: map, signal transitions, safety shield, traffic files. No long simulations."""
from __future__ import annotations

import re

import pytest

from demand.generate import write_routes
from env.shield import PhaseDemand, Shield, ShieldConfig
from env.tls import MAX_PHASES, load

LIGHTS = list(load().values())
GREEN = set("Gg")


def test_twelve_named_lights():
    assert len(LIGHTS) == 12
    assert [L.short for L in LIGHTS] == [f"J{k:02d}" for k in range(1, 13)]
    assert all(" × " in L.name for L in LIGHTS)


@pytest.mark.parametrize("L", LIGHTS, ids=lambda L: L.short)
def test_phases_and_crosswalks(L):
    assert 2 <= len(L.phases) <= MAX_PHASES
    assert all(p.lanes for p in L.phases)
    # both ends of every crosswalk are watched (a crosswalk is used both ways)
    assert all(len(ends) == 2 for ends in L.crossing_wait.values()), L.crossing_wait


@pytest.mark.parametrize("L", LIGHTS, ids=lambda L: L.short)
def test_transitions_only_take_green_away(L):
    """Between two phases a light may only switch greens off (clearance, yellow, all-red), never on."""
    for i in range(len(L.phases)):
        for j in range(len(L.phases)):
            if i == j:
                continue
            a = L.phases[i].state
            stages = L.transition(i, j)
            assert stages[-1][0] == "all_red"
            for _, st in stages:
                assert len(st) == L.n_links
                for k, ch in enumerate(st):
                    if ch in GREEN:
                        assert a[k] in GREEN, (L.short, i, j, k)
            # every vehicle link that loses its green shows yellow first
            names = [n for n, _ in stages]
            lost = [k for k in range(L.n_links) if L.link_kind[k] == "veh" and a[k] in GREEN
                    and L.phases[j].state[k] not in GREEN]
            if lost:
                y = dict(stages)["yellow"]
                assert all(y[k] == "y" for k in lost)
            # walk ends before cars get yellow
            if "ped_clear" in names:
                assert names.index("ped_clear") < names.index("all_red")


def demand(n=3, **kw):
    out = [PhaseDemand() for _ in range(n)]
    for k, v in kw.items():
        out[int(k[1:])] = v
    return out


def test_min_green_holds():
    d = Shield(ShieldConfig()).decide(0, 3.0, 0.0, [0, 10, 10], demand(p1=PhaseDemand(vehicles=9, queued=9)), True, 1)
    assert d.next_phase is None and d.reason == "min_green"


def test_rest_in_green_when_nobody_waits_elsewhere():
    d = Shield(ShieldConfig()).decide(0, 500.0, 0.0, [0, 100, 100], demand(p0=PhaseDemand(vehicles=30)), True, 1)
    assert d.next_phase is None


def test_ai_cannot_give_green_to_empty_road():
    d = Shield(ShieldConfig()).decide(0, 30.0, 0.0, [0, 30, 30],
                                      demand(p0=PhaseDemand(vehicles=20), p2=PhaseDemand(vehicles=2)), True, 1)
    assert d.next_phase != 1


def test_ninety_second_cap():
    d = Shield(ShieldConfig()).decide(0, 30.0, 0.0, [0, 95, 20],
                                      demand(p0=PhaseDemand(vehicles=40), p1=PhaseDemand(vehicles=1, max_wait=95)), True, None)
    assert d.next_phase == 1 and d.reason == "max_red_cap"


def test_four_minute_backstop_even_when_cameras_see_nobody():
    d = Shield(ShieldConfig()).decide(0, 300.0, 0.0, [0, 250, 30], demand(p0=PhaseDemand(vehicles=40)), True, None)
    assert d.next_phase == 1 and d.reason == "backstop_4min"


def test_sensor_fallback_cycles():
    d = Shield(ShieldConfig()).decide(0, 31.0, 0.0, [0, 30, 30], demand(), False, None)
    assert d.next_phase == 1 and d.reason == "sensor_fallback"


def test_shield_off_obeys_the_ai_but_keeps_min_green():
    sh = Shield(ShieldConfig(enabled=False))
    assert sh.decide(0, 3.0, 0.0, [0, 0, 0], demand(), True, 2).next_phase is None
    assert sh.decide(0, 10.0, 0.0, [0, 0, 0], demand(), True, 2).next_phase == 2


def test_padded_action_slot_means_keep():
    d = Shield(ShieldConfig()).decide(0, 30.0, 0.0, [0, 10], demand(2, p1=PhaseDemand(vehicles=3)), True, 3)
    assert d.reason != "ai"


def test_routes_are_identical_for_every_controller(tmp_path):
    a = write_routes("midday", "winter", 7).read_text()
    b = write_routes("midday", "winter", 7).read_text()
    assert a == b
    assert "<personFlow" in a and 'type="speeder"' in a and 'type="impaired"' in a


def test_speeders_keep_a_physically_possible_headway():
    """tau below the 1 s step made speeders crash into each other and get teleported."""
    txt = write_routes("evening_rush", "summer", 3).read_text()
    tau = float(re.search(r'<vType id="speeder"[^>]*tau="([0-9.]+)"', txt).group(1))
    assert tau >= 1.0


def test_no_bluelight_device():
    """SUMO's bluelight device crashed the simulator natively during training."""
    assert "bluelight" not in write_routes("night", "winter", 18).read_text()
