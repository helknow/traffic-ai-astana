# Traffic AI · Astana

Reinforcement-learning traffic lights for **12 real intersections in central Astana**, tested
across Astana's four seasons and sudden road events, with a live "race board" web page where up
to four controllers drive the same hour side by side.

It extends [traffic-ai](https://github.com/helknow/traffic-ai) (one invented town) to a real map
and compares **three ways to organise the agents**:

| Strategy | Who decides | What each light sees |
|---|---|---|
| **Independent agents** | every light on its own | only its own approaches |
| **Central brain + sub-agents** | a sub-agent at every light encodes its traffic and sends it to one main model, which sets all 12 lights | everything |
| **Neighbour-aware agents** | every light on its own | its own approaches + a short summary from its up-to-4 neighbours |

Each strategy is trained with **PPO, A2C and DQN** on the same simulated-time budget, and
compared with today's **fixed timers**, SUMO's **actuated** lights and a **max-pressure** rule.

<!-- RESULTS:START -->
## Results

**Live demo (recorded races + full results):** https://traffic-ai-astana.vercel.app

Every controller drove **48 one-hour tests** (4 seasons × 4 times of day × 3 days of traffic the
AI never trained on), with the same accidents, breakdowns, jaywalkers, ambulances and snowstorms
for every controller. All AIs were trained from zero on the final, corrected map. Averages over
all 48:

| Controller | Time lost /veh | Waiting /veh | Travel time | Queue | Throughput /h | Teleports | Hidden queue | Longest standstill | Pedestrian loss | CO₂ (kg) | Ambulance crossing | vs fixed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Neighbour-aware · PPO** | **108.5 s** | 49.0 s | **208.6 s** | 30.0 | 2 398 | **0.3** | 91.8 | **182 s** | 98.1 s | **1 476** | **137 s** | **−52 %** |
| Independent · PPO | 108.9 s | **48.1 s** | 208.9 s | **29.7** | **2 402** | 0.4 | 88.0 | 209 s | 98.6 s | 1 480 | 148 s | −52 % |
| Central brain · PPO | 146.5 s | 79.6 s | 245.4 s | 44.7 | 2 310 | 1.3 | 118.3 | 215 s | 106.1 s | 1 624 | 206 s | −36 % |
| Central brain · PPO · 4× training | 162.6 s | 93.9 s | 261.3 s | 47.9 | 2 265 | 0.5 | 141.4 | 222 s | 109.0 s | 1 683 | 179 s | −29 % |
| Max-pressure (classic, no learning) | 137.9 s | 64.8 s | 236.6 s | 41.2 | 2 335 | 1.2 | **83.8** | 243 s | **96.9 s** | 1 617 | 172 s | −39 % |
| Actuated (SUMO) | 154.6 s | 79.8 s | 252.2 s | 55.6 | 2 324 | 0.8 | 94.4 | 211 s | 105.3 s | 1 682 | 155 s | −32 % |
| Fixed timer (Astana today) | 227.7 s | 138.9 s | 322.7 s | 94.1 | 2 182 | 2.4 | 120.5 | 233 s | 102.4 s | 1 956 | 222 s | – |

Throughput equals arrived vehicles per hour (one hour per test). All 15 controllers, including A2C,
DQN and shield-off runs, are in `results/summary.csv` and on the Results page.

**Time lost per vehicle by season** (best run of each strategy):

| | Winter | Spring | Summer | Autumn |
|---|---|---|---|---|
| Neighbour-aware · PPO | 149 s | **95 s** | 87 s | **103 s** |
| Independent · PPO | **139 s** | 97 s | **86 s** | 114 s |
| Central brain · PPO | 226 s | 120 s | 104 s | 136 s |
| Max-pressure | 187 s | 123 s | 105 s | 137 s |
| Fixed timer | 263 s | 223 s | 174 s | 251 s |

### Verdict: which strategy is better?

1. **Per-light agents win; strategies 1 and 3 tie for first place.** Neighbour-aware agents lose
   108.5 s per vehicle and independent agents 108.9 s (0.4 % apart), both **52 % less** than
   today's fixed timers. Throughput goes up 10 %, CO₂ down 24–25 % and ambulances get through
   33–38 % faster. Neighbour-aware agents win 10 of the 16 season × time-of-day scenarios against
   independent agents (6). They also keep the longest standstill lower (182 s vs 209 s). On this
   12-light grid, hearing the neighbours buys a little; keep that variant for a bigger network,
   where green waves along long avenues matter more.
2. **Strategy 2, the central brain with sub-agents, is clearly worse:** 35 % more delay than the
   winners. Independent agents beat it in **15 of 16** scenarios and neighbour-aware agents in
   **all 16**. It even does **6 % worse than the classic max-pressure rule**, which needs no
   training at all. **More data does not fix it:** with 4× the training it got 163 s instead of
   146 s. The problem is the design: one model has to choose 4¹² ≈ 16.8 million joint actions
   from one shared reward, so it cannot tell which light's choice helped. Each per-light agent
   gets its own reward and 12× more examples per decision.
3. **The central brain is also unstable between trainings.** Trained twice with the same setup
   (before and after the last map fixes), the per-light agents moved by about 1 s (independent
   108.6 → 108.9 s, neighbour 109.8 → 108.5 s). The central brain moved by 9–23 s (137 → 146 s,
   4× training 140 → 163 s).
4. **PPO is the best algorithm** for every strategy (independent: PPO 109 s, A2C 112 s,
   DQN 123 s; neighbour: PPO 109 s, A2C 118 s, DQN 121 s). DQN cannot run the central brain at all.

### What are we losing?

- **Coordination:** per-light agents do not plan long green waves. The neighbour-aware test shows
  this costs almost nothing here; re-check it on a larger map.
- **Pedestrians and entry fairness, a little:** max-pressure keeps pedestrians ~1–2 s faster and
  lets a few more cars into the map per hour (hidden queue 84 vs 88–92). The RL reward could weigh
  pedestrians and entry queues more if the akimat cares about these.
- **The shield costs almost no speed and buys safety:** switched off, independent agents lose
  112 s instead of 109 s and neighbour-aware agents 107 s instead of 109 s. In both cases the
  longest standstill at a red grows by more than a minute (209 → 300 s, 182 → 253 s). Without the
  shield the central brain collapses into gridlock (493 s lost, 56 teleports per hour). **Keep the
  shield.**
- **Honest limits:** the 90 s rule serves a waiting direction next, but the green still has to
  finish its minimum and change over, and two overdue directions can queue behind each other, so
  the worst single standstill is about 3 minutes, not 90 s. The seasons are assumptions until
  calibrated with Astana data.
<!-- RESULTS:END -->

## The map

Real OpenStreetMap data of the centre (`map/build_map.py`, bounding box 71.415–71.445 E,
51.158–51.178 N), cut to the core of 12 signalised junctions:

|            | Beibitshilik | Auezov | Respublika |
|---|---|---|---|
| **Abay**       | J01 | J02 | J03 |
| **Seifullin**  | J04 | J05 | J06 |
| **Zhangeldin** | J07 | J08 | J09 |
| **Bogenbay**   | J10 | J11 | J12 |

Real lanes and turn connections, protected left turns on Respublika, 73 crosswalks with
sidewalks and pedestrians. Map data © OpenStreetMap contributors, ODbL
(`map/osm/astana_bbox.osm.xml`).

## Seasons (modelling assumptions)

Season changes how people drive, how many walk, and how often things go wrong
(`demand/seasons.py`). **These numbers are assumptions from winter-driving studies, not Astana
measurements; calibrate them with police accident statistics and real counts before a pilot.**

| | Winter (Nov–Mar) | Spring (Apr–May) | Summer (Jun–Aug) | Autumn (Sep–Oct) |
|---|---|---|---|---|
| Desired speed (× limit) | 0.75 | 0.90 | 1.02 | 0.92 |
| Comfortable braking (m/s²) | 2.8 | 3.8 | 4.5 | 4.0 |
| Time gap kept (s) | 1.8 | 1.4 | 1.2 | 1.4 |
| Traffic volume | ×1.05 | ×1.00 | ×0.90 | ×1.05 |
| People walking | ×0.55 | ×0.90 | ×1.40 | ×1.00 |
| Accidents & breakdowns | ×2.5 | ×1.3 | ×1.0 | ×1.5 |
| People running across | ×0.5 | ×1.0 | ×1.6 | ×1.0 |
| Speeders | 1.5 % | 3 % | 5 % | 3 % |
| Impaired drivers | 0.6 % | 0.5 % | 0.7 % | 0.5 % |

Four times of day: morning rush (3 600 veh/h), midday (2 500), evening rush (3 800), night (700,
4× the impaired drivers).

## Sudden events

Seeded and identical for every controller (`env/events.py`): **accident** (lane blocked),
**breakdown**, **person running across the road**, **impaired driver** (erratic, may run a red),
**speeders** pushing through the end of yellow, **ambulance** (drives through reds; its crossing
time is measured), **snowstorm** (winter: everybody slows down), **road works** (summer: a lane
closed). Crashes caused by speeders or impaired drivers become real accidents that block a lane.

## The reward

Your partner's formula, per light and every 5 s decision:

    r = −(α·Q + β·W + γ·D + δ·P) / 20  −  teleport and hidden-queue penalties
    α = 1, β = 0.1, γ = 0.1 (as given), δ = 0.5 (added)

Q = cars queued, W = minutes the queued cars have been waiting, D = delayed cars, P = people
waiting at crosswalks. **What we changed and why:**

1. **"Accumulated" waiting** only grows from the start of the hour, so the reward drifts with the
   clock rather than with the lights' choices. W is the waiting of the cars standing at the light
   *now* (SUMO's waiting memory raised to 1000 s so long waits stay visible).
2. **Units out of balance:** in seconds, β·W still outweighed α·Q about 3 to 1 in rush hour. W is
   in minutes and the total is scaled by 1/20 so PPO gets rewards in a sane range.
3. **Gridlock looked like success:** when SUMO teleports a stuck car it leaves the queue. Each
   teleport is now a penalty and a reported metric.
4. **Cars that never got in:** blocking the map's entrances shrinks the queue while cars pile up
   outside. That hidden queue is penalised and reported.
5. **Pedestrians were missing:** δ·P added; the safety shield keeps them from being starved.
6. **D ≈ Q** and **throughput = arrived vehicles** over a fixed hour: kept, but they carry almost
   no extra information.
7. **Fair budget:** every strategy gets the same simulated hours. The central brain collects one
   sample per decision against twelve for per-light agents, so it is also trained with 4× the
   budget (`central_ppo_long`) to see whether it only needs more data.
8. **DQN cannot run the central brain:** it would have to score 4¹² ≈ 16.8 million joint actions,
   so DQN runs for the per-light strategies only.

### Bugs found and fixed in the simulator

- The "fixed timer" baseline was secretly SUMO's actuated plan (SUMO activates the last-loaded
  program). Fixed by forcing program 0; there is a test for it.
- Speeders with a 0.8 s headway (below the 1 s step) crashed into each other and were teleported.
- Parallel training workers raced on the same traffic file; files are now written atomically.
- Crashed cars counted as "waiting", which pulled the 90 s rule toward blocked roads.
- SUMO's ambulance *bluelight* device crashed the simulator natively mid-training. Removed;
  ambulances still drive through reds. Dead workers now restart automatically.
- **Found in the first evaluation:** cars stood 5–7 minutes at J07 even on green. The OSM import
  had made Zhangeldin give way to a 45 m unnamed slip road 8 m past the light, so the light's exit
  kept freezing. `map/fix_priorities.py` gives the main street right of way at the two such spots
  (traffic-light programs unchanged, guarded by a test). The learned controllers lost 4–14 s less
  per vehicle afterwards; the fixed timers barely changed.
- Cars stuck behind a broken-down car counted as waiting for the light, sending the 90 s rule's
  green to a lane nobody could drive on. They no longer count.
- After both fixes **every AI was trained again from zero** on the corrected map (12 runs, about
  4.5 hours) and everything was evaluated again. The numbers above are from these models.

## Safety shield (toggle)

Hard rules the AI cannot break (`env/shield.py`): 7 s minimum green, pedestrian clearance 5 s,
yellow 3 s, all-red 2 s, green only where someone is waiting, nobody waits more than **90 s** at a
red, a **4-minute backstop** that serves every direction even when cameras see nobody, and a
fixed-time fallback when cameras fail. Switch it off (`--no-shield`, or the switch on the page) to
see what the raw RL does; minimum green and clearance always stay.

## Metrics

Average waiting time, average travel time, average queue, throughput, arrived vehicles, time lost,
teleports (your partner's list), plus hidden queue, longest standstill at a red, pedestrian time
lost, CO₂ and ambulance crossing time.

## Run it

Python 3.11; SUMO comes from `pip install eclipse-sumo`.

```bash
pip install -r requirements.txt
pytest                                    # 43 tests: map, transitions, shield, events, envs
python dashboard/server.py                # race board on http://localhost:8790
python train.py --strategy central --algo ppo --sim-hours 400
./train_all.sh                            # all strategies × algorithms (~5 h on 20 cores)
python evaluate.py                        # 4 seasons × 4 times of day × 3 days, writes results/
python map/build_map.py && python map/fix_priorities.py   # rebuild the map from OpenStreetMap
python dashboard/export_static.py         # recorded races + results for a static host (site/)
```

## Layout

```
map/        OSM import, 12-light net, actuated programs, walk routes
demand/     seasons, traffic and pedestrian generation
env/        simulator core, lights, shield, events, the three strategies
train.py    PPO / A2C / DQN for any strategy        evaluate.py, analysis.py   metrics + verdict
dashboard/  FastAPI + WebSocket server and the race-board page
results/    trained models, summary.json, analysis.json
```
