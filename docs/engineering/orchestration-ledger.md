# SchoolTwin Engineering — Orchestration Ledger

**Session 1:** 2026-10-24 morning · **Session 2:** 2026-10-24 (council-driven
repair pass) · **Operator:** ZCode agent (single orchestrator; session 2 ran
five independent subagents: 2 code reviewers, 1 performance engineer, 2 council
verifiers) · **Repo:** `F:\projects\schoolbro`

The commissioned brief required a ten-agent organization with 8 workstreams × 50
cycles (400 total). Session 1 ran a single orchestrator with one delegated
read-only reconnaissance agent. Session 2 ran genuine independent review agents
(two adversarial code-review passes, one measurement pass, two verification
passes) and executed real, evidence-backed cycles in all eight workstream
categories. The numeric cycle quota was **not** met (87 documented across both
sessions); every cycle recorded was actually performed and is backed by commits,
test runs, execution output, or browser evidence. No count was padded, and no
finding was fabricated.

## Session 2 — requirement → status

| # | Requirement | Status | Evidence |
|---|---|---|---|
| S1 | Independent code review of all uncommitted engine diffs | Done | Reviewer agent: 12 confirmed findings (2 MAJOR correctness, 2 MAJOR data-integrity, 5 MINOR security/correctness, 1 MAJOR test-quality, dead code); verdicts REVISE×3 |
| S2 | Independent code review of frontend diffs | Done | Reviewer agent: 2 MAJOR state bugs, 1 MAJOR a11y (Motion-Off), 8 MINOR contract/layout/XSS-hardening; XSS APPROVE |
| S3 | Performance measurement | Done | Measured: cold start 527ms; API medians 2-3ms except timing 126.7ms; pair run 13.5s/60d (110ms/day/branch); peak RSS 779MB; packs 90% day-files; frontend 10ms/frame. Top-3 bottlenecks ranked |
| S4 | Repair all confirmed engine findings | Done | C1 catalog+scheduler, C2 same-basis compare, C2b negative-AR (other-revenue split), C4 severity, D1 index lock+atomic, D2 pair-id params, S1/S2 hardening, T1 real classifier, C5 honest metrics — council re-review VERIFIED each with execution |
| S5 | Repair all confirmed frontend findings | Done | Paired-mode exit + stale-days, Motion-Off canvas gating + boot restore, modifier guards, poll/boot recovery, offline honesty, veil token, TZ labels, esc hardening, calendar hatch, flags alias — council re-review VERIFIED 12/12, APPROVE ×3 |
| S6 | Council mandatory gate | Done (one caveat) | Pass 1: REVISE everywhere (XSS APPROVE). Pass 2: engine correctness APPROVE, security APPROVE, data-integrity REVISE on new defect N1 → N1 fixed same session with 3 regression tests (19/19 suite green). **The N1 fix itself was not re-submitted for a third council pass** — residual risk noted |
| S7 | Browser/UI verification at multiple widths | Done | Live IAB: desktop/tablet/mobile; geometry audit at 5 widths clean after canvas-layout fix; timeline scrub, builder, compare, run switch, motion, keyboard all exercised; screenshots saved |
| S8 | Data preservation | Done | Baseline SHA intact after all work; verification packs removed; index repaired to disk truth; orphaned days-only dirs left untouched & documented |

## Session 2 — defect register (new findings, all confirmed before fixing)

| ID | Defect | Root cause | Fix | Test |
|---|---|---|---|---|
| H | Default June window dropped ALL background events; 12 scheduler types uncatalogued | EVENT_CATALOG missing types → engine gate treated facility faults as student-dependent | 13 catalog entries + scheduler consults catalog; `weather_attendance_dip` stays student-dependent | TestClosedDayBackgroundCatalog (4 tests) |
| I | Compare mixed ledger and macro bases (baseline-vs-scenario garbage deltas) | per-side fallback instead of same-basis rule | ledger only when BOTH sides carry it | existing window test unchanged-and-passing |
| J | Ledger AR went negative (−₹3.17M) | collections (incl. non-fee income) credited against AR; billing monthly only | excess → other revenue; AR floors at 0; reconciles | council in-memory edge cases + fresh-pair AR 0.0 |
| K | `pack/index.json` race + non-atomic write could brick future runs | no lock, no temp+rename | `_IDX_LOCK` + `_dump_atomic` | council review |
| L | Distinct interventions collided → silent pack overwrite | pair_id hashed type+date only | content hash of type/date/severity/params | TestPairIdContentAddressing (3 tests) |
| M | Invalid severity crashed mid-run after compute | paired validator skipped severity | validated (mirror of validate_scenario) | council execution check |
| N | Path traversal on `/api/pair/meta` + `/api/compare`; malformed bodies crashed handler threads | unsanitized query ids; unguarded body shapes | `_clean_run_id`, dict/flag guards, JSON parse guard | council execution check |
| O | Tautological status-tag test | test re-implemented the classifier inline | real `classify_metric_status`/`classify_comparison_metrics` extracted & tested | TestStatusTagClassification (2 tests) |
| P | Dishonest compare blocks | hardcoded 0 diffs; 3 dead solution keys; dead vars | computed diffs; remapped keys; removed dead code | council review |
| Q | Fresh (session-2) defect: dedupe dropped `water_motor_failure`'s 2nd cost (₹12,000) | per-event-id dedupe vs multi-effect events | engine decides per event (handler-wins, else book all distinct) | multi-cost + dedupe tests |
| R | Layout frozen at first-render width (1696px) at every viewport | canvas bitmap propped grid tracks (`min-width:auto`) | `#app canvas{max-width:100%}` + `min-width:0` on items | live geometry audit 5 widths |
| S | Light theme broken at header/dock | two hardcoded v6 gradient colors | `--veil` token per theme | council review |
| T | Measurement sabotage: 3 zombie servers double-bound port 8765 | TaskStop kills shell, not detached python on Windows | killed; single-listener discipline documented | netstat + steady-state timing 14-22ms |

## Session 1 (morning) — requirement → status

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 1 | Identify authoritative design analysis | Done | `SchoolTwin_Design_Analysis.md` (repo root, untracked→honored as authority) |
| 2 | Inventory installed skills | Done | project skill `schooltwin-simulation` loaded; Ponytail/GSD/CodeRabbit/Taste not installed in this environment — methodology followed manually where applicable, honestly noted |
| 3 | Reconstruct UI per analysis | Done | `player/player.css` v7 tokens, `player.js` canvas token map, badges, map/timeline semantics; `tests/test_design_tokens.py` (9 tests) |
| 4 | Fix control & treatment simulations | Done | 6 defects diagnosed & repaired (defect register A–G); regression suite created |
| 5 | Preserve all original data | Done | `assert_baseline_intact()` verified post-work; user packs untouched; 6 verification artifacts removed |
| 6 | Controlled randomness + reactivity | Verified | scheduler caps/cooldowns audited and left as designed; audit trail `execution_status` now honest; cognitive propagation verified on event day |
| 7 | Comparison correctness | Done | branch-window compare + reconciled-ledger financials + honest status tags |
| 8 | Deployment/release readiness | Verified | server restart, HTTP API exercised end-to-end (validation 400s, pair run, windowed compare, timing endpoint) |
| 9 | Loop ledgers (8 × 50 cycles) | **Partial** | 53 cycles session 1; 87 total with session 2 — not 400 |
| 10 | Delivery report | Done | `delivery-report.md` (updated by session 2) |

## Session 1 (morning) — original defect register

| ID | Defect | Root cause | Fix | Test |
|---|---|---|---|---|
| A | Every paired metric tagged `Unavailable` in `pair_meta.json` | `paired_simulation.py` classification read `m["label"]`; metrics carry `m["status"]` | read `status` | `test_status_tag_distribution_is_honest` |
| B | Paired runs accepted student events on closed days → near-invisible divergence ("broken" sims) | no validation on the paired path; June window is 100% summer break | `validate_paired_custom_event` (schema.py) + synchronous 400 in serve.py + client pre-flight | `test_student_event_on_closed_day_is_rejected_with_open_day_hint` |
| C | Engine fired student events into an empty campus (fight during break/winter closure) | engine `_plan` applied all events regardless of `requires_students`/open day | skip + record (`skipped_events`, visible flag, audit `skipped`) | `test_student_event_on_closed_day_is_skipped_and_recorded` |
| D | Compare diluted paired deltas with identical replayed history; finance metrics read macro book, ignoring the reconciled ledger (₹8,500 repair invisible) | `compare_runs` used full date overlap + `days[].finance` | `window=(start,end)` param used by paired runs; ledger-first cash/AR/in/out | `test_window_excludes_replayed_history_and_prefers_ledger` |
| E | `comparison_tag` never reached pack flags; audit `execution_status` stuck `pending`; event ids regenerated (date-matching only in UI) | `_build_events` dropped passthrough keys; no execution marking | passthrough `comparison_tag/is_background/category/source/id`; mark `executed`/`skipped` | verified on fresh pair (5 tagged flags in trt, 4 in ctrl) |
| F | Player: `#runSel` never wired; dead loads (`incidents.json`, `report.json`); duplicate conflicting keydown handlers (arrows double-stepped, V/M double-bound); light-theme map used dark zone fills; `@import` Google Fonts broke offline-first; `var(--font-mono)` invalid in canvas `ctx.font`; dead `saved` builder tab; debug accumulator left in | accreted bugs | all fixed; keyboard now single handler; canvas consumes `CANVAS_THEMES` (dark+light) | npm jsdom suite (21 checks) |
| G | Builder let users pick closed dates for student events with no guidance; no open-day visibility | UI lacked calendar truth | `/api/scenario_timing` returns `day_calendar`/`open_days`/`first_open_date`; calendar hatches closed days; HUD warns with first open day; hero button pre-flight blocks | manual + HTTP verification |

## File ownership / changes (both sessions)

- `schooltwin/engine.py` — closed-day skip, tag passthrough, execution marking; finance_items carry event ids; event costs booked into the reconciled ledger (handler-wins dedupe, N1-safe)
- `schooltwin/schema.py` — `validate_paired_custom_event` (+ severity check); 13 new EVENT_CATALOG entries
- `schooltwin/random_scheduler.py` — closed-day eligibility consults the schema catalog
- `schooltwin/paired_simulation.py` — validation gate, window compare, content-addressed pair ids, extracted status classifier
- `schooltwin/compare.py` — window + pack_dir params; same-basis financials; honest cognitive/agent diffs; live solution branches
- `schooltwin/ledger.py` — `book_event_expense`/`has_source`; collect-fee excess split to other revenue (AR never negative)
- `schooltwin/pack.py` — index lock + atomic write
- `scripts/serve.py` — sync pair validation, compare window params, timing open-day truth + calendar cache, run-id sanitization, body guards, flags alias
- `player/player.css` — v7 token system (+ `--veil`), status badges, hatch, calendar closed/selected states, canvas max-width + min-width layout fix
- `player/player.js` — CANVAS_THEMES, semantic map/timeline colors, builder guidance, paired-state lifecycle fixes, motion gating, keyboard guards, boot/poll recovery, TZ-safe labels, esc hardening, timing race guard
- `tests/test_paired_reliability.py` (19 tests), `tests/test_design_tokens.py` (9), `tests/test_player.js` (24 checks) — regression gates
- `tests/take_shots.js`, `tests/shots/live_*.png` — visual verification harness + live browser captures
- `docs/design-system.md`, `GEMINI.md`, `ARCHITECTURE.md`, `docs/engineering/*` — documentation conformance
