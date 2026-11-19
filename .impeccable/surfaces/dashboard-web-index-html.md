---
version: 1
slug: "dashboard-web-index-html"
primary_target: "dashboard/web/index.html"
related_targets: []
---

# Surface: Astana strategy bench (dashboard/web/index.html)

Mode: Operate. Audience: the two-person team choosing an RL strategy; later the defence and the akimat.
Job: see which controller is ahead on identical traffic, stress them with sudden events, read the full verdict.
Constraints: plain HTML/CSS/JS, FastAPI + WebSocket, canvas map of 12 real lights; every number from the simulator.

## Direction contract

THESIS: The bench is a departures board for traffic-light strategies: up to four controllers drive the same Astana hour and a board re-ranks them live by time lost. It refuses the category default of two static maps over a KPI strip.

OWN-WORLD: the incumbent midnight system (void / carbon / obsidian ladder, 1px inset rings, Inter 400/510/590, JetBrains Mono for ids, clock and ranks, lime only on Run). New, documented: a strategy palette for boards and charts only (independent periwinkle #8b9cff, central orchid #d58cff, neighbour mint #6fd3a8; baselines in greys) and event markers in coral on the map.

STORY: In seconds the team sees who leads; they throw an accident or a snowstorm at all controllers at once and watch the ranks move; they click a row to watch that controller's streets; Results gives every metric, season by season, and a written verdict with costs.

FIRST VIEWPORT: 52px bar (brand, Race / Results tabs, season, time of day, shield switch, speed, lime Run). Left column ~600px: clock and scenario line, the race board (rank, controller, time lost, queue, throughput, hidden queue), controller picker, six event buttons, event log. Right: the selected row's live map of the 12 lights, filling the height, with a light-detail strip.

FORM: race board from the boarding-pass-and-gate-board challenger (won its place on audience fit and clarity). Signature move: rows re-rank in place (FLIP, identity kept) and a row that moved holds a lit state for 4 s. seed:e3e041577b8facf2

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
