"""Astana's four seasons, as they change driving.

These numbers are modelling assumptions, not measurements. They are set from typical winter-driving
studies (longer headways, softer braking on snow and ice, slower free speed) and should be
calibrated with Astana police accident statistics and real traffic counts before any pilot.

Per season:
  speed       - drivers' desired speed as a share of the limit (snow/ice: slower)
  decel       - comfortable braking in m/s^2 (ice: much softer)
  tau         - time headway drivers keep, seconds (ice: larger gaps)
  min_gap     - standstill gap, metres
  sigma       - driver imperfection 0..1 (bad visibility: higher)
  demand      - traffic volume multiplier
  peds        - pedestrian volume multiplier (-30 C keeps people indoors)
  ped_speed   - walking speed m/s (snow and ice: slower)
  incident    - multiplier on accidents and breakdowns
  jaywalk     - multiplier on people running across the road
  speeders    - share of speeding drivers
  impaired    - share of impaired (drunk/high) drivers
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Season:
    name: str
    title: str
    months: str
    speed: float
    decel: float
    tau: float
    min_gap: float
    sigma: float
    demand: float
    peds: float
    ped_speed: float
    incident: float
    jaywalk: float
    speeders: float
    impaired: float
    note: str


SEASONS = {
    "winter": Season("winter", "Winter", "Nov–Mar", speed=0.75, decel=2.8, tau=1.8, min_gap=3.5,
                     sigma=0.6, demand=1.05, peds=0.55, ped_speed=1.05, incident=2.5, jaywalk=0.5,
                     speeders=0.015, impaired=0.006,
                     note="Snow and ice down to −40 °C: slower, softer braking, longer gaps, "
                          "2.5× the crashes, fewer people walking, snowstorms"),
    "spring": Season("spring", "Spring", "Apr–May", speed=0.9, decel=3.8, tau=1.4, min_gap=2.8,
                     sigma=0.5, demand=1.0, peds=0.9, ped_speed=1.25, incident=1.3, jaywalk=1.0,
                     speeders=0.03, impaired=0.005,
                     note="Melting snow, slush and potholes: a bit slower, more crashes than summer"),
    "summer": Season("summer", "Summer", "Jun–Aug", speed=1.02, decel=4.5, tau=1.2, min_gap=2.5,
                     sigma=0.5, demand=0.9, peds=1.4, ped_speed=1.35, incident=1.0, jaywalk=1.6,
                     speeders=0.05, impaired=0.007,
                     note="Dry roads: fastest flow, most speeders and walkers, road works, "
                          "fewer cars (holidays)"),
    "autumn": Season("autumn", "Autumn", "Sep–Oct", speed=0.92, decel=4.0, tau=1.4, min_gap=2.8,
                     sigma=0.55, demand=1.05, peds=1.0, ped_speed=1.25, incident=1.5, jaywalk=1.0,
                     speeders=0.03, impaired=0.005,
                     note="Rain and early darkness, back-to-school traffic: more crashes, "
                          "heavier rush hours"),
}
