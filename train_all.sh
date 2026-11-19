#!/usr/bin/env bash
# Train every strategy x algorithm with the same simulated-time budget (about 3 h on 20 cores).
PY=${PY:-python}
HOURS=${HOURS:-400}
mkdir -p results/logs
for algo in ppo a2c dqn; do
  for s in independent central neighbour; do
    [ "$algo" = dqn ] && [ "$s" = central ] && continue
    $PY train.py --strategy $s --algo $algo --sim-hours $HOURS > results/logs/${s}_${algo}.log 2>&1
  done
done
for s in independent central neighbour; do
  $PY train.py --strategy $s --algo ppo --sim-hours $HOURS --no-shield > results/logs/${s}_ppo_noshield.log 2>&1
done

# does the central brain catch up with 4x the data? (it gets 1 sample per decision, the others 12)
$PY train.py --strategy central --algo ppo --sim-hours $((HOURS * 4)) --tag long > results/logs/central_ppo_long.log 2>&1
echo done
