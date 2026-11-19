---
name: Traffic AI
description: A midnight control room for an AI that runs traffic lights, where every light change shows its reason.
colors:
  void: "#08090a"
  carbon: "#0f1011"
  obsidian: "#161718"
  raised: "#1c1d1f"
  line: "#23252a"
  line-hi: "#383b3f"
  paper: "#ffffff"
  bone: "#e5e5e6"
  mist: "#d0d6e0"
  fog: "#8a8f98"
  ash: "#62666d"
  slate: "#4a4e55"
  lime: "#e4f222"
  lime-hover: "#eef75a"
  lime-active: "#cfdc1c"
  iris: "#6366f1"
  iris-soft: "#a5a7ff"
  lavender: "#8b5cf6"
  coral: "#eb5757"
  coral-soft: "#ffb4b4"
  teal: "#02b8cc"
  signal-green: "#27a644"
  signal-amber: "#f2b33d"
  signal-red: "#ff3b2f"
typography:
  headline:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "24px"
    fontWeight: 510
    lineHeight: 1.5
    letterSpacing: "-0.02em"
    fontFeature: "\"cv01\" on, \"ss03\" on, \"zero\" on"
  title-lg:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 590
    lineHeight: 1.25
    letterSpacing: "-0.018em"
  title:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 590
    lineHeight: 1.5
    letterSpacing: "-0.011em"
  metric:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 510
    lineHeight: 1.25
    letterSpacing: "-0.02em"
    fontFeature: "\"tnum\" on"
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
    fontFeature: "\"cv01\" on, \"ss03\" on, \"zero\" on"
  label:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.3
    letterSpacing: "normal"
  mono-display:
    fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "20px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "-0.03em"
    fontFeature: "\"tnum\" on"
  mono:
    fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "-0.013em"
    fontFeature: "\"tnum\" on"
rounded:
  hair: "2px"
  xs: "4px"
  sm: "6px"
  md: "8px"
  lg: "12px"
  pill: "9999px"
spacing:
  "2xs": "4px"
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  "2xl": "32px"
components:
  button-primary:
    backgroundColor: "{colors.lime}"
    textColor: "{colors.void}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "32px"
  button-primary-hover:
    backgroundColor: "{colors.lime-hover}"
  button-primary-active:
    backgroundColor: "{colors.lime-active}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.mist}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "0 12px"
    height: "32px"
  button-ghost-tiny:
    textColor: "{colors.mist}"
    rounded: "{rounded.sm}"
    padding: "0 8px"
    height: "24px"
  tab:
    backgroundColor: "transparent"
    textColor: "{colors.fog}"
    rounded: "{rounded.sm}"
    padding: "6px 10px"
  tab-selected:
    textColor: "{colors.paper}"
  segmented-option-selected:
    backgroundColor: "{colors.obsidian}"
    textColor: "{colors.paper}"
    rounded: "{rounded.sm}"
    height: "28px"
  select:
    textColor: "{colors.mist}"
    rounded: "{rounded.sm}"
    padding: "0 30px 0 12px"
    height: "32px"
  pane:
    backgroundColor: "{colors.carbon}"
    rounded: "{rounded.lg}"
  card:
    backgroundColor: "{colors.carbon}"
    rounded: "{rounded.lg}"
    padding: "20px"
  status-pill:
    textColor: "{colors.fog}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "1px 8px"
  status-pill-bad:
    textColor: "{colors.coral-soft}"
    rounded: "{rounded.pill}"
  phase-ribbon:
    backgroundColor: "{colors.void}"
    rounded: "{rounded.xs}"
    height: "26px"
  toast:
    backgroundColor: "{colors.obsidian}"
    textColor: "{colors.mist}"
    rounded: "{rounded.md}"
    padding: "9px 14px"
---

# Design System: Traffic AI

## Overview

**Creative North Star: "The Midnight Signal Box"**

A precision instrument at night. The world comes from the user-pinned visual reference, Refero's write-up of Linear's style ("midnight precision instrument"): its near-black canvas, hairline rings, three-weight Inter and tight numeric tracking are adopted as a style; nothing of Linear's brand (name, mark, product colours as identity) is carried. Here the instrument watches a town: the map and each junction's reasoning are the content, and every surface around them recedes into graded near-blacks so that the few saturated hues on screen always mean something.

Density is high and calm: 13px body, 11px labels, tabular numerals everywhere numbers live, hairlines instead of boxes. Colour is a vocabulary, not a mood. Lime is the one action. Iris, lavender and coral name why a light went green. Red, amber and green are reserved for the state of a real light. Everything else is a grey.

**Key Characteristics:**
- Graded near-black surfaces (void, carbon, obsidian, raised) separated by 1px inset rings, not borders or shadows.
- One lime primary action per screen.
- A reason palette (iris, lavender, coral, slate, hatch) that encodes the safety shield's decisions.
- Signal colours treated as data: they appear only where a light's state is shown.
- Inter at 400 / 510 / 590 with negative tracking on numbers; JetBrains Mono for IDs, timers and phase names.
- Line icons at 16px, 1.6 stroke, round caps.

## Colors

A grey ladder from void to paper, plus a small set of hues each with one job.

### Primary
- **Run Lime** (lime): the single primary action (Run / Restart) and the word "Run" when copy refers to that button. Nothing else is lime. Hover lightens to lime-hover, press darkens to lime-active.

### Secondary
- **Shield Iris** (iris): the AI. Dot before the AI pane title and AI row in results, AI-choice segments in phase ribbons, the AI series in charts, selected junction row tint (10%), the "best" underline in the results table, text selection (45%).
- **Gain Iris** (iris-soft): a metric where the AI beats the fixed timer. Losses are shown in fog, plainly, never hidden.

### Tertiary
- **Cap Lavender** (lavender): the 90-second max-red cap forcing a change.
- **Backstop Coral** (coral): the 4-minute backstop, sensor-fallback hatch, and fault state (a camera down, a blocked lane, the shield flash on the reason line). Coral means "the safety net acted or something broke".
- **Fault Pink** (coral-soft): text on coral-tinted fault surfaces (bad status pill, pressed block-lane button, broken camera state).
- **Walker Teal** (teal): pedestrians on the map and the pedestrian share of demand bars.

### Signal (data only)
- **Go Green** (signal-green), **Yellow Amber** (signal-amber), **Stop Red** (signal-red): the state of a real traffic light. On the map's stop lines and green-wave arcs, the junction table's phase dot, the active phase row (green tint), and the map legend. Stop Red is distinct from Backstop Coral on purpose: one is a light, the other is a reason.

### Neutral
- **Void** (void): page canvas, phase ribbon wells, empty-map veil (82%).
- **Carbon** (carbon): panels: top bar, rail, map panes, results cards.
- **Obsidian** (obsidian): lifted controls: selected segment, toast, select options, inline code.
- **Raised** (raised): reserved step above obsidian.
- **Line** (line): hairline rings and dividers, chart gridlines.
- **Line High** (line-hi): hover border, scrollbar thumb.
- **Paper** (paper): headings, metric values, selected states.
- **Bone** (bone): reserved bright secondary text.
- **Mist** (mist): body text, control labels, bus outline on the map.
- **Fog** (fog): secondary text, labels, axes, moving cars on the map.
- **Ash** (ash): fixed-timer dot, vans, lowest-emphasis text.
- **Slate** (slate): "empty road handed over" reason in ribbons.

### Named Rules
**The One Lime Rule.** Lime marks the one primary action on a surface. If two things are lime, one of them is wrong.

**The Reason Palette Rule.** Iris, lavender, coral, slate and the coral hatch encode why a phase was served. Never reuse them as decoration or category colour; a new reason gets a new, documented hue.

**The Signal Is Data Rule.** Red, amber and green appear only where a light's actual state is drawn. They are never status, success or error colours for UI.

## Typography

**Display Font:** none; the system has no display face. Headlines are Inter.
**Body Font:** Inter (with ui-sans-serif, system-ui, Segoe UI, Roboto)
**Label/Mono Font:** JetBrains Mono (with ui-monospace, SFMono-Regular, Menlo, Consolas)

**Character:** Inter with cv01, ss03 and slashed zero, set at the in-between weights 510 and 590 so hierarchy comes from small steps rather than bold jumps. Mono is for things a machine names: junction IDs, phase names, clocks, code.

### Hierarchy
- **Headline** (510, 24px, -0.02em): the results page title only.
- **Title Large** (590, 17px, -0.018em): selected junction name in the rail.
- **Metric** (510, 17px/1.25, -0.02em, tabular): live KPI values in pane heads; unit in 11px fog beside it.
- **Title** (590 for rail section heads, 510 for pane heads, 14px, -0.011em).
- **Body** (400, 13px/1.5): all running text and controls. Lede and empty-state copy step up to 14px, capped at 68ch / 46ch.
- **Label** (400, 11px/1.3, fog): KPI terms, table headers, ribbon row labels, legends. Sentence case, never uppercase.
- **Mono Display** (400, 20px, -0.03em): the simulation clock.
- **Mono** (400, 12px, -0.013em; 11 to 11.5px in tables): IDs, phase names, axis ticks. The map's junction labels are mono 11px, the ribbon segment labels mono 10px (500).

### Named Rules
**The Tabular Numbers Rule.** Every number that updates live is tabular and slightly tight. Numbers must not jitter as they tick.

**The No Shouting Rule.** No uppercase labels, no bold above 590. Hierarchy is weight 400 / 510 / 590 and colour paper / mist / fog.

## Layout

Full-height operating surface. A 52px sticky top bar, then a two-column grid: the map column (fluid) and a 372px rail that scrolls independently and sticks under the bar. The map column holds a head row (clock, layout switch, fit), the panes (two equal columns in split view, one column in AI-only or Fixed-only), and a one-line legend. Results is a centred column, max 1200px, padding 32px 24px 64px, with a full-width table card over a 1.25fr / 1fr chart grid.

Spacing runs on small steps: 4, 6, 8, 10, 12, 16, 20, 24, 32px. Inside panels it is 8 to 16px; between panes 10px; between results cards 12px.

Responsive: at 1100px the rail drops below the maps and the results grid stacks. At 760px the bar unsticks and wraps, the scenario select goes full width, panes stack at 340px minimum, and the interaction hint hides. Pane heads use a container query: under 500px the KPI row reflows to three columns.

## Elevation & Depth

Depth is tonal: void, carbon and obsidian are the layers, and a 1px inset ring (line colour) draws every container edge. Dividers are 1px box-shadow hairlines, not borders. Real shadows are rare and small.

### Shadow Vocabulary
- **Ring** (`box-shadow: rgb(35 37 42) 0 0 0 1px inset`): panes, cards, ghost buttons, segmented tracks, camera rows, ribbons.
- **Hairline divider** (`box-shadow: 0 1px 0 #23252a`, or `0 -1px 0` / `-1px 0 0`): bar bottom, pane heads, rail edge, table rows, stacked rail blocks.
- **Lime bevel** (`box-shadow: rgba(0,0,0,.08) 0 1px 1px inset, rgba(255,255,255,.35) 0 1px 0 inset`): the primary button only.
- **Segment lift** (`box-shadow: rgba(255,255,255,.04) 0 1px 0 inset, rgba(0,0,0,.4) 0 1px 2px`): the selected option in a segmented control.
- **Toast float** (`box-shadow: rgba(255,255,255,.04) 0 1px 0 inset, rgba(0,0,0,.6) 0 0 0 1px, rgba(0,0,0,.35) 0 8px 24px`): the toast, the only floating element.
- **Tinted ring** (`box-shadow: <hue at 28 to 60%> 0 0 0 1px inset` over a 8 to 14% fill of the same hue): state on a row or button (active phase green, fault coral).

### Named Rules
**The Ring Not Border Rule.** Container edges are 1px inset rings in line colour. The one real border in the system is the native select (1px white at 8%).

## Shapes

Small, consistent corners: 2px on swatches, demand bars and ribbon segments; 4px on ribbon wells and inline code; 6px on every control, row highlight and the focus outline; 8px on segmented tracks and the toast; 12px on panes and cards; pills only for status. Dots are 6px circles (run identity, phase state, warnings). The map is the one free-form surface: roads, junction polygons and crossings drawn on canvas with no rounding imposed.

## Components

### Buttons
Quiet, compact, 32px tall.
- **Shape:** gently rounded (6px).
- **Primary:** lime fill, void text, 510 weight, 14px side padding, lime bevel. Only Run.
- **Hover / Focus:** primary lightens; ghost gets a 4% white wash and paper text. Focus is a 1.5px mist outline, 2px offset, 6px radius. Transitions 150ms on colour, background, shadow.
- **Ghost:** transparent, mist text, 400 weight, inset ring. Icon-only variant is 32px square. Tiny variant (24px, 12px text, 13px icon) for camera actions. Pressed toggle turns coral-tinted with fault-pink text.
- **Disabled:** 40% opacity.

### Tabs and Segmented Controls
- **Tabs:** text-only, fog at rest, mist on hover with a 3% wash, paper with a 5% wash when selected.
- **Segmented:** 2px-padded track at 2% white with the ring; options 28px (24px small), fog; the selected option becomes an obsidian chip with the segment lift.

### Select
Native select restyled: 32px, 2% white fill, 1px white-8% border, line-hi on hover, a 14px chevron icon in fog.

### Cards / Containers
- **Corner Style:** 12px.
- **Background:** carbon on void.
- **Shadow Strategy:** ring only.
- **Internal Padding:** 20px for results cards; map panes have a 12px 14px head and a full-bleed canvas.

### Data Tables
Hairline-ruled, no zebra. Headers 11 to 11.5px fog, 400. Numbers right-aligned and tabular. Rows hover at 2.5% white; the selected row tints iris at 10%. In results the best value per column is paper 510 with a 2px iris underline.

### Status Pill
11px pill at 5% white, fog text. Fault state: coral at 14% with fault-pink text.

### Phase Ribbon (signature)
A per-junction five-minute timeline, one 26px canvas row per run (AI, Fixed), set in a void well with the ring and 4px radius. Each served green is a 2px-rounded segment coloured by the shield's reason (iris AI choice, lavender 90 s cap, coral 4-min backstop, coral hatch for sensor fallback, slate for empty road handed over; fixed cycles in a flat dark grey). Segments wide enough carry the phase name in white mono 10px. A mono axis (−5 min / now) and a legend of 9px swatches sit underneath.

### Reason Line
The sentence under the junction name explaining the current decision: fog text with the reason term in mist 510. When the shield takes over it flashes a coral wash and ring for 1.6s.

### Town Map
Canvas on a near-void ground: roads and junction plates in dark greys, sidewalks a step darker, bus lanes faintly violet-grey. Moving cars fog, waiting cars paper, vans ash, buses as hollow mist outlines, pedestrians teal dots. Stop lines carry the signal colours. Selected junction gets a thin white ring at 35%; junction labels are mono.

### Toast
Obsidian, 8px radius, mist 12.5px text, bottom centre, rises 12px and fades in over 200ms.

## Do's and Don'ts

### Do:
- **Do** keep every surface on the void / carbon / obsidian ladder and draw edges with the 1px ring.
- **Do** give lime to exactly one action per surface.
- **Do** colour phase and decision data with the reason palette and say what each hue means in a visible legend.
- **Do** set live numbers in tabular Inter 510 with negative tracking, units in 11px fog.
- **Do** use 16px line icons (1.6 stroke, round caps, currentColor) from the inline sprite.
- **Do** show where the AI loses in plain fog text, as visibly as its wins in iris-soft.
- **Do** use the cubic-bezier(.16, 1, .3, 1) ease and 150ms state transitions.

### Don't:
- **Don't** use red, amber or green for UI status, success or error; they belong to lights.
- **Don't** reuse iris, lavender or coral as category or decorative colour.
- **Don't** use gradients, except the coral sensor-fallback hatch, which is data.
- **Don't** introduce uppercase labels, small text above the headings, or weights above 590.
- **Don't** add drop shadows to panels or cards; depth is tonal.
- **Don't** carry Linear's name, logo or brand identity; the reference supplies the style only.
