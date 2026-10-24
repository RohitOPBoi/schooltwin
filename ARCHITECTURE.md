# SchoolTwin: Architecture

## What you asked for, and where it lives

| You wanted | How it works | Where |
|---|---|---|
| Use the story as the base | The story file is split into **scenario input**, **reference history** and a hidden **answer key** | `schooltwin/story.py` |
| Give it randomness and an events overview | One JSON **overview**: seed, randomness, which story events to keep, events you add, random events, levers | `schooltwin/overview.py`, `config/overview.example.json` |
| Watch the model run like a time-lapse | The engine writes a **pack**; the **player** replays it: watch one day minute by minute, or time-lapse the whole term | `schooltwin/pack.py`, `player/` |
| Stop at any point and look | Pause anywhere. Click any dot or room: who, mood, **why**, where they have been today, who their friends are | `player/player.js` |
| Check students' mood and stats | A mood (0-100) for every student and staff member, with reasons; live "Now" panel; term trends | `schooltwin/mood.py` |
| Flag important events, rewind, go to that day/time | Flags on the timeline from the detector, incident register, AI decisions and **you**. Jump, step flag to flag, auto-pause at flags | `player/player.js` |

## The shape of it

```
 story JSON ─────────────┐
 (calendar, roster,      │          overview.json
  staff, cameras,        ▼          (seed, randomness, events, levers)
  hidden event causes)  [1] SCENARIO  ◄──────────┘
                           │
                           ▼
                      [2] ENGINE  (Python, no LLM inside, deterministic)
                           │   PLAN   the day's numbers   (anchor: from the story | generate: from hidden traits,
                           │                               weather, events, randomness)
                           │   PLAY   minute-by-minute movement on the 2D campus, counters, behaviour
                           │   CLOSE  mood, feedback, signals ─► DETECTOR ─► AI PRINCIPAL ─► finance
                           ▼
                      [3] PACK    meta.json · history.json · days/dNNNN.json   (plain files, ~5 MB gzipped)
                           │
              ┌────────────┴─────────────┐
              ▼                          ▼
        [4] PLAYER (browser)       [5] EVALUATOR
         play / pause / scrub        fidelity to the story,
         inspect / flags / trends    detector vs hidden causes
```

**Why a pack and a player instead of a live simulation in the page.** Rewinding, scrubbing and jumping to a flag have to be instant and exact. If the page re-simulated, every rewind would be a re-run. Instead the engine runs once and writes, for every person, a list of `[minute, place]` changes. The player finds anyone's place at any minute with one binary search. So "rewind to 08:35 on 12 Feb" is a lookup, and it shows exactly what happened.

**Why the engine is separate from the AI.** The engine is plain deterministic code. The AI principal reads its summaries and proposes actions; a person approves. Remove the AI and the school still runs.

## The two run modes (the key design decision)

| | **Anchor** | **Generate** |
|---|---|---|
| Who is in, who is late, teachers absent, money | read from the story, day by day | produced by the engine |
| Used for | the story as written, made watchable, with mood and minute-level movement on top | "what if": your events, randomness and levers |
| Hidden traits | used for mood and behaviour | also drive **attendance** |
| Levers (fees, teachers, support, buses) | ignored (it is the story) | applied |

**Forking** combines them. "Story up to day 90, then the engine takes over with a 10% fee rise" is a `patch` in the overview: `{"from_day": 90, "mode": "generate", "levers": {...}}`. Every day has its own random stream, so a change on day 91 cannot disturb days 1-90. That is why a fork is a fair comparison.

## The three layers of truth

| Layer | Who sees it | What it is |
|---|---|---|
| **Simulation truth** | the "Simulation" view | where every person actually is |
| **Counters** | the "Camera counters" view, and the detector | numbers from 19 aggregate counters: no faces, no identities. Most rooms have none |
| **Hidden causes** | **Author view only** | why each planted event happened; each person's hidden traits |

**Operator view** hides the third layer. A **redacted pack** (`--redact`) removes it from the files, for a truly blind demo. The detector reads only counters, daily numbers and operational signals, never incident text or causes, and is scored afterwards against the hidden events.

## A day inside the engine

1. **Plan.** Calendar and weather come from the story. Anchor mode takes attendance from the story; generate mode draws each student's attendance from their hidden propensity, today's weather and heat, and the events. Late arrivals, absent teachers, and which buses are held up are fixed here.
2. **Play.** From 07:10 to 15:00, minute by minute: arrival (bus bay, gate), prayer, 6 periods with lab sessions and a weekly teacher rota, break, lunch with a canteen queue that gives up past 14 minutes, washroom and library trips through the corridor, hidden areas that few students know about, staff patrols. Events fire at their own minute: a lab circuit trips, a class moves rooms, visitors arrive.
3. **Close.** Moods settle, a survey sample is drawn from them, operational signals are collected, the detector runs, the AI principal proposes, money is booked.

## Mood

A 0-100 tendency for each person: a baseline (temperament, academics, attendance habits, rule trouble) plus a slow personal drift, pulled each morning toward a target made from the day: weather, heat, assessments, uncovered lessons, whether friends are in. During the day it moves: canteen waits, crowds, being late, being caught, time outdoors, events. **Every nudge is recorded under a reason**, so the inspector answers "why is Vihaan low today?". It is a synthetic tendency, not a measurement or a diagnosis, and is labelled that way.

## Flags

| Kind | Source | Who sees it |
|---|---|---|
| alert | detector rules over counters and signals | everyone |
| incident | the school's incident register (what happened, not why) | everyone |
| decision | AI principal proposals and approvals | everyone |
| calendar | breaks and closures | everyone |
| **you** | the ⚑ button, saved in your browser (and the run folder when served) | you |
| event | hidden causes of planted events | **Author view** |

The player can pause automatically whenever playback crosses a flag. Alerts say *look here*, not *why*; some are false alarms, as in the story.

## Files

```
story/                       the story JSON (11 MB)
config/                      school.yaml (bell schedule) · map.yaml (campus) · behavior.yaml (every behaviour number)
                             overview.example.json · overview.whatif.json
schooltwin/story.py          load and index the story           events.py     23 event templates, one vocabulary
schooltwin/world.py          zones and counters                 mood.py       mood model and reasons
schooltwin/agents.py         people from the roster             detect.py     rule-based detector (counters only)
schooltwin/engine.py         plan / play / close                decide.py     AI principal (proposes; people approve)
schooltwin/finance.py        ledger (story) or model            pack.py       writes the playback pack
schooltwin/overview.py       the overview and forking           evaluate.py   fidelity and detection scores
schooltwin/extension_calendar.py  CBSE calendar for Days 151+   control_run.py content-addressed control run generator
schooltwin/snapshots.py      bit-for-bit state snapshot cache   spatial_incidents.py spatial deviation & progression
schooltwin/report.py         evidence-based impact report gen   report_narrative.py grounded narrative post-validator
schooltwin/baseline_manifest.py SHA-256 baseline protection     checkpoints.py pack-derived baseline checkpoints
player/                      index.html · player.js · player.css (no dependencies, works offline)
scripts/run_story.py         run and write a pack               serve.py      local server + scenario runner
tests/                       Python pytest suites (69 tests)    test_player.js (simulated browser in jsdom)
pack/                        story_baseline/ · whatif_fee_up_apr/   (ready to play)
```

## Core Architecture Systems

### 1. Foundation & Baseline Immutability
- `pack/story_baseline/MANIFEST.sha256`: SHA-256 cryptographic manifest verified before runs, on server startup, and in test suites. The server unconditionally refuses write operations targeting the baseline directory.
- `schooltwin/checkpoints.py`: Derived dynamically from `meta.json` records (eliminating typed/fabricated balances).
- `schooltwin/compare.py`: Strict date-based and day-index alignment across runs, replacing fabricated fallback constants with explicit `not_modeled` or `unavailable` statuses.

### 2. Timeline Branching & Duration
- Scenarios start by default on **Day 151 (Monday 1 June 2026)** without re-simulating Days 0–150.
- Instant branch resumption powered by serialized end-of-baseline state snapshots (`schooltwin/snapshots.py`).
- Transparent Extension Calendar (`schooltwin/extension_calendar.py`) explicitly labelling CBSE summer break and assumed reopening dates (default `2026-07-01`).
- Content-addressed control continuation (`schooltwin/control_run.py`) providing an unperturbed baseline partner (`ctrl_<hash>`) over the scenario window.

### 3. Spatial Incident Visualization
- Derives affected areas dynamically by comparing minute-by-minute zone occupancy deviation against the control run.
- Classifies zones into exclusive roles: `origin`, `directly_affected`, `secondary`.
- Produces 6-phase progression timeline: `onset`, `escalation`, `response`, `containment`, `resolution`, `aftermath`.
- Enforces honest location reporting: unconfigured origins render an explicit warning banner with zero guessed markers.

### 4. Interactive Evidence-Based Impact Report
- `report.json`: Deterministically computed deltas with complete formulas, source files, and JSON paths.
- Strict narrative post-validator (`schooltwin/report_narrative.py`): Rejects any hallucinated numbers not present in the facts payload and uncited causal claims, falling back to an offline deterministic template.
- Simulates counterfactual intervention branches for policy levers.

### 5. Cockpit & Player Controls
- Quiet-instrument digital twin cockpit (design system v7): tonal dark surfaces (`#0E1014` → `#171C23` → `#202630`), meaning colours with shape partners (see `docs/design-system.md`), and tabular numerals (`font-variant-numeric: tabular-nums`).
- 6-step workflow rail: `Replay` · `Create` · `Run` · `Explore` · `Report` · `Compare`.
- Signature motion engine: Linear interpolation agent gliding (eliminating teleportation), concentric origin reticle pulsing, animated spread ripple, and easing camera pans.
- In-app Motion settings: `Full` / `Reduced` / `Off` respecting `prefers-reduced-motion` and persisting locally.

## Storage

Plain JSON files, no database. A pack is about 27 MB raw and 5 MB gzipped, and static hosting serves it as is. A database becomes worthwhile only when many visitors must save their own scenarios online; then use a free Postgres tier for runs and flags, and keep packs as files.

## Deploying free

Host `player/` and `pack/` on any static host (GitHub Pages, Netlify, Cloudflare Pages). The page detects there is no server and hides the scenario runner, so visitors explore the prebuilt runs. Build the public pack with `--redact` if you want visitors to find the causes themselves. To let visitors run scenarios you need `serve.py` somewhere that runs Python.

## Known limits (honest)

- Corridor B counter averages about 18 against the story's 42, and room 8B about 20 against 30. The story's counters read higher than the rooms' actual rolls allow; the engine keeps them physically consistent rather than inflate them. The other counters are within about 13%.
- Movement is room to room; no pathfinding, stairs, or walking time between buildings.
- Timetable is a weekly rota without subjects. Lab sessions are scheduled, not planned by syllabus.
- Fee sensitivity is a simple multiplier on absence, with no model of withdrawals or competing schools.
- Money in generate mode follows the story's own cost calendar scaled by changes; it is not a full ledger.
- The player's styling was checked through drawn images and text output, not in a real browser; expect small visual tweaks.
