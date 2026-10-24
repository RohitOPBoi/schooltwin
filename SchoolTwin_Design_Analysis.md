# SchoolTwin: Design Analysis of the Dark "Bento" Dashboard Theme

**Reference studied:** the "Resq.io" incident dashboard image you shared (863 × 602 px).
**Companion file:** `SchoolTwin_design_study_board.png`, a rendered study of the adapted system (palette, components, chart, incident map language).

---

## 1. How to use this document

The reference is someone else's concept design. Treat it as **a source of principles, not a layout to copy.** That matches your earlier instruction that the redesign must be built from scratch with no existing templates. So this analysis does three things:

1. Records what the reference does, with measurements taken from the image itself.
2. Separates the ideas worth borrowing from the ones that would hurt SchoolTwin.
3. Turns the good ideas into an **original** token system and component set for a map-first digital twin.

Section 11 is a short, paste-ready addendum for the implementation prompt.

---

## 2. What the reference does (anatomy)

| Region | What it contains | Design device |
|---|---|---|
| **Top bar** | Wordmark at left; a centred dark capsule holding five tabs (one lit); round icon buttons (search, bell); round avatar | Capsule geometry; one active state |
| **Greeting** | "Welcome in, Caroline" at large size; the name in a muted lavender-grey | Two-tone headline: context in white, subject in muted |
| **Meter pills** | Four labelled horizontal pills with partial fills: pink (20%), white (25%), dark grey (40%), **diagonal-hatched** grey (15%) | Fill = quantity; hatch = "other / inactive" |
| **Headline numerals** | 38, 26, 103 at large size, each with a tiny round delta badge (green up, green up, orange down) and a small label underneath | Big number, small chip, quiet label |
| **Summary card** | Three status rows (Triage, Fixing, Investigating), each a coloured dot, a label and a count pill; a one-line takeaway with an info icon | Status as dot + label + count |
| **Line chart card** | Two smooth lines (blue, pink) on a faint grid; a segmented range control (12 months / **30 days** / 1 week); one **glowing highlighted point** with a tooltip ("7 September, 318 Incidents") | Glow marks the point of interest |
| **Highlight card** | The only saturated blue surface on the page, with a short sentence and two **overlapping white cards** (Priority 3, Thread 1) | One loud surface; stacked-card metaphor |
| **Incident cards** | Status pill, ID, elapsed time, description, assignee avatar with name and email | Card-in-card, pill-first |
| **Statistics** | Three overlapping circles sized to 64%, 26%, 15%; a peeled-page corner | Decorative proportion chart |
| **Assistant card** | Greeting, a 2 × 2 grid of quick-action buttons with small coloured icons, and an "Ask something…" input with a sparkle icon | Chips plus one input |

**Layout:** a three-row "bento" grid with consistent gutters. Every row is a different column split (about 1.9 : 3.1 : 1.5 on row two). Everything lives in a rounded card.

---

## 3. What I measured (pixel sampling)

Method: sampled colours and text from the supplied PNG. Small text is anti-aliased and the image is compressed, so treat contrast figures as **close estimates (±10%)**, not exact. Pixel sizes are in the image's own scale.

**Surfaces and depth**

| Layer | Colour | Step from the layer below |
|---|---|---|
| Page | `#141316` | — |
| Card | `#211F25` | **1.13 : 1** against the page |
| Nested pill / inner card | `#2B2A32` | **1.15 : 1** against the card |

Depth is carried by very small tonal steps plus a faint hairline border, not by shadows.

**Accent colours sampled:** hot pink `#E83B81`, indigo-blue `#494EEE`, orange-red chip `#D8593A`, plus white as a high-emphasis fill. (The large azure card was not sampled cleanly; it reads as a saturated royal blue.)

**Text contrast (estimated)**

| Text | Colour on surface | Contrast |
|---|---|---|
| Greeting, card titles | white on near-black | about 16 to 18 : 1 |
| Muted name "Caroline" | `#CFCDDB` on page | about 12 : 1 |
| Labels ("Days spent", inactive nav) | `#A6A5AC`-`#ABAAAE` | 6.9 to 8.4 : 1 |
| Email, footnote | `#B6B4BE`, `#9B9AA2` | 7.4 and 5.3 : 1 |
| "Ask something…" hint | `#B0AEBC` on `#3E3D4A` | 4.9 : 1 |
| Elapsed time "7h 7m" | `#7D7C85` on `#2A2832` | **3.5 : 1** (below the 4.5 : 1 AA line for small text) |
| Chart date labels | `#64636A` on `#211F27` | **2.7 : 1** (fails) |
| Chart y-axis numbers | `#4D4557` on `#222028` | **1.8 : 1** (fails) |

**Type scale:** numerals about 27 px of ink height, greeting about 19, the smallest footnote line about 7. So the hierarchy from big numeral to smallest text is roughly **3.9 : 1**. The typeface is a geometric grotesk with tight tracking; I cannot identify it from the image.

**Reading:** the reference is strong where it is large (titles, labels, numerals) and weak exactly where a data tool needs to be strong: chart axes and secondary figures.

---

## 4. The genre: what "dark bento dashboard" gets right

1. **Tonal depth with hairlines.** Cards are barely lighter than the page; a 1 px border does the separating.
2. **Capsule geometry.** Navigation, range selectors, pills and buttons all share one rounded vocabulary, which makes the interface feel like one object.
3. **Big numerals, tiny deltas.** The number is the hero; its change is a small chip; the label is quiet.
4. **Few accent colours, used decisively.** One hot colour, one cool colour, white for emphasis, and neutrals for everything else.
5. **Texture as meaning.** The hatched pill says "not the main thing" without adding a colour.
6. **A glow on the active data point.** It tells the eye where to look in a busy chart.
7. **Status as a pill.** Colour plus a word.
8. **Consistent gutters and radii**, so the grid reads as calm even when dense.
9. **A human tone.** A greeting and plain words.

---

## 5. Where it falls short for SchoolTwin

| Issue in the reference | Why it matters here | What we do instead |
|---|---|---|
| **A summary dashboard, not a workspace.** Every region is a card of equal importance. | SchoolTwin is spatial and temporal. The campus map and the timeline are the product. | The **map is the hero**. Cards become the drawers and the report, not the home screen. |
| **Chart axis text at 1.8 : 1 and 2.7 : 1; small figures at 3.5 : 1** | A trends tool lives on its axes. These fail AA contrast. | All text tokens ≥ 4.5 : 1 on every surface (measured, section 7). Axis labels use `text-2`, never `text-3` below 12.5 px. |
| **Colour-only encoding** (pink, blue, white pills) | Fails for colour-blind users and on dim screens. | Every semantic colour has a **shape, line style or pattern** partner (section 7.2). |
| **Very low depth contrast (1.13 : 1)** | On a dim projector or a laptop at low brightness the cards disappear. | Raise steps to 1.11, 1.13, 1.16 **and** keep a visible 1 px border; test at reduced brightness. |
| **Decorative elements:** a peeled page corner; overlapping bubbles whose sizes are not reliable encodings | They add no information and cost attention. | Not adopted. Proportions use plain bars. |
| **Static.** No loading, empty, error, focus, selected or disabled states; no motion | We need all of them, and motion is a stated requirement. | Define states and motion explicitly (sections 6 and 9). |
| **Hue meaning collides with ours.** Pink means "Investigating"; blue means "Triage". | In SchoolTwin, hue already means origin, affected, scenario, control. | Do not reuse the pink + indigo pairing. Fresh palette. |
| **Dark only.** | Some users and rooms need light. | Build tokens so a light theme is a value swap, not a redesign. Ship dark first. |
| **It is a third-party design.** | Reproducing its layout, copy, branding or avatars would not be "from scratch". | Borrow the principles in section 4 only. See the originality checklist in section 10. |

---

## 6. Translating the ideas to SchoolTwin

| Reference device | SchoolTwin use | Data behind it | Motion |
|---|---|---|---|
| Capsule nav | **Step rail:** Replay · Create · Run · Explore · Report · Compare (replaces seven tabs) | current step, completed steps | A lit pill **slides** to the new step; labels cross-fade |
| Two-tone greeting | **Context headline:** "Water cooler breakdown" in white, "Day 183 · Thu 2 Jul" muted. On Replay: "Baseline" and "1 Jan – 31 May 2026" | scenario name, date | Text rises and fades in, 160 ms |
| Segmented range control | **Duration picker** (1 month / 3 months / Custom) and **chart range** (30 d / 90 d / All) | scenario duration; computed end date shown live beneath | Active pill slides; end date counts to the new value |
| Big numerals with delta chips | **Report KPI strip:** attendance, added cost, response time, lost instructional hours, each with a status badge (Computed / Assumed / …) | `report.json` metrics | Numerals count up; chip pops |
| Meter pills | **Meters:** scenario vs control attendance, teacher cover, canteen queue vs capacity. **Hatched = not modeled** | metric values | Fill grows from zero with ease-out |
| Status rows with counts | **Incident phases:** Onset · Responding · Contained · Resolved with counts | `incidents.json` phases | Counts tick |
| Line chart with glow point | **Trends:** baseline context (thin solid), control (dashed), scenario (thick violet), a labelled **seam at Day 150 | 151**, a glowing point and tooltip | Lines draw in; the glow travels with the cursor |
| One saturated card | **"Needs your decision":** pending AI proposals to approve or reject. The single loud surface on a screen | decisions awaiting approval | Gentle entrance; pulses once when new |
| Stacked white cards | **Decision queue** stack | proposals by risk | Top card lifts away when handled |
| Incident cards | **Incident cards:** ID, phase pill, time range, **location chip**, severity, people counts. The assignee slot becomes the location | `incidents.json` | Card rises with 24 ms stagger; "Open on map" flies the camera |
| Bubble statistics | **Not adopted.** Use a stacked bar of where people are by zone type (true proportions) | zone counts | Segments grow |
| Assistant card with quick actions and input | **"Describe an incident":** chips (Fight, Water cooler, Strike, Bus delay) plus a text box, both feeding the **same validated flow** | natural-language parse, then validation | Chip press ripples; invalid input shakes once and explains |

See the board for these components rendered in the adapted system.

---

## 7. The adapted token system

### 7.1 Colour (dark default)

Contrast measured with the WCAG formula for the exact values below.

**Surfaces:** `canvas #0E1014` → `surface-1 #171C23` → `surface-2 #202630` → `surface-3 #2A313C`. Steps: **1.11, 1.13, 1.16 : 1.** Border: `rgba(255,255,255,0.09)`.

**Text:**

| Token | Hex | on canvas | on surface-1 | on surface-2 | on surface-3 |
|---|---|---|---|---|---|
| text-1 | `#F4F6FA` | 17.6 | 15.8 | 14.1 | 12.1 |
| text-2 | `#B4BCC9` | 10.0 | 8.9 | 7.9 | 6.8 |
| text-3 | `#8F99A8` | 6.6 | 5.9 | 5.3 | **4.5** |

The minimum over every text/surface pair is **4.55 : 1**. `text-3` is the floor: use it only on `surface-3` and darker, and never below 12.5 px.

**Meaning colours:**

| Token | Hex | Contrast on surface-1 | on surface-3 | Role |
|---|---|---|---|---|
| origin | `#FF5C3A` | 5.6 | **4.3** | where an incident started (map only) |
| affected | `#FFB224` | 9.5 | 7.3 | directly affected area |
| secondary | `#FFD98A` | 12.7 | 9.7 | knock-on effects |
| response | `#2FD3BE` | 9.1 | 7.0 | staff and response; "Computed" |
| scenario | `#B39CFF` | 7.4 | 5.7 | the branch under study |
| control | `#7FB2D9` | 7.6 | 5.8 | no-incident continuation |
| baseline | `#9AA6B8` | 6.9 | 5.3 | Jan–May history |
| better / worse | `#4ADE80` / `#FB7185` | 9.8 / 6.4 | 7.5 / 4.9 | direction of a change |
| accent | `#7C9BFF` | 6.5 | 5.0 | interactive controls only |

Ink on any pill fill: `#0E1014` gives 6.2 to 14.1 : 1.
`origin` on `surface-3` is 4.3 : 1, so on raised surfaces origin is always a **filled dot with a ring**, never small text.

### 7.2 Colour is never the only signal

Several pairs are too close in brightness to rely on hue: baseline vs control **1.09 : 1**, scenario vs accent **1.14 : 1**, origin vs worse **1.14 : 1**, response vs better **1.08 : 1**. So each pair differs by something else:

| Meaning | Colour | Plus |
|---|---|---|
| Baseline | slate | thin solid line, direct label |
| Control | blue-grey | **dashed** line |
| Scenario | violet | **thick** solid line, glowing point |
| Origin | vermilion | **dot with two rings** and an icon; used on the map and origin chips only, never for deltas |
| Directly affected | amber | solid tint |
| Secondary | pale amber | **dashed outline**, faint tint |
| Response | teal | **dotted trail** |
| Better / worse | green / rose | ▲ ▼ **and the words** "better" / "worse" |
| Not modeled / not configured / unknown | grey | **diagonal hatch**, no marker |
| Assumed | neutral | **dashed outline** |

**Status vocabulary (used everywhere):** Computed (solid) · Configured (tick) · Assumed (dashed) · Not modeled (hatched) · AI-written (sparkle).

### 7.3 Geometry, spacing, type

- **Radii:** 8 (small controls), 12, 16, 22 (cards), full pill. One family, used consistently.
- **Spacing:** 4-point base, 8-point rhythm; gutters 12 or 16; card padding 20 to 24.
- **Elevation:** tonal steps and borders, no heavy shadows. At most **one glow** per screen (the active data point or the origin).
- **Type:** a neutral grotesk (the system stack, or a self-hosted open-licence face with its licence file; to be confirmed). Scale: numerals 38 / 700, title 24, section 20, body 14, small **12.5 minimum**. **Tabular numerals** everywhere numbers change.
- **Density:** one primary action per step; secondary options appear on demand.

---

## 8. The map in a dark theme

The map is the hero, so it sets the luminance hierarchy:

1. **Zones** sit on `surface-2` with hairline borders and quiet labels in `text-2`.
2. **People** are the brightest ordinary marks (small, crisp, no glow).
3. **Selected person** gets a ring and a name label.
4. **Incident origin** is the brightest thing on screen: vermilion dot, two slow pulsing rings.
5. **Affected zones** fill in amber in order of first deviation; **secondary** zones get a pale dashed outline; **response** staff leave a dotted teal trail.
6. **No counter / unknown / not configured** is hatched grey with **no marker**.
7. **Camera-counter layer** shows only counters; places with none are plain, never shaded with hidden counts.

Performance notes for dark and glowing styles: canvas `shadowBlur` for 1,300 dots is expensive, so **pre-render dot sprites** and apply glow only to the selected person and the origin. Avoid `backdrop-filter` on large layers. Render static background gradients once.

---

## 9. Layout recipes (map first)

```
EXPLORE
┌────────────────────────────────────────────────────────────────────┐
│ ◖ SchoolTwin   ( Replay · Create · Run · [Explore] · Report · Compare )   ◗ ? │
├──────────────────────────────────────────────┬─────────────────────┤
│  Water cooler breakdown   Day 183 · Thu 2 Jul │  DRAWER (changes     │
│  ┌ layer │ colour │ floor │ incidents ┐       │  with the step)      │
│  ┌──────────────────────────────────┐        │  ┌ INC-0001 ───────┐ │
│  │            CAMPUS MAP            │        │  │ Medium·Responding│ │
│  │   ◉ origin   ▒ affected          │        │  │ Origin: Corr. 1  │ │
│  └──────────────────────────────────┘        │  │ 140 students …   │ │
│                                               │  └─────────────────┘ │
├──────────────────────────────────────────────┴─────────────────────┤
│ ⏮ ⏪ ▶ ⏩ ⏭  speed │ mode │ ▭▭▭▭▭▭▭▭▭▭▭▭ Day 150 | 151 ▭▭▭▭▭▭ ● flags  │
└────────────────────────────────────────────────────────────────────┘

CREATE (three cards, one visible at a time)
  When ▸ How long ▸ What   → live end date, location picked on the map

REPORT
  KPI strip (numerals + chips + status badges)
  Trends card (baseline / control / scenario, seam, glow point)
  Incident timeline card │ Cost breakdown card
  Possible solutions (Computed vs AI-suggested) │ Assumptions & not-modeled
```

---

## 10. Motion that suits this theme

Aligns with the motion system in the implementation prompt.

- **Numerals** count up with tabular figures; **meter pills** fill from zero with ease-out; **delta chips** pop with a light spring.
- **The capsule's lit pill slides** between steps (shared-element feel); the drawer cross-fades with a short upward slide.
- **Charts** draw in; the **glowing point travels** with the cursor and the tooltip follows with a small delay.
- **Cards** rise 8 px with a 24 ms stagger (max 8 items).
- **Hatching stays still.** It is a meaning cue, so it must not distract.
- **Origin pulse and ripple** are the signature motions on the map.
- **People glide** between rooms instead of teleporting.
- Honour `prefers-reduced-motion` plus an in-app Motion setting; reduced motion swaps movement for brief fades and loses no information. Animate only transform and opacity.

---

## 11. Originality checklist and decisions

**This is "from scratch" if all of these are true:**
- [ ] The layout is map-first, not a card grid of equals.
- [ ] No pink + indigo pairing; the palette and its meanings are our own.
- [ ] No stacked-card peel, bubble chart, copied avatars, copy or branding.
- [ ] Our own signature motifs: origin rings and spread ripple, the **Day 150 | 151 seam**, hatched "not known", glowing cursor point.
- [ ] No framework, template, kit, icon pack or chart library; icons are our own inline SVG.
- [ ] The wordmark and any illustration are original.

**Decisions to confirm with you:**
1. Dark as the default theme, with tokens ready for a light theme later?
2. System font stack, or a self-hosted open-licence font?
3. Keep the capsule step rail as the main navigation?

---

## 12. Paste-ready addendum for the implementation prompt

> **Design direction (add to WP4).** Use a dark, quiet "instrument" theme: tonal surfaces with 1 px borders (steps ≥ 1.11 : 1), capsule geometry for navigation, segmented controls and pills, large tabular numerals with small delta chips, and one glowing active data point per chart. The **map is the hero**; cards live in the drawer, the report and the compare view. Use the token set in `SchoolTwin_Design_Analysis.md` section 7 as the starting point and write the final tokens to `docs/design-system.md`. Build `tests/test_design_tokens.py` that fails if any text token is below 4.5 : 1 on any surface, or any meaning colour is below 3 : 1 on `surface-1`. **Never rely on colour alone**: pair every meaning colour with a shape, line style or pattern (section 7.2). Hatch means "not modeled / not configured / unknown" and is never given a marker. Do not copy any third-party dashboard's layout, palette pairing, copy, icons or decorative devices (no bubble chart, no peeled corner). Pre-render dot sprites; limit glow to the selected person and the incident origin; avoid `backdrop-filter` on large layers. Review screenshots at three viewport sizes and at reduced screen brightness, and report what you actually checked.

---

## Appendix: method and limits

- Colours and text contrast were sampled from the supplied PNG with the WCAG relative-luminance formula. Compression and anti-aliasing mean small-text figures are estimates.
- Token contrast figures are exact calculations for the stated hex values.
- Nothing here has been tested on real devices or with colour-blindness simulation yet; the test and screenshot requirements in section 12 exist to close that gap.
