# SchoolTwin Design System — v7.0 "Quiet Instrument"

Derived from `SchoolTwin_Design_Analysis.md` (§7 token set) and enforced by
`tests/test_design_tokens.py`. The player implements these tokens twice — as CSS
custom properties (`player/player.css`) and as the canvas token map
`CANVAS_THEMES` (`player/player.js`), because canvas 2D cannot read CSS
variables; parity between the two is test-enforced.

## Surfaces (dark default)

| Token | Value | Note |
|---|---|---|
| canvas / `--bg-base` | `#0E1014` | page floor |
| surface-1 / `--bg-surface` | `#171C23` | panels, floor plates |
| surface-2 / `--bg-card` | `#202630` | cards, nested pills |
| surface-3 / `--bg-card-hover` | `#2A313C` | hover/active, chips |
| `--bg-input` | `#12151A` | inputs |
| border | `rgba(255,255,255,0.09)` | 1px hairlines everywhere |

Depth steps are 1.11 / 1.13 / 1.16 : 1 with a visible border — tonal depth, not
shadows. A light theme is a pure value swap of the same names.

## Text

| Token | Dark | Use |
|---|---|---|
| text-1 `--text-primary` | `#F4F6FA` | headings, numerals |
| text-2 `--text-secondary` | `#B4BCC9` | body, labels |
| text-3 `--text-muted` | `#8F99A8` | quiet captions; never below 12.5 px |

Minimum contrast over every text/surface pair: **4.55 : 1** (AA).

## Meaning colours — never used alone (§7.2)

| Meaning | Dark | Shape / line partner |
|---|---|---|
| origin | `#FF5C3A` | dot with two rings + crosshair; map & origin chips only |
| affected | `#FFB224` | solid amber tint, dashed amber border |
| secondary | `#FFD98A` | dashed outline, faint tint |
| response | `#2FD3BE` | dotted trail (responder connector) |
| scenario (treatment) | `#B39CFF` | thick solid line, star marker, glow |
| control | `#7FB2D9` | dashed line, diamond marker |
| baseline | `#9AA6B8` | thin solid line, "LEGACY BASELINE" seam label |
| better / worse | `#4ADE80` / `#FB7185` | ▲▼ plus the words |
| accent (interactive only) | `#7C9BFF` | buttons, focus rings, playhead |

All meaning colours ≥ 3 : 1 on surface-1 (both themes), verified by test.

## Status vocabulary

Computed (solid dot) · Configured (✓) · Assumed (dashed outline) ·
Not modeled (diagonal hatch, no marker) · Unavailable (grey) · AI-written (✦).

## Geometry, spacing, type

- Radii: 8 / 12 / 16 / 22 px + full pill — one capsule family.
- Spacing: 4 pt base, 8 pt rhythm; gutters 12–16; card padding 20–24.
- Type: system grotesk stack (offline-first — no remote fonts); tabular
  numerals everywhere numbers change; scale 38 / 24 / 20 / 14 / 12.5 min.
- At most **one glow** per screen: the incident origin (or the selected chart point).

## Map luminance hierarchy (§8)

canvas → zone surface-2 + hairline → people (brightest ordinary marks) →
selected person ring → **incident origin = brightest thing on screen**.
Affected zones fill amber; camera-counter layer shows counters only.

## Motion

Numerals count up; meter fills ease out; the capsule's lit pill slides; cards
rise 8 px with 24 ms stagger (max 8); hatching never animates. Honour
`prefers-reduced-motion` plus the in-app Motion setting. Only transform and
opacity animate.
