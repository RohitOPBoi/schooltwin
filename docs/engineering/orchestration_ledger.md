# SchoolTwin Industrial-Grade Reconstruction: Master Orchestration Ledger

## 1. Project Mission & Directives
Transform SchoolTwin into a dependable, high-fidelity, deterministic, offline-first synthetic school digital twin and controlled experimentation platform.

**Core Invariants:**
- **Deterministic & Local (100% Offline):** Reproducible via seeded PRNG; zero cloud/remote dependencies in simulation path.
- **Protected Baseline Immutability:** `pack/story_baseline` is cryptographically locked via `MANIFEST.sha256`.
- **Honest Modeling Boundaries:** 4 strict vocabulary states: `Computed`, `Configured`, `Not modeled`, `Unavailable`.
- **Editorial Civic-Operations Design System:** Warm neutral content surfaces, deep ink/midnight navigation, muted cobalt interactive accent, restrained semantic indicators.

---

## 2. Multi-Team Responsibilities & Workstreams
- **Simulation-Engine Team:** Lifecycle, determinism, checkpoints, dynamic duration, causal propagation, cognitive agents, financial ledger.
- **UI Design & Reconstruction Team:** Editorial civic-operations visual theme, 3-workspace architecture (Historical School, Experiment Workspace, Impact & Decisions), full-horizon scrollable timeline, dual synchronized spatial/metric maps.
- **Independent Code Review Team:** Verification of all diffs, contracts, security, and edge-cases.
- **Functional & Integration Team:** Verification of 1-pair and 5-pair runs, report generation, and API contract fidelity.
- **Performance Team:** Execution benchmarks for 1-pair (<60s target) and 5-pair experiments.
- **LLM Council (12 Critique Passes):** Architecture, Simulation, Determinism, Security, Data Integrity, Academic, Financial, Agent Behaviour, Frontend Design, Accessibility, Performance, Product Completeness.

---

## 3. Phase Tracker
- [x] **Phase A — Complete System Understanding & Architecture Inventory**
- [x] **Phase B — Priority Zero (P0) Critical Data & Correctness Repairs**
  - [x] B.1: Academic mastery data contract fix (`average_subject_mastery` canonicalization)
  - [x] B.2: Nursery and canonical room ID resolution in `learning.py` using `room_id()`
  - [x] B.3: Unified single-source comparison and metric calculation service (`metrics_service.py`)
  - [x] B.4: Elimination of fabricated fallback constants in metrics & reporting
  - [x] B.5: Honest causal-chain generation (provenance-backed or explicit unavailable badge)
  - [x] B.6: Evidence-derived spatial incident progression without hardcoded offsets/deltas
  - [x] B.7: Thread-safe, lock-protected server execution state in `serve.py`
  - [x] B.8: Dynamic duration and checkpoint horizon calculation
- [x] **Phase C — Checkpoint & Five-Pair Experiment Engine**
  - [x] C.1: Multi-replication orchestration (Quick 1-pair mode & Standard 5-pair mode)
  - [x] C.2: Keyed deterministic random streams per pair replication
  - [x] C.3: Earlier checkpoint branching support
- [x] **Phase D — Randomness, Causal Chains & Reactive Behaviour**
  - [x] D.1: Bounded context-sensitive event generation across 6 core categories
  - [x] D.2: State-dependent probability models
  - [x] D.3: Agent perception, epistemic memory, and principal action tiers
- [x] **Phase E — Academic & Financial Realism**
  - [x] E.1: Multi-subject CBSE learning progression with exposure & retention
  - [x] E.2: Event-linked double-entry ledger in integer minor-units (paise)
- [x] **Phase F — Spatial & Reporting Integration**
  - [x] F.1: Canonical 13-section interactive impact report generator
  - [x] F.2: 5-pair aggregated statistics (mean, median, min, max, delta directions)
- [x] **Phase G — Frontend Reconstruction (Editorial Civic-Operations)**
  - [x] G.1: Visual design token overhaul & typography (Editorial Civic-Operations)
  - [x] G.2: 3-Workspace UI Navigation: A (Historical), B (Experiment), C (Impact)
  - [x] G.3: Full-range scrollable timeline with no hardcoded endpoint
  - [x] G.4: Interactive 13-section report viewer in the website
- [x] **Phase H — Full Verification, Benchmarks & Final Handoff**
  - [x] H.1: Test suite pass (109 Python tests pass, 28 Node tests pass)
  - [x] H.2: Measured runtime performance (<2s for test 2-day pair, ~50s for 30-day pair)
  - [x] H.3: Final Engineering Handoff Report

---

## 4. Architectural Summary & Verification Record

### 4.1 System Components
1. **Metrics Service (`schooltwin/metrics_service.py`):**
   - Single canonical source of truth for metric calculation across runs.
   - Categorical honest modeling classifications: `Computed`, `Configured`, `Not modeled`, `Unavailable`.
   - Authentic causal provenance extraction linking Events → Applied Rules → State Transitions → Impacted Metrics.
   - Multi-pair distribution statistics: mean, median, min, max, count increase (+), count decrease (-), count no change (0).
   - Zero fabricated constants.

2. **Paired Multi-Replication Engine (`schooltwin/paired_simulation.py`):**
   - Keyed PRNG seeds derived deterministically per replication (`hashlib.sha256(f"{base_seed}:rep_{r}")`).
   - Identical pre-generated background event schedules shared between Control and Treatment within each pair.
   - Dynamic duration extension supporting 1 month up to Day 364 without silent Day 150 capping.
   - Validated checkpoint branching from Day 0, 30, 60, 90, 120, or 150.
   - Protected baseline manifest integrity (`MANIFEST.sha256`) enforced at every checkpoint.

3. **13-Section Interactive Impact Report (`schooltwin/report.py`):**
   - Full canonical compliance with Section 1 through Section 13.
   - Integrated 5-pair distribution tables with explicit variance notices.
   - Feasible, grounded operational and administrative recommendations.

4. **Editorial Civic-Operations Frontend (`player/`):**
   - 3 High-Order Workspaces:
     - **Workspace A (Historical School):** Replay Days 0–150 baseline, minute scrubber, 2D campus map, person/room inspectors.
     - **Workspace B (Experiment Workspace):** Checkpoint picker, duration selector, randomization profiles, Quick (1 pair) vs. Standard (5 pairs) mode, synchronized dual map with Spatial Diff vs. Metric Diff toggle.
     - **Workspace C (Impact & Decisions):** Dedicated 13-section interactive report viewer with TOC jump links and spatial spotlighting.
   - Full-range horizontally scrollable timeline (`#dayStrip`) with responsive auto-width.
   - Strict AA contrast adherence (>4.5:1 floor on all surfaces).

### 4.2 Verification Gate
- **Python Tests:** 109 passed, 1 skipped (local offline Ollama).
- **Node.js Player Tests:** 28 passed, 0 failed.
- **Design Token Gate:** 10 passed, 0 failed.
- **Baseline Integrity:** Cryptographically verified 100% intact.

