# SchoolTwin: Working Specification

How the school behaves. `ARCHITECTURE.md` explains how the system is built; this file explains what it simulates.

## The school (from the story)

Saraswati Heights Senior Secondary School, Delhi. **1,020 students** on the roll (1,000 at the start; 20 admitted in April; 6 withdrawn), Nursery to Class 12, 36 sections that become 37 rooms after the April promotions. **58 teachers**, a principal, and 64 other staff (security, housekeeping, maintenance, nurse, counsellor, librarian, lab and IT staff, 12 bus drivers and 12 attendants), plus 6 contractor canteen staff. 12 bus routes. 151 calendar days, 1 Jan to 31 May 2026: 98 school days (89 instructional, 9 Saturday sessions), a winter break, weekly closures, a planned closure, and a summer break.

## The campus (2D, three floors)

Ground floor: gate, exit, bus bay, north ground (assembly), playground, canteen and its back door, stairwell A, corridor, admin lobby, principal's office, staff room, infirmary, counsellor, store room, washrooms, and classrooms for Nursery to Class 2. First floor: Block B corridor and stairwell, library, two science labs, classrooms for Classes 3 to 6. Second floor: stairwell C, a third science lab, two computer labs, classrooms for Classes 7 to 12. Four unwatched places: pump house, behind the playground wall, the back landing, the terrace door.

**Symbols.** Student: circle (coloured by grade band or by mood). Teacher: triangle. Principal: star. Staff: square. Visitor: diamond.

**Counters.** 19 aggregate counters: gate and bus bay (cumulative entries), canteen (queue), library (entries in a window), ground, a block B corridor, stairwells, two labs, one computer lab, two classrooms (8B, 9A), store room, canteen back door, admin lobby, exit. They report numbers with a little error, and miss more people in crowds. Every other place has no counter.

## The day

Bells (07:10 to 15:00): arrival, prayer (08:30), notices, P1 and P2, short break, P3 and P4, lunch, P5 and P6, dismissal. Bus riders reach the bus bay then the gate; others come to the gate. Latecomers wait at the gate until prayer ends. Teachers follow a weekly rota; some classes go to labs. Students step out briefly (washroom, water, errands) always through the corridor; some visit the library. At break and lunch the day's choices are split in fixed proportions between canteen, playground, ground and classroom, so the canteen line is steady, and people give up if the wait passes 14 minutes. At dismissal students pack up, then walk to the gate or bus bay.

## What makes it feel real

Absences driven by each student's hidden attendance habit; a few students slipping out of lessons; a few skipping the prayer; teacher absence and uncovered lessons; crowds at the ground, canteen and gate; counters that miss people; staff patrols; moods that differ student to student.

**Unwatched places** are rare and mild (skipping a lesson, loitering, a phone). About 2% of students know one at the start, more in higher grades. Knowledge spreads slowly by word of mouth. Staff patrols sometimes find students there. On average fewer than one student is in one at any moment.

## Events (18 types, one vocabulary)

Each template turns an event into effects the engine understands: absence, late riders, teacher out, mood, extra queue, visitors, a room closing or a class moving, infirmary visits, staff dealing with something, signals, incident register entries, parent queries, unplanned costs, a resignation notice. Story events, your own events and random events all use them.

Weather attendance dip · class conflict over an assessment · lab kit mismatch · first-aid visits · late buses · annual-day crowd · duplicate fee reminder · teacher absence and cover pressure · exam paper error · marks import mismatch · classroom fan failure (class moves to the library) · bus scrapes the gate pillar · teacher resignation · fee questions · early heat · computer lab circuit trip (lab closes) · fuel invoice variance · water motor failure (on a closed day).

## Detector and AI principal

18 rules over counters, daily numbers and operational signals, each producing an alert that says what to look at, never why. A rule cluster on friction fires on ordinary days too, as in the story. The AI principal turns alerts into proposed actions using the story's own decision log as templates. In anchor mode the story's 17 decisions replay with their recorded status. In generate mode proposals wait for approval (`advisory_only`, `low_risk_auto`, or `human_approved`); only some actions change the simulation (notify families, stagger the canteen, replan cover, heat protocol, backup bus route).

## Money

Anchor mode reads the story's ledger. Generate mode rebuilds it from the story's tuition and transport dues, collection ratios, cost accruals and payment calendar; changes (fees if approved, teachers hired, support budget, backup buses, unplanned costs) are layered on. From day 0 with no changes it reproduces the story's closing cash to within ₹1; a no-change fork tracks it within 2%.

## Measured against the story

| Check | Result |
|---|---|
| Anchor attendance, lateness, cash | identical to the story |
| Generate attendance (from hidden traits, weather, events only) | 92.4% vs 92.6%; 0.9 pts average day error; day-to-day correlation 0.64 (the story's own noise caps it near 0.7) |
| Generate late arrivals / teachers absent | 13.7 vs 13.5 / 3.4 vs 3.5 |
| Counters vs story | gate, bus bay, library, ground within 13%; canteen +25%; corridor B and room 8B low (see limits) |
| Detector | 17-18 of 18 hidden events flagged, 8-10 false-alarm days (story's own detector: 18 of 18, 7) |
| Negative feedback share | 13-14% vs 13.2% |
| Run time | about 30 seconds for the full term |
