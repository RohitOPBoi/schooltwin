# Loop Ledger — documented cycles by workstream

Cycle format: objective → evidence observed → action/conclusion → verification.
Counts below are the cycles actually performed and documented.
**Session 1 (2026-10-24 morning): 53 cycles. Session 2 (2026-10-24, council-driven
repair pass): 34 cycles → 87 total.** The commissioned minimum (50 per
workstream, 400 total) was **not reached**; see the delivery report for the
honest statement. No cycle below is fabricated or a counter increment.

## Session 2 — 2026-10-24 (independent council review → repair → verify)

Review pass 1: two independent reviewer agents (engine-side diff; frontend-side
diff) plus one measurement agent. Review pass 2: two independent council
verifiers (engine findings; frontend findings) after repairs.

### WS1 Design analysis — 1 cycle (session 2)

- **DA-8** Light-theme veil token. Evidence: two v6-era gradients hardcoded `rgba(15,19,28,.95)` in `#top`/`#dock`, breaking light theme (reviewer finding). Action: derived `--veil` per theme (dark rgba(14,16,20,.95) / light rgba(238,241,246,.95)), both gradients tokenized. Verified: council frontend reviewer (VERIFIED, finding 8).

### WS2/3 UI construction & conformance — 11 cycles (session 2)

- **UC-10** Paired-mode exit on run switch (chimera UI). loadRun resets paired state + restores single-map surfaces; jsdom test added. Council VERIFIED.
- **UC-11** Stale `S.days` behind Now/Inspect during pairs. loadPairedRun clears day cache + cmp + activeFlag. Council VERIFIED.
- **UC-12** Motion Off gates canvas. `animPhase()` static phase; responder dash offset gated; `applyMotionSetting` sets `S.motionOff`; boot restores localStorage. jsdom test added. Council VERIFIED.
- **UC-13** Keyboard: modifier guard (Ctrl+F no longer hijacked), V respects redacted packs. jsdom test added. Council VERIFIED.
- **UC-14** Hero poll failure recovery (server death mid-run no longer strands the button). Council VERIFIED.
- **UC-15** Bad `?run=` boot fallback: toast + first-run fallback, terminating recursion. Council VERIFIED.
- **UC-16** Honest open-day line: null (offline/unknown, muted) vs 0 (amber). Council VERIFIED.
- **UC-17** ensureTiming race guard + patch-`#openDayLine`-by-id (builder form focus preserved). Live-verified in browser: 30d amber → 60d "24 open school days" in place.
- **UC-18** Timezone-safe date labels (`isoOfDay`/`isoOfDate`; zero `toISOString()` day-labels remain). Council VERIFIED.
- **UC-19** esc() hardening on pack-derived interpolations (compare deltas, horizon, affinity chip attrs). Council VERIFIED.
- **UC-20** Selected closed calendar day keeps its hatch (`.cal-day-cell.selected.closed`). Council VERIFIED.

### WS4 Simulation engine & paired reliability — 9 cycles (session 2)

- **SR-10** Closed-day catalog completeness. 13 EVENT_CATALOG entries added (8 closed-day + 5 teaching-day); scheduler closed-day eligibility now consults the catalog (excludes `weather_attendance_dip`); June window now schedules executing facility faults. Council VERIFIED by execution (3 bg events in June, all student-free).
- **SR-11** `pack/index.json` atomicity: module lock + tempfile/`os.replace`. Council VERIFIED (notes in-process-only limitation).
- **SR-12** pair_id content addressing includes params/severity (sorted JSON). Collision + reproducibility tests added. Council VERIFIED.
- **SR-13** Compare same-basis financials (ledger only when BOTH sides have it). Council VERIFIED.
- **SR-14** Negative AR root cause: 181 days of collections credited against AR vs 10 billing entries (−₹3.17M). Fix: excess collections booked as other revenue; reconciliation passes, AR floors at 0. Council VERIFIED incl. in-memory edge cases.
- **SR-15** Generic event costs reach the reconciled ledger (`book_event_expense`). Council VERIFIED for purpose; found N1 (see SR-16).
- **SR-16** N1 repair: per-event-id dedupe dropped `water_motor_failure`'s second legitimate cost (₹12,000 tanker). Fix: engine decides per event — handler-booked → skip generics entirely; otherwise book every distinct effect. Regression tests for both sides (multi-cost booking; handler-wins dedupe).
- **SR-17** Severity validated on the paired path (no more mid-run KeyError). Council VERIFIED.
- **SR-18** Compare honesty: agents_evaluated_population real diffs; solution branches remapped to existing metric ids; dead vars removed. Council VERIFIED.

### WS5 Failure discovery & root-cause repair — 3 cycles (session 2)

- **FR-7** "Calendar cache doesn't work" (timing endpoint still 120ms) → root cause: three zombie server processes double-bound port 8765 on Windows (SO_REUSEADDR); measurements were hitting a stale pre-fix server. Killed all, single listener verified; steady-state 14–22ms (from 127ms).
- **FR-8** Pack index inconsistent both directions: 4 stale entries (dirs deleted) + 7 loadable packs invisible to the UI. Repaired from disk metadata (21 consistent entries); 5 orphaned `days/`-only dirs left untouched and documented (interrupted runs, predate this session).
- **FR-9** App layout frozen at first-render pane width (1696px) at EVERY viewport — canvas bitmap `width` attribute propped grid tracks open via `min-width:auto`; `overflow:hidden` masked it. Fix: `#app canvas { max-width: 100% }` + `min-width: 0` on grid/flex items. Live-verified at 1440/1279/1024/768/390 (zero past-edge elements, zero clipped text).

### WS6 Testing & integration verification — 4 cycles (session 2)

- **TV-7** Full suites after all repairs: **105 Python tests** (95 → 103 → 105) and jsdom suite **24 checks** (21 → 24) — all pass; perf budget 12.7ms/frame.
- **TV-8** Live HTTP end-to-end paired run (60d, water cooler ₹9,000): completed; cash delta exactly −₹9,000 (Computed); honest status tags; 2 background events executing; AR 0.0 both branches; new pack written to its own content-addressed dir.
- **TV-9** Live browser (Team E, IAB): desktop structure+data, timeline scrub (day 11→146), builder flow with live open-day patch, compare report render, run-selector switch, motion 3-state cycle, keyboard Space/arrows — all verified; screenshots at 1440/900/390 saved (`tests/shots/live_*.png`).
- **TV-10** Responsive audit at 5 widths (programmatic geometry: past-edge elements, clipped text) before and after the canvas fix — evidence in browser session, after-state clean.

### WS7 Risk management — 3 cycles (session 2)

- **RM-6** Verification-pair cleanup: fresh c78461 pair + index entries removed after verification; user packs untouched; baseline SHA intact post-work.
- **RM-7** Orphaned `days/`-only pack dirs (5): left in place (cannot prove unwanted), documented, invisible to UI.
- **RM-8** Index repair conservatively derived from each pack's own meta.json; baseline entry preserved first.

### WS8 Deployment & release readiness — 3 cycles (session 2)

- **DR-5** `/api/scenario_timing` profiled (calendar ctor 121ms of 127ms median) → thread-safe singleton cache; steady-state 14–22ms (≈8× faster) on the endpoint the builder hits interactively.
- **DR-6** Hardened endpoints verified over HTTP: sanitized run ids, body-shape guards, guarded pair_meta parse (council S1/S2 VERIFIED).
- **DR-7** Server restart discipline documented: TaskStop on Windows leaves detached python processes that double-bind 8765 (SO_REUSEADDR) — check `netstat`/tasklist before measuring or serving.

---

## Session 1 — 2026-10-24 morning (original repair pass)

## WS1 Design analysis — 7 cycles

- **DA-1** Identify authority. Evidence: repo root contains `SchoolTwin_Design_Analysis.md` (created 2026-10-24) + companion PNG. Conclusion: this file is the design authority per project instruction; no competing analysis exists.
- **DA-2** Extract token set. Evidence: §7.1 exact hex values and measured contrast steps. Action: transcribed verbatim into `player.css` v7 blocks (no invented values).
- **DA-3** Colour-alone audit. Evidence: §7.2 pairs (control=dashed, scenario=thick, hatch=unknown…). Action: implemented shape partners in canvas renderers + timeline markers.
- **DA-4** Contrast verification. Evidence: computed WCAG ratios for all token/surface pairs (worst dark pair 4.55:1). Action: codified in `tests/test_design_tokens.py`.
- **DA-5** Status vocabulary. Evidence: §7.2 badge vocabulary. Action: CSS for Computed/Configured/Assumed/Not modeled/Unavailable/AI-written.
- **DA-6** Map luminance hierarchy. Evidence: §8 ordering (zones < people < selected < origin). Action: reticle double-ring vermilion origin, amber affected tint, dotted teal responder trail.
- **DA-7** Originality constraints. Evidence: §10 checklist (no pink+indigo, no bubbles/peel, own motifs). Conclusion: v7 uses none of the reference's devices; signature motifs are origin rings, hatch, Day 150|151 seam.

## WS2 UI construction — 9 cycles

- **UC-1** Canvas token architecture. Built `CANVAS_THEMES` (dark+light) + `CT()` + `hexA()`; canvas can't read CSS vars.
- **UC-2** Zone tints per theme. Added `TINT_LIGHT`; fixed light-theme dark-map bug (was recon finding).
- **UC-3** Dual-map branch semantics. Custom intervention = scenario violet (was emerald), shared bg = control blue-grey (was sky), other = origin vermilion.
- **UC-4** Timeline markers. Shared = control diamond, custom = scenario star, seam = baseline slate dashed, playhead = accent.
- **UC-5** Calendar open/closed rendering. Closed days hatched + titled with reason; open days marked.
- **UC-6** Builder guidance surfaces. Horizon line shows open-day count; selection HUD warns for student events on closed days with first-open-date.
- **UC-7** Pre-flight validation UX. Hero run button blocks closed-day student events client-side with actionable message.
- **UC-8** Timing data path. `ensureTiming()` consumes `/api/scenario_timing` `day_calendar`; offline fallback = reopen+Sundays (documented approximation).
- **UC-9** run selector wiring. `#runSel.onchange` loads the chosen pack (was dead since introduction).

## WS3 UI reconstruction & conformance — 7 cycles

- **RC-1** Token block rewrite (dark). All names preserved, values per analysis.
- **RC-2** Token block rewrite (light). Value-swap maintaining AA (verified 4.5+ everywhere).
- **RC-3** Badge system restyle with shape partners; removed colour-glow badges.
- **RC-4** Map renderer pass: floors, zones, crowding heat, labels, reticle, responder, legend — all tokenized (25+ hardcoded hexes removed).
- **RC-5** Strips renderer pass: day/minute strips, flags, seam, playheads tokenized.
- **RC-6** Panel HTML pass: inline hexes in generated markup → tokens (bars, legends, chips, sparks, hero buttons).
- **RC-7** Visual verification. Screenshots via jsdom+node-canvas: dark map, incident map, light map, paired event day (ctrl/trt/strip), builder, now, compare panels — inspected; violet star reticle confirmed on treatment only.

## WS4 Simulation engine & paired reliability — 9 cycles

- **SR-1** Pack audit of 4 saved pairs (isolation/shared schedules verified correct).
- **SR-2** Fresh paired run (fight, June date) → found closed-day firing + divergence only in `queries`.
- **SR-3** Calendar mapping → June window (days 151–180) has **zero** open days; reopen = day 181.
- **SR-4** Validation layer added (`validate_paired_custom_event`) with suggested-open-day hints.
- **SR-5** Engine skip-and-record for student events on closed days; winter-break test case relocated to an open day (test had asserted the dishonest behavior).
- **SR-6** Audit execution_status lifecycle (pending→executed/skipped).
- **SR-7** Comparison window semantics: paired deltas over branch window only.
- **SR-8** Ledger-first financial metrics (macro book vs reconciled ledger divergence quantified: ₹8,500 repair invisible in old compare).
- **SR-9** Determinism spot-check: same seed → same pair_id and identical background schedule; separate engines → independent state.

## WS5 Failure discovery & root-cause repair — 6 cycles

- **FR-1** "All metrics Unavailable" → wrong key (`label` vs `status`). Fixed + test.
- **FR-2** "Water cooler cost missing" → two finance books; compare read the macro one. Fixed (ledger-first) + test.
- **FR-3** "Simulation shows nothing happened" → closed June window. Fixed at three layers (schema/server/engine).
- **FR-4** jsdom failure `AC is not defined` → my own batch-edit scoping bug; hoisted declaration.
- **FR-5** pytest regression in cognitive integration test → the test asserted fights during winter break; moved to open day 12 (the engine is now honest, the test was wrong).
- **FR-6** jsdom paired-load failure in shot harness (`pack/undefined/meta.json`) → harness lacked API server; pass pair_meta object directly.

## WS6 Testing & integration verification — 6 cycles

- **TV-1** Full pytest at session start: 76 passed, 1 skipped (baseline health established).
- **TV-2** npm jsdom suite at start: all pass (player health established).
- **TV-3** New `tests/test_paired_reliability.py` (9 tests) — all pass.
- **TV-4** New `tests/test_design_tokens.py` (9 tests incl. light theme, canvas parity, offline-first) — all pass.
- **TV-5** Final combined: **95 passed** Python + full jsdom suite; perf budget 11.7 ms/frame.
- **TV-6** Live HTTP verification against restarted `scripts/serve.py`: timing endpoint (0 open days for 30-day window), pair/run 400 with actionable message, valid pair → completed, windowed compare, pair/meta.

## WS7 Risk management — 5 cycles

- **RM-1** Baseline immutability: `assert_baseline_intact()` verified after all engine changes (SHA-256).
- **RM-2** Test-fixture isolation: `compare_runs` gained `pack_dir` param so compare tests use temp dirs instead of writing into `pack/`.
- **RM-3** Verification-artifact cleanup: 6 generated pairs removed from `pack/` and `index.json`; user runs untouched; count 23→17.
- **RM-4** Overwrite risk on repeat pairs: `make_pair_id` is content-addressed (same event+profile+seed ⇒ same run) — documented as deterministic-replay behaviour, not data loss.
- **RM-5** Client/server calendar drift risk: single source of truth (server ExtensionCalendar) consumed via timing endpoint; client fallback explicitly weaker and labeled.

## WS8 Deployment & release readiness — 4 cycles

- **DR-1** Server cold start with modified code: baseline assert passes, binds 127.0.0.1:8765.
- **DR-2** API surface regression over HTTP (see TV-6) — no 500s; validation path returns structured 400s.
- **DR-3** Offline-first audit: Google Fonts `@import` removed; system stack; test-enforced.
- **DR-4** Static behavior: player loads packs from filesystem in jsdom harness with `api/` 404s (S.api=false path) — no crashes.

**Total documented cycles: 53.** Commissioned minimum: 400. Gap is stated, not hidden.
