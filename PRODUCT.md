# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Plain HTML/CSS/JS, no build step. One static page served by a Python FastAPI server (`dashboard/server.py`), live data over a WebSocket, the real Astana street map drawn on `<canvas>` from the SUMO network.

## Users

The two-person team: a student and a professional-programmer partner. They use the dashboard to decide which reinforcement-learning strategy to build on: watch strategies run live on identical traffic, switch between them, throw sudden events at them (accidents, jaywalkers, impaired drivers, snowstorms), and read the full metric comparison. Later shown at the university defence and possibly to the Astana akimat, but the strategy decision comes first.

## Product Purpose

A research bench for traffic-light RL on 12 real signalised junctions in central Astana (Respublika, Abay, Auezov, Beibitshilik, Seifullin, Zhangeldin, Bogenbay), imported from OpenStreetMap into SUMO. Four Astana seasons change driving (snow and ice in winter), demand and accident rates. Three strategies are compared against conventional lights: independent agents (one per light, own traffic only), a central brain fed by sub-agents at every light, and neighbour-aware agents (the middle ground). Success means the team can say, with numbers, which strategy wins, where, and what each costs.

## Positioning

Learned control never has the last word by default: a safety shield (min green, 90 s cap on real waiting, 4-minute backstop, sensor fallback, demand-only switching) sits between every RL strategy and the lights, with a toggle to switch it off and see raw RL.

## Operating Context

- Runs locally: `python dashboard/server.py`, open `http://localhost:8790`.
- Two simulations side by side on the same traffic, same season, same sudden events; each side picks its controller (any strategy × algorithm, or fixed / actuated / max-pressure).
- Event buttons inject an accident, a jaywalker, an impaired driver, an ambulance, a snowstorm or road works into both sides at once.
- Results from `evaluate.py` + `analysis.py` (`results/summary.json`, `results/analysis.json`): every controller × 4 seasons × 4 times of day × 3 seeds, plus a written verdict.

## Capabilities and Constraints

- 12 traffic lights J01–J12 named by their streets ("Abay × Respublika"); 2–4 action phases each, protected lefts on Respublika.
- Terminology: light, phase, approach, strategy (independent / central / neighbour-aware), algorithm (PPO / A2C / DQN), shield, season, event, time loss, hidden queue (cars that cannot enter the map).
- Signal colours (red/amber/green) are data, not decoration. Event markers are data too.
- Every number comes from the simulator; nothing is estimated or invented. Season parameters are labelled as assumptions.

## Evidence on Hand

- Simulation and evaluation output produced by this repo (`results/`). OpenStreetMap street data (ODbL).
- No real Astana traffic counts, accident statistics or city partnerships yet. Do not imply any.

## Product Principles

1. Like for like: both sides always run identical traffic and identical events.
2. Honest verdicts: show where each strategy loses as plainly as where it wins, and what it costs.
3. Every light change is explainable: reason shown, shield visible.
4. The real city: street names, not node ids.

## Brand Commitments

Visual reference chosen by the user: the Refero entry for Linear's style ("midnight precision instrument"), copying its style but not its brand. Default palettes and gradients are not allowed. This project extends the design system of the first Traffic AI control room (DESIGN.md).
