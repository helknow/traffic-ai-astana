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

Training and evaluation are running; the verdict and every metric land here when they finish.
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
pytest                                    # 42 tests: map, transitions, shield, events, envs
python dashboard/server.py                # race board on http://localhost:8790
python train.py --strategy central --algo ppo --sim-hours 400
./train_all.sh                            # all strategies × algorithms (~5 h on 20 cores)
python evaluate.py                        # 4 seasons × 4 times of day × 3 days, writes results/
python map/build_map.py                   # rebuild the map from OpenStreetMap
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
