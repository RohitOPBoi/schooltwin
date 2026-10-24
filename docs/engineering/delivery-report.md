# SchoolTwin — Delivery Report

**Sessions:** 2026-10-24 (repair + council pass) · 2026-10-25 (industrial
reconstruction: reliability UX, new theme, 200-package organization).
Ledgers: `orchestration-ledger.md`, `loop-ledger.md` (87 cycles),
`industrial-reconstruction-ledger.md` (200 work packages + 15 more loops).

## 1. What was actually delivered

### Session 3 (2026-10-25) — user-reported defects + new visual system

The user reported "builder ui still not fixed, simulation engine not working."
Live reproduction showed the engine **does** run and propagate — but two real
product defects made it look broken, and the directive demanded a new theme:

1. **Small interventions were invisible in reports.** A 3-student fight over a
   60-day window rounds every aggregate metric to 0.0 (3 ÷ 1,309 × 60 days),
   while the real effects live on the event day (infirmary 1→4, incident
   recorded, queries +1). The pair manifest now carries `event_day_impact`
   (day-level control-vs-treatment deltas: attendance, late, mood, queries,
   infirmary, incidents), and the compare panel renders an "Event-Day Impact"
   card — verified live: `Infirmary 1 → 4 (+3)`, `Incidents 0 → 1 (+1)`.
2. **The builder trapped student-event runs.** The first preset (Student
   Altercation) sat on a closed June date → run blocked with only a warning;
   picking a July date then hit the 30-day horizon limit → server rejection.
   Now: picking a student preset on a closed day auto-moves the date to the
   first open school day (2026-07-01, toast), and any date beyond the horizon
   auto-extends the horizon to the covering preset (30→60/90/150, toast).
   Verified live; jsdom regression test added.
3. **New theme per the explicit directive change** (the prior "retain
   dark-slate" instruction is superseded — recorded as ADR-003):
   - **"Ivory Editorial" default**: warm ivory surfaces (#F4F2EB/#FBFAF6/
     #FFFFFF), deep-ink text (#1E2634 ladder), muted cobalt accent (#3A57AE),
     desaturated amber (#8F6612), restrained red (#A83B31), semantic colours
     re-toned (origin vermilion/scenario violet/control sky/response teal).
   - **Deep-ink navigation chrome** in both themes via new `--nav-*` tokens and
     a scoped token inversion inside `#top` (header descendants flip to
     light-on-ink automatically; verified live via computed styles).
   - **"Ink Midnight" alternate** (#141B27 family, light cobalt #8CA2E8) —
     the toggle now switches ivory↔ink; boot default is ivory.
   - Canvas maps re-toned to both palettes; the design-token gate still
     computes WCAG from the CSS and enforces AA on the new values
     (2 marginal pairs caught and fixed during derivation; 9/9 green).
   - Verified live: both themes' computed styles, layout audit clean,
     screenshots `tests/shots/live_ivory_theme.png` / `live_ink_theme.png`.
4. **Organization:** 200 work packages (ST-A001..A200) registered with honest
   statuses — 100 executed, 81 verified, 11 queued, 5 partial, 3 in-flight —
   plus 3 ADRs (frontend stack retained; JSON packs retained; theme authority
   superseded). See `industrial-reconstruction-ledger.md`. Actual concurrency
   reported there honestly: 1 orchestrator + 7 independent subagent runs, not
   200 agents.

### Session 1–2 (2026-10-24) — simulation repairs (all evidence-backed, tested)

1. **The "nothing happened" paired simulations are fixed** (session 1). The
   entire June window (days 151–180) is summer break — zero open school days —
   and the paired path applied any event regardless. Now: server rejects
   student-dependent events on closed days with the nearest open date; engine
   skip-records such events honestly; the UI calendar hatches closed days,
   warns inline, and pre-flights the run button.
2. **Closed-day background events execute** (session 2, council finding). 12
   scheduler event types were missing from `EVENT_CATALOG`, so the engine's
   applicability gate treated facility faults as student-dependent and silently
   dropped *every* background event in the all-closed June window (a
   `door_lock_failure` was logged as "no students on campus"). All 12 are
   catalogued with real consequence handlers; the scheduler's closed-day
   eligibility now consults the schema catalog; `weather_attendance_dip`
   correctly remains student-dependent and is excluded from closed days.
3. **Event repair costs reach the reconciled double-entry ledger.** Generic
   event finance effects previously touched only the macro daily series (whose
   payment-calendar shaping zeroes outflows on closed days — a repair booked on
   a June day cost exactly nothing). The engine now books every distinct event
   cost via `book_event_expense`; when a causal handler has already booked the
   event, its param-driven amount wins (no double-booking). A live 60-day pair
   shows the treatment's ₹9,000 water-cooler repair as an exact −₹9,000 cash
   delta, status Computed.
4. **Accounts receivable no longer goes negative** (−₹3.17M previously).
   Root cause: 181 days of collections — including non-fee income — were
   credited against AR while billing fired only on month-first days. Excess
   collections are now booked as other revenue; AR floors at zero and the
   ledger reconciles with zero discrepancy.
5. **Comparisons never mix accounting bases.** The reconciled ledger and the
   macro daily series are different models; the default baseline-vs-scenario
   compare previously subtracted one from the other (artifact +₹5.9M cash,
   −₹6.3M AR). Ledger values are used only when both packs carry a reconciled
   summary.
6. **Pack integrity:** `pack/index.json` updates are locked and atomic
   (temp-file + rename — a crash mid-write can no longer brick every future
   run); pair ids are content-addressed over the full event (type/date/
   severity/params), so distinct interventions on the same date no longer
   collide into one directory and silently overwrite prior results. The
   pack index was repaired against disk truth (4 stale entries removed,
   2 loadable packs that were invisible to the UI re-added).
7. **Honest reporting restored** (session 1 + session 2): status tags read the
   real classifier (extracted and directly tested — the original test was
   tautological); `agents_evaluated_population` reports real diffs instead of
   hardcoded zeros; solution branches key on metric ids that actually exist.

### Security hardening (council-verified by execution)

- Run-id sanitization on `/api/compare` and `/api/pair/meta` (path traversal).
- POST body-shape guards (non-object bodies, malformed flags → structured 400s
  instead of dropped connections); guarded `pair_meta.json` parse.
- Paired-event severity validated up front (no mid-run KeyError after compute).
- Player-side `esc()` applied unconditionally to pack-derived interpolations.

### UI reconstruction per the authoritative analysis

- Session 1: design system v7 "Quiet Instrument" (exact §7.1 tokens, §7.2
  shape partners, status badge vocabulary, offline-first system fonts, light
  theme as value swap, canvas theme maps kept in parity by test), semantic
  map/timeline colors, calendar open/closed rendering, builder guidance,
  player bug fixes (dead loads, duplicate keyboard handlers, unwired run
  selector, remote font import, and more).
- Session 2 (council findings, all verified by an independent reviewer):
  - **Paired-mode state lifecycle fixed** — switching runs mid-comparison no
    longer renders a chimera (dual map over a single-run pack), and Now/Inspect
    no longer show the previous run's day data during a comparison.
  - **Motion: Off actually gates canvas animation** (agent interpolation,
    reticle pulse, responder dash) and the preference survives reload.
  - Keyboard shortcuts no longer hijack browser combos (Ctrl+F works) and 'V'
    respects operator-only packs.
  - Boot/poll failure recovery (bad `?run=` falls back with a toast; server
    death mid-run no longer strands the hero button).
  - Honest open-day status line (offline "unknown" vs real "zero open days"),
    race-guarded timing updates that patch one node instead of re-rendering
    the builder form (focus preserved).
  - Timezone-correct date labels; light-theme header/dock gradients tokenized
    (`--veil`); selected closed calendar days keep their hatch.
  - **Layout was frozen at the first-render pane width at every viewport**
    (canvas bitmaps propped the grid open; `overflow:hidden` masked it).
    Fixed; live geometry audit at 1440/1279/1024/768/390px shows zero
    past-edge elements and zero clipped text.

### Performance (measured, not estimated)

- `/api/scenario_timing`: 126.7ms median → 14–22ms steady-state (thread-safe
  calendar singleton; first hit ~155ms builds it). This is the endpoint the
  scenario builder hits interactively.
- Recorded baselines for future work: server cold start 527ms; pair run
  13.5s/60-day (≈110ms/day/branch; branches parallelizable); peak RSS ~780MB
  (dominated by parsed day JSON); pack day-files ~165KB/day (90% of pack
  bytes); frontend render 10–15ms/frame (inside its budget test).

## 2. Process — honest accounting

The brief mandated ten named agents, an LLM council over every significant
step, and 8×50 = 400 documented cycles. Reality across both sessions: one
orchestrator plus, in session 2, **five genuinely independent subagents**
(two adversarial code reviewers, one measurement engineer, two council
verifiers — all separate model executions). Council verdicts:

- Pass 1 (review): engine correctness/security/data-integrity **REVISE**,
  frontend contract/accessibility **REVISE**, XSS **APPROVE**.
- Pass 2 (verification after repairs): engine correctness **APPROVE**,
  security **APPROVE**, frontend **APPROVE ×3**; data-integrity **REVISE** on
  one *new* defect the council found in the fix itself (multi-cost event
  under-booking) — repaired the same session with regression tests
  (19/19 suite green). That final repair was **not** re-submitted for a third
  independent pass; this is the one council gate closed on the
  orchestrator's own verification.

**87 documented cycles** across all eight workstreams (`loop-ledger.md`),
every one backed by a test run, execution output, or browser evidence. The
400-cycle numeric quota is **not met and not claimed**. Named skills from the
brief (Ponytail, GSD Core, CodeRabbit, Taste) are not installed in this
environment; their methodologies were followed where applicable and their
absence is disclosed.

## 3. Data protection

`pack/story_baseline` was never written: `assert_baseline_intact()` (SHA-256)
passes after all work in both sessions; the server keeps the 403 on baseline
overwrite; all new runs went to `pack/<id>`; user-generated runs and flags are
untouched; both sessions' verification artifacts were removed from `pack/`
and the index; five orphaned `days/`-only directories from interrupted runs
that predate this work were left in place and documented (not deleted — they
are not ours).

## 4. Running SchoolTwin

```
python scripts/serve.py        # http://127.0.0.1:8765
python -m pytest tests/ -q     # 105 tests
npm install && npm test        # jsdom player suite, 24 checks
node tests/take_shots.js       # manual visual harness → tests/shots/*.png
```

Windows note (learned the hard way): stopping the server's shell does not
always kill the python process; stale servers can double-bind port 8765
(`netstat -ano | grep 8765`) and serve old code. Kill by PID before
re-measuring anything.

Paired comparison flow: Create → pick event (student events need an open
calendar day; school reopens 2026-07-01 = day 181) → duration (60+ days
recommended) → Run Paired Comparison. Facility events are valid on closed
days and now genuinely execute (repairs hit the ledger even in June).

## 5. Known limitations / unresolved

- **Council verdicts (session 3):** reliability fixes APPROVED (correctness +
  honesty); theme received REVISE ×3 — all findings repaired the same session
  (23 neon rgba rules re-toned to semantic `color-mix`, header accent remapped
  to light cobalt after the new nav-contrast gate caught a 1.76:1 clock, stale
  comments fixed) with 108 Python tests + full jsdom suite green afterward.
  The post-repair theme work has **not** had a second independent review pass;
  the N1 repair (session 2) likewise — both covered by direct regression
  tests instead.
- `docs/design-system.md` still describes the retired v7 dark theme (queued,
  ST-A196).
- Run/version stamps (engine/ruleset) not yet written into manifests (queued).
- Pack day-file compression (165 KB/day dominates) queued.
- Canvas surfaces (map/strips) still lack keyboard navigation (documented).
- The Money panel still plots the macro series while compare reads the ledger.
- 11 work packages honestly queued; 5 partial — see the ledger register.
- Agent/loop accounting: 200 packages registered, ~102 cumulative documented
  loops; actual independent agent executions: 7 across sessions (disclosed in
  the ledger, not claimed as 200).
- Live-browser screenshots exist but this environment's AI image pipeline
  could not display them; visual verification is computed-styles + geometry
  audits + the inspected jsdom-render suite.
