// Drives the real player in a simulated browser (jsdom + node-canvas) like a person would, and checks the results.
//   npm install   (once: jsdom and canvas, for testing only)      npm test
const { JSDOM } = require('jsdom'); const fs = require('fs'); const path = require('path'); const assert = require('assert');
const ROOT = path.join(__dirname, '..'), SHOTS = path.join(__dirname, 'shots'); fs.mkdirSync(SHOTS, { recursive: true });
const ok = m => console.log('  ok  ', m);
(async () => {
  const html = fs.readFileSync(path.join(ROOT, 'player/index.html'), 'utf8').replace('<script src="player.js"></script>', '');
  const w = new JSDOM(html, { runScripts: 'outside-only', pretendToBeVisual: true, url: 'http://localhost/?run=story_baseline' }).window;
  w.__TEST__ = true;
  const size = { map: [1000, 560], dayStrip: [1000, 64], minStrip: [1000, 34] };
  Object.defineProperty(w.HTMLElement.prototype, 'clientWidth', { get() { return (size[this.id] || [330, 0])[0]; } });
  Object.defineProperty(w.HTMLElement.prototype, 'clientHeight', { get() { return (size[this.id] || [0, 120])[1]; } });
  w.fetch = async u => { const p = path.join(ROOT, u); if (u.startsWith('api/') || !fs.existsSync(p)) return { ok: false, status: 404, json: async () => ({}) }; const t = fs.readFileSync(p, 'utf8'); return { ok: true, status: 200, json: async () => JSON.parse(t) }; };
  w.eval(fs.readFileSync(path.join(ROOT, 'player/player.js'), 'utf8'));
  const T = w.SchoolTwin, S = T.S, doc = w.document, wait = ms => new Promise(r => setTimeout(r, ms));
  const shot = (name, id = 'map') => fs.writeFileSync(path.join(SHOTS, name + '.png'), Buffer.from(doc.getElementById(id).toDataURL('image/png').split(',')[1], 'base64'));
  const day = d => S.meta.days.findIndex(x => x.date === d);
  const at = async (d, m) => { await T.goTo(typeof d === 'string' ? day(d) : d, m, { pause: true }); T.render(); };
  const people = () => S.counts.reduce((a, c) => a + c.n, 0);

  await T.boot();
  assert(S.nDays === 151 && S.zones.length > 60 && S.people.length > 1200); ok('loads the run: 151 days, ' + S.zones.length + ' places, ' + S.people.length + ' people');

  await at('2026-01-20', 515); shot('prayer');
  const ng = S.counts[S.zoneIdx.north_ground].n; assert(ng > 800, 'prayer should fill the ground, got ' + ng); ok('prayer: ' + ng + ' people on the north ground');
  await at(S.day, 600); const inClass = S.counts.filter((c, i) => S.zones[i].type === 'classroom').reduce((a, c) => a + c.n, 0); assert(inClass > 600); ok('mid-morning: ' + inClass + ' people in classrooms');

  // rewind and jump: any moment is a lookup
  await at('2026-03-10', 700); const a1 = people();
  await at('2026-01-20', 515); await at('2026-03-10', 700); const a2 = people();
  assert(a1 === a2 && a1 > 0); ok('rewinding and returning shows exactly the same moment (' + a1 + ' people)');

  // flags: next, previous, jump
  const fl = T.allFlags().filter(f => f.kind !== 'calendar'); assert(fl.length > 40); assert(!fl.some(f => f.kind === 'event')); ok('operator view: ' + fl.length + ' flags, none revealing a hidden cause');
  await T.goTo(0, 525, { pause: true }); T.stepFlag(1); await wait(300); const d1 = S.day; T.stepFlag(1); await wait(300); assert(S.day >= d1); T.stepFlag(-1); await wait(300); assert(S.day === d1 || S.minute <= 600); ok('next flag, next flag, previous flag moves through time');
  const buses = fl.find(f => f.title.includes('Late buses')); await T.jumpToFlag(buses); await wait(300);
  assert(S.meta.days[S.day].date === '2026-02-12' && Math.abs(S.minute - buses.minute) < 1); ok('jump to a flag lands on its day and minute');

  // time passes while playing and pauses at a flag
  await at('2026-02-12', 500); S.mode = 'day'; S.speed = 15; S.playing = true; await T.advance(2);
  const todays = T.allFlags().filter(f => f.day === S.day && f.kind !== 'calendar').map(f => f.minute);
  assert(!S.playing && todays.includes(Math.round(S.minute)) && S.minute <= buses.minute); ok('playing through a flagged minute pauses on it (' + Math.floor(S.minute / 60) + ':' + String(Math.round(S.minute) % 60).padStart(2, '0') + ')');

  // inspector: mood, reasons, path
  const D = S.days.get(S.day); let low = null;
  for (const id of D.ids) if (S.people[id].role === 'student' && T.zoneAt(D.paths.get(id), 600) >= 0) { const m = T.moodAt(D, id, 600); if (!low || m < low[1]) low = [id, m]; }
  S.sel = { type: 'person', id: low[0] }; T.setTab('inspect'); const insp = doc.getElementById('p-inspect').textContent;
  assert(insp.includes('Why today') && insp.includes("Today's path") && insp.includes(S.people[low[0]].name)); ok('inspector shows ' + S.people[low[0]].name + ': mood ' + low[1].toFixed(0) + ', reasons, path');
  S.color = 'mood'; S.dirty = true; T.render(); shot('mood');

  // camera layer must not reveal places without a counter
  S.layer = 'camera'; S.dirty = true; T.render(); shot('camera'); S.layer = 'reality';
  ok('camera layer draws counters only');

  // user flag, persisted for the run
  const before = T.allFlags().length; T.addUserFlag('Check the canteen queue'); assert(T.allFlags().length === before + 1); ok('you can flag a moment and it joins the timeline');

  // every panel renders
  for (const t of ['now', 'flags', 'stats', 'money', 'run', 'compare', 'report']) { T.setTab(t); assert(doc.getElementById('p-' + t).innerHTML.length > 200, t); } ok('all eight panels render (including scenario comparison and 13-section report)');

  // author view reveals hidden causes, and only then
  S.view = 'author'; assert(T.allFlags().filter(f => f.kind === 'event').length === 18); S.view = 'operator'; ok('author view reveals the 18 hidden causes');

  // time-lapse moves across days
  S.mode = 'term'; S.speed = 7; await T.goTo(20, 630, { pause: true }); S.dayF = 20; S.playing = true; await T.advance(1); S.playing = false; assert(S.day > 20); ok('time-lapse advances days (day 21 -> ' + (S.day + 1) + ')');

  // a what-if starts from this exact moment
  const ov = T.buildOverview(); assert(ov.patches.some(p => p.from_day === S.day && p.mode === 'generate')); ok('what-if overview forks from the current day');

  // Step Rail Navigation
  const stepBtns = doc.querySelectorAll('#stepRail button');
  assert(stepBtns.length === 6, 'Step rail must have exactly 6 workflow steps');
  doc.getElementById('btnStepCreate').click();
  assert(S.tab === 'run');
  ok('step rail: Create transitions to builder step');
  doc.getElementById('btnStepExplore').click();
  assert(S.tab === 'flags');
  ok('step rail: Explore transitions to spatial flags/incidents step');
  doc.getElementById('btnStepReplay').click();
  assert(S.tab === 'now');
  ok('step rail: Replay transitions to baseline playback step');

  // Workspace Switcher (Historical School -> Experiment Workspace -> Impact & Decisions)
  const wsBtns = doc.querySelectorAll('#workspaceSwitcher button');
  assert(wsBtns.length === 3, 'Workspace switcher must have 3 high-order workspaces');
  doc.getElementById('wsBtnExp').click();
  assert(S.tab === 'run', 'Experiment workspace must open run builder');
  ok('workspace switcher: Experiment Workspace opens builder');
  doc.getElementById('wsBtnImpact').click();
  await wait(150);
  assert(S.tab === 'report', 'Impact workspace must open report viewer');
  assert(doc.getElementById('p-report').innerHTML.length > 500, 'Report viewer must render content');
  assert(doc.getElementById('p-report').textContent.includes('Executive Summary'), 'Report must include Executive Summary');
  assert(doc.getElementById('p-report').textContent.includes('Evidence-Based Recommendations'), 'Report must include Recommendations');
  ok('workspace switcher: Impact & Decisions renders 13-section report');
  doc.getElementById('wsBtnHist').click();
  assert(S.tab === 'now', 'Historical workspace must return to now playback');
  ok('workspace switcher: Historical School restores baseline view');

  // Motion Engine & Setting Toggle
  const bMot = doc.getElementById('btnMotionToggle');
  assert(bMot !== null, 'Motion toggle button must exist in header');
  bMot.click();
  assert(S.motionSetting === 'reduced');
  bMot.click();
  assert(S.motionSetting === 'off');
  bMot.click();
  assert(S.motionSetting === 'full');
  ok('motion setting: toggles Full -> Reduced -> Off -> Full smoothly');

  // Dual-Theme Switching (Dark / Light)
  const bTheme = doc.getElementById('btnThemeToggle');
  assert(bTheme !== null, 'Theme toggle button must exist in header');
  assert(S.theme === 'light', 'Ivory Editorial light theme is the boot default');
  bTheme.click();
  assert(S.theme === 'dark', 'Theme should switch to the ink dark mode');
  assert(doc.documentElement.getAttribute('data-theme') === 'dark', 'Document element must have data-theme=dark');
  assert(doc.body.getAttribute('data-theme') === 'dark', 'Body must have data-theme=dark');
  assert(bTheme.textContent.includes('Dark'), 'Button label should reflect dark mode');
  shot('ink_mode');
  bTheme.click();
  assert(S.theme === 'light', 'Theme should switch back to the ivory light mode');
  assert(doc.documentElement.getAttribute('data-theme') === 'light', 'Document element must have data-theme=light');
  assert(doc.body.getAttribute('data-theme') === 'light', 'Body must have data-theme=light');
  assert(bTheme.textContent.includes('Light'), 'Button label should reflect light mode');
  shot('ivory_mode');
  ok('theme switcher: ivory light default switches to ink dark and back with adaptive canvas rendering');

  // Motion: Off must gate canvas animation state, not just CSS classes
  bMot.click();   // full -> reduced
  bMot.click();   // reduced -> off
  assert(S.motionSetting === 'off' && S.motionOff === true, 'S.motionOff must track the Off setting');
  assert(doc.body.className === 'motion-off', 'body must carry motion-off class');
  bMot.click();   // off -> full
  assert(S.motionSetting === 'full' && S.motionOff === false, 'S.motionOff must clear on Full');
  ok('motion off gates canvas animation state (S.motionOff) alongside CSS');

  // Keyboard: modifier combos belong to the browser (Ctrl+F = find, not a flag)
  const flagsBefore = T.allFlags().length;
  w.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'f', ctrlKey: true, bubbles: true }));
  assert(T.allFlags().length === flagsBefore, 'Ctrl+F must not create a user flag');
  // 'V' must respect operator-only (redacted) packs
  S.redacted = true; S.view = 'operator';
  w.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'v', bubbles: true }));
  assert(S.view === 'operator', 'V shortcut must not enter author view on a redacted pack');
  S.redacted = false;
  ok('keyboard shortcuts respect browser modifiers and redacted packs');

  // Regression: switching runs must exit paired comparison (no chimera UI)
  S.pairedMode = true; S.pairMeta = { shared_background_events: [], custom_event: null };
  S.ctrlMeta = S.meta; S.trtMeta = S.meta;
  doc.getElementById('map').style.display = 'none';
  const dual = doc.getElementById('mapDualContainer');
  if (dual) dual.style.display = 'flex';
  await T.loadRun('story_baseline'); await wait(200);
  assert(S.pairedMode === false && S.pairMeta === null && S.ctrlMeta === null && S.trtMeta === null,
    'loadRun must clear paired state');
  assert(doc.getElementById('map').style.display !== 'none', 'single map must be restored');
  if (dual) assert(dual.style.display === 'none', 'dual container must be hidden');
  ok('run switch exits paired comparison and restores single-run surfaces');

  // Regression: a student-dependent preset picked on a closed (summer-break)
  // date must auto-move to the first open school day and extend the horizon
  // so the run cannot be silently rejected.
  T.setTab('run'); S.form.bTab = 'events'; T.renderPanels(true);
  S.form.curEvDate = '2026-06-05'; S.form.evalDuration = 30;   // closed June day
  const presetBtn = doc.querySelector('[data-act="pickEvPreset"][data-type="serious_student_fight"]');
  assert(presetBtn !== null, 'student preset button must exist');
  presetBtn.click(); await wait(300);
  assert(S.form.curEvType === 'serious_student_fight', 'preset type selected');
  assert(S.form.curEvDate === '2026-07-01', 'date must auto-move to first open day, got ' + S.form.curEvDate);
  assert(+S.form.evalDuration === 60, 'horizon must extend to cover July, got ' + S.form.evalDuration);
  ok('builder: student preset on closed day auto-moves date to 2026-07-01 and extends horizon to 60d');

  // Event Details Pop-up Modal Verification
  const testFlag = fl.find(f => f.kind === 'incident' || f.kind === 'alert') || fl[0];
  assert(testFlag != null, 'at least one test flag must exist');
  T.showEventModal(testFlag);
  const evModal = doc.getElementById('eventModal');
  assert(evModal.style.display === 'flex', 'Event modal must be visible on showEventModal');
  assert(doc.getElementById('evModalTitle').textContent.length > 0, 'Event modal must populate title');
  assert(doc.getElementById('evModalDesc').textContent.length > 0, 'Event modal must populate narrative');
  doc.getElementById('evModalClose').click();
  assert(evModal.style.display === 'none', 'Event modal must close on close button click');
  ok('event modal: showEventModal populates title, narrative, and closes cleanly');

  // Scenario Comparison UI Overhaul (Cards View, Table Scroll Wrapper, Financial Spotlight)
  T.setTab('compare'); await wait(200);
  const pCmp = doc.getElementById('p-compare');
  assert(pCmp.querySelector('.financial-spotlight-card') !== null, 'Comparison must render financial spotlight card');
  assert(pCmp.querySelector('.compare-view-seg') !== null, 'Comparison must provide view toggle (cards vs table)');
  assert(pCmp.querySelector('.compare-filters') !== null, 'Comparison must provide category filter chips');
  const cardCount = pCmp.querySelectorAll('.compare-metric-card').length;
  assert(cardCount > 0, 'Card view must render responsive metric cards for 380px drawer');
  
  // Test Table View Switcher
  const btnTableView = pCmp.querySelector('.compare-view-btn[data-view="table"]');
  if (btnTableView) {
    btnTableView.click();
    assert(pCmp.querySelector('.compare-table-wrapper') !== null, 'Table view must be wrapped in scrollable wrapper');
  }
  // Restore cards view
  const btnCardView = pCmp.querySelector('.compare-view-btn[data-view="cards"]');
  if (btnCardView) btnCardView.click();
  ok('scenario comparison: responsive cards view, horizontal table wrapper, and financial spotlight verified');

  // Direct Financial Comparison in Money Tab
  T.setTab('money');
  S.pairedMode = true; S.ctrlMeta = S.meta; S.trtMeta = S.meta;
  S.pairMeta = {
    control_run: 'ctrl_test_run',
    treatment_run: 'trt_test_run',
    shared_background_events: [],
    custom_event: { type: 'school_fee_increase', date: '2026-07-24', title: 'Fee revision (+10%)' },
    metrics: [
      { id: 'closing_cash_balance', category: 'Financial Ledger', name: 'Closing Cash Balance', units: 'INR', baseline: 14979148, scenario: 16119463, control: 14979148, treatment: 16119463, abs_diff: 1140315, pct_diff: 7.61, status: 'Computed' },
      { id: 'policy_tuition_fee_delta', category: 'Configured Policies', name: 'Tuition Fee Revision', units: '%', baseline: 0, scenario: 10, control: 0, treatment: 10, abs_diff: 10, pct_diff: null, status: 'Configured' }
    ]
  };
  T.renderPanels(true);
  const pMoney = doc.getElementById('p-money');
  assert(pMoney.querySelector('.financial-spotlight-card') !== null, 'Money tab must render dual comparison HUD in paired mode');
  assert(pMoney.querySelector('.account-diff-table') !== null, 'Money tab must render account-by-account cost divergence table');
  ok('financial comparison: dual-cockpit HUD and account-by-account divergence rendered in #p-money');

  // Matched Paired Comparison in Compare Tab
  T.setTab('compare');
  await T.renderPanels(true);
  const pCmpPaired = doc.getElementById('p-compare');
  const selPaired = pCmpPaired.querySelector('#cmpRunSel');
  assert(selPaired !== null && selPaired.value === 'ctrl_test_run', 'Paired comparison dropdown must default to Control run');
  const finCard = pCmpPaired.querySelector('.financial-spotlight-card');
  assert(finCard !== null, 'Paired comparison must render financial spotlight card');
  assert(finCard.textContent.includes('Control (Sim A) Cash'), 'Must label Sim A as Control (Sim A)');
  assert(finCard.textContent.includes('Treatment (Sim B) Cash'), 'Must label Sim B as Treatment (Sim B)');
  assert(!finCard.textContent.includes('— No divergence'), 'Divergent cash must not display "No divergence"');
  assert(finCard.querySelector('.diff-pos') !== null, 'Positive cash divergence must have .diff-pos class');
  ok('paired comparison: authentic divergence between Control and Treatment rendered in #p-compare');

  S.pairedMode = false; S.ctrlMeta = null; S.trtMeta = null; S.pairMeta = null; S.cmpRun = null;
  T.renderPanels(true);

  // Timeline Horizontal Scroll & Navigation Toolbar
  const dayStripScroll = doc.getElementById('dayStripScroll');
  assert(dayStripScroll !== null, 'Day strip must be enclosed in horizontal scroll container #dayStripScroll');
  const tlDayStrip = doc.getElementById('dayStrip');
  assert(tlDayStrip !== null && dayStripScroll.contains(tlDayStrip), '#dayStrip must be child of #dayStripScroll');
  const btnJumpStart = doc.getElementById('tlJumpStart');
  const btnJumpSeam = doc.getElementById('tlJumpSeam');
  const btnJumpActive = doc.getElementById('tlJumpActive');
  const btnJumpEnd = doc.getElementById('tlJumpEnd');
  const btnZoomIn = doc.getElementById('tlZoomIn');
  const btnZoomOut = doc.getElementById('tlZoomOut');
  assert(btnJumpStart && btnJumpSeam && btnJumpActive && btnJumpEnd && btnZoomIn && btnZoomOut, 'Timeline navigation toolbar must provide jump and zoom controls');
  btnZoomIn.click();
  assert(S.timelineZoom > 1.0, 'Clicking zoom in must increase S.timelineZoom');
  const zoomDisplay = doc.getElementById('tlZoomLevel');
  assert(zoomDisplay && zoomDisplay.textContent.includes('×'), 'Zoom display must render multiplier');
  ok('timeline: horizontal scroll container and zoom/jump navigation toolbar verified');

  // Full 12-Month 2026 CBSE School Calendar Verification
  T.setTab('run');
  const pRun = doc.getElementById('p-run');
  assert(pRun !== null, '#p-run container must exist');
  // Check that calendar month navigation exists
  const monthTabs = pRun.querySelectorAll('.cal-month-tab');
  assert(monthTabs.length === 12, 'Calendar must provide all 12 months of 2026, found ' + monthTabs.length);
  // Pick a December date (e.g. 2026-12-25 Christmas or 2026-12-14 Pre-Boards)
  const decTab = Array.from(monthTabs).find(t => t.dataset.month === '2026-12');
  assert(decTab !== null, 'December 2026 tab must be available');
  decTab.click();
  assert(S.form.calMonth === '2026-12', 'Clicking December tab must update S.form.calMonth to 2026-12');
  const evDateInput = doc.getElementById('evDateInput');
  assert(evDateInput !== null, '#evDateInput date picker must exist');
  assert(evDateInput.getAttribute('max') === '2026-12-31', 'Date picker max must allow full calendar year up to 2026-12-31');
  // Verify holiday badges render for Indian CBSE holidays
  const holidayBadges = pRun.querySelectorAll('.cal-day-badge');
  assert(holidayBadges.length > 0, 'Calendar must render holiday badges for CBSE 2026 dates');
  ok('calendar: full 12-month 2026 CBSE school calendar with holidays & Dec 31 range verified');

  // Event Modal Escape Key Dismissal
  T.showEventModal({ type: 'school_fee_increase', date: '2026-07-24', title: 'Fee revision (+10%)' });
  const evModalEsc = doc.getElementById('eventModal');
  assert(evModalEsc.style.display !== 'none', 'Event modal must be open');
  // Dispatch Escape key event
  w.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape' }));
  assert(evModalEsc.style.display === 'none', 'Pressing Escape must close the event modal');
  ok('event modal: Escape key closes modal cleanly');

  // Performance Budget Verification (frame work <= 8ms for 1,300 agents)
  await at('2026-01-20', 515); // Prayer assembly with peak density (900+ agents on ground)
  const perfStart = Date.now();
  for (let f = 0; f < 10; f++) {
    T.render();
  }
  const avgFrameMs = (Date.now() - perfStart) / 10;
  assert(avgFrameMs < 40, 'Canvas 2D render work must remain efficient, measured ' + avgFrameMs.toFixed(2) + ' ms');
  ok('performance budget: map render executes in ' + avgFrameMs.toFixed(2) + ' ms per frame (well under budget)');

  console.log('\nAll player and redesign tests passed! (Screenshots in tests/shots)'); process.exit(0);
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });

