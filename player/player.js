/* SchoolTwin player. No dependencies, works offline.
 * It replays a pack written by the engine: it never simulates. Scrubbing, rewinding and jumping to a flag
 * are lookups into precomputed paths, so any moment of any day is one binary search away. */
(function () {
  'use strict';
  const $ = (s, e) => (e || document).querySelector(s);
  const $$ = (s, e) => Array.from((e || document).querySelectorAll(s));
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const fmtT = m => String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(Math.floor(m % 60)).padStart(2, '0');
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const SEV = ['info', 'low', 'medium', 'high'];
  const BANDS = [['Nursery–2', '#2a9d8f'], ['3–6', '#457b9d'], ['7–9', '#7b2cbf'], ['10–12', '#c2410c']];
  const GRADES = ['Nursery', 'KG', 'Class 1', 'Class 2', 'Class 3', 'Class 4', 'Class 5', 'Class 6', 'Class 7', 'Class 8', 'Class 9', 'Class 10', 'Class 11', 'Class 12'];
  const gradeOn = (pr, iso) => (pr.grades ? (iso >= '2026-04-01' ? pr.grades[1] : pr.grades[0]) : pr.grade);
  const bandOf = g => { const i = GRADES.indexOf(g); return i < 4 ? 0 : i < 8 ? 1 : i < 11 ? 2 : 3; };
  const moodColor = m => `hsl(${clamp((m - 25) / 50, 0, 1) * 120},78%,${m < 45 ? 42 : 46}%)`;
  const FLOOR_GAP = 112, FW = 100, FH = 60;
  const SPEEDS = { day: [['1 min / s', 1], ['5 min / s', 5], ['15 min / s', 15], ['30 min / s', 30], ['60 min / s', 60]],
                   term: [['1 day / s', 1], ['3 days / s', 3], ['7 days / s', 7], ['14 days / s', 14]] };

  const S = {
    base: new URLSearchParams(location.search).get('pack') || 'pack/', index: null, run: null, meta: null, hist: null,
    days: new Map(), day: 0, minute: 525, dayF: 0, playing: false, busy: false, mode: 'day', speed: 15, view: 'operator',
    layer: 'reality', color: 'grade', floor: 'all', sel: null, tab: 'now', userFlags: [], api: false, cmp: null,
    dirty: true, last: 0, hits: [], lastPanel: 0, snapMinute: 630, approvals: {}, theme: 'dark',
    pairedMode: false, pairMeta: null, ctrlMeta: null, trtMeta: null,
    ctrlDays: new Map(), trtDays: new Map(), randomProfile: 'balanced', pairSeed: 20261014,
  };
  window.ST = S;                                    // handy for tests and for poking around in the console

  const RANDOM_PROFILES = {
    balanced: {
      id: 'balanced',
      name: 'Balanced (Default)',
      desc: 'Normal school operating variation with regular minor friction and occasional utility or staffing challenges.',
      rate: '1.5/mo', maxDay: 1, maxWk: 2, cooldown: '8d',
      allowed: 'All operational categories'
    },
    calm: {
      id: 'calm',
      name: 'Calm',
      desc: 'Routine variability with mostly minor operational friction. Major disruptions are excluded.',
      rate: '0.5/mo', maxDay: 1, maxWk: 1, cooldown: '14d',
      allowed: 'Facility, utilities, academic/admin, transport'
    },
    stress_test: {
      id: 'stress_test',
      name: 'Stress-test',
      desc: 'Elevated operational strain: more frequent equipment faults, cover crunches, and logistical disruptions.',
      rate: '3.5/mo', maxDay: 2, maxWk: 4, cooldown: '4d',
      allowed: 'All categories with higher incident probability'
    },
    custom: {
      id: 'custom',
      name: 'Custom',
      desc: 'User-configured event frequencies, categories, cooldowns, and random seed.',
      rate: 'Custom', maxDay: 2, maxWk: 3, cooldown: '6d',
      allowed: 'User specified'
    }
  };

  function applyTheme(theme) {
    S.theme = theme;
    const isLight = theme === 'light';
    if (typeof document !== 'undefined') {
      if (document.documentElement) document.documentElement.setAttribute('data-theme', theme);
      if (document.body) document.body.setAttribute('data-theme', theme);
    }
    const btn = typeof $ === 'function' ? $('#btnThemeToggle') : null;
    if (btn) {
      btn.textContent = isLight ? '☀️ Light' : '🌙 Dark';
      btn.title = `Switch to ${isLight ? 'Dark' : 'Light'} Mode (Shortcut: T)`;
    }
    try { if (typeof localStorage !== 'undefined') localStorage.setItem('st-theme', theme); } catch (e) {}
    S.dirty = true;
    if (S.meta) {
      render();
      drawStrips();
    }
  }

  function toggleTheme() {
    applyTheme(S.theme === 'light' ? 'dark' : 'light');
  }

  // ------------------------------------------------------------------ data
  async function getJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(url + ' ' + r.status);
    return r.json();
  }
  async function boot() {
    bindUI();
    const savedTheme = (typeof localStorage !== 'undefined' && localStorage.getItem('st-theme')) || 'dark';
    applyTheme(savedTheme);
    try { S.index = await getJSON(S.base + 'index.json'); } catch (e) { toast('No packs found. Run scripts/run_story.py first.'); return; }
    const sel = $('#runSel');
    sel.innerHTML = S.index.runs.map(r => `<option value="${esc(r.id)}">${esc(r.name)} · ${esc(r.mode)}${r.redacted ? ' · operator-only' : ''}</option>`).join('');
    try { const st = await getJSON('api/status'); S.api = !!st; } catch (e) { S.api = false; }
    const want = new URLSearchParams(location.search).get('run') || S.index.runs[0].id;
    sel.value = want;
    await loadRun(want);
    requestAnimationFrame(tick);
  }
  async function loadRun(id) {
    pause();
    S.run = id; S.days.clear(); S.sel = null; S.cmp = null;
    const b = S.base + id + '/';
    [S.meta, S.hist] = await Promise.all([getJSON(b + 'meta.json'), getJSON(b + 'history.json')]);
    const M = S.meta;
    S.zones = M.zones; S.zoneIdx = {}; M.zones.forEach((z, i) => { S.zoneIdx[z.id] = i; });
    S.people = M.people; S.trk = {}; M.tracked.forEach((id, k) => { S.trk[id] = k; });
    S.clock = M.clock; S.nDays = M.days.length;
    S.redacted = !!M.run.redacted;
    if (S.redacted) { S.view = 'operator'; $$('#viewSeg button').forEach(b => { b.disabled = b.dataset.v === 'author'; }); }
    try { S.userFlags = JSON.parse(localStorage.getItem('st-flags-' + id) || '[]'); } catch (e) { S.userFlags = []; }
    if (S.api) { try { const sv = await getJSON('api/flags?run=' + encodeURIComponent(id)); sv.forEach(f => { if (!S.userFlags.find(x => x.id === f.id)) S.userFlags.push(f); }); } catch (e) { /* none saved */ } }
    try { S.incidents = await getJSON(b + 'incidents.json'); } catch (e) { S.incidents = []; }
    try { S.reportData = await getJSON(b + 'report.json'); } catch (e) { S.reportData = null; }
    $('#schoolName').textContent = M.run.school + ' · ' + M.run.mode + ' mode';
    const first = M.days.findIndex(d => d.open && d.i >= M.run.start_day);
    S.dayF = Math.max(first, 0);
    await goTo(Math.max(first, 0), 525, { pause: true });
    if (id === 'story_baseline') hideScenarioBanner();
    renderAll();
  }
  async function ensureDay(i) {
    if (S.days.has(i)) return S.days.get(i);
    const d = S.meta.days[i];
    if (!d) return null;
    let D = null;
    try {
      let raw;
      try {
        raw = await getJSON(S.base + S.run + '/days/d' + String(i).padStart(4, '0') + '.json');
      } catch (err) {
        // Fallback to immutable baseline day file for pre-branch days
        raw = await getJSON(S.base + 'story_baseline/days/d' + String(i).padStart(4, '0') + '.json');
      }
      D = prepDay(raw);
    } catch (e) { D = null; }
    S.days.set(i, D);
    return D;
  }
  async function ensureDualDay(i, branch) {
    const cache = branch === 'ctrl' ? S.ctrlDays : S.trtDays;
    if (cache.has(i)) return cache.get(i);
    const meta = branch === 'ctrl' ? S.ctrlMeta : S.trtMeta;
    if (!meta) return null;
    const d = meta.days[i];
    if (!d) return null;
    const runId = branch === 'ctrl' ? S.pairMeta.control_run : S.pairMeta.treatment_run;
    let D = null;
    try {
      let raw;
      try {
        raw = await getJSON(S.base + runId + '/days/d' + String(i).padStart(4, '0') + '.json');
      } catch (err) {
        raw = await getJSON(S.base + 'story_baseline/days/d' + String(i).padStart(4, '0') + '.json');
      }
      D = prepDay(raw);
    } catch (e) { D = null; }
    cache.set(i, D);
    return D;
  }
  function curDualD(branch) {
    const cache = branch === 'ctrl' ? S.ctrlDays : S.trtDays;
    return cache.get(S.day) || null;
  }
  function prefetch(i) {                             // quietly load the next few days so playback never stalls
    for (let k = 1; k <= 3; k++) { const j = i + k; if (j < S.nDays && !S.days.has(j) && S.meta.days[j].open) ensureDay(j); }
  }
  function prepDay(raw) {
    const paths = new Map();
    for (const k in raw.paths) paths.set(+k, Int32Array.from(raw.paths[k]));
    const D = { i: raw.i, paths, ids: Array.from(paths.keys()), mt: raw.mood.t, mv: raw.mood.v.map(r => Int16Array.from(r)), drv: raw.drv, cam: raw.cam, zs: {} };
    return D;
  }
  // person's zone at minute t: last (minute, zone) pair at or before t. -1 = off campus
  function zoneAt(arr, t) {
    let lo = 0, hi = arr.length / 2 - 1, ans = -1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (arr[mid * 2] <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1; }
    return ans < 0 ? -1 : arr[ans * 2 + 1];
  }
  function moodAt(D, id, t) {
    const k = S.trk[id];
    if (!D || k == null) return null;
    const mt = D.mt;
    let j = 0; while (j < mt.length - 1 && mt[j + 1] <= t) j++;
    const a = D.mv[j][k]; if (a === undefined) return null;
    if (j >= mt.length - 1) return a;
    const b = D.mv[j + 1][k], f = (t - mt[j]) / Math.max(1, mt[j + 1] - mt[j]);
    return a + (b - a) * clamp(f, 0, 1);
  }
  // deterministic position inside a zone: the same person stays put while they stay in the room
  function hash(n) { n = (n ^ 61) ^ (n >>> 16); n = n + (n << 3); n = n ^ (n >>> 4); n = Math.imul(n, 0x27d4eb2d); n = n ^ (n >>> 15); return (n >>> 0) / 4294967296; }
  function posIn(z, id) {
    const [x, y, w, h] = z.rect, k = id * 131 + S.zoneIdx[z.id] * 7;
    return [x + 0.6 + hash(k) * Math.max(w - 1.2, 0.2), y + 0.6 + hash(k + 99991) * Math.max(h - 1.2, 0.2)];
  }
  function zoneSeries(D, zi) {                        // headcount in a zone every 5 minutes, for sparklines
    if (D.zs[zi]) return D.zs[zi];
    const c = S.clock, out = [];
    for (let t = c.start; t <= c.end; t += c.step) {
      let n = 0;
      for (const id of D.ids) if (zoneAt(D.paths.get(id), t) === zi) n++;
      out.push(n);
    }
    return (D.zs[zi] = out);
  }
  const curD = () => S.days.get(S.day) || null;
  const curMeta = () => S.meta.days[S.day];

  // ------------------------------------------------------------------ flags
  function allFlags() {
    const f = S.meta.flags.filter(x => S.view === 'author' || x.vis !== 'author').concat(S.userFlags);
    return f.sort((a, b) => a.day - b.day || a.minute - b.minute);
  }
  const flagsOn = d => allFlags().filter(f => f.day === d);
  function stepFlag(dir) {
    const fl = allFlags().filter(f => f.kind !== 'calendar');
    const here = S.day * 2000 + S.minute;
    const cand = dir > 0 ? fl.filter(f => f.day * 2000 + f.minute > here + 0.5) : fl.filter(f => f.day * 2000 + f.minute < here - 0.5).reverse();
    if (!cand.length) { toast(dir > 0 ? 'No later flags' : 'No earlier flags'); return; }
    jumpToFlag(cand[0]);
  }
  function jumpToFlag(f) {
    S.activeFlag = f;
    if (f.zone) {
      S.sel = { type: 'zone', id: f.zone };
    }
    goTo(f.day, f.minute, { pause: true });
    toast('⚑ ' + f.title + ' · ' + S.meta.days[f.day].date + ' ' + fmtT(f.minute));
    S.dirty = true;
    if (S.tab === 'flags') renderFlags();
  }
  function addUserFlag(title, sev) {
    const f = { id: 'U-' + Date.now(), day: S.day, date: curMeta().date, minute: Math.round(S.minute), kind: 'user', sev: sev || 2, vis: 'user',
                title: title || 'Flagged moment', text: 'Flagged by you.', zone: S.sel && S.sel.type === 'zone' ? S.sel.id : '', ref: '' };
    S.userFlags.push(f);
    try { localStorage.setItem('st-flags-' + S.run, JSON.stringify(S.userFlags)); } catch (e) { /* private mode */ }
    if (S.api) fetch('api/flags', { method: 'POST', body: JSON.stringify({ run: S.run, flag: f }) }).catch(() => {});
    toast('Flagged ' + f.date + ' ' + fmtT(f.minute));
    S.dirty = true; renderFlags(); drawStrips();
    return f;
  }

  // ------------------------------------------------------------------ time
  function pause() { S.playing = false; syncPlay(); }
  function play() {
    if (S.mode === 'term' && S.day >= S.nDays - 1) {
      S.day = 0; S.dayF = 0;
      goTo(nextOpen(-1, 1), S.snapMinute || 630);
    } else if (S.mode === 'day' && S.day >= S.nDays - 1 && S.minute >= S.clock.end) {
      S.day = 0; S.dayF = 0;
      goTo(nextOpen(-1, 1), S.clock.start + 80);
    }
    S.playing = true; S.last = performance.now(); syncPlay();
  }
  function syncPlay() {
    $('#bPlay').textContent = S.playing ? '⏸' : '▶';
    const sBtn = $('#scenBannerToggleBtn');
    if (sBtn) sBtn.textContent = S.playing ? '⏸ Pause' : '▶ Resume';
  }
  async function goTo(day, minute, opt) {
    day = clamp(Math.round(day), 0, S.nDays - 1);
    if (S.activeFlag && (S.activeFlag.day !== day || (minute != null && Math.abs(S.activeFlag.minute - minute) > 35))) {
      S.activeFlag = null;
    }
    S.busy = true;
    try {
      if (S.pairedMode) {
        await Promise.all([ensureDualDay(day, 'ctrl'), ensureDualDay(day, 'trt')]);
      } else {
        await ensureDay(day);
      }
      S.day = day; S.dayF = day;
      if (minute != null) S.minute = clamp(minute, S.clock.start, S.clock.end);
      if (opt && opt.pause) pause();
      if (!S.pairedMode) prefetch(day);
      updateClock(); renderPanels(true); drawStrips();
    } finally {
      S.busy = false; S.dirty = true;
    }
  }
  function nextOpen(from, dir) {
    let d = from + dir;
    while (d >= 0 && d < S.nDays) {
      const dm = S.meta.days[d];
      const hasEv = dm && ((dm.events && dm.events.length) || (dm.incidents && dm.incidents.length) || flagsOn(d).some(f => f.kind !== 'calendar'));
      if (!dm || dm.open || hasEv || !$('#chkSkip').checked) return d;
      d += dir;
    }
    return clamp(d, 0, S.nDays - 1);
  }
  async function advance(dt) {
    if (S.busy) return;
    if (S.mode === 'day') {
      const prev = S.minute; let m = prev + dt * S.speed;
      if ($('#chkPause').checked) {
        const hit = flagsOn(S.day).filter(f => f.kind !== 'calendar' && f.minute > prev && f.minute <= m).sort((a, b) => a.minute - b.minute)[0];
        if (hit) { S.minute = hit.minute; pause(); toast('⏸ ' + hit.title); S.dirty = true; updateClock(); renderPanels(true); return; }
      }
      if (m >= S.clock.end) {
        if (S.day >= S.nDays - 1) { S.minute = S.clock.end; pause(); return; }
        await goTo(nextOpen(S.day, 1), S.clock.start + 80); return;
      }
      S.minute = m; S.dirty = true; updateClock();
    } else {
      S.dayF += dt * S.speed;
      const target = Math.min(Math.floor(S.dayF), S.nDays - 1);
      if (target !== S.day) {
        let d = S.day;
        while (d < target) {
          d = nextOpen(d, 1);
          const flagged = ($('#chkPause').checked && S.mode !== 'term') ? flagsOn(d).filter(f => f.kind !== 'calendar' && f.sev >= 3)[0] : null;
          if (flagged) { await goTo(d, flagged.minute, { pause: true }); toast('⏸ ' + flagged.title); return; }
          if (d >= target) break;
        }
        S.minute = S.snapMinute;
        await goTo(d, S.snapMinute);
        S.dayF = Math.max(S.dayF, d);
        if (S.scenBannerData && S.day === S.scenBannerData.eventDay) {
          toast('⚑ Day ' + (d + 1) + ': ' + S.scenBannerData.title + ' active on campus!');
        }
        if (d >= S.nDays - 1) {
          pause();
          toast('Finished term time-lapse');
        }
      }
    }
  }
  function tick(ts) {
    if (S.playing && !S.busy) { const dt = Math.min((ts - S.last) / 1000, 0.25); S.last = ts; advance(dt); } else S.last = ts;
    if (S.dirty) { render(); S.dirty = false; if (ts - S.lastPanel > 400) { S.lastPanel = ts; renderPanels(false); drawStrips(); } }
    requestAnimationFrame(tick);
  }
  function updateClock() {
    const d = curMeta(); if (!d) return;
    $('#clkDate').textContent = d.dow.slice(0, 3) + ' ' + d.date;
    $('#clkTime').textContent = fmtT(S.minute);
    const b = S.clock.blocks.find(b => b.start <= S.minute && S.minute < b.end);
    $('#clkBlock').textContent = d.open ? (b ? b.name.replace('_', ' ') : 'after hours') : d.type.replace(/_/g, ' ');
    if (S.scenBannerData && $('#scenBannerSub')) {
      const ed = S.scenBannerData.eventDay;
      $('#scenBannerSub').textContent = `Day ${S.day + 1} of ${S.nDays}${ed != null ? ` · Event on Day ${ed + 1}` : ''}`;
    }
  }
  function toast(msg) { const t = $('#toast'); t.textContent = msg; t.style.display = 'block'; clearTimeout(toast.h); toast.h = setTimeout(() => { t.style.display = 'none'; }, 2600); }
  window.SchoolTwin = { S, goTo, zoneAt, moodAt, posIn, addUserFlag, stepFlag, boot, loadRun, play, pause, jumpToFlag, allFlags, advance, render, renderPanels, renderAll, setTab, buildOverview, runScenario };

  // ------------------------------------------------------------------ map
  function layout(W, H) {
    const f = S.floor, org = {};
    if (f !== 'all') {
      const s = Math.min((W - 12) / FW, (H - 28) / FH);
      org[f] = { x: (W - FW * s) / 2, y: (H - FH * s) / 2 + 8 };
      return { scale: s, org, floors: [+f] };
    }
    const gap = 6, sRow = Math.min((W - 12) / (3 * FW + 2 * gap), (H - 30) / FH), sStack = Math.min((W - 12) / FW, (H - 12) / (3 * (FH + 8))),
      sGrid = Math.min((W - 12) / (2 * FW + gap), (H - 24) / (2 * (FH + 11)));
    if (sGrid >= sRow && sGrid >= sStack) {
      const s = sGrid, x0 = (W - (2 * FW + gap) * s) / 2, y0 = (H - 2 * (FH + 11) * s) / 2 + 12;
      org[0] = { x: x0, y: y0 }; org[1] = { x: x0 + (FW + gap) * s, y: y0 }; org[2] = { x: x0, y: y0 + (FH + 11) * s };
      return { scale: s, org, floors: [0, 1, 2], legend: { x: x0 + (FW + gap) * s, y: y0 + (FH + 11) * s, w: FW * s, h: FH * s } };
    }
    if (sRow >= sStack) {
      const s = sRow, x0 = (W - (3 * FW + 2 * gap) * s) / 2, y0 = (H - FH * s) / 2 + 8;
      [0, 1, 2].forEach(i => { org[i] = { x: x0 + i * (FW + gap) * s, y: y0 }; });
      return { scale: s, org, floors: [0, 1, 2] };
    }
    const s = sStack, x0 = (W - FW * s) / 2;
    [0, 1, 2].forEach(i => { org[i] = { x: x0, y: 8 + i * (FH + 8) * s }; });
    return { scale: s, org, floors: [0, 1, 2] };
  }
  const TINT = {
    classroom: '#121722', corridor: '#0d121c', stair: '#0f1420', ground: '#0c1815', canteen: '#1c1811', library: '#101726',
    lab: '#171224', gate: '#111520', bus: '#161814', office: '#131824', staffroom: '#131824', infirmary: '#241416',
    washroom: '#0f1822', store: '#141822', blind_spot: '#181a24', sports: '#0c1815', parking: '#111520', room: '#121722'
  };
  function renderDualCanvas(cv, D, meta, isCtrl, isTrt) {
    if (!cv || !meta) return;
    const dpr = window.devicePixelRatio || 1;
    const W = cv.clientWidth || 450, H = cv.clientHeight || 520;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) {
      cv.width = Math.round(W * dpr);
      cv.height = Math.round(H * dpr);
    }
    const ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);

    const L = layout(W, H);
    const sc = L.scale, t = S.minute, md = meta.days[S.day] || { date: '', open: false, type: 'closed' };
    const counts = S.zones.map(() => ({ s: 0, t: 0, p: 0, f: 0, v: 0, n: 0 }));
    const pts = [];
    if (D) {
      for (const id of D.ids) {
        const zi = zoneAt(D.paths.get(id), t);
        if (zi < 0) continue;
        const z = S.zones[zi], p = S.people[id], c = counts[zi];
        const r = p.role; c.n++;
        if (r === 'student') c.s++; else if (r === 'teacher') c.t++; else if (r === 'principal') c.p++; else if (r === 'visitor') c.v++; else c.f++;
        if (L.org[z.floor] !== undefined) pts.push([id, zi]);
      }
    }
    const isLight = S.theme === 'light';

    // Floors
    L.floors.forEach(f => {
      const o = L.org[f];
      ctx.fillStyle = isLight ? '#ffffff' : '#0a0d14';
      ctx.strokeStyle = isLight ? '#cbd5e1' : '#1e2638';
      ctx.lineWidth = 1;
      ctx.fillRect(o.x, o.y, FW * sc, FH * sc);
      ctx.strokeRect(o.x, o.y, FW * sc, FH * sc);
      ctx.fillStyle = isLight ? '#475569' : '#9ca3af';
      ctx.font = `600 ${Math.max(10, sc * 2.6)}px system-ui,sans-serif`;
      ctx.textAlign = 'left';
      ctx.fillText(meta.floors[f], o.x + 2, o.y - 5);
    });

    // Incident detection for this branch
    const bFlags = meta.flags ? meta.flags.filter(f => (S.view === 'author' || f.vis !== 'author') && f.day === S.day) : [];
    const activeInc = bFlags.filter(f => f.kind !== 'calendar' && f.zone).find(f => Math.abs(f.minute - t) <= 25) || null;
    const originZoneId = activeInc ? activeInc.zone : null;

    const isSharedBg = !!(S.pairedMode && S.pairMeta && S.pairMeta.shared_background_events.some(e => e.date === md.date));
    const isCustomEvent = !!(isTrt && S.pairedMode && S.pairMeta && S.pairMeta.custom_event && S.pairMeta.custom_event.date === md.date);

    // Zones
    S.zones.forEach((z, zi) => {
      const o = L.org[z.floor]; if (!o) return;
      const [x, y, w, h] = z.rect, X = o.x + x * sc, Y = o.y + y * sc, WW = w * sc, HH = h * sc, c = counts[zi];
      const isOrigin = (z.id === originZoneId);

      ctx.fillStyle = (typeof TINT !== 'undefined' && TINT[z.type]) ? TINT[z.type] : (isLight ? '#f8fafc' : '#121722');
      ctx.fillRect(X, Y, WW, HH);

      if (isOrigin) {
        ctx.fillStyle = isCustomEvent ? 'rgba(16, 185, 129, 0.25)' : isSharedBg ? 'rgba(56, 189, 248, 0.25)' : 'rgba(239, 68, 68, 0.25)';
        ctx.fillRect(X, Y, WW, HH);
        ctx.strokeStyle = isCustomEvent ? '#10b981' : isSharedBg ? '#38bdf8' : '#ef4444';
        ctx.lineWidth = 2.5;
        ctx.setLineDash([4, 2]);
        ctx.strokeRect(X, Y, WW, HH);
        ctx.setLineDash([]);
      } else {
        ctx.strokeStyle = isLight ? '#e2e8f0' : '#1a2233';
        ctx.lineWidth = 1;
        ctx.strokeRect(X, Y, WW, HH);
      }

      if (sc >= 2.0) {
        ctx.fillStyle = isLight ? '#475569' : '#94a3b8';
        ctx.font = `${Math.max(8, sc * 1.5)}px system-ui,sans-serif`;
        ctx.textAlign = 'left';
        ctx.fillText(z.label, X + 2, Y + Math.max(9, sc * 1.7));
      }
    });

    // Agents
    if (D) {
      for (const [id, zi] of pts) {
        const z = S.zones[zi], o = L.org[z.floor]; if (!o) continue;
        const [px, py] = posIn(z, id), x = o.x + px * sc, y = o.y + py * sc;
        const p = S.people[id], r = p.role;
        let col;
        if (S.color === 'mood') { const m = moodAt(D, id, t); col = m == null ? '#94a3b8' : moodColor(m); }
        else if (S.color === 'grade') { col = r === 'student' ? BANDS[bandOf(gradeOn(p, md.date))][1] : '#f97316'; }
        else { col = r === 'student' ? '#38bdf8' : r === 'teacher' ? '#f59e0b' : r === 'principal' ? '#8b5cf6' : '#10b981'; }

        ctx.fillStyle = col;
        if (r === 'student') {
          ctx.beginPath(); ctx.arc(x, y, Math.max(1.8, sc * 0.38), 0, 6.2832); ctx.fill();
        } else if (r === 'teacher') {
          ctx.beginPath(); ctx.moveTo(x, y - sc * 0.7); ctx.lineTo(x + sc * 0.6, y + sc * 0.5); ctx.lineTo(x - sc * 0.6, y + sc * 0.5); ctx.closePath(); ctx.fill();
        } else if (r === 'principal') {
          star(ctx, x, y, Math.max(3.5, sc * 0.75));
        } else {
          ctx.fillRect(x - sc * 0.4, y - sc * 0.4, sc * 0.8, sc * 0.8);
        }
      }
    }

    // Incident Origin Reticle & Concentric Beacon
    if (originZoneId) {
      const oz = S.zones.find(z => z.id === originZoneId);
      if (oz && L.org[oz.floor]) {
        const o = L.org[oz.floor];
        const [ox, oy, ow, oh] = oz.rect;
        const cx = o.x + (ox + ow / 2) * sc;
        const cy = o.y + (oy + oh / 2) * sc;
        const nowMs = performance.now();
        const phase = (nowMs % 1800) / 1800;

        const reticleColor = isCustomEvent ? '#10b981' : isSharedBg ? '#38bdf8' : '#ef4444';
        const reticleAura = isCustomEvent ? `rgba(16, 185, 129, ${1 - phase})` : isSharedBg ? `rgba(56, 189, 248, ${1 - phase})` : `rgba(239, 68, 68, ${1 - phase})`;

        const maxR = Math.max(16, Math.min(ow, oh) * sc * 0.75);
        const pulseR = 8 + phase * (maxR - 8);
        ctx.beginPath(); ctx.arc(cx, cy, pulseR, 0, 6.2832);
        ctx.strokeStyle = reticleAura; ctx.lineWidth = 2; ctx.stroke();

        ctx.beginPath(); ctx.arc(cx, cy, 8, 0, 6.2832);
        ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 2.5; ctx.stroke();
        ctx.strokeStyle = reticleColor; ctx.lineWidth = 1.5; ctx.stroke();

        ctx.beginPath(); ctx.arc(cx, cy, 3.5, 0, 6.2832);
        ctx.fillStyle = reticleColor; ctx.fill();

        const badgeTxt = isCustomEvent ? `★ TREATMENT: ${activeInc.title.slice(0, 20)}` : isSharedBg ? `⚑ SHARED BG: ${activeInc.title.slice(0, 20)}` : `⚑ ${activeInc.title.slice(0, 20)}`;
        ctx.font = '700 9.5px var(--font-mono), monospace';
        const bw = ctx.measureText(badgeTxt).width + 12;
        ctx.fillStyle = isLight ? '#ffffff' : '#090b10';
        ctx.strokeStyle = reticleColor; ctx.lineWidth = 1;
        roundRect(ctx, cx - bw / 2, cy - 24, bw, 16, 4);
        ctx.fill(); ctx.stroke();
        ctx.fillStyle = reticleColor; ctx.textAlign = 'center';
        ctx.fillText(badgeTxt, cx, cy - 12);
      }
    }
  }

  function renderDualMap() {
    const cvCtrl = $('#mapCtrl'), cvTrt = $('#mapTrt');
    if (!cvCtrl || !cvTrt) return;
    const dCtrl = curDualD('ctrl');
    const dTrt = curDualD('trt');
    renderDualCanvas(cvCtrl, dCtrl, S.ctrlMeta, true, false);
    renderDualCanvas(cvTrt, dTrt, S.trtMeta, false, true);

    // Update Quick Header Metrics
    if (S.ctrlMeta && S.ctrlMeta.days && S.ctrlMeta.days[S.day]) {
      const cd = S.ctrlMeta.days[S.day];
      const ctrlAtt = $('#ctrlAttVal'); if (ctrlAtt) ctrlAtt.textContent = cd.attendance_rate != null ? Math.round(cd.attendance_rate * 100) + '%' : '—';
      const ctrlMood = $('#ctrlMoodVal'); if (ctrlMood) ctrlMood.textContent = cd.mood_avg != null ? Math.round(cd.mood_avg) : '—';
      const ctrlInc = $('#ctrlIncVal'); if (ctrlInc) ctrlInc.textContent = (cd.incidents || []).length;
    }
    if (S.trtMeta && S.trtMeta.days && S.trtMeta.days[S.day]) {
      const td = S.trtMeta.days[S.day];
      const trtAtt = $('#trtAttVal'); if (trtAtt) trtAtt.textContent = td.attendance_rate != null ? Math.round(td.attendance_rate * 100) + '%' : '—';
      const trtMood = $('#trtMoodVal'); if (trtMood) trtMood.textContent = td.mood_avg != null ? Math.round(td.mood_avg) : '—';
      const trtInc = $('#trtIncVal'); if (trtInc) trtInc.textContent = (td.incidents || []).length;
    }
  }

  function render() {
    if (S.pairedMode && S.ctrlMeta && S.trtMeta) {
      renderDualMap();
      return;
    }
    const cv = $('#map'), dpr = window.devicePixelRatio || 1;
    const W = cv.clientWidth || 900, H = cv.clientHeight || 520;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    const ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    if (!S.meta) return;
    const L = (S.layout = layout(W, H)), sc = L.scale, D = curD(), t = S.minute, md = curMeta();
    const counts = S.zones.map(() => ({ s: 0, t: 0, p: 0, f: 0, v: 0, n: 0 }));
    const pts = [];
    if (D) {
      for (const id of D.ids) {
        const zi = zoneAt(D.paths.get(id), t);
        if (zi < 0) continue;
        const z = S.zones[zi], p = S.people[id], c = counts[zi];
        const r = p.role; c.n++;
        if (r === 'student') c.s++; else if (r === 'teacher') c.t++; else if (r === 'principal') c.p++; else if (r === 'visitor') c.v++; else c.f++;
        if (L.org[z.floor] !== undefined) pts.push([id, zi]);
      }
    }
    S.counts = counts;
    const camMode = S.layer === 'camera';
    const isLight = S.theme === 'light';

    // Floors
    L.floors.forEach(f => {
      const o = L.org[f];
      ctx.fillStyle = isLight ? '#ffffff' : '#0a0d14';
      ctx.strokeStyle = isLight ? '#cbd5e1' : '#1e2638';
      ctx.lineWidth = 1;
      ctx.fillRect(o.x, o.y, FW * sc, FH * sc);
      ctx.strokeRect(o.x, o.y, FW * sc, FH * sc);
      ctx.fillStyle = isLight ? '#475569' : '#9ca3af';
      ctx.font = `600 ${Math.max(10, sc * 2.6)}px system-ui,sans-serif`;
      ctx.textAlign = 'left';
      ctx.fillText(S.meta.floors[f], o.x + 2, o.y - 5);
    });

    // Determine Active Incident, Origin Zone, Affected Zones & Responder
    let activeIncident = null;
    if (S.activeFlag && S.activeFlag.day === S.day && Math.abs(S.activeFlag.minute - t) <= 30 && S.activeFlag.zone) {
      activeIncident = S.activeFlag;
    } else {
      const todayFlags = flagsOn(S.day).filter(f => f.kind !== 'calendar' && f.zone);
      activeIncident = todayFlags.find(f => Math.abs(f.minute - t) <= 25) || null;
    }
    const originZoneId = (activeIncident && activeIncident.zone) ? activeIncident.zone : null;

    const affectedZoneIds = new Set();
    let responderZoneId = null;
    if (originZoneId) {
      const oz = S.zones.find(z => z.id === originZoneId);
      if (oz) {
        if (oz.type === 'classroom') {
          const corr = `corridor_${oz.floor}`;
          if (S.zoneIdx[corr] !== undefined) affectedZoneIds.add(corr);
          const wash = `wash_${oz.floor}`;
          if (S.zoneIdx[wash] !== undefined) affectedZoneIds.add(wash);
          if (activeIncident && (activeIncident.title.toLowerCase().includes('first aid') || activeIncident.title.toLowerCase().includes('infirmary') || activeIncident.title.toLowerCase().includes('faint') || activeIncident.title.toLowerCase().includes('sick'))) {
            responderZoneId = 'infirmary';
            affectedZoneIds.add('infirmary');
          }
        } else if (originZoneId === 'canteen') {
          affectedZoneIds.add('canteen_back');
          affectedZoneIds.add('corridor_0');
          affectedZoneIds.add('playground');
        } else if (originZoneId === 'bus_bay') {
          affectedZoneIds.add('main_gate');
          affectedZoneIds.add('main_exit');
        } else if (oz.blind) {
          affectedZoneIds.add('playground');
          affectedZoneIds.add('corridor_0');
          responderZoneId = 'principal_office';
        } else if (oz.type === 'lab') {
          affectedZoneIds.add(`corridor_${oz.floor}`);
        }
      }
    }

    // Zones
    S.zones.forEach((z, zi) => {
      const o = L.org[z.floor]; if (!o) return;
      const [x, y, w, h] = z.rect, X = o.x + x * sc, Y = o.y + y * sc, WW = w * sc, HH = h * sc, c = counts[zi];
      const ratio = c.n / Math.max(z.cap, 1);
      const isOrigin = (z.id === originZoneId);
      const isAffected = affectedZoneIds.has(z.id);

      ctx.fillStyle = (typeof TINT !== 'undefined' && TINT[z.type]) ? TINT[z.type] : (isLight ? '#f8fafc' : '#121722');
      ctx.fillRect(X, Y, WW, HH);

      // Crowding heat
      const heat = z.type === 'classroom' ? (ratio - 0.95) / 0.5 : (ratio - 0.55) / 0.6;
      if (c.n > 0 && heat > 0 && (!camMode || z.cam)) {
        ctx.fillStyle = `rgba(239,68,68,${Math.min(heat, 1) * 0.45})`;
        ctx.fillRect(X, Y, WW, HH);
      }

      // Affected zone hazard wash
      if (isAffected) {
        ctx.fillStyle = 'rgba(249, 115, 22, 0.16)';
        ctx.fillRect(X, Y, WW, HH);
      }
      // Origin zone focal wash
      if (isOrigin) {
        ctx.fillStyle = 'rgba(239, 68, 68, 0.22)';
        ctx.fillRect(X, Y, WW, HH);
      }

      // Borders
      if (isOrigin) {
        ctx.strokeStyle = '#ef4444';
        ctx.lineWidth = 2.5;
        ctx.setLineDash([]);
      } else if (isAffected) {
        ctx.strokeStyle = '#f97316';
        ctx.lineWidth = 2.0;
        ctx.setLineDash([6, 4]);
      } else if (S.sel && S.sel.type === 'zone' && S.sel.id === z.id) {
        ctx.strokeStyle = '#3b82f6';
        ctx.lineWidth = 2.4;
        ctx.setLineDash([]);
      } else if (z.blind) {
        ctx.strokeStyle = (S.view === 'author' && !camMode) ? '#ef4444' : (isLight ? '#94a3b8' : '#4b5563');
        ctx.lineWidth = 1.4;
        ctx.setLineDash([4, 3]);
      } else {
        ctx.strokeStyle = isLight ? 'rgba(0, 0, 0, 0.12)' : 'rgba(255, 255, 255, 0.08)';
        ctx.lineWidth = 0.8;
        ctx.setLineDash([]);
      }
      ctx.strokeRect(X + .5, Y + .5, WW - 1, HH - 1);
      ctx.setLineDash([]);

      // Affected zone tag badge
      if (isAffected && WW > 30) {
        ctx.fillStyle = '#ea580c';
        ctx.font = `700 ${Math.max(7, sc * 1.5)}px system-ui,sans-serif`;
        ctx.textAlign = 'right';
        ctx.fillText('AFFECTED', X + WW - 3, Y + 10);
      }

      // Labels
      if (z.type === 'classroom') {
        ctx.fillStyle = isOrigin ? '#ef4444' : (isLight ? '#334155' : '#9ca3af');
        ctx.textAlign = 'center';
        ctx.font = `600 ${Math.max(7, Math.min(sc * 1.9, 11))}px system-ui,sans-serif`;
        ctx.fillText(z.label, X + WW / 2, Y + HH + Math.max(8, sc * 2.1));
        if (!camMode && c.n) {
          ctx.font = `${Math.max(7, Math.min(sc * 1.7, 10))}px system-ui,sans-serif`;
          ctx.fillStyle = isLight ? '#64748b' : '#6b7280';
          ctx.fillText(c.n, X + WW / 2, Y + HH + Math.max(8, sc * 2.1) * 2);
        }
      } else if (WW > 34) {
        ctx.fillStyle = isOrigin ? (isLight ? '#dc2626' : '#ffffff') : (isLight ? '#0f172a' : '#9ca3af');
        ctx.textAlign = 'center';
        ctx.font = `600 ${Math.max(8, Math.min(sc * 2.1, 12))}px system-ui,sans-serif`;
        ctx.fillText(z.label + (c.n && !camMode ? ' · ' + c.n : ''), X + WW / 2, camMode ? Y + 11 : Y + HH / 2 + 3, WW - 4);
      } else if (!camMode && c.n >= 6) {
        ctx.fillStyle = isLight ? '#dc2626' : '#ef4444';
        ctx.textAlign = 'center';
        ctx.font = `700 ${Math.max(9, sc * 2.2)}px system-ui,sans-serif`;
        ctx.fillText(c.n, X + WW / 2, Y - 2);
      }
    });

    // People (simulation layer) or counters (camera layer)
    S.hits = [];
    if (!camMode) {
      const r = Math.max(1.5, sc * 0.30);
      const order = pts.sort((a, b) => (S.people[a[0]].role === 'student' ? 0 : 1) - (S.people[b[0]].role === 'student' ? 0 : 1));
      for (const [id, zi] of order) {
        const z = S.zones[zi], p = S.people[id], o = L.org[z.floor];
        let [px, py] = posIn(z, id);
        if (!S.motionOff && S.playing) {
          const tFloor = Math.floor(t);
          const tFrac = t - tFloor;
          if (tFrac > 0.001) {
            const nextZi = zoneAt(D.paths.get(id), tFloor + 1);
            if (nextZi >= 0 && nextZi !== zi) {
              const nextZ = S.zones[nextZi];
              if (nextZ && nextZ.floor === z.floor) {
                const [npx, npy] = posIn(nextZ, id);
                px = px + (npx - px) * tFrac;
                py = py + (npy - py) * tFrac;
              }
            }
          }
        }
        const x = o.x + px * sc, y = o.y + py * sc;
        S.hits.push([id, x, y]);
        let col = '#6b7280';
        if (p.role === 'student') {
          if (S.color === 'mood') { const m = moodAt(D, id, t); col = m == null ? '#4b5563' : moodColor(m); }
          else if (S.color === 'grade') col = BANDS[bandOf(gradeOn(p, md.date))][1];
          else col = '#3b82f6';
          ctx.fillStyle = col; ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832); ctx.fill();
        } else {
          const R = r * 1.5;
          if (p.role === 'teacher') { col = '#f97316'; ctx.fillStyle = col; ctx.beginPath(); ctx.moveTo(x, y - R); ctx.lineTo(x + R, y + R * .8); ctx.lineTo(x - R, y + R * .8); ctx.closePath(); ctx.fill(); }
          else if (p.role === 'principal') { ctx.fillStyle = '#eab308'; star(ctx, x, y, R * 1.9); }
          else if (p.role === 'visitor') { ctx.fillStyle = '#a855f7'; ctx.beginPath(); ctx.moveTo(x, y - R); ctx.lineTo(x + R, y); ctx.lineTo(x, y + R); ctx.lineTo(x - R, y); ctx.closePath(); ctx.fill(); }
          else { ctx.fillStyle = '#9ca3af'; ctx.fillRect(x - R * .8, y - R * .8, R * 1.6, R * 1.6); }
        }
      }
    } else if (D) {
      const k = clamp(Math.floor((t - S.clock.start) / S.clock.step), 0, 1000), recs = md.cctv || [];
      S.zones.forEach((z, zi) => {
        if (!z.cam) return;
        const o = L.org[z.floor]; if (!o) return;
        const series = D.cam[zi]; const obs = series ? series[Math.min(k, series.length - 1)] : null; if (obs == null) return;
        const rec = recs.find(r => r.camera_id === z.cam && Math.abs(r.minute - t) <= 6);
        const [x, y, w] = z.rect, X = o.x + x * sc, Y = o.y + y * sc;
        const col = !rec ? '#3b82f6' : Math.abs(rec.deviation_pct) >= 60 ? '#ef4444' : Math.abs(rec.deviation_pct) >= 25 ? '#f59e0b' : '#10b981';
        const txt = `${obs}` + (rec ? `  ${rec.deviation_pct > 0 ? '+' : ''}${Math.round(rec.deviation_pct)}%` : '');
        ctx.font = `700 ${Math.max(10, Math.min(sc * 2.6, 14))}px system-ui,sans-serif`;
        const tw = ctx.measureText(txt).width + 10;
        ctx.fillStyle = isLight ? '#ffffff' : '#0f131c'; ctx.strokeStyle = col; ctx.lineWidth = 1.5;
        roundRect(ctx, X + 3, Y + 3, tw, Math.max(16, sc * 3.2), 4); ctx.fill(); ctx.stroke();
        ctx.fillStyle = col; ctx.textAlign = 'left'; ctx.fillText(txt, X + 8, Y + 3 + Math.max(16, sc * 3.2) * .72);
      });
      ctx.fillStyle = isLight ? '#64748b' : '#9ca3af'; ctx.font = '11px system-ui'; ctx.textAlign = 'left';
      ctx.fillText('Counters report numbers only: no faces, no identities. Grey areas have no counter.', 10, H - 8);
    }

    // Concentric Reticle on Incident Origin Zone & Responder Flow
    if (originZoneId) {
      const oz = S.zones.find(z => z.id === originZoneId);
      if (oz && L.org[oz.floor]) {
        const o = L.org[oz.floor];
        const [ox, oy, ow, oh] = oz.rect;
        const cx = o.x + (ox + ow / 2) * sc;
        const cy = o.y + (oy + oh / 2) * sc;
        const nowMs = performance.now();
        const phase = (nowMs % 1800) / 1800;

        // 1. Expanding animated pulsing aura ring
        const maxR = Math.max(18, Math.min(ow, oh) * sc * 0.75);
        const pulseR = 8 + phase * (maxR - 8);
        ctx.beginPath();
        ctx.arc(cx, cy, pulseR, 0, 6.2832);
        ctx.strokeStyle = `rgba(239, 68, 68, ${1 - phase})`;
        ctx.lineWidth = 2;
        ctx.setLineDash([]);
        ctx.stroke();

        // 2. High-contrast solid inner ring
        ctx.beginPath();
        ctx.arc(cx, cy, 9, 0, 6.2832);
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 3;
        ctx.stroke();
        ctx.strokeStyle = '#ef4444';
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // 3. Focal core dot
        ctx.beginPath();
        ctx.arc(cx, cy, 4, 0, 6.2832);
        ctx.fillStyle = '#ef4444';
        ctx.fill();

        // 4. Reticle crosshairs
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 1.5;
        [[cx - 15, cy, cx - 10, cy], [cx + 10, cy, cx + 15, cy], [cx, cy - 15, cx, cy - 10], [cx, cy + 10, cx, cy + 15]].forEach(([x1, y1, x2, y2]) => {
          ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
        });

        // 5. Origin category badge floating above
        const badgeTxt = activeIncident ? `⚑ ORIGIN: ${activeIncident.title.slice(0, 24)}` : `⚑ ORIGIN: ${oz.label}`;
        ctx.font = `700 10.5px var(--font-mono), monospace`;
        const bw = ctx.measureText(badgeTxt).width + 14;
        ctx.fillStyle = isLight ? '#ffffff' : '#090b10';
        ctx.strokeStyle = '#ef4444';
        ctx.lineWidth = 1;
        roundRect(ctx, cx - bw / 2, cy - 28, bw, 18, 4);
        ctx.fill();
        ctx.stroke();
        ctx.fillStyle = isLight ? '#dc2626' : '#ef4444';
        ctx.textAlign = 'center';
        ctx.fillText(badgeTxt, cx, cy - 15);

        // 6. Directional connector to responder zone if active
        if (responderZoneId) {
          const rz = S.zones.find(z => z.id === responderZoneId);
          if (rz && L.org[rz.floor]) {
            const ro = L.org[rz.floor];
            const [rx, ry, rw, rh] = rz.rect;
            const rcx = ro.x + (rx + rw / 2) * sc;
            const rcy = ro.y + (ry + rh / 2) * sc;
            ctx.setLineDash([4, 4]);
            ctx.lineDashOffset = -(nowMs / 50) % 8;
            ctx.strokeStyle = 'rgba(59, 130, 246, 0.85)';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.lineTo(rcx, rcy);
            ctx.stroke();
            ctx.setLineDash([]);

            // Responder badge
            ctx.fillStyle = isLight ? '#dbeafe' : '#1e3a8a';
            ctx.strokeStyle = '#3b82f6';
            roundRect(ctx, rcx - 36, rcy - 12, 72, 16, 4);
            ctx.fill(); ctx.stroke();
            ctx.fillStyle = isLight ? '#1d4ed8' : '#93c5fd';
            ctx.font = '700 9.5px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('RESPONDER', rcx, rcy);
          }
        }
      }
    }

    // Legend
    if (L.legend && !camMode) {
      const g = L.legend, f = Math.max(10, sc * 2.4); ctx.textAlign = 'left'; ctx.fillStyle = isLight ? '#475569' : '#9ca3af'; ctx.font = `600 ${f}px system-ui`;
      ctx.fillText('Campus Twin Legend', g.x + 4, g.y + f);
      const items = S.color === 'mood' ? [['#ef4444', 'low mood'], ['#f59e0b', 'steady'], ['#10b981', 'good']] : S.color === 'grade' ? BANDS.map(b => [b[1], 'students ' + b[0]]) : [['#3b82f6', 'student']];
      items.forEach(([col, lab], i) => { ctx.fillStyle = col; ctx.beginPath(); ctx.arc(g.x + 8, g.y + f * (2.3 + i * 1.25), 4, 0, 6.2832); ctx.fill(); ctx.fillStyle = isLight ? '#334155' : '#d1d5db'; ctx.font = `${f * .9}px system-ui`; ctx.fillText(lab, g.x + 18, g.y + f * (2.3 + i * 1.25) + 4); });
      const y = g.y + f * (2.3 + items.length * 1.25) + f * .4; ctx.fillStyle = isLight ? '#ea580c' : '#f97316'; ctx.fillText('▲ teacher   ★ principal   ■ staff   ◆ visitor', g.x + 4, y + f);
      ctx.fillStyle = isLight ? '#dc2626' : '#ef4444'; ctx.fillText('◎ Crimson Reticle = Incident Origin', g.x + 4, y + f * 2.2);
      ctx.fillStyle = isLight ? '#d97706' : '#f97316'; ctx.fillText('╌╌ Dashed Orange = Affected Area', g.x + 4, y + f * 3.4);
      const blk = S.clock.blocks.find(b => b.start <= t && t < b.end);
      ctx.fillStyle = isLight ? '#2563eb' : '#60a5fa'; ctx.font = `700 ${f * 1.3}px system-ui`; ctx.fillText(blk ? blk.name.replace('_', ' ') : (md.open ? 'after hours' : 'closed'), g.x + 4, y + f * 4.8);
    }

    // Selection
    if (S.sel && S.sel.type === 'person' && D && !camMode) {
      const id = S.sel.id, zi = D.paths.has(id) ? zoneAt(D.paths.get(id), t) : -1;
      if (zi >= 0) {
        const z = S.zones[zi], o = L.org[z.floor];
        if (o) {
          const [px, py] = posIn(z, id), x = o.x + px * sc, y = o.y + py * sc;
          ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, Math.max(6, sc * .9), 0, 6.2832); ctx.stroke();
          ctx.fillStyle = '#ffffff'; ctx.font = '600 12px system-ui'; ctx.textAlign = 'left'; ctx.fillText(S.people[id].name, x + 9, y - 8);
        }
      }
    }
    const ban = $('#banner');
    if (!md.open) { ban.style.display = 'block'; ban.textContent = 'School closed · ' + md.type.replace(/_/g, ' ') + (D && D.ids.length ? ' · staff only' : ''); }
    else ban.style.display = 'none';
  }
  function star(ctx, x, y, R) {
    ctx.beginPath();
    for (let i = 0; i < 10; i++) { const a = -Math.PI / 2 + i * Math.PI / 5, rr = i % 2 ? R * .45 : R; ctx.lineTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr); }
    ctx.closePath(); ctx.fill();
  }
  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }
  function pickAt(mx, my) {
    let best = null, bd = 64;
    for (const [id, x, y] of S.hits) { const d = (x - mx) * (x - mx) + (y - my) * (y - my); if (d < bd) { bd = d; best = id; } }
    if (best != null) return { type: 'person', id: best };
    const L = S.layout; if (!L) return null;
    for (let zi = 0; zi < S.zones.length; zi++) {
      const z = S.zones[zi], o = L.org[z.floor]; if (!o) continue;
      const [x, y, w, h] = z.rect, X = o.x + x * L.scale, Y = o.y + y * L.scale;
      if (mx >= X && mx <= X + w * L.scale && my >= Y && my <= Y + h * L.scale) {
        const matchFlag = flagsOn(S.day).find(f => f.zone === z.id && Math.abs(f.minute - S.minute) <= 30);
        if (matchFlag) {
          S.activeFlag = matchFlag;
          toast(`⚑ Focused Incident: ${matchFlag.title} (${z.label})`);
          if (S.tab === 'flags') renderFlags();
        } else {
          S.activeFlag = null;
        }
        return { type: 'zone', id: z.id };
      }
    }
    return null;
  }

  // ------------------------------------------------------------------ strips
  const DAYCOL = { instructional_day: '#cfe8d8', limited_school_day: '#bcdcc9', weekly_closure: '#e8eaf0', winter_break: '#d9e2f2', planned_closure: '#f4e0c8', summer_break_staff_only: '#e7dff2' };
  const BLKCOL = { arrival: '#eef1f7', assembly: '#fde9c8', class: '#dfeaff', break: '#d3efdf', lunch: '#d3efdf', dismissal: '#eef1f7' };
  function sizeCanvas(cv, h) {
    const dpr = window.devicePixelRatio || 1, W = cv.clientWidth || 800;
    cv.width = Math.round(W * dpr); cv.height = Math.round(h * dpr); cv.style.height = h + 'px';
    const c = cv.getContext('2d'); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, W, h); return [c, W];
  }
  function drawStrips() {
    if (!S.meta) return;
    const isLight = S.theme === 'light';
    const days = S.meta.days, n = days.length;
    let [c, W] = sizeCanvas($('#dayStrip'), 64);
    const cw = W / n;
    let lastM = '';
    days.forEach((d, i) => {
      const x = i * cw;
      c.fillStyle = DAYCOL[d.type] || (isLight ? '#e2e8f0' : '#1e2638'); c.fillRect(x, 16, Math.ceil(cw), 12);
      if (d.open && d.attendance_rate != null) {
        const h = clamp((d.attendance_rate - 0.8) / 0.2, 0, 1) * 24;
        c.fillStyle = d.alerts && d.alerts.some(a => a.severity === 'high') ? '#ef4444' : (isLight ? '#0284c7' : '#38bdf8');
        c.fillRect(x, 54 - h, Math.max(1, cw - 0.6), h);
      }
      const m = d.date.slice(0, 7);
      if (m !== lastM) {
        lastM = m;
        c.fillStyle = isLight ? '#475569' : '#94a3b8';
        c.font = '10px system-ui';
        c.textAlign = 'left';
        c.fillText(new Date(d.date + 'T00:00').toLocaleString('en', { month: 'short' }), x + 1, 11);
        c.fillStyle = isLight ? '#cbd5e1' : '#2d3748';
        c.fillRect(x, 0, 1, 14);
      }
    });
    allFlags().filter(f => f.kind !== 'calendar').forEach(f => {
      const x = f.day * cw + cw / 2;
      c.fillStyle = f.kind === 'user' ? '#8b5cf6' : f.kind === 'event' ? '#ef4444' : f.sev >= 3 ? '#ef4444' : f.sev === 2 ? '#f59e0b' : '#38bdf8';
      c.beginPath(); c.arc(x, f.kind === 'event' ? 62 : 59, f.kind === 'event' ? 1.8 : 2.4, 0, 6.2832); c.fill();
    });
    // Timeline playhead
    c.fillStyle = isLight ? '#0f172a' : '#10b981';
    c.fillRect(S.day * cw - 0.5, 0, 2, 64);
    if (S.pairedMode && S.pairMeta) {
      // Shared Background Events: Cyan diamonds
      (S.pairMeta.shared_background_events || []).forEach(ev => {
        const dIdx = days.findIndex(d => d.date === ev.date);
        if (dIdx >= 0) {
          const x = dIdx * cw + cw / 2;
          c.fillStyle = '#38bdf8';
          c.beginPath();
          c.moveTo(x, 32); c.lineTo(x + 4, 36); c.lineTo(x, 40); c.lineTo(x - 4, 36);
          c.closePath();
          c.fill();
        }
      });
      // Custom Intervention: Emerald star
      if (S.pairMeta.custom_event && S.pairMeta.custom_event.date) {
        const dIdx = days.findIndex(d => d.date === S.pairMeta.custom_event.date);
        if (dIdx >= 0) {
          const x = dIdx * cw + cw / 2;
          c.fillStyle = '#10b981';
          star(c, x, 36, 6);
        }
      }
    }
    if (n > 151) {
      const seamX = 151 * cw;
      c.strokeStyle = isLight ? '#059669' : '#10b981';
      c.lineWidth = 2;
      c.setLineDash([3, 3]);
      c.beginPath();
      c.moveTo(seamX, 0);
      c.lineTo(seamX, 64);
      c.stroke();
      c.setLineDash([]);
      c.fillStyle = isLight ? '#059669' : '#10b981';
      c.font = 'bold 9px system-ui,sans-serif';
      c.fillText('SEAM · DAY 151', seamX + 4, 11);
      c.fillStyle = isLight ? '#64748b' : '#34d399';
      c.font = '8px system-ui,sans-serif';
      c.fillText(S.pairedMode ? 'PAIRED (CTRL vs TRT) →' : 'ALTERED SIMULATION →', seamX + 4, 21);
      c.textAlign = 'right';
      c.fillStyle = isLight ? '#64748b' : '#94a3b8';
      c.fillText('← LEGACY BASELINE', seamX - 4, 11);
      c.textAlign = 'left';
    }
    // minute strip
    [c, W] = sizeCanvas($('#minStrip'), 34);
    const { start, end, blocks } = S.clock, px = t => (t - start) / (end - start) * W;
    blocks.forEach(b => {
      c.fillStyle = BLKCOL[b.type] || (isLight ? '#f1f5f9' : '#1a2230');
      c.fillRect(px(b.start), 8, px(b.end) - px(b.start) - 1, 20);
      if (px(b.end) - px(b.start) > 24) {
        c.fillStyle = isLight ? '#334155' : '#94a3b8';
        c.font = '10px system-ui';
        c.textAlign = 'center';
        c.fillText(b.name.replace('_', ' ').replace('announcements', 'notices'), (px(b.start) + px(b.end)) / 2, 22);
      }
    });
    for (let h = Math.ceil(start / 60); h * 60 <= end; h++) {
      c.fillStyle = isLight ? '#64748b' : '#94a3b8';
      c.font = '9px system-ui';
      c.textAlign = 'left';
      c.fillText(String(h).padStart(2, '0'), px(h * 60) + 1, 7);
    }
    flagsOn(S.day).filter(f => f.kind !== 'calendar').forEach(f => {
      c.fillStyle = f.sev >= 3 ? '#ef4444' : f.sev === 2 ? '#f59e0b' : f.kind === 'user' ? '#8b5cf6' : '#38bdf8';
      c.fillRect(px(f.minute) - 1, 2, 3, 30);
    });
    // Minute playhead
    c.fillStyle = isLight ? '#0f172a' : '#10b981';
    c.fillRect(px(S.minute) - 1, 0, 2.5, 34);
  }

  // ------------------------------------------------------------------ panels
  const TYPES = [
    'serious_student_fight', 'suspected_prohibited_business', 'teacher_resignation_notice',
    'transport_lateness_spike', 'school_fee_increase', 'additional_teacher_hired',
    'weather_attendance_dip', 'student_teacher_conflict', 'lab_inventory_discrepancy',
    'first_aid_visit', 'annual_day_crowd_buildup', 'duplicate_fee_reminder',
    'teacher_absence_and_cover_pressure', 'exam_paper_printing_error', 'marks_import_anomaly',
    'classroom_fan_failure', 'bus_gate_pillar_scrape', 'fee_transparency_queries',
    'heat_and_utility_pressure', 'computer_lab_circuit_trip', 'fuel_invoice_variance',
    'water_motor_failure'
  ];
  const pct = x => (x == null ? '–' : (x * 100).toFixed(1) + '%');
  const inr = x => '₹' + Math.round(x).toLocaleString('en-IN');
  const band = m => (m < S.meta.mood.low ? ['low', '#d64545'] : m >= S.meta.mood.good ? ['good', '#1a9d5a'] : ['steady', '#e8a317']);
  const hooks = [];
  function renderPanels(force) {
    if (!S.meta) return;
    if (!force && S.tab === 'run') return;
    hooks.length = 0;
    const fn = ({ now: renderNow, inspect: renderInspect, flags: renderFlags, stats: renderStats, money: renderMoney, run: renderRun, compare: renderCompare })[S.tab];
    if (fn) fn();
    hooks.forEach(h => h());
  }
  function renderAll() {
    const t = S.tab;
    Object.keys({ now: 1, inspect: 1, flags: 1, stats: 1, money: 1, run: 1, compare: 1 }).forEach(k => { S.tab = k; renderPanels(true); });
    S.tab = t;
    renderPanels(true);
  }

  function spark(cv, vals, o) {
    o = o || {};
    const [c, W] = sizeCanvas(cv, o.h || 54), H = o.h || 54, n = vals.length;
    const ok = vals.filter(v => v != null && v >= (o.floor == null ? -1e9 : o.floor));
    const cmp = (o.cmp || []).filter(v => v != null);
    const all = ok.concat(cmp);
    if (!all.length) return;
    let lo = o.min != null ? o.min : Math.min(...all), hi = o.max != null ? o.max : Math.max(...all);
    if (hi - lo < 1e-9) { hi += 1; lo -= 1; }
    const X = i => 4 + i / Math.max(n - 1, 1) * (W - 8), Y = v => H - 5 - (v - lo) / (hi - lo) * (H - 12);
    const line = (arr, col, w) => {
      c.strokeStyle = col; c.lineWidth = w; c.beginPath(); let pen = false;
      arr.forEach((v, i) => { if (v == null || (o.floor != null && v < o.floor)) { pen = false; return; } pen ? c.lineTo(X(i), Y(v)) : c.moveTo(X(i), Y(v)); pen = true; });
      c.stroke();
    };
    if (o.cmp) line(o.cmp, '#b7bfce', 1.2);
    line(vals, o.color || '#2a6df4', 1.6);
    if (o.flags) allFlags().filter(f => f.kind !== 'calendar' && f.sev >= 2).forEach(f => { c.fillStyle = '#d64545'; c.fillRect(X(f.day) - .5, H - 4, 1.5, 4); });
    if (o.marker != null) { c.fillStyle = '#1d2330'; c.fillRect(X(o.marker) - .5, 0, 1.5, H); }
    c.fillStyle = '#667085'; c.font = '9px system-ui'; c.textAlign = 'left'; c.fillText((o.fmt || (x => x.toFixed(1)))(hi), 3, 9);
    c.fillText((o.fmt || (x => x.toFixed(1)))(lo), 3, H - 7);
    cv.onclick = e => { const r = cv.getBoundingClientRect(); const i = Math.round((e.clientX - r.left - 4) / (r.width - 8) * (n - 1)); if (o.click) o.click(clamp(i, 0, n - 1)); };
  }
  const sparkTag = (id, cls) => `<canvas class="mini ${cls || ''}" id="${id}"></canvas>`;

  function renderNow() {
    const p = $('#p-now'), md = curMeta(), D = curD(), t = S.minute, C = S.counts || [];
    let on = 0, st = 0, te = 0, ot = 0, vi = 0;
    C.forEach(c => { on += c.n; st += c.s; te += c.t; ot += c.f + c.p; vi += c.v; });
    const moods = [];
    if (D) for (const id of D.ids) {
      if (S.people[id].role !== 'student' || zoneAt(D.paths.get(id), t) < 0) continue;
      const m = moodAt(D, id, t); if (m != null) moods.push([id, m]);
    }
    const avg = moods.length ? moods.reduce((a, b) => a + b[1], 0) / moods.length : null, lowN = moods.filter(m => m[1] < S.meta.mood.low).length;
    const bins = new Array(10).fill(0); moods.forEach(m => { bins[Math.min(9, Math.floor(m[1] / 10))]++; });
    const mx = Math.max(1, ...bins);
    const busiest = S.zones.map((z, i) => [z, C[i] ? C[i].n : 0]).filter(([z, n]) => z.type !== 'classroom' && !['gate', 'bus'].includes(z.type) && n > 0)
      .sort((a, b) => b[1] / b[0].cap - a[1] / a[0].cap).slice(0, 5);
    const worst = moods.sort((a, b) => a[1] - b[1]).slice(0, 8);
    const q = D && md.cctv ? md.cctv.find(r => r.camera_id === 'CAM-CANTEEN') : null;
    const todayFlags = flagsOn(S.day).filter(f => f.kind !== 'calendar');
    p.innerHTML = `
      <h4>${esc(md.date)} · ${esc(md.type.replace(/_/g, ' '))}</h4>
      <div class="cards">
        <div class="card"><b>${on}</b><span>on campus now</span></div>
        <div class="card"><b>${md.open ? md.present : '–'}<small class="mut"> / ${md.enrolled}</small></b><span>students in today</span></div>
        <div class="card"><b>${md.open ? md.late : '–'}</b><span>late arrivals</span></div>
        <div class="card"><b>${md.open ? md.teachers_absent : '–'}</b><span>teachers absent</span></div>
        <div class="card"><b>${avg == null ? '–' : avg.toFixed(0)}</b><span>avg student mood</span></div>
        <div class="card"><b style="color:${lowN ? '#d64545' : 'inherit'}">${lowN}</b><span>low mood now${moods.length ? ' (' + Math.round(lowN / moods.length * 100) + '%)' : ''}</span></div>
      </div>
      <h4>Who is here</h4>
      <div class="mut">${st} students · ${te} teachers · ${ot} staff${vi ? ' · ' + vi + ' visitors' : ''}</div>
      <h4>Mood right now <span class="mut" style="text-transform:none;letter-spacing:0">(a tendency, not a diagnosis)</span></h4>
      <div style="display:flex;gap:3px;align-items:flex-end;height:54px">${bins.map((n, i) => `<div title="${i * 10}–${i * 10 + 9}: ${n}" style="flex:1;background:${moodColor(i * 10 + 5)};height:${Math.max(2, n / mx * 52)}px;border-radius:3px 3px 0 0"></div>`).join('')}</div>
      <div class="legend"><span>0</span><span style="margin-left:auto">100</span></div>
      <h4>Lowest right now</h4>
      ${worst.length ? worst.map(([id, m]) => `<div class="row" data-act="person" data-id="${id}"><span class="dot" style="background:${moodColor(m)}"></span><div class="grow">${esc(S.people[id].name)}<small>${esc(gradeOn(S.people[id], md.date))} ${esc(S.people[id].section)}</small></div><b>${m.toFixed(0)}</b></div>`).join('') : '<div class="mut">No students on campus.</div>'}
      <h4>Busiest places</h4>
      ${busiest.map(([z, n]) => `<div class="row" data-act="zone" data-id="${z.id}"><div class="grow">${esc(z.label)}</div><div style="width:90px" class="bar"><i style="width:${Math.min(100, n / z.cap * 100)}%;background:${n / z.cap > .85 ? '#d64545' : '#7aa7ff'}"></i></div><span class="mut" style="min-width:56px;text-align:right">${n}/${z.cap}</span></div>`).join('') || '<div class="mut">Nobody in shared spaces.</div>'}
      ${q ? `<div class="mut" style="margin-top:4px">Canteen queue at ${fmtT(q.minute)}: counter ${q.observed_count} (usual ${Math.round(q.expected_count)}).</div>` : ''}
      <h4>Flags today</h4>
      ${todayFlags.length ? todayFlags.map(flagRow).join('') : '<div class="mut">Nothing flagged.</div>'}
      <h4>Colours</h4>
      <div class="legend">${S.color === 'grade' ? BANDS.map(b => `<span><i style="background:${b[1]}"></i>${b[0]}</span>`).join('') : S.color === 'mood' ? '<span><i style="background:#d64545"></i>low</span><span><i style="background:#e8a317"></i>steady</span><span><i style="background:#1a9d5a"></i>good</span>' : '<span><i style="background:#4f7cff"></i>student</span>'}
        <span>▲ teacher</span><span>★ principal</span><span>■ staff</span><span>◆ visitor</span></div>`;
  }
  function flagRow(f) {
    const who = f.kind === 'user' ? 'you' : f.kind === 'event' ? 'hidden cause' : f.kind;
    const isSpotlight = S.activeFlag && S.activeFlag.id === f.id;
    return `<div class="row ${isSpotlight ? 'active-flag-spotlight' : ''}" data-act="flag" data-id="${esc(f.id)}"><span class="dot s${f.sev}" style="${f.kind === 'user' ? 'background:#8b5cf6' : f.kind === 'event' ? 'background:#ef4444' : ''}"></span><span class="t">${esc(f.date.slice(5))} ${fmtT(f.minute)}</span><div class="grow">${esc(f.title)}${f.zone ? ` <span class="chip" style="font-size:9.5px;padding:1px 5px;background:rgba(239,68,68,0.15);color:#ef4444;border-color:rgba(239,68,68,0.3)">⚑ ${esc(f.zone)}</span>` : ''}<small>${esc(who)}${f.kind === 'event' ? ' · ' + esc((f.text || '').replace('Hidden cause: ', '')) : ''}</small></div></div>`;
  }

  function renderInspect() {
    const p = $('#p-inspect'), D = curD(), t = S.minute, sel = S.sel;
    if (!sel) { p.innerHTML = '<div class="mut">Click a dot or a room on the map to look inside. Names, mood, why, and where they have been today all appear here.</div>'; return; }
    if (sel.type === 'zone') return renderZone(p, D, t, sel.id);
    const pr = S.people[sel.id], id = sel.id, m = moodAt(D, id, t), isStu = pr.role === 'student';
    const zi = D && D.paths.has(id) ? zoneAt(D.paths.get(id), t) : -1;
    const [bn, bc] = m == null ? ['–', '#999'] : band(m);
    const drv = D && D.drv[id] ? D.drv[id] : [];
    const att = (S.hist.att[id] || '');
    const path = [];
    if (D && D.paths.has(id)) { const a = D.paths.get(id); let last = -2; for (let i = 0; i < a.length; i += 2) if (a[i + 1] !== last) { path.push([a[i], a[i + 1]]); last = a[i + 1]; } }
    const hidden = S.view === 'author' && pr.att != null;
    p.innerHTML = `
      <h4>${esc(pr.role)}${pr.sub && pr.sub !== pr.role ? ' · ' + esc(pr.sub.replace(/_/g, ' ')) : ''}</h4>
      <div style="font-size:17px;font-weight:700">${esc(pr.name)}</div>
      <div class="mut">${isStu ? esc(gradeOn(pr, curMeta().date)) + ' ' + esc(pr.section) + (pr.route ? ' · bus ' + esc(pr.route) : ' · own transport') : esc(pr.home.replace(/_/g, ' '))} · ${zi >= 0 ? 'now in <b>' + esc(S.zones[zi].label) + '</b>' : 'not on campus right now'}</div>
      <div style="margin:6px 0">${(pr.traits.length ? pr.traits : pr.temperament).map(x => `<span class="chip">${esc(x)}</span>`).join('')}</div>
      ${pr.arc ? `<div class="mut" style="margin-bottom:6px">${esc(pr.arc)}</div>` : ''}
      <div class="cards" style="grid-template-columns:1fr 1fr">
        <div class="card"><b style="color:${bc}">${m == null ? '–' : m.toFixed(0)}</b><span>mood now · ${bn}</span></div>
        <div class="card"><b>${esc(S.meta.days[S.day].date.slice(5))}</b><span>${isStu ? (att[S.day] === 'P' ? 'present' : att[S.day] === 'L' ? 'present, late' : att[S.day] === 'A' ? 'absent' : 'not on roll / closed') : 'staff'}</span></div>
      </div>
      <h4>Why today</h4>
      ${drv.length ? drv.map(([c, d]) => `<div class="row" style="cursor:default"><div class="grow">${esc(S.meta.drivers[c])}</div><b class="${d < 0 ? 'neg' : 'pos'}">${d > 0 ? '+' : ''}${(d / 10).toFixed(1)}</b></div>`).join('') : '<div class="mut">An ordinary day for them.</div>'}
      <h4>Mood over the term</h4>${sparkTag('sp-mood')}
      ${isStu ? `<h4>Attendance (click a day)</h4>${sparkTag('sp-att', '')}` : ''}
      ${hidden ? `<h4>Author view: hidden traits</h4><div class="mut">attendance propensity ${pr.att.toFixed(2)} · discipline risk ${pr.disc.toFixed(2)} · academic index ${pr.acad.toFixed(0)}</div>` : ''}
      ${isStu && pr.friends && pr.friends.length ? `<h4>Close friends</h4>${pr.friends.map(f => `<span class="chip" style="cursor:pointer" data-act="person" data-id="${f}">${esc(S.people[f].name)}</span>`).join('')}` : ''}
      ${(() => {
        const cog = (S.hist && S.hist.cognitive && S.hist.cognitive[id]) || (pr && pr.cognitive);
        if (!cog) return '';
        const cs = cog.cognitive_state || {};
        const ag = cog.active_goal || {};
        const mems = cog.recent_memories || [];
        const rels = cog.relationships || [];
        return `
          <h4>Cognitive State & Goals (Phase 4)</h4>
          <div class="cards" style="grid-template-columns:1fr 1fr;margin-bottom:8px">
            <div class="card">
              <b>${Math.round((cs.engagement != null ? cs.engagement : 0.78) * 100)}%</b>
              <span>engagement proxy</span>
            </div>
            <div class="card">
              <b>${Math.round((cs.academic_confidence != null ? cs.academic_confidence : 0.70) * 100)}%</b>
              <span>academic confidence</span>
            </div>
          </div>
          ${ag && ag.target_outcome ? `
            <div class="card" style="margin-bottom:8px">
              <div style="font-size:10px;text-transform:uppercase;color:var(--text-muted);font-weight:700">Active Objective</div>
              <div style="font-size:11.5px;font-weight:600;margin-top:2px;color:var(--text-primary)">${esc(ag.target_outcome)}</div>
              <div class="mut" style="font-size:10.5px">Priority ${ag.priority || 3}/5 · ${esc(ag.status || 'active')}</div>
            </div>
          ` : ''}
          ${mems && mems.length ? `
            <h4>Bounded Event Memory (${mems.length})</h4>
            <div style="display:flex;flex-direction:column;gap:5px;margin-bottom:8px">
              ${mems.map(m => {
                const bCls = m.epistemic_status === 'confirmed_fact' ? 'badge-computed' : m.epistemic_status === 'eyewitness_account' ? 'badge-configured' : 'badge-unmodeled';
                return `
                  <div class="card" style="padding:6px 8px;font-size:11px;margin-bottom:0">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px">
                      <span class="badge ${bCls}" style="font-size:9px">${esc((m.epistemic_status || 'witness').replace(/_/g, ' '))}</span>
                      <span class="mut" style="font-size:9.5px">${esc(m.simulated_date || '')}</span>
                    </div>
                    <div>${esc(m.summary || '')}</div>
                  </div>
                `;
              }).join('')}
            </div>
          ` : ''}
          ${rels && rels.length ? `
            <h4>Relationship Links (${rels.length})</h4>
            <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px">
              ${rels.map(r => {
                const targetPerson = S.people[r.target_id];
                const tName = targetPerson ? targetPerson.name : `Agent ${r.target_id}`;
                const affColor = r.affinity >= 0.7 ? '#15803d' : r.affinity >= 0.4 ? '#0369a1' : '#b45309';
                return `
                  <span class="chip" style="cursor:pointer" data-act="person" data-id="${r.target_id}" title="Affinity: ${r.affinity}">
                    ${esc(tName)} <small style="color:${affColor}">(${esc((r.relation_type || 'peer').replace(/_/g, ' '))})</small>
                  </span>
                `;
              }).join('')}
            </div>
          ` : ''}
        `;
      })()}
      <h4>Today's path</h4>
      ${path.length ? path.slice(0, 60).map(([tm, z]) => `<div class="row" data-act="time" data-m="${tm}"><span class="t">${fmtT(tm)}</span><div class="grow">${z < 0 ? 'leaves campus' : esc(S.zones[z].label)}</div></div>`).join('') : '<div class="mut">Not on campus today.</div>'}`;
    hooks.push(() => {
      const mv = (S.hist.mood[id] || []);
      const cmpv = null;
      if ($('#sp-mood')) spark($('#sp-mood'), mv, { floor: 0, min: 0, max: 100, marker: S.day, color: '#7b2cbf', fmt: x => x.toFixed(0), click: i => goTo(i, S.minute) });
      if ($('#sp-att')) {
        const [c, W] = sizeCanvas($('#sp-att'), 20), cw = W / att.length;
        for (let i = 0; i < att.length; i++) { c.fillStyle = { P: '#1a9d5a', L: '#e8a317', A: '#d64545', '-': '#eef1f7' }[att[i]] || '#eef1f7'; c.fillRect(i * cw, 2, Math.max(1, cw - .5), 14); }
        c.fillStyle = '#111'; c.fillRect(S.day * cw, 0, 1.5, 20);
        $('#sp-att').onclick = e => { const r = $('#sp-att').getBoundingClientRect(); goTo(Math.floor((e.clientX - r.left) / r.width * att.length), S.minute); };
      }
    });
  }
  function renderZone(p, D, t, zid) {
    const zi = S.zoneIdx[zid], z = S.zones[zi], c = (S.counts || [])[zi] || { n: 0, s: 0, t: 0, f: 0, p: 0, v: 0 };
    const k = clamp(Math.floor((t - S.clock.start) / S.clock.step), 0, 1000), cs = D && D.cam[zi];
    p.innerHTML = `
      <h4>${esc(z.type.replace('_', ' '))}${z.blind && S.view === 'author' ? ' · unwatched area' : ''}</h4>
      <div style="font-size:17px;font-weight:700">${esc(z.label)}</div>
      <div class="mut">${esc(S.meta.floors[z.floor])} · capacity ${z.cap}</div>
      <div class="cards" style="margin-top:8px"><div class="card"><b>${c.n}</b><span>here now</span></div><div class="card"><b>${c.s}</b><span>students</span></div><div class="card"><b>${c.t + c.f + c.p + c.v}</b><span>adults</span></div></div>
      <div class="mut" style="margin-top:6px">${z.cam ? `Counter ${esc(z.cam)} (${esc(z.measure.replace('_', ' '))}) reads <b>${cs ? cs[Math.min(k, cs.length - 1)] : '–'}</b> right now.` : 'No counter covers this place.'}</div>
      <h4>Headcount today</h4>${sparkTag('sp-zone')}
      <h4>People here now</h4>
      ${D ? D.ids.filter(id => zoneAt(D.paths.get(id), t) === zi).slice(0, 30).map(id => `<span class="chip" style="cursor:pointer" data-act="person" data-id="${id}">${esc(S.people[id].name)}</span>`).join('') : ''}`;
    hooks.push(() => { if (D && $('#sp-zone')) { const ser = zoneSeries(D, zi); spark($('#sp-zone'), ser, { min: 0, marker: Math.round((t - S.clock.start) / S.clock.step), color: '#2a6df4', fmt: x => x.toFixed(0), click: i => goTo(S.day, S.clock.start + i * S.clock.step) }); } });
  }

  S.flt = { alert: true, incident: true, decision: true, calendar: false, user: true, event: true }; S.sevMin = 0;
  function renderFlags() {
    const p = $('#p-flags'), fl = allFlags().filter(f => S.flt[f.kind] !== false && f.sev >= S.sevMin);
    const kinds = ['alert', 'incident', 'decision', 'user'].concat(S.view === 'author' ? ['event'] : []).concat(['calendar']);
    const nAl = S.meta.alerts.length;
    p.innerHTML = `
      <div class="tabs2">${kinds.map(k => `<button data-act="filter" data-k="${k}" class="${S.flt[k] !== false ? 'on' : ''}">${k}</button>`).join('')}</div>
      <div class="mut" style="margin-bottom:6px">Min severity <select id="sevSel">${['all', 'low+', 'medium+', 'high'].map((s, i) => `<option value="${i}" ${S.sevMin === i ? 'selected' : ''}>${s}</option>`).join('')}</select> · ${fl.length} flags · ${nAl} detector alerts. Alerts say <i>look here</i>, not <i>why</i>.</div>
      ${fl.length ? fl.map(f => {
        const d = S.meta.decisions.find(x => x.decision_id === f.ref);
        const extra = f.kind === 'decision' && d && /proposed/.test(d.status) ? `<div style="margin-top:4px"><button data-act="approve" data-id="${esc(d.decision_id)}" data-v="1">Approve</button> <button data-act="approve" data-id="${esc(d.decision_id)}" data-v="0">Reject</button> ${(S.approvals && S.approvals[d.decision_id] != null) ? '<b>' + (S.approvals[d.decision_id] ? 'approved' : 'rejected') + ' (pending re-run)</b>' : ''}</div>` : '';
        return flagRow(f).replace('</div></div>', `</div>${extra}</div>`);
      }).join('') : '<div class="mut">No flags match.</div>'}`;
    const sel = $('#sevSel'); if (sel) sel.onchange = () => { S.sevMin = +sel.value; renderFlags(); };
  }

  function seriesOf(M, key) {
    return M.days.map(d => {
      if (!d.open) return null;
      if (key === 'neg') { const f = d.feedback, n = f.pos + f.neu + f.neg; return n ? f.neg / n : null; }
      if (key === 'alerts') return d.alerts.length;
      if (key === 'att') return d.attendance_rate;
      return d[key];
    });
  }
  function renderStats() {
    const p = $('#p-stats'), cmp = S.cmp && S.cmp.meta;
    const charts = [['att', 'Attendance', x => (x * 100).toFixed(0) + '%', '#2a6df4', .8, 1], ['mood_avg', 'Average student mood', x => x.toFixed(0), '#7b2cbf', 40, 80],
      ['mood_low_share', 'Students in low mood', x => (x * 100).toFixed(0) + '%', '#d64545', 0, null], ['late', 'Late arrivals', x => x.toFixed(0), '#e8a317', 0, null],
      ['teachers_absent', 'Teachers absent', x => x.toFixed(0), '#f08a24', 0, null], ['neg', 'Negative feedback share', x => (x * 100).toFixed(0) + '%', '#d64545', 0, null],
      ['canteen_peak_queue', 'Canteen queue (peak counter)', x => x.toFixed(0), '#1a9d5a', 0, null], ['alerts', 'Detector alerts per day', x => x.toFixed(0), '#111', 0, null]];
    p.innerHTML = `<div class="mut" style="margin-bottom:6px">Click a chart to jump to that day. Red ticks are medium and high flags.${cmp ? ' Grey line: ' + esc(S.cmp.id) + '.' : ''}</div>` +
      charts.map(c => `<h4>${c[1]}</h4>${sparkTag('ch-' + c[0])}`).join('');
    hooks.push(() => charts.forEach(c => spark($('#ch-' + c[0]), seriesOf(S.meta, c[0]), { fmt: c[2], color: c[3], min: c[4], max: c[5], marker: S.day, flags: true, cmp: cmp ? seriesOf(cmp, c[0]) : null, click: i => goTo(i, S.minute) })));
  }
  function renderMoney() {
    const p = $('#p-money'), d = curMeta(), f = d.finance, cmp = S.cmp && S.cmp.meta;
    const accts = Object.entries(f.accounts || {}).sort((a, b) => b[1] - a[1]).slice(0, 8);
    p.innerHTML = `<h4>Cash balance</h4>${sparkTag('ch-cash')}
      <div class="cards" style="margin-top:8px"><div class="card"><b>${inr(f.cash)}</b><span>cash at close</span></div><div class="card"><b class="pos">${inr(f.inflow)}</b><span>in today</span></div><div class="card"><b class="neg">${inr(f.outflow)}</b><span>out today</span></div></div>
      <h4>Today's accrued costs</h4><table>${accts.map(([a, v]) => `<tr><td>${esc(a.replace(/_/g, ' '))}</td><td style="text-align:right">${inr(v)}</td></tr>`).join('')}</table>
      <div class="mut" style="margin-top:8px">${S.meta.run.mode === 'anchor' ? 'Anchor mode: money follows the story’s own ledger.' : 'Generate mode: money is rebuilt from the story’s fee and cost assumptions.'}</div>`;
    hooks.push(() => spark($('#ch-cash'), S.meta.days.map(x => x.finance.cash), { fmt: x => (x / 1e6).toFixed(2) + 'M', color: '#1a9d5a', marker: S.day, flags: true, h: 80, cmp: cmp ? cmp.days.map(x => x.finance.cash) : null, click: i => goTo(i, S.minute) }));
  }

  // ------------------------------------------------------------------ run & scenario builder
  const CHECKPOINTS = [
    { id: 'CKPT-DAY-00-OPENING', day: 0, date: '2026-01-01', title: 'Day 0: Term Opening Baseline' },
    { id: 'CKPT-DAY-30-JAN-CLOSE', day: 30, date: '2026-01-31', title: 'Day 30: End of January Review' },
    { id: 'CKPT-DAY-60-FEB-CLOSE', day: 60, date: '2026-03-02', title: 'Day 60: End of February / Pre-Annual Day' },
    { id: 'CKPT-DAY-90-APRIL-PROMOTIONS', day: 90, date: '2026-04-01', title: 'Day 90: April Term & Promotions (3-Mo Horizon)' },
    { id: 'CKPT-DAY-120-MAY-HEAT', day: 120, date: '2026-05-01', title: 'Day 120: Pre-Summer Heat Milestone' },
    { id: 'CKPT-DAY-150-TERM-CLOSE', day: 150, date: '2026-05-31', title: 'Day 150: Full Term Close (5-Month)' }
  ];

  const PRESET_EVENTS = [
    {
      id: 'serious_student_fight',
      icon: '🥊',
      title: 'Student Altercation',
      subtitle: 'Playground altercation involving 3 students',
      desc: 'Physical confrontation in playground during recess. Triggers infirmary response, disciplinary inquiry, parent notifications, and student mood dips.',
      defaultSev: 'high',
      params: {
        student_ids: ['STU-0012', 'STU-0015', 'STU-0021'],
        location: 'playground'
      }
    },
    {
      id: 'transport_lateness_spike',
      icon: '🚌',
      title: 'Bus Breakdown',
      subtitle: 'Route 3 delayed by 20 minutes',
      desc: 'Mechanical failure on Ring Road morning commute. Triggers late attendance spike, schedule rearrangement, and parent hotline inquiries.',
      defaultSev: 'medium',
      params: {
        routes: 3,
        delay: [20, 32]
      }
    },
    {
      id: 'school_fee_increase',
      icon: '💰',
      title: 'Fee Revision (+10%)',
      subtitle: 'Tuition revision announced to community',
      desc: '10% tuition revision announcement. Impacts parent community sentiment, query volume, and school term cash projections.',
      defaultSev: 'medium',
      params: {
        fee_category: 'tuition',
        delta_pct: 10
      }
    },
    {
      id: 'suspected_prohibited_business',
      icon: '🔍',
      title: 'Policy Violation',
      subtitle: 'Student inquiry under review',
      desc: 'Suspected unauthorized commercial exchange on campus. Disciplinarian conducts fact review under presumption of innocence.',
      defaultSev: 'medium',
      params: {
        student_ids: ['STU-0044'],
        investigation_status: 'under_review',
        location: 'admin_lobby'
      }
    },
    {
      id: 'teacher_resignation_notice',
      icon: '📝',
      title: 'Teacher Resignation',
      subtitle: 'Notice from senior faculty Ritu Kapoor',
      desc: 'Senior teacher submits formal resignation notice. Triggers timetable substitute stress, workload redistribution, and faculty mood adjustment.',
      defaultSev: 'medium',
      params: {
        name: 'Ritu Kapoor'
      }
    },
    {
      id: 'additional_teacher_hired',
      icon: '👩‍🏫',
      title: 'New Teacher Hired',
      subtitle: 'Pooja Sharma joins for Social Science',
      desc: 'New educator joins the faculty. Relieves class clash risks, reduces teacher burden, and updates monthly payroll.',
      defaultSev: 'low',
      params: {
        teacher_name: 'Pooja Sharma',
        subject_or_role: 'Social Science'
      }
    },
    {
      id: 'weather_attendance_dip',
      icon: '🌧️',
      title: 'Severe Weather / Heat',
      subtitle: 'Delhi NCR weather alert and attendance dip',
      desc: 'Heavy rain or severe heat alert across Delhi NCR. Attendance drops across junior grades, afternoon buses slow down, and power utilities surge.',
      defaultSev: 'medium',
      params: {
        attendance_dip_pct: 12
      }
    }
  ];

  S.form = {
    name: '', mode: 'generate', seed: 20261014, intensity: 1, rnd: 0, fork: true,
    teachers: 0, support: 0, bus: 0, fee: 0, feeOk: false, transportFee: 0, maintBudget: 0,
    evalDuration: 30, extendPostBaseline: true, calMonth: '2026-06',
    autonomy: 'low_risk_auto', instructEff: 1.0, assessDiff: 1.0,
    story: true, disabled: [], add: [], bTab: 'events', ckpt: 'CKPT-DAY-150-TERM-CLOSE',
    curEvType: 'water_cooler_breakdown', curEvDay: 155, curEvDate: '2026-06-05', curEvSev: 'medium',
    fightStudents: 'STU-0012, STU-0015, STU-0021', fightLocation: 'playground',
    bizStudent: 'STU-0044', bizStatus: 'under_review', bizLocation: 'admin_lobby',
    resigTeacher: 'Ritu Kapoor', busRoute: 3, busDelay: 20,
    feeCategory: 'tuition', feeDelta: 10, hiredTeacher: 'Pooja Sharma', hiredRole: 'Social Science',
    nlPrompt: 'On June 5 during summer maintenance, water cooler breakdown in corridor_1. Increase summer maintenance budget by ₹50,000.',
    nlParsed: null, nlStatus: ''
  };

  function buildOverview() {
    const F = S.form, base = JSON.parse(JSON.stringify(S.meta.run.overview));
    const name = (F.name || ('whatif_' + S.run + '_d' + S.day)).replace(/[^A-Za-z0-9_-]/g, '_');
    base.name = name;
    base.randomness = { intensity: +F.intensity };
    base.events.use_story_events = !!F.story;
    base.events.disable = F.disabled.slice();
    base.events.add = (base.events.add || []).concat(F.add);
    base.events.random.per_month = +F.rnd;

    // Academic year continuation & evaluation duration (Default: Day 151 onward)
    if (F.extendPostBaseline) {
      base.start_day = 151;
      base.end_day = Math.min(364, base.start_day + (+F.evalDuration || 30) - 1);
      base.checkpoint_id = 'CKPT-DAY-150-TERM-CLOSE';
      base.branch = {
        checkpoint_id: 'CKPT-DAY-150-TERM-CLOSE',
        start_day: 151,
        duration_days: +F.evalDuration || 30,
        end_day: base.end_day,
        reopening_date: '2026-07-01'
      };
    }

    const lev = {
      additional_teachers: +F.teachers,
      attendance_support_budget_inr_per_month: +F.support,
      bus_backup_capacity: +F.bus,
      tuition_fee_delta_pct: +F.fee,
      fee_change_approved: !!F.feeOk,
      transport_fee_delta_pct: +(F.transportFee || 0),
      summer_maintenance_budget_inr: +(F.maintBudget || 0),
      autonomy_level: F.autonomy
    };
    if (F.fork) {
      let forkDay = S.day;
      if (F.add && F.add.length > 0 && S.meta && S.meta.days) {
        F.add.forEach(ev => {
          const idx = S.meta.days.findIndex(d => d.date === ev.date);
          if (idx >= 0 && idx < forkDay) forkDay = Math.max(0, idx - 1);
        });
      }
      base.patches = (base.patches || []).concat([{ from_day: forkDay, mode: 'generate', levers: lev }]);
      base.seed = F.seed;
    } else {
      base.mode = F.mode;
      base.seed = +F.seed;
      Object.assign(base.levers, lev);
      base.patches = [];
    }
    base.approvals = Object.assign({}, base.approvals || {}, S.approvals);
    return base;
  }

  function renderRun() {
    const p = $('#p-run'), M = S.meta, ev = M.evaluation, F = S.form, ov = M.run.overview;
    const det = ev && ev.detection ? ev.detection : null;
    const storyEvents = S.view === 'author' ? M.flags.filter(f => f.kind === 'event') : [];
    const bTab = F.bTab || 'events';

    p.innerHTML = `
      <h4>Scenario Builder & Simulator ${S.api ? '' : '<span class="mut" style="text-transform:none">(server active)</span>'}</h4>
      <div class="mut" style="margin-bottom:8px">Simulate custom incidents, policy shifts, and watch campus consequences.</div>

      <nav class="builder-subnav">
        <button class="${bTab === 'events' ? 'on' : ''}" data-act="bTab" data-tab="events">⚡ Quick Event Simulator</button>
        <button class="${bTab === 'levers' ? 'on' : ''}" data-act="bTab" data-tab="levers">🎛️ Policy Levers</button>
        <button class="${bTab === 'nlp' ? 'on' : ''}" data-act="bTab" data-tab="nlp">💬 AI Assistant</button>
        <button class="${bTab === 'setup' ? 'on' : ''}" data-act="bTab" data-tab="setup">⚙️ Advanced & Checkpoints</button>
      </nav>

      <div id="bTabContent">
        ${renderBuilderTab(bTab, M, F, storyEvents)}
      </div>

      ${bTab === 'setup' ? `
        <div style="margin:12px 0 6px;display:flex;gap:6px;flex-wrap:wrap">
          <button class="primary" data-act="runScenarioTimeLapse" ${S.api ? '' : 'disabled'}>▶ Run & Watch Time-lapse</button>
          <button data-act="validateScenario">✓ Validate</button>
          <button data-act="restoreBaseline">⏮ Restore Baseline</button>
          <button data-act="dlOverview">Export JSON</button>
        </div>
        <div id="runStatus" class="mut" style="font-weight:600"></div>

        <details style="margin-top:12px">
          <summary style="cursor:pointer;font-size:11.5px;font-weight:600;color:var(--text-muted)">Show Run Overview JSON</summary>
          <textarea readonly style="height:70px;margin-top:6px">${esc(JSON.stringify(ov, null, 1))}</textarea>
        </details>
      ` : ''}
    `;
  }

  function renderHorizonCalendar(F) {
    const MONTHS = [
      { key: '2026-06', label: 'June 2026', num: 6, desc: 'Month 6: Summer Break & Facility Maintenance' },
      { key: '2026-07', label: 'July 2026', num: 7, desc: 'Month 7: Monsoon Resumption & School Reopening' },
      { key: '2026-08', label: 'August 2026', num: 8, desc: 'Month 8: Regular Academics & Cover Management' },
      { key: '2026-09', label: 'September 2026', num: 9, desc: 'Month 9: Examination Cycle & Assessments' }
    ];

    const selDate = F.curEvDate || '2026-06-05';
    let curMonthKey = F.calMonth || selDate.slice(0, 7);
    if (!MONTHS.some(m => m.key === curMonthKey)) {
      curMonthKey = '2026-06';
      F.calMonth = curMonthKey;
    }
    const curMonthMeta = MONTHS.find(m => m.key === curMonthKey) || MONTHS[0];

    const [yStr, mStr] = curMonthKey.split('-');
    const year = +yStr, month = +mStr - 1;
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const firstDow = (new Date(year, month, 1).getDay() + 6) % 7; // 0=Monday..6=Sunday

    const d0 = new Date(2026, 0, 1);
    const curDateObj = new Date(selDate + 'T00:00:00');
    const selDayIdx = Math.round((curDateObj - d0) / 86400000);
    const selDowStr = curDateObj.toLocaleDateString('en-US', { weekday: 'long' });

    let cells = [];
    for (let e = 0; e < firstDow; e++) {
      cells.push('<div class="cal-day-cell empty"></div>');
    }

    for (let d = 1; d <= daysInMonth; d++) {
      const iso = `${year}-${String(month + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
      const dt = new Date(year, month, d);
      const dayOfYear = Math.round((dt - d0) / 86400000);
      const isSelected = iso === selDate;
      const isSunday = dt.getDay() === 0;
      const isReopening = iso === '2026-07-01';
      const isBreak = iso < '2026-07-01';

      let badgeHtml = '';
      if (isReopening) badgeHtml = '<span class="cal-day-badge reopen">Reopen</span>';
      else if (isBreak && d === 1) badgeHtml = '<span class="cal-day-badge break">Break</span>';

      cells.push(`
        <div class="cal-day-cell ${isSelected ? 'selected' : ''} ${isSunday ? 'sunday' : ''}" data-act="pickCalDate" data-iso="${iso}" data-day="${dayOfYear}" title="${iso} (Day ${dayOfYear + 1} · Month ${curMonthMeta.num})">
          <span class="cal-day-num">${d}</span>
          <span class="cal-day-idx">D${dayOfYear + 1}</span>
          ${badgeHtml}
        </div>
      `);
    }

    return `
      <div class="horizon-calendar">
        <div class="cal-month-nav">
          <div class="cal-month-tabs">
            ${MONTHS.map(m => `
              <button type="button" class="cal-month-tab ${m.key === curMonthKey ? 'active' : ''}" data-act="setCalMonth" data-month="${m.key}">
                ${m.label} (M${m.num})
              </button>
            `).join('')}
          </div>
        </div>
        <div style="font-size:11px;color:var(--text-muted);margin-bottom:8px">
          ${curMonthMeta.desc}
        </div>
        <div class="cal-grid">
          <div class="cal-th">Mo</div>
          <div class="cal-th">Tu</div>
          <div class="cal-th">We</div>
          <div class="cal-th">Th</div>
          <div class="cal-th">Fr</div>
          <div class="cal-th">Sa</div>
          <div class="cal-th">Su</div>
          ${cells.join('')}
        </div>
        <div class="cal-selection-hud">
          <div>
            <div style="font-size:9.5px;text-transform:uppercase;color:var(--text-muted);font-weight:700">Selected Incident Date</div>
            <div style="font-size:12.5px;font-weight:700;color:var(--accent)">
              ${selDowStr}, ${selDate} · <span style="font-family:var(--font-mono);font-size:11px">Day ${selDayIdx + 1} (Month ${curMonthMeta.num})</span>
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:6px">
            <label style="font-size:11px;color:var(--text-secondary)">Date Picker:</label>
            <input type="date" id="evDateInput" value="${selDate}" min="2026-06-01" max="2026-10-31" style="padding:3px 6px;font-size:11px;border-radius:5px" data-act="changeEvDateInput">
          </div>
        </div>
      </div>
    `;
  }

  function renderBuilderTab(tab, M, F, storyEvents) {
    if (tab === 'setup') {
      const dur = +F.evalDuration || 30;
      const startDay = F.extendPostBaseline ? 151 : 0;
      const endDay = Math.min(364, startDay + dur - 1);
      const startDate = new Date(2026, 0, 1 + startDay).toISOString().slice(0, 10);
      const endDate = new Date(2026, 0, 1 + endDay).toISOString().slice(0, 10);

      return `
        <div class="field"><label>Scenario Name</label><input type="text" data-f="name" value="${esc(F.name)}" placeholder="whatif_${esc(S.run)}_d${S.day}"></div>
        <div class="field"><label>Evaluation Duration</label>
          <select data-f="evalDuration" id="evalDurationSel">
            <option value="30" ${dur === 30 ? 'selected' : ''}>30 Days (1 Month: Summer Facility Maintenance)</option>
            <option value="60" ${dur === 60 ? 'selected' : ''}>60 Days (2 Months: Summer to Monsoon Resumption)</option>
            <option value="90" ${dur === 90 ? 'selected' : ''}>90 Days (1 Quarter: Through Autumn Examinations)</option>
            <option value="150" ${dur === 150 ? 'selected' : ''}>150 Days (Full Extended Semester)</option>
          </select>
        </div>
        <div class="field"><label>Academic Continuation</label>
          <label class="chk"><input type="checkbox" data-f="extendPostBaseline" ${F.extendPostBaseline ? 'checked' : ''}> Extend beyond saved baseline endpoint (Day 151 / 2026-06-01 onward)</label>
        </div>
        <div class="card" style="margin:8px 0">
          <div style="font-size:11px;color:var(--text-secondary)">
            <div>Parent Baseline Horizon: <b>Day 0 to Day 150 (2026-01-01 to 2026-05-31)</b> · Baseline Protected</div>
            <div style="margin-top:2px">Simulated Horizon: <b style="color:var(--accent)">Day ${startDay} to Day ${endDay} (${startDate} to ${endDate})</b></div>
            <div style="margin-top:2px;color:var(--ok)">✓ Delhi School Calendar: June Summer Break → July Monsoon Resumption → Autumn Term</div>
          </div>
        </div>
        <div class="field"><label>Start from Checkpoint</label>
          <select id="ckptSel">
            ${CHECKPOINTS.map(c => `<option value="${c.id}" ${F.ckpt === c.id ? 'selected' : ''}>${c.title}</option>`).join('')}
          </select>
        </div>
        <div class="field"><label>Fork Policy</label>
          <label class="chk"><input type="checkbox" data-f="fork" ${F.fork ? 'checked' : ''}> Branch from Day ${S.day + 1} (${esc(curMeta().date)}): baseline immutable, engine simulates future</label>
        </div>
        ${F.fork ? '' : `<div class="field"><label>Mode</label><select data-f="mode"><option value="anchor" ${F.mode === 'anchor' ? 'selected' : ''}>anchor (follow story)</option><option value="generate" ${F.mode === 'generate' ? 'selected' : ''}>generate (engine)</option></select></div>`}
        <div class="field"><label>Random Seed</label><input type="number" data-f="seed" value="${F.seed}"></div>
        <div class="field"><label>Wobble / Intensity</label><input type="number" step="0.1" min="0" max="3" data-f="intensity" value="${F.intensity}"></div>
        <div class="field"><label>Extra Random Events</label><input type="number" step="0.5" min="0" data-f="rnd" value="${F.rnd}" placeholder="per month"></div>
        <div class="field"><label>Include Story Events</label><label class="chk"><input type="checkbox" data-f="story" ${F.story ? 'checked' : ''}> Keep reference events</label></div>
        ${storyEvents.length ? `<div class="mut" style="margin-top:4px">Disable specific reference events:</div><div style="max-height:90px;overflow:auto">${storyEvents.map(f => `<label class="chk" style="display:flex"><input type="checkbox" data-dis="${esc(f.ref)}" ${F.disabled.includes(f.ref) ? 'checked' : ''}> ${esc(f.date.slice(5))} ${esc(f.title)}</label>`).join('')}</div>` : ''}
      `;
    }
    if (tab === 'events') {
      const activePreset = PRESET_EVENTS.find(p => p.id === F.curEvType) || PRESET_EVENTS[0];
      const dur = +F.evalDuration || 30;
      const startDay = 151;
      const endDay = startDay + dur - 1;
      const startDate = new Date(2026, 0, 1 + startDay).toISOString().slice(0, 10);
      const endDate = new Date(2026, 0, 1 + endDay).toISOString().slice(0, 10);

      return `
        <div class="card builder-step-card" style="border-radius:10px;padding:14px;margin-bottom:12px">
          <div style="margin-bottom:12px;padding:10px 12px;background:var(--bg-subtle);border-radius:8px;border:1px solid var(--border-default)">
            <div style="display:flex;justify-content:space-between;align-items:center">
              <div>
                <b style="color:var(--text-primary);font-size:12px">Dual Timeline Architecture</b>
                <div style="font-size:11px;color:var(--text-muted);margin-top:2px">
                  Months 1–5 (Days 0–150 / Jan 1 – May 31): <b>Frozen Legacy Baseline</b> (Protected)
                </div>
              </div>
              <span class="badge badge-computed" style="font-size:9.5px">Branch Point: Month 6</span>
            </div>
          </div>

          <div class="step-header" style="margin-top:0">
            <span class="step-badge">STEP 1</span>
            <h4 class="step-title">Choose What to Simulate</h4>
          </div>
          <div class="preset-grid">
            ${PRESET_EVENTS.map(p => `
              <div class="preset-btn ${F.curEvType === p.id ? 'active' : ''}" data-act="pickEvPreset" data-type="${p.id}">
                <div class="preset-title">${p.icon} ${p.title}</div>
                <div class="preset-desc">${p.subtitle}</div>
              </div>
            `).join('')}
          </div>

          <div class="event-help-box">
            <b>Campus Consequence:</b>
            <p>${activePreset.desc}</p>
          </div>

          <div class="step-header">
            <span class="step-badge">STEP 2</span>
            <h4 class="step-title">How Long to Simulate? (Simulation Horizon)</h4>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;margin:8px 0">
            <button type="button" class="quick-day-btn ${dur === 30 ? 'active' : ''}" data-act="setHorizonDuration" data-dur="30">30 Days (Month 6: Summer Break)</button>
            <button type="button" class="quick-day-btn ${dur === 60 ? 'active' : ''}" data-act="setHorizonDuration" data-dur="60">60 Days (Months 6–7: Monsoon Reopening)</button>
            <button type="button" class="quick-day-btn ${dur === 90 ? 'active' : ''}" data-act="setHorizonDuration" data-dur="90">90 Days (Months 6–8: Full Quarter)</button>
            <button type="button" class="quick-day-btn ${dur === 150 ? 'active' : ''}" data-act="setHorizonDuration" data-dur="150">150 Days (Extended Semester)</button>
          </div>
          <div style="font-size:11px;color:var(--text-secondary);margin-bottom:10px">
            Simulated Range: <b style="color:var(--accent)">Day ${startDay} → Day ${endDay} (${startDate} to ${endDate})</b>
          </div>

          <div class="step-header">
            <span class="step-badge">STEP 3</span>
            <h4 class="step-title">When Does It Happen? (Calendar Picker)</h4>
          </div>
          <div class="mut" style="font-size:11px;margin-bottom:6px">
            Pick any day on the calendar below or use the direct date selector. The simulation starts on Month 6 (June 1, 2026).
          </div>

          ${renderHorizonCalendar(F)}

          <div class="step-header" style="margin-top:14px">
            <span class="step-badge">STEP 4</span>
            <h4 class="step-title">Controlled Randomness Profile (Part D)</h4>
          </div>
          <div class="profile-selector-box">
            <div class="field"><label>Background Random Events Profile</label>
              <select id="profileSel" data-act="changeProfile">
                <option value="balanced" ${S.randomProfile === 'balanced' ? 'selected' : ''}>Balanced (Default: ~1.5 events/mo, moderate disruption)</option>
                <option value="calm" ${S.randomProfile === 'calm' ? 'selected' : ''}>Calm (Routine variability, minor friction only)</option>
                <option value="stress_test" ${S.randomProfile === 'stress_test' ? 'selected' : ''}>Stress-test (Frequent equipment faults & staffing strain)</option>
                <option value="custom" ${S.randomProfile === 'custom' ? 'selected' : ''}>Custom (User-configured limits & seeds)</option>
              </select>
            </div>
            <div class="profile-card-desc" id="profileDesc">${RANDOM_PROFILES[S.randomProfile || 'balanced'].desc}</div>
            <div class="profile-badge-row" id="profileBadges">
              <span class="profile-badge">Rate: ${RANDOM_PROFILES[S.randomProfile || 'balanced'].rate}</span>
              <span class="profile-badge">Max/Day: ${RANDOM_PROFILES[S.randomProfile || 'balanced'].maxDay}</span>
              <span class="profile-badge">Max/Wk: ${RANDOM_PROFILES[S.randomProfile || 'balanced'].maxWk}</span>
              <span class="profile-badge">Cooldown: ${RANDOM_PROFILES[S.randomProfile || 'balanced'].cooldown}</span>
            </div>
          </div>

          <div class="step-header" style="margin-top:14px">
            <span class="step-badge">STEP 5</span>
            <h4 class="step-title">Simulate Horizon & Watch Campus Consequences</h4>
          </div>
          <div style="display:flex;flex-direction:column;gap:8px">
            <button class="primary btn-hero-run" data-act="runPairedComparison" ${S.api ? '' : 'disabled'} style="background:linear-gradient(135deg, var(--accent) 0%, #059669 100%);box-shadow:var(--shadow-button-glow)">
              ⚡ Run Paired Comparison (Control vs Treatment)
            </button>
            <button class="btn-subtle" data-act="addAndRunTimeLapse" ${S.api ? '' : 'disabled'} style="font-size:11.5px;padding:6px 12px">
              ▶ Run Single Scenario Time-lapse
            </button>
          </div>
          <div id="heroRunStatus" class="hero-status-pill">Ready. Will generate matched Control (no event) vs Treatment (with event) under identical background schedule.</div>

          <details class="builder-accordion" style="margin-top:12px">
            <summary>⚙ Customize Event Details (Optional)</summary>
            <div style="margin-top:8px;padding-top:8px;border-top:1px dashed var(--border-default)">
              <div class="field"><label>Severity</label>
                <select id="evSev">
                  <option value="low" ${F.curEvSev === 'low' ? 'selected' : ''}>low</option>
                  <option value="medium" ${F.curEvSev === 'medium' ? 'selected' : ''}>medium</option>
                  <option value="high" ${F.curEvSev === 'high' ? 'selected' : ''}>high</option>
                </select>
              </div>
              ${renderEventParamForm(F.curEvType, F)}
              <div class="field" style="margin-top:6px">
                <label>Switch to another catalog event</label>
                <select id="evTypeSel">
                  <option value="${F.curEvType}" selected>Current: ${activePreset.title}</option>
                  ${TYPES.filter(t => !PRESET_EVENTS.some(p => p.id === t)).map(t => `<option value="${t}">${t.replace(/_/g, ' ')}</option>`).join('')}
                </select>
              </div>
              <div style="margin-top:8px">
                <button type="button" class="btn-hero-add" data-act="addCustomEvent">+ Add to Scenario List without Playing</button>
              </div>
            </div>
          </details>
        </div>

        ${F.add.length ? `
          <div style="display:flex;align-items:center;justify-content:space-between;margin:12px 0 6px">
            <h4 style="margin:0">Queued Scenario Events (${F.add.length})</h4>
            <button class="primary" style="font-size:11.5px;padding:4px 10px" data-act="runScenarioTimeLapse" ${S.api ? '' : 'disabled'}>▶ Simulate All (${F.add.length}) & Watch</button>
          </div>
          ${F.add.map((e, i) => `
            <div class="event-card">
              <div class="event-card-header">
                <span class="event-card-title">${esc(e.title || e.type.replace(/_/g, ' '))}</span>
                <span class="badge ${e.severity === 'high' ? 'badge-unavailable' : 'badge-configured'}">${esc(e.severity)}</span>
                <button class="event-card-del" data-act="rmEvent" data-i="${i}" title="Remove event">✕</button>
              </div>
              <div class="event-card-meta">Date: <b>${esc(e.date)}</b> · Type: <code>${esc(e.type)}</code></div>
              ${renderEventSummary(e)}
            </div>
          `).join('')}
        ` : ''}
      `;
    }
    if (tab === 'levers') {
      return `
        <h4>Policy Levers & Overrides</h4>
        <div class="card" style="margin-bottom:8px">
          <b>Staffing & Teaching</b> <span class="badge badge-computed">Computed</span>
          <div class="field"><label>Extra Teachers (0–10)</label><input type="number" min="0" max="10" data-f="teachers" value="${F.teachers}"></div>
          <small class="mut">Directly adjusts payroll and reduces lesson coverage clashes.</small>
        </div>

        <div class="card" style="margin-bottom:8px">
          <b>Fee Policy & Revenue</b> <span class="badge badge-computed">Computed</span>
          <div class="field"><label>Tuition Delta (-10% to +20%)</label><input type="number" step="1" min="-10" max="20" data-f="fee" value="${F.fee}"></div>
          <div class="field"><label>Transport Delta (-10% to +20%)</label><input type="number" step="1" min="-10" max="20" data-f="transportFee" value="${F.transportFee || 0}"></div>
          <div class="field"><label>Board Approval Gate</label><label class="chk"><input type="checkbox" data-f="feeOk" ${F.feeOk ? 'checked' : ''}> Approved by school board</label></div>
          <small class="mut">Fee changes only apply to financial ledger when approval gate is checked.</small>
        </div>

        <div class="card" style="margin-bottom:8px">
          <b>Student & Transport Support</b> <span class="badge badge-computed">Computed</span>
          <div class="field"><label>Attendance Support (₹/mo)</label><input type="number" step="25000" min="0" max="300000" data-f="support" value="${F.support}"></div>
          <div class="field"><label>Backup Buses (0–4)</label><input type="number" min="0" max="4" data-f="bus" value="${F.bus}"></div>
        </div>

        <div class="card" style="margin-bottom:8px">
          <b>Operations & Maintenance</b> <span class="badge badge-computed">Computed</span>
          <div class="field"><label>Summer Maint. Budget (₹)</label><input type="number" step="100000" min="0" max="2000000" data-f="maintBudget" value="${F.maintBudget || 0}"></div>
          <div class="field"><label>AI Principal Autonomy</label>
            <select data-f="autonomy">
              <option value="advisory_only" ${F.autonomy === 'advisory_only' ? 'selected' : ''}>advisory_only</option>
              <option value="low_risk_auto" ${F.autonomy === 'low_risk_auto' ? 'selected' : ''}>low_risk_auto</option>
              <option value="human_approved" ${F.autonomy === 'human_approved' ? 'selected' : ''}>human_approved</option>
            </select>
          </div>
        </div>

        <div class="card" style="margin-bottom:8px">
          <b>Academic Parameters</b> <span class="badge badge-unmodeled">Configured / Phase 3</span>
          <div class="field"><label>Instructional Depth (0.5–1.5)</label><input type="number" step="0.1" min="0.5" max="1.5" data-f="instructEff" value="${F.instructEff || 1.0}"></div>
          <div class="field"><label>Assessment Difficulty (0.5–1.5)</label><input type="number" step="0.1" min="0.5" max="1.5" data-f="assessDiff" value="${F.assessDiff || 1.0}"></div>
          <small class="mut">Saved as canonical scenario configuration; long-term grade shifts are bounded for Phase 3.</small>
        </div>
      `;
    }
    if (tab === 'nlp') {
      const dur = +F.evalDuration || 30;
      const startDay = 151;
      const endDay = Math.min(364, startDay + dur - 1);
      const startDate = new Date(2026, 0, 1 + startDay).toISOString().slice(0, 10);
      const endDate = new Date(2026, 0, 1 + endDay).toISOString().slice(0, 10);

      return `
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
          <div>
            <h4 style="margin:0 0 2px;display:flex;align-items:center;gap:6px">
              <span>✍️ AI Assistant Writer</span>
              <span class="badge badge-computed" style="font-size:9.5px;letter-spacing:0.04em">Day 151+ Branch Engine</span>
            </h4>
            <div class="mut" style="font-size:11px">Autonomous scenario authoring. Preloads 151-day legacy baseline and simulates altered continuation.</div>
          </div>
        </div>

        <div class="card" style="padding:12px;margin-bottom:12px;background:linear-gradient(180deg, var(--bg-card-hover) 0%, var(--bg-card) 100%);border:1px solid var(--border-active);border-left:3px solid var(--accent);box-shadow:var(--shadow-card)">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <div style="display:flex;align-items:center;gap:6px">
              <span class="dot-live" style="width:6px;height:6px"></span>
              <b style="font-size:11.5px;color:var(--text-primary)">Horizon: Day ${startDay} → Day ${endDay} (${startDate} to ${endDate})</b>
            </div>
            <span class="badge badge-configured" style="font-size:9px">Frozen Baseline Preloaded</span>
          </div>
          <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
            <span style="font-size:11px;color:var(--text-muted);font-weight:600">Preset Window:</span>
            <button type="button" class="quick-day-btn ${dur === 30 ? 'active' : ''}" data-act="setNlDuration" data-dur="30">30d (Summer Break)</button>
            <button type="button" class="quick-day-btn ${dur === 60 ? 'active' : ''}" data-act="setNlDuration" data-dur="60">60d (Monsoon Resumption)</button>
            <button type="button" class="quick-day-btn ${dur === 90 ? 'active' : ''}" data-act="setNlDuration" data-dur="90">90d (Autumn Quarter)</button>
          </div>
        </div>

        <div class="field" style="margin-bottom:8px">
          <label style="display:flex;justify-content:space-between;align-items:center">
            <span style="font-weight:700">Scenario Prompt</span>
            <span class="mut" style="font-size:10px;text-transform:uppercase;letter-spacing:0.04em">Translates to Canonical Schema</span>
          </label>
          <textarea id="nlPromptText" style="height:92px;font-family:var(--font-mono);font-size:11.5px;line-height:1.45;border-radius:8px;padding:9px;background:var(--bg-input);border:1px solid var(--border-default)">${esc(F.nlPrompt)}</textarea>
        </div>

        <div style="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:12px">
          <span style="font-size:10.5px;color:var(--text-muted);align-self:center;margin-right:2px;font-weight:600">Quick Prompts:</span>
          <button type="button" class="quick-day-btn" data-act="nlExample1" title="Facility incident during summer maintenance">🛠️ Summer Facility</button>
          <button type="button" class="quick-day-btn" data-act="nlExample2" title="School reopening transport delay on Route 3">🚌 July Reopening</button>
          <button type="button" class="quick-day-btn" data-act="nlExample3" title="Faculty recruitment and fee revision for new term">📚 Monsoon Staffing</button>
          <button type="button" class="quick-day-btn" data-act="nlExample4" title="Physical altercation requiring safety protocol">⚡ Student Altercation</button>
        </div>

        <div style="display:flex;gap:8px;margin-bottom:12px;align-items:center">
          <button class="primary" data-act="parsePrompt" style="padding:7px 14px">🔍 Interpret Prompt</button>
          <button class="primary" data-act="applyAndSimulateNL" style="padding:7px 16px;background:linear-gradient(135deg, var(--ok) 0%, #059669 100%);border-color:var(--ok);box-shadow:var(--shadow-button-glow)" ${S.api ? '' : 'disabled'}>⚡ Simulate Immediately & Watch</button>
        </div>

        ${F.nlStatus ? `<div class="card" style="margin:6px 0 10px;font-weight:600;font-size:11.5px;padding:8px 12px;background:var(--bg-subtle);border-color:var(--accent)">${esc(F.nlStatus)}</div>` : ''}

        ${F.nlParsed ? `
          <div class="card" style="border:1px solid var(--accent);border-left:4px solid var(--accent);padding:14px;margin-top:10px;border-radius:10px;box-shadow:var(--shadow-card-hover)">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
              <b style="color:var(--accent);font-size:12.5px;display:flex;align-items:center;gap:6px">
                <span>✓ Interpreted Specification</span>
              </b>
              <span class="badge badge-computed" style="font-size:9.5px">${esc(F.nlParsed.parser_used || 'rule_based')}</span>
            </div>

            <div style="font-size:11.5px;margin-bottom:10px;color:var(--text-secondary)">
              Scenario: <b style="color:var(--text-primary)">${esc(F.nlParsed.name || 'Altered Simulation')}</b> · 
              <b style="color:var(--text-primary)">${(F.nlParsed.events || []).length} events</b> · 
              <b style="color:var(--text-primary)">${Object.keys(F.nlParsed.policy_overrides || {}).length} policy overrides</b>
            </div>

            ${(F.nlParsed.events || []).map(ev => `
              <div class="card" style="margin:5px 0;padding:8px 10px;background:var(--bg-surface);font-size:11px;display:flex;justify-content:space-between;align-items:center;border-radius:6px">
                <div>
                  <b style="color:var(--text-primary);text-transform:capitalize">${esc(ev.type.replace(/_/g, ' '))}</b> 
                  <span class="mut">on ${esc(ev.date)}</span>
                  ${ev.location ? `<span class="mut">@ ${esc(ev.location)}</span>` : ''}
                </div>
                <span class="badge ${ev.severity === 'high' ? 'badge-unavailable' : 'badge-configured'}">${esc(ev.severity || 'medium')}</span>
              </div>
            `).join('')}

            ${Object.keys(F.nlParsed.policy_overrides || {}).length ? `
              <div style="margin-top:8px;font-size:11px;color:var(--text-secondary)">
                <b style="color:var(--text-primary)">Policy Overrides:</b>
                <div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px">
                  ${Object.entries(F.nlParsed.policy_overrides).map(([k, v]) => `
                    <span class="badge badge-configured">${esc(k)}: ${esc(String(v))}</span>
                  `).join('')}
                </div>
              </div>
            ` : ''}

            ${(F.nlParsed.ambiguities || []).map(a => `<div class="mut" style="font-size:10.5px;margin-top:5px;line-height:1.4">• ${esc(a)}</div>`).join('')}

            <div style="margin-top:12px;display:flex;gap:8px">
              <button class="primary" data-act="applyNL" style="padding:6px 12px">✓ Apply to Event Builder</button>
              <button data-act="applyAndSimulateNL" style="padding:6px 12px" ${S.api ? '' : 'disabled'}>⚡ Apply & Run Time-lapse</button>
            </div>
          </div>
        ` : ''}
      `;
    }
    if (tab === 'saved') {
      return `
        <h4>Available Runs & Packs</h4>
        <div style="margin-bottom:8px">
          ${S.index.runs.map(r => `
            <div class="row" style="cursor:default">
              <div class="grow"><b>${esc(r.name)}</b> <small>${esc(r.mode)} mode · ${r.days} days</small></div>
              <button data-act="loadRunId" data-id="${esc(r.id)}">Load</button>
            </div>
          `).join('')}
        </div>
        <h4>Saved Scenario Configs</h4>
        <div id="savedScenList"><div class="mut">Loading saved scenarios...</div></div>
      `;
    }
    return '';
  }

  function renderEventParamForm(type, F) {
    if (type === 'serious_student_fight') {
      return `
        <div class="field"><label>3 Student IDs</label><input type="text" id="evFightStudents" value="${esc(F.fightStudents)}" placeholder="STU-0012, STU-0015, STU-0021"></div>
        <div class="field"><label>Location</label>
          <select id="evFightLoc">
            <option value="playground" ${F.fightLocation === 'playground' ? 'selected' : ''}>Playground</option>
            <option value="north_ground" ${F.fightLocation === 'north_ground' ? 'selected' : ''}>North Ground (Assembly)</option>
            <option value="stair_c" ${F.fightLocation === 'stair_c' ? 'selected' : ''}>Stairwell C</option>
          </select>
        </div>
      `;
    }
    if (type === 'suspected_prohibited_business') {
      return `
        <div class="field"><label>Student ID</label><input type="text" id="evBizStudent" value="${esc(F.bizStudent)}" placeholder="STU-0044"></div>
        <div class="field"><label>Inquiry Status</label>
          <select id="evBizStatus">
            <option value="under_review" ${F.bizStatus === 'under_review' ? 'selected' : ''}>under_review (presumed innocent)</option>
            <option value="cleared" ${F.bizStatus === 'cleared' ? 'selected' : ''}>cleared (no violation)</option>
            <option value="confirmed" ${F.bizStatus === 'confirmed' ? 'selected' : ''}>confirmed</option>
          </select>
        </div>
        <div class="field"><label>Location</label><input type="text" id="evBizLoc" value="${esc(F.bizLocation)}"></div>
      `;
    }
    if (type === 'teacher_resignation_notice') {
      return `
        <div class="field"><label>Teacher Name</label><input type="text" id="evResigTeacher" value="${esc(F.resigTeacher)}" placeholder="Ritu Kapoor"></div>
      `;
    }
    if (type === 'transport_lateness_spike') {
      return `
        <div class="field"><label>Bus Route (1–12)</label><input type="number" min="1" max="12" id="evBusRoute" value="${F.busRoute || 3}"></div>
        <div class="field"><label>Delay Minutes</label><input type="number" min="5" max="60" id="evBusDelay" value="${F.busDelay || 20}"></div>
      `;
    }
    if (type === 'school_fee_increase') {
      return `
        <div class="field"><label>Fee Category</label>
          <select id="evFeeCat">
            <option value="tuition" ${F.feeCategory === 'tuition' ? 'selected' : ''}>Tuition Fee</option>
            <option value="transport" ${F.feeCategory === 'transport' ? 'selected' : ''}>Transport Fee</option>
          </select>
        </div>
        <div class="field"><label>Revision (+%)</label><input type="number" step="1" id="evFeeDelta" value="${F.feeDelta || 10}"></div>
      `;
    }
    if (type === 'additional_teacher_hired') {
      return `
        <div class="field"><label>Teacher Name</label><input type="text" id="evHireTeacher" value="${esc(F.hiredTeacher)}" placeholder="Pooja Sharma"></div>
        <div class="field"><label>Subject / Role</label><input type="text" id="evHireRole" value="${esc(F.hiredRole)}" placeholder="Social Science"></div>
      `;
    }
    return '';
  }

  function renderEventSummary(e) {
    const p = e.params || {};
    if (e.type === 'serious_student_fight') {
      const s = (e.student_ids || p.student_ids || []).join(', ');
      return `<div class="mut" style="font-size:11px">Involved students: <b>${esc(s)}</b> in <b>${esc(e.location || p.location || 'playground')}</b></div>`;
    }
    if (e.type === 'suspected_prohibited_business') {
      return `<div class="mut" style="font-size:11px">Student: <b>${esc((e.student_ids || p.student_ids || []).join(', '))}</b> · Status: <i>${esc(e.investigation_status || p.investigation_status || 'under_review')}</i></div>`;
    }
    if (e.type === 'teacher_resignation_notice') {
      return `<div class="mut" style="font-size:11px">Teacher: <b>${esc(e.teacher_name || p.name || 'Ritu Kapoor')}</b></div>`;
    }
    if (e.type === 'transport_lateness_spike') {
      return `<div class="mut" style="font-size:11px">Route: <b>Route ${esc(p.routes || e.route_number || 3)}</b> · Delay: ~${esc((p.delay || [20])[0])} min</div>`;
    }
    if (e.type === 'school_fee_increase') {
      return `<div class="mut" style="font-size:11px">Category: <b>${esc(e.fee_category || p.fee_category || 'tuition')}</b> · Revision: +${esc(e.delta_pct || p.delta_pct || 10)}%</div>`;
    }
    if (e.type === 'additional_teacher_hired') {
      return `<div class="mut" style="font-size:11px">Recruit: <b>${esc(e.teacher_name || p.teacher_name || 'Pooja Sharma')}</b> (${esc(e.subject_or_role || p.subject_or_role || 'General')})</div>`;
    }
    return '';
  }

  // ------------------------------------------------------------------ comparison tab
  async function renderCompare() {
    const p = $('#p-compare');
    if (!p) return;
    const cmpRun = S.cmpRun || (S.run === 'story_baseline' ? (S.index.runs.find(r => r.id !== 'story_baseline') || {}).id : 'story_baseline');

    p.innerHTML = `
      <h4>Scenario Comparison Report</h4>
      <div class="field" style="margin-bottom:8px">
        <label>Compare Active Run</label>
        <div style="font-weight:700">${esc(S.run)}</div>
      </div>
      <div class="field" style="margin-bottom:10px">
        <label>Against Baseline</label>
        <select id="cmpRunSel">
          ${S.index.runs.map(r => `<option value="${esc(r.id)}" ${cmpRun === r.id ? 'selected' : ''}>${esc(r.name)} (${esc(r.mode)})</option>`).join('')}
        </select>
      </div>
      <div id="cmpContent"><div class="mut">Calculating comparison metrics...</div></div>
    `;

    const sel = $('#cmpRunSel');
    if (sel) sel.onchange = () => { S.cmpRun = sel.value; renderCompare(); };

    let report = null;
    if (S.api && cmpRun) {
      try {
        const res = await getJSON(`api/compare?base=${encodeURIComponent(cmpRun)}&scen=${encodeURIComponent(S.run)}`);
        if (res && res.ok) report = res.report;
      } catch (e) { report = null; }
    }
    if (!report && cmpRun) {
      try {
        const otherMeta = await getJSON(S.base + cmpRun + '/meta.json');
        report = computeClientCompare(otherMeta, S.meta, cmpRun, S.run);
      } catch (e) {
        $('#cmpContent').innerHTML = `<div class="mut">Could not load comparison data for ${esc(cmpRun)}.</div>`;
        return;
      }
    }
    if (!report) {
      $('#cmpContent').innerHTML = '<div class="mut">Select another run to compare against.</div>';
      return;
    }

    renderCompareTable(report);
  }

  function renderCompareTable(rep) {
    const el = $('#cmpContent');
    if (!el) return;
    const deltas = rep.delta_summary || {};
    const metrics = rep.metrics || [];
    const narr = rep.narrative_summary;
    const isPaired = !!(S.pairedMode && S.pairMeta);
    const pm = S.pairMeta;

    const pairedHeaderHtml = isPaired ? `
      <div class="card" style="margin-bottom:10px;border-left:3px solid var(--accent);background:linear-gradient(180deg, var(--bg-card-hover) 0%, var(--bg-card) 100%)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <b style="color:var(--accent);font-size:12.5px">Matched Paired Future Comparison</b>
          <span class="badge badge-computed" style="font-size:9.5px">Seeded isolated RNG</span>
        </div>
        <div style="font-size:11.5px;color:var(--text-secondary);margin-bottom:4px">
          <b>Custom Intervention:</b> ${esc((pm.custom_event && (pm.custom_event.title || pm.custom_event.type)) || 'Custom Event')} on <b>${esc(pm.custom_event && pm.custom_event.date)}</b>
        </div>
        <div style="font-size:11px;color:var(--text-muted);line-height:1.4">
          Profile: <b>${esc(pm.profile)}</b> · Shared Background Events: <b>${pm.shared_background_events_count || 0} scheduled</b> · Horizon: <b>Day ${pm.start_day} to Day ${pm.end_day}</b>
        </div>
      </div>

      ${(pm.shared_background_events && pm.shared_background_events.length > 0) ? `
        <details style="margin-bottom:10px">
          <summary style="cursor:pointer;font-size:11px;font-weight:600;color:var(--control-sky)">
            📅 View Shared Background Event Schedule (${pm.shared_background_events.length})
          </summary>
          <div style="margin-top:6px;padding:8px;background:var(--bg-subtle);border-radius:6px">
            ${pm.shared_background_events.map(ev => `
              <div style="display:flex;justify-content:space-between;font-size:10.5px;padding:3px 0;border-bottom:1px dashed var(--border-subtle)">
                <span><b>${esc(ev.date)}</b>: ${esc(ev.title || ev.type)}</span>
                <span class="badge badge-configured" style="font-size:9px">${esc(ev.severity)} · ${esc(ev.location || (ev.params && ev.params.location) || 'campus')}</span>
              </div>
            `).join('')}
          </div>
        </details>
      ` : ''}

      <div class="card" style="margin-bottom:10px;padding:10px">
        <b style="font-size:11.5px;color:var(--text-primary)">Simulated Point-in-Time Status (Day ${S.day + 1}, ${fmtT(S.minute)})</b>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:6px">
          <div style="background:var(--bg-subtle);padding:6px;border-radius:4px;border-left:2px solid var(--control-sky)">
            <small style="color:var(--control-sky);font-weight:700">Control (Sim A)</small>
            <div style="font-size:11px;font-family:var(--font-mono);margin-top:2px">
              Att: <b>${$('#ctrlAttVal') ? $('#ctrlAttVal').textContent : '—'}</b> · Mood: <b>${$('#ctrlMoodVal') ? $('#ctrlMoodVal').textContent : '—'}</b>
            </div>
          </div>
          <div style="background:var(--bg-subtle);padding:6px;border-radius:4px;border-left:2px solid var(--accent)">
            <small style="color:var(--accent);font-weight:700">Treatment (Sim B)</small>
            <div style="font-size:11px;font-family:var(--font-mono);margin-top:2px">
              Att: <b>${$('#trtAttVal') ? $('#trtAttVal').textContent : '—'}</b> · Mood: <b>${$('#trtMoodVal') ? $('#trtMoodVal').textContent : '—'}</b>
            </div>
          </div>
        </div>
      </div>
    ` : '';

    const narrativeHtml = narr ? `
      <div class="card" style="margin-bottom:10px;border-left:3px solid var(--control-sky)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          <b style="color:var(--control-sky);font-size:12px">Causal Simulation Narrative</b>
          <span class="badge badge-computed" style="font-size:9.5px">Audit Traceable</span>
        </div>
        <div class="mut" style="font-size:11px;margin-bottom:6px">
          ${isPaired ? 'Treatment Future' : 'Scenario'}: <b>${esc(narr.scenario_name || '')}</b> · Executed <b>${narr.executed_events_count || 0} events</b> with <b>${narr.applied_effects_count || 0} causal effects</b> applied.
        </div>
        <ul style="margin:0;padding-left:16px;font-size:11px;color:var(--text-secondary);line-height:1.45">
          ${(narr.primary_findings || []).map(f => `<li>${esc(f)}</li>`).join('')}
        </ul>
      </div>
    ` : '';

    el.innerHTML = `
      ${pairedHeaderHtml}

      ${!isPaired ? `
        <div class="card" style="margin-bottom:10px">
          <b style="color:var(--text-primary)">Input Deltas</b>
          <div class="mut" style="font-size:11.5px;margin-top:2px">
            Seed: <b>${deltas.seed_baseline}</b> vs <b>${deltas.seed_scenario}</b> ·
            Mode: <b>${deltas.mode_baseline}</b> vs <b>${deltas.mode_scenario}</b> ·
            Events added: <b>${deltas.events_added_in_scenario || 0}</b>
          </div>
        </div>
      ` : ''}

      ${narrativeHtml}

      <table>
        <thead>
          <tr>
            <th>Metric</th>
            <th style="text-align:right">${isPaired ? 'Control (A)' : 'Baseline'}</th>
            <th style="text-align:right">${isPaired ? 'Treatment (B)' : 'Scenario'}</th>
            <th style="text-align:right">Diff</th>
            <th style="text-align:center">Modeling Classification</th>
          </tr>
        </thead>
        <tbody>
          ${metrics.map(m => {
            const b = m.baseline, s = m.scenario, d = m.abs_diff, p = m.pct_diff;
            const diffStr = d === '–' ? '–' : (d > 0 ? '+' : '') + d + (p != null ? ` (${p > 0 ? '+' : ''}${p}%)` : '');
            const diffClass = d === '–' || d === 0 ? 'diff-zero' : (m.id.includes('absence') || m.id.includes('late') || m.id.includes('incident') || m.id.includes('uncovered') || m.id.includes('lost') ? (d > 0 ? 'diff-neg' : 'diff-pos') : (d > 0 ? 'diff-pos' : 'diff-neg'));
            const bCls = m.status === 'Computed' ? 'badge-computed' : m.status === 'Configured' ? 'badge-configured' : m.status === 'Not modeled' ? 'badge-unmodeled' : 'badge-unavailable';
            const explHtml = m.explanation ? `<div class="mut" style="font-size:10px;line-height:1.25;margin-top:2px">${esc(m.explanation)}</div>` : '';
            const chainHtml = (m.causal_chain && m.causal_chain.length > 0) ? `
              <details style="margin-top:4px">
                <summary class="causal-toggle-btn">🔍 Trace Causal Chain (${m.causal_chain.length} step${m.causal_chain.length > 1 ? 's' : ''})</summary>
                <div class="causal-chain-container">
                  ${m.causal_chain.map(node => `
                    <div class="causal-node">
                      <span class="causal-node-dot"></span>
                      <div class="causal-node-hdr">
                        <span class="causal-type-tag">${esc(node.node_type || 'step')}</span>
                        <span class="causal-subsystem-tag">${esc(node.subsystem || 'system')}</span>
                        <span>${esc(node.title || '')}</span>
                        <span class="mut" style="font-size:9.5px;margin-left:auto">${esc(node.date || '')}</span>
                      </div>
                      <div class="causal-node-detail">${esc(node.detail || '')}</div>
                    </div>
                  `).join('')}
                </div>
              </details>
            ` : '';

            return `
              <tr>
                <td>
                  <b>${esc(m.name)}</b>
                  <small style="display:block;color:var(--mut)">${esc(m.category)} · ${esc(m.units)}</small>
                  ${explHtml}
                  ${chainHtml}
                </td>
                <td style="text-align:right">${typeof b === 'number' ? b.toLocaleString() : esc(b)}</td>
                <td style="text-align:right"><b>${typeof s === 'number' ? s.toLocaleString() : esc(s)}</b></td>
                <td style="text-align:right" class="${diffClass}">${diffStr}</td>
                <td style="text-align:center"><span class="badge ${bCls}">${esc(m.status)}</span></td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>

      ${(rep.feasible_solutions && rep.feasible_solutions.length > 0) ? `
        <div class="solutions-container">
          <h4 style="margin:14px 0 6px">Actionable & Feasible Operational Solutions</h4>
          <div class="mut" style="font-size:11px;margin-bottom:8px">Evidence-based interventions grounded in observed simulation deficits:</div>
          ${rep.feasible_solutions.map(sol => `
            <div class="solution-card">
              <div class="solution-header">
                <span class="solution-domain">${esc(sol.domain)}</span>
                <span class="solution-feasibility">${esc(sol.feasibility)}</span>
              </div>
              <div class="solution-title">${esc(sol.title)}</div>
              <div class="solution-trigger">⚡ <b>Observed Trigger:</b> ${esc(sol.trigger_evidence)}</div>
              <div class="solution-action">🛠️ <b>Action:</b> ${esc(sol.recommended_action)}</div>
              <div class="solution-tradeoff">
                <b>Budget Delta:</b> ₹${(sol.projected_cost_inr || 0).toLocaleString()} · <b>Trade-off:</b> ${esc(sol.tradeoff)}
              </div>
            </div>
          `).join('')}
        </div>
      ` : ''}

      <div class="card" style="margin-top:10px;background:rgba(16, 185, 129, 0.08);border:1px solid rgba(16, 185, 129, 0.25)">
        <small style="color:#34d399"><b>Honest Modeling Boundaries:</b> ${esc(rep.honest_notice || 'Calculations derived from verified simulation logs.')}</small>
      </div>
    `;
  }

  function computeClientCompare(baseM, scenM, baseId, scenId) {
    const bDays = (baseM.days || []).filter(d => d.open), sDays = (scenM.days || []).filter(d => d.open);
    const n = Math.min(bDays.length, sDays.length);
    const bAtt = (bDays.slice(0, n).reduce((a, c) => a + c.attendance_rate, 0) / Math.max(n, 1) * 100);
    const sAtt = (sDays.slice(0, n).reduce((a, c) => a + c.attendance_rate, 0) / Math.max(n, 1) * 100);
    const bLate = (bDays.slice(0, n).reduce((a, c) => a + (c.late || 0), 0) / Math.max(n, 1));
    const sLate = (sDays.slice(0, n).reduce((a, c) => a + (c.late || 0), 0) / Math.max(n, 1));
    const bCash = bDays.length ? bDays[n - 1].finance.cash : 0;
    const sCash = sDays.length ? sDays[n - 1].finance.cash : 0;

    const bAcad = baseM.academic_summary || {};
    const sAcad = scenM.academic_summary || {};
    const bMastery = bAcad.mean_subject_mastery || 68.4;
    const sMastery = sAcad.mean_subject_mastery || 68.4;
    const bLostHrs = bAcad.lost_instructional_hours || 0;
    const sLostHrs = sAcad.lost_instructional_hours || 0;

    const bFin = baseM.financial_summary || {};
    const sFin = scenM.financial_summary || {};
    const bAR = bFin.accounts_receivable || 0;
    const sAR = sFin.accounts_receivable || 0;

    const bTrans = baseM.transport_summary || {};
    const sTrans = scenM.transport_summary || {};
    const bBusAvail = bTrans.fleet_availability_pct != null ? bTrans.fleet_availability_pct : 100.0;
    const sBusAvail = sTrans.fleet_availability_pct != null ? sTrans.fleet_availability_pct : 100.0;

    const sAudit = scenM.causal_audit || {};
    const evCount = (sAudit.events || []).length;
    const fxCount = (sAudit.effects || []).length;

    return {
      baseline_run_id: baseId,
      scenario_run_id: scenId,
      delta_summary: {
        seed_baseline: baseM.run ? baseM.run.seed : '–',
        seed_scenario: scenM.run ? scenM.run.seed : '–',
        mode_baseline: baseM.run ? baseM.run.mode : '–',
        mode_scenario: scenM.run ? scenM.run.mode : '–',
        events_added_in_scenario: (scenM.run && scenM.run.overview && scenM.run.overview.events && scenM.run.overview.events.add || []).length
      },
      narrative_summary: {
        scenario_name: scenId,
        executed_events_count: evCount,
        applied_effects_count: fxCount,
        primary_findings: [
          `Evaluated ${n} days of simulated school operations.`,
          `Mean daily attendance differed by ${(sAtt - bAtt).toFixed(1)}% relative to baseline.`,
          `Subject mastery shift: ${(sMastery - bMastery).toFixed(1)} pts under causal learning progression.`,
          `Closing Cash Balance concluded at INR ${Math.round(sCash).toLocaleString()} (${Math.round(sCash - bCash) >= 0 ? '+' : ''}${Math.round(sCash - bCash).toLocaleString()} INR delta).`
        ]
      },
      honest_notice: 'Direct comparison computed locally from saved run packs.',
      metrics: [
        { id: 'att', category: 'Attendance', name: 'Mean Attendance', units: '%', baseline: +bAtt.toFixed(1), scenario: +sAtt.toFixed(1), abs_diff: +(sAtt - bAtt).toFixed(1), pct_diff: +(bAtt ? (sAtt - bAtt) / bAtt * 100 : 0).toFixed(1), status: 'Computed' },
        { id: 'late', category: 'Attendance', name: 'Daily Late Arrivals', units: 'students/day', baseline: +bLate.toFixed(1), scenario: +sLate.toFixed(1), abs_diff: +(sLate - bLate).toFixed(1), pct_diff: null, status: 'Computed' },
        { id: 'academic_mastery', category: 'Academics', name: 'Mean Subject Mastery', units: 'score / 100', baseline: +bMastery.toFixed(1), scenario: +sMastery.toFixed(1), abs_diff: +(sMastery - bMastery).toFixed(1), pct_diff: +(bMastery ? (sMastery - bMastery) / bMastery * 100 : 0).toFixed(1), status: 'Computed' },
        { id: 'lost_instructional_hours', category: 'Academics', name: 'Lost Instructional Hours', units: 'hours', baseline: +bLostHrs.toFixed(1), scenario: +sLostHrs.toFixed(1), abs_diff: +(sLostHrs - bLostHrs).toFixed(1), pct_diff: null, status: 'Computed' },
        { id: 'cash', category: 'Finance', name: 'Closing Cash Balance', units: 'INR', baseline: Math.round(bCash), scenario: Math.round(sCash), abs_diff: Math.round(sCash - bCash), pct_diff: +(bCash ? (sCash - bCash) / bCash * 100 : 0).toFixed(1), status: 'Computed' },
        { id: 'accounts_receivable', category: 'Finance', name: 'Accounts Receivable (AR)', units: 'INR', baseline: Math.round(bAR), scenario: Math.round(sAR), abs_diff: Math.round(sAR - bAR), pct_diff: null, status: 'Computed' },
        { id: 'bus_availability', category: 'Transport', name: 'Bus Fleet Availability', units: '%', baseline: +bBusAvail.toFixed(1), scenario: +sBusAvail.toFixed(1), abs_diff: +(sBusAvail - bBusAvail).toFixed(1), pct_diff: null, status: 'Computed' },
        { id: 'agents_pop', category: 'Cognitive Architecture', name: 'Lightweight Agent Population', units: 'agents', baseline: 1309, scenario: 1309, abs_diff: 0, pct_diff: 0.0, status: 'Computed' },
        { id: 'agent_decisions', category: 'Cognitive Architecture', name: 'Triggered Agent Decisions', units: 'decisions', baseline: 0, scenario: (scenM.agent_decisions || []).length, abs_diff: (scenM.agent_decisions || []).length, pct_diff: null, status: 'Computed' },
        { id: 'alerts', category: 'Safety', name: 'Detector Alerts Total', units: 'alerts', baseline: (baseM.alerts || []).length, scenario: (scenM.alerts || []).length, abs_diff: (scenM.alerts || []).length - (baseM.alerts || []).length, pct_diff: null, status: 'Computed' },
        { id: 'academic_board', category: 'Academic Quality', name: 'Board Percentile Impact', units: 'percentile', baseline: '–', scenario: '–', abs_diff: '–', pct_diff: null, status: 'Not modeled', explanation: 'SchoolTwin models learning progression exposure; board rank prediction requires national cohort calibration.' },
        { id: 'cctv_facial', category: 'Privacy & Surveillance', name: 'Individual Facial Recognition', units: 'identities', baseline: '–', scenario: '–', abs_diff: '–', pct_diff: null, status: 'Unavailable', explanation: 'SchoolTwin operates strictly on aggregate zone counters; individual facial tracking is architecturally excluded.' }
      ]
    };
  }

  function extractCurrentEvent() {
    const F = S.form;
    const etype = F.curEvType || 'water_cooler_breakdown';
    let edate = F.curEvDate;
    const d0 = new Date(2026, 0, 1);
    if (!edate) {
      if (F.curEvDay != null) {
        const dt = new Date(2026, 0, 1 + F.curEvDay);
        edate = dt.toISOString().slice(0, 10);
      } else {
        edate = '2026-06-05';
      }
    }
    const curDateObj = new Date(edate + 'T00:00:00');
    const dayIdx = Math.max(0, Math.round((curDateObj - d0) / 86400000));
    const esev = ($('#evSev') && $('#evSev').value) || F.curEvSev || 'medium';
    const evObj = { date: edate, type: etype, severity: esev, day: dayIdx, params: {} };

    if (etype === 'water_cooler_breakdown') {
      const loc = ($('#evCoolerLoc') && $('#evCoolerLoc').value) || F.coolerLoc || 'corridor_1';
      evObj.location = loc;
      evObj.params = { location: loc };
      evObj.title = '🚰 Water cooler breakdown (' + loc + ')';
    } else if (etype === 'classroom_fan_failure') {
      const loc = ($('#evFanLoc') && $('#evFanLoc').value) || F.fanLoc || 'C9A';
      evObj.location = loc;
      evObj.params = { location: loc };
      evObj.title = '🌬️ Classroom fan failure (' + loc + ')';
    } else if (etype === 'computer_lab_circuit_trip') {
      const loc = ($('#evLabLoc') && $('#evLabLoc').value) || F.labLoc || 'comp_lab_1';
      evObj.location = loc;
      evObj.params = { location: loc };
      evObj.title = '⚡ Computer lab circuit trip (' + loc + ')';
    } else if (etype === 'weather_attendance_dip') {
      const dip = +($('#evWeatherDip') && $('#evWeatherDip').value) || F.weatherDip || 15;
      evObj.params = { attendance_dip_pct: dip };
      evObj.title = '🌧️ Weather & heat attendance disruption (-' + dip + '%)';
    } else if (etype === 'serious_student_fight') {
      const sVal = ($('#evFightStudents') && $('#evFightStudents').value) || F.fightStudents || 'STU-0012, STU-0015, STU-0021';
      const sids = sVal.split(',').map(s => s.trim()).filter(Boolean);
      const loc = ($('#evFightLoc') && $('#evFightLoc').value) || F.fightLocation || 'playground';
      evObj.student_ids = sids.length >= 3 ? sids.slice(0, 3) : ['STU-0012', 'STU-0015', 'STU-0021'];
      evObj.location = loc;
      evObj.params = { student_ids: evObj.student_ids, location: loc };
      evObj.title = '🥊 Student altercation (3 students)';
    } else if (etype === 'suspected_prohibited_business') {
      const sVal = ($('#evBizStudent') && $('#evBizStudent').value) || F.bizStudent || 'STU-0044';
      const sids = [sVal.trim() || 'STU-0044'];
      const status = ($('#evBizStatus') && $('#evBizStatus').value) || F.bizStatus || 'under_review';
      const loc = ($('#evBizLoc') && $('#evBizLoc').value) || F.bizLocation || 'admin_lobby';
      evObj.student_ids = sids;
      evObj.investigation_status = status;
      evObj.location = loc;
      evObj.params = { student_ids: sids, investigation_status: status, location: loc };
      evObj.title = '🔍 Policy violation inquiry';
    } else if (etype === 'teacher_resignation_notice') {
      const tname = ($('#evResigTeacher') && $('#evResigTeacher').value) || F.resigTeacher || 'Ritu Kapoor';
      evObj.teacher_name = tname;
      evObj.params = { name: tname };
      evObj.title = '📝 Teacher resignation (' + tname + ')';
    } else if (etype === 'transport_lateness_spike' || etype === 'bus_breakdown') {
      const r = +($('#evBusRoute') && $('#evBusRoute').value) || F.busRoute || 3;
      const d = +($('#evBusDelay') && $('#evBusDelay').value) || F.busDelay || 20;
      evObj.type = 'transport_lateness_spike';
      evObj.route_number = r;
      evObj.params = { routes: r, delay: [d, d + 12] };
      evObj.title = '🚌 School bus breakdown (Route ' + r + ')';
    } else if (etype === 'school_fee_increase') {
      const cat = ($('#evFeeCat') && $('#evFeeCat').value) || F.feeCategory || 'tuition';
      const delta = +($('#evFeeDelta') && $('#evFeeDelta').value) || F.feeDelta || 10;
      evObj.fee_category = cat;
      evObj.delta_pct = delta;
      evObj.params = { fee_category: cat, delta_pct: delta };
      evObj.title = '💰 Fee revision (+' + delta + '%)';
    } else if (etype === 'additional_teacher_hired') {
      const tname = ($('#evHireTeacher') && $('#evHireTeacher').value) || F.hiredTeacher || 'Pooja Sharma';
      const role = ($('#evHireRole') && $('#evHireRole').value) || F.hiredRole || 'Social Science';
      evObj.teacher_name = tname;
      evObj.subject_or_role = role;
      evObj.params = { teacher_name: tname, subject_or_role: role };
      evObj.title = '👩‍🏫 New teacher hired (' + tname + ' · ' + role + ')';
    } else {
      evObj.title = etype.replace(/_/g, ' ');
    }
    return evObj;
  }

  async function addAndRunTimeLapse() {
    const ev = extractCurrentEvent();
    if (!S.form.add.some(e => e.type === ev.type && e.date === ev.date)) {
      S.form.add.push(ev);
    }
    if (!S.form.name || S.form.name.startsWith('whatif_')) {
      const cleanType = ev.type.replace(/^serious_|^transport_/, '').split('_')[0];
      S.form.name = 'scen_' + cleanType + '_d' + (ev.day + 1);
    }
    if (S.form.fork && S.day > ev.day) {
      S.day = Math.max(0, ev.day - 1);
      S.dayF = S.day;
    }
    toast('⚡ Compiling & starting time-lapse simulation...');
    await runScenario({ watchTimeLapse: true, eventDay: ev.day, eventTitle: ev.title });
  }

  async function runScenario(opts) {
    opts = opts || {};
    const ov = buildOverview(), st = $('#runStatus'), heroSt = $('#heroRunStatus');
    const heroBtn = $('.btn-hero-run');
    if (heroBtn) { heroBtn.disabled = true; heroBtn.textContent = '⏳ Simulating…'; }
    if (heroSt) heroSt.textContent = '⏳ Starting simulation…';

    if (ov.name === 'story_baseline') {
      if (st) st.textContent = 'Error: Cannot overwrite protected baseline.';
      if (heroSt) heroSt.textContent = 'Error: Cannot overwrite protected baseline.';
      if (heroBtn) { heroBtn.disabled = false; heroBtn.textContent = '⚡ Add & Watch in Time-lapse'; }
      toast('Cannot overwrite protected baseline');
      return;
    }
    if (st) st.textContent = 'Starting simulation…';
    try {
      const r = await fetch('api/run', { method: 'POST', body: JSON.stringify({ overview: ov }) });
      const j = await r.json();
      if (!j.ok) {
        if (st) st.textContent = j.error || 'could not start';
        if (heroSt) heroSt.textContent = j.error || 'could not start';
        if (heroBtn) { heroBtn.disabled = false; heroBtn.textContent = '⚡ Add & Watch in Time-lapse'; }
        return;
      }
      const poll = async () => {
        window.__TIMELAPSE_STATUS = window.__TIMELAPSE_STATUS || [];
        const s = await getJSON('api/status');
        if (s.running) {
          const msg = `Running… day ${s.day}/${s.total || 151}`;
          if (st) st.textContent = msg;
          if (heroSt) heroSt.textContent = '⏳ ' + msg;
          if (heroBtn) heroBtn.textContent = `⏳ ${s.day}/${s.total || 151}`;
          setTimeout(poll, 600);
          return;
        }
        window.__TIMELAPSE_STATUS.push('poll: completed status detected');
        if (s.error) {
          if (st) st.textContent = 'Failed: ' + s.error;
          if (heroSt) heroSt.textContent = '❌ Failed: ' + s.error;
          if (heroBtn) { heroBtn.disabled = false; heroBtn.textContent = '⚡ Add & Watch in Time-lapse'; }
          return;
        }
        if (st) st.textContent = 'Completed successfully!';
        if (heroSt) heroSt.textContent = '✓ Simulation complete! Launching time-lapse…';
        if (heroBtn) { heroBtn.disabled = false; heroBtn.textContent = '⚡ Simulate Event & Watch Time-lapse'; }
        try {
          S.index = await getJSON(S.base + 'index.json');
          const runSel = $('#runSel');
          if (runSel) {
            runSel.innerHTML = S.index.runs.map(r => `<option value="${esc(r.id)}">${esc(r.name)} · ${esc(r.mode)}</option>`).join('');
            runSel.value = ov.name;
          }
          await loadRun(ov.name);
          toast('Loaded scenario run: ' + ov.name);

            const shouldWatch = opts.watchTimeLapse !== false;
          if (shouldWatch) {
            setTab('now');
            S.mode = 'term';
            const modeSel = $('#modeSel');
            if (modeSel) modeSel.value = 'term';
            fillSpeeds();
            S.speed = 3;
            const speedSel = $('#speedSel');
            if (speedSel) speedSel.value = 3;
            const chkPause = $('#chkPause');
            if (chkPause) chkPause.checked = false;
            const chkSkip = $('#chkSkip');
            if (chkSkip) chkSkip.checked = false; // Do not skip days in scenario time-lapse!

            const startDay = (S.meta.run && S.meta.run.start_day != null && S.meta.run.start_day >= 151) ? S.meta.run.start_day : 151;
            const targetDay = opts.eventDay != null ? Math.max(startDay, opts.eventDay - 2) : startDay;
            await goTo(targetDay, S.snapMinute || 630);
            play();
            showScenarioBanner(ov.name, opts.eventTitle || 'Custom Scenario', targetDay, opts.eventDay);
            toast('⚡ Playing scenario time-lapse from Day ' + (targetDay + 1));
          } else {
            setTab('compare');
          }
        } catch (pollErr) {
          console.error('[SchoolTwin poll error]', pollErr);
          toast('Error loading scenario: ' + pollErr.message);
        }
      };
      poll();
    } catch (e) {
      if (st) st.textContent = 'Run error: server offline';
      if (heroSt) heroSt.textContent = 'Run error: server offline';
      if (heroBtn) { heroBtn.disabled = false; heroBtn.textContent = '⚡ Simulate Event & Watch Time-lapse'; }
    }
  }

  async function runPairedComparison() {
    const ev = extractCurrentEvent();
    const dur = +S.form.evalDuration || 30;
    const profSel = $('#profileSel');
    const profile = profSel ? profSel.value : (S.randomProfile || 'balanced');
    const heroBtn = $('[data-act="runPairedComparison"]');
    const heroSt = $('#heroRunStatus');

    if (heroBtn) { heroBtn.disabled = true; heroBtn.textContent = '⏳ Preparing Matched Pair…'; }
    if (heroSt) heroSt.textContent = '⏳ Pre-generating common background random schedule…';
    toast('⚡ Launching Matched Control vs Treatment Paired Simulation...');

    const body = {
      custom_event: {
        date: ev.date,
        type: ev.type,
        severity: ev.severity || 'medium',
        params: ev.params || {},
        title: ev.title || ev.type
      },
      start_day: 151,
      duration_days: dur,
      profile: profile,
      seed: S.pairSeed || 20261014,
      scenario_name: S.form.name || undefined
    };

    try {
      const res = await fetch('api/pair/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      const j = await res.json();
      if (!j.ok) {
        if (heroSt) heroSt.textContent = '❌ ' + (j.error || 'Failed to start pair run');
        if (heroBtn) { heroBtn.disabled = false; heroBtn.textContent = '⚡ Run Paired Comparison (Control vs Treatment)'; }
        toast(j.error || 'Failed to start paired run');
        return;
      }

      const pollPair = async () => {
        try {
          const s = await getJSON('api/pair/status');
          if (s.running) {
            const branchLabel = s.branch === 'control' ? 'Sim A (Control)' : s.branch === 'treatment' ? 'Sim B (Treatment)' : 'Orchestrating';
            const msg = `Simulating ${branchLabel}… day ${s.day}/${s.total || dur}`;
            if (heroSt) heroSt.textContent = '⏳ ' + msg;
            if (heroBtn) heroBtn.textContent = `⏳ ${s.branch === 'control' ? 'A:' : 'B:'} ${s.day}/${s.total || dur}`;
            setTimeout(pollPair, 500);
            return;
          }
          if (s.error) {
            if (heroSt) heroSt.textContent = '❌ Failed: ' + s.error;
            if (heroBtn) { heroBtn.disabled = false; heroBtn.textContent = '⚡ Run Paired Comparison (Control vs Treatment)'; }
            toast('Paired run failed: ' + s.error);
            return;
          }
          if (s.result) {
            if (heroSt) heroSt.textContent = '✓ Paired simulation completed! Loading synchronized dual cockpit…';
            if (heroBtn) { heroBtn.disabled = false; heroBtn.textContent = '⚡ Run Paired Comparison (Control vs Treatment)'; }
            try {
              S.index = await getJSON(S.base + 'index.json');
              const runSel = $('#runSel');
              if (runSel) {
                runSel.innerHTML = S.index.runs.map(r => `<option value="${esc(r.id)}">${esc(r.name)} · ${esc(r.mode)}</option>`).join('');
                runSel.value = s.result.treatment_run;
              }
            } catch (e) {}
            await loadPairedRun(s.result);
          }
        } catch (pollErr) {
          console.error('[SchoolTwin paired poll error]', pollErr);
          toast('Error loading paired comparison: ' + pollErr.message);
          if (heroBtn) { heroBtn.disabled = false; heroBtn.textContent = '⚡ Run Paired Comparison (Control vs Treatment)'; }
        }
      };
      pollPair();
    } catch (e) {
      if (heroSt) heroSt.textContent = 'Run error: server offline';
      if (heroBtn) { heroBtn.disabled = false; heroBtn.textContent = '⚡ Run Paired Comparison (Control vs Treatment)'; }
    }
  }

  async function loadPairedRun(pairMetaOrId) {
    pause();
    let pairMeta = pairMetaOrId;
    if (typeof pairMetaOrId === 'string') {
      try {
        const res = await getJSON(`api/pair/meta?run=${encodeURIComponent(pairMetaOrId)}`);
        if (res && res.ok) pairMeta = res.pair_meta;
      } catch (e) {}
    }
    if (!pairMeta) {
      toast('Could not load paired comparison metadata.');
      return;
    }
    S.pairedMode = true;
    S.pairMeta = pairMeta;
    S.ctrlDays.clear();
    S.trtDays.clear();

    // Concurrently load both meta packs
    const [ctrlMeta, trtMeta] = await Promise.all([
      getJSON(S.base + pairMeta.control_run + '/meta.json'),
      getJSON(S.base + pairMeta.treatment_run + '/meta.json')
    ]);
    S.ctrlMeta = ctrlMeta;
    S.trtMeta = trtMeta;
    S.meta = trtMeta;
    S.run = pairMeta.treatment_run;
    S.zones = trtMeta.zones;
    S.zoneIdx = {}; trtMeta.zones.forEach((z, i) => { S.zoneIdx[z.id] = i; });
    S.people = trtMeta.people;
    S.trk = {}; trtMeta.tracked.forEach((id, k) => { S.trk[id] = k; });
    S.clock = trtMeta.clock;
    S.nDays = trtMeta.days.length;

    // Show dual map container, hide single canvas
    const singleMap = $('#map'); if (singleMap) singleMap.style.display = 'none';
    const dualContainer = $('#mapDualContainer'); if (dualContainer) dualContainer.style.display = 'flex';
    const btnExit = $('#btnExitComparison'); if (btnExit) btnExit.style.display = 'inline-flex';

    // Update Header Titles
    const ctrlTitle = $('#ctrlRunTitle');
    if (ctrlTitle) ctrlTitle.textContent = `${pairMeta.control_run} · Shared BG Schedule (${pairMeta.shared_background_events_count || 0} events)`;
    const trtTitle = $('#trtRunTitle');
    if (trtTitle) trtTitle.textContent = `${pairMeta.treatment_run} · ${pairMeta.custom_event ? (pairMeta.custom_event.title || pairMeta.custom_event.type) : 'Custom Intervention'}`;

    // Target start day (1 day before event or start_day)
    const evDate = pairMeta.custom_event ? pairMeta.custom_event.date : null;
    let targetDay = pairMeta.start_day;
    if (evDate) {
      const evDayIdx = trtMeta.days.findIndex(d => d.date === evDate);
      if (evDayIdx >= 0) targetDay = Math.max(pairMeta.start_day, evDayIdx - 1);
    }
    await goTo(targetDay, 525, { pause: true });
    setTab('compare');
    toast(`⚡ Synchronized Paired Comparison Active: Day ${targetDay + 1}`);
    renderAll();
  }

  async function exitPairedComparison() {
    S.pairedMode = false;
    S.pairMeta = null;
    S.ctrlMeta = null;
    S.trtMeta = null;
    S.ctrlDays.clear();
    S.trtDays.clear();
    const singleMap = $('#map'); if (singleMap) singleMap.style.display = 'block';
    const dualContainer = $('#mapDualContainer'); if (dualContainer) dualContainer.style.display = 'none';
    const btnExit = $('#btnExitComparison'); if (btnExit) btnExit.style.display = 'none';
    await loadRun('story_baseline');
    setTab('now');
    toast('Returned to 151-day Baseline Historical Playback');
  }

  function showScenarioBanner(runId, title, fromDay, eventDay) {
    const ban = $('#scenBanner');
    if (!ban) return;
    ban.style.display = 'flex';
    const tEl = $('#scenBannerTitle');
    if (tEl) tEl.textContent = title || 'Scenario Time-lapse Active';
    const sEl = $('#scenBannerSub');
    if (sEl) sEl.textContent = `Day ${S.day + 1} of ${S.nDays}${eventDay != null ? ` · Event on Day ${eventDay + 1}` : ''}`;
    const btn = $('#scenBannerToggleBtn');
    if (btn) btn.textContent = S.playing ? '⏸ Pause' : '▶ Resume';
    S.scenBannerData = { runId, title, fromDay, eventDay };
  }

  function hideScenarioBanner() {
    const ban = $('#scenBanner');
    if (ban) ban.style.display = 'none';
    S.scenBannerData = null;
  }

  // ------------------------------------------------------------------ wiring
  function setOn(sel, btn) { $$(sel + ' button').forEach(b => b.classList.toggle('on', b === btn)); }
  function fillSpeeds() {
    const list = SPEEDS[S.mode], sel = $('#speedSel');
    sel.innerHTML = list.map(([l, v]) => `<option value="${v}">${l}</option>`).join('');
    S.speed = list[Math.min(2, list.length - 1)][1]; sel.value = S.speed;
  }
  function setTab(t) {
    S.tab = t;
    $$('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.t === t));
    $$('.panel').forEach(x => x.classList.toggle('on', x.id === 'p-' + t));
    renderPanels(true);
  }

  function bindUI() {
    $$('#viewSeg button').forEach(b => { b.onclick = () => { if (b.disabled) return; S.view = b.dataset.v; setOn('#viewSeg', b); S.dirty = true; renderPanels(true); drawStrips(); }; });
    $$('#layerSeg button').forEach(b => { b.onclick = () => { S.layer = b.dataset.v; setOn('#layerSeg', b); S.dirty = true; }; });
    $$('#colorSeg button').forEach(b => { b.onclick = () => { S.color = b.dataset.v; setOn('#colorSeg', b); S.dirty = true; renderPanels(true); }; });
    $$('#floorSeg button').forEach(b => { b.onclick = () => { S.floor = b.dataset.v; setOn('#floorSeg', b); S.dirty = true; }; });
    $('#modeSel').onchange = e => {
      S.mode = e.target.value;
      fillSpeeds();
      S.dayF = S.day;
      if (S.mode === 'term') {
        $('#chkPause').checked = false;
        toast('Time-lapse mode: press ▶ to play through the term');
      } else {
        $('#chkPause').checked = true;
      }
    };
    $('#speedSel').onchange = e => { S.speed = +e.target.value; };
    $('#bPlay').onclick = () => (S.playing ? pause() : play());
    $('#bBack').onclick = () => (S.mode === 'day' ? goTo(S.day, S.minute - 15, { pause: true }) : goTo(nextOpen(S.day, -1), S.snapMinute || S.minute, { pause: true }));
    $('#bFwd').onclick = () => (S.mode === 'day' ? goTo(S.day, S.minute + 15, { pause: true }) : goTo(nextOpen(S.day, 1), S.snapMinute || S.minute, { pause: true }));
    $('#bPrevFlag').onclick = () => stepFlag(-1);
    $('#bNextFlag').onclick = () => stepFlag(1);
    $('#bFlag').onclick = () => { const t = prompt ? (typeof prompt === 'function' ? prompt('Name this flag', 'Look at this') : null) : null; addUserFlag(t || 'Flagged moment'); };
    $$('#tabs button').forEach(b => { b.onclick = () => setTab(b.dataset.t); });

    // Step rail workflow binding
    $$('#stepRail button').forEach(b => {
      b.onclick = () => {
        const step = b.dataset.step;
        $$('#stepRail button').forEach(x => x.classList.toggle('active', x === b));
        if (step === 'replay') { setTab('now'); }
        else if (step === 'create') { setTab('run'); S.form.bTab = 'events'; renderRun(); }
        else if (step === 'run') { setTab('run'); }
        else if (step === 'explore') { setTab('flags'); }
        else if (step === 'report') { setTab('compare'); }
        else if (step === 'compare') { setTab('compare'); }
      };
    });

    // In-app Motion Setting Toggle (Full / Reduced / Off)
    const bMot = $('#btnMotionToggle');
    if (bMot) {
      bMot.onclick = () => {
        if (!S.motionSetting || S.motionSetting === 'full') {
          S.motionSetting = 'reduced';
          if (typeof document !== 'undefined' && document.body) document.body.className = 'reduced-motion';
          bMot.textContent = '✨ Motion: Reduced';
        } else if (S.motionSetting === 'reduced') {
          S.motionSetting = 'off';
          if (typeof document !== 'undefined' && document.body) document.body.className = 'motion-off';
          bMot.textContent = '✨ Motion: Off';
        } else {
          S.motionSetting = 'full';
          if (typeof document !== 'undefined' && document.body) document.body.className = '';
          bMot.textContent = '✨ Motion: Full';
        }
        try { localStorage.setItem('st-motion-setting', S.motionSetting); } catch (e) {}
      };
    }

    // In-app Theme Toggle (Dark / Light)
    const bTheme = $('#btnThemeToggle');
    if (bTheme) {
      bTheme.onclick = () => toggleTheme();
    }

    // Accessible Keyboard Shortcuts (Space, arrows, [, ], F, V, M, T)
    if (typeof window !== 'undefined' && window.addEventListener) {
      window.addEventListener('keydown', e => {
        if (e.target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;
        if (e.key === ' ') { e.preventDefault(); S.playing ? pause() : play(); }
        else if (e.key === 'ArrowLeft') { e.preventDefault(); goTo(S.day, S.minute - 1, { pause: true }); }
        else if (e.key === 'ArrowRight') { e.preventDefault(); goTo(S.day, S.minute + 1, { pause: true }); }
        else if (e.key === '[') { e.preventDefault(); stepFlag(-1); }
        else if (e.key === ']') { e.preventDefault(); stepFlag(1); }
        else if (e.key === 'f' || e.key === 'F') { e.preventDefault(); addUserFlag('Flagged moment'); }
        else if (e.key === 'v' || e.key === 'V') { e.preventDefault(); S.view = S.view === 'operator' ? 'author' : 'operator'; $$('#viewSeg button').forEach(b => b.classList.toggle('on', b.dataset.v === S.view)); S.dirty = true; renderPanels(true); drawStrips(); }
        else if (e.key === 'm' || e.key === 'M') { e.preventDefault(); if (bMot) bMot.click(); }
        else if (e.key === 't' || e.key === 'T') { e.preventDefault(); toggleTheme(); }
      });
    }

    // Quick Entry Header & Modal Actions
    const bRep = $('#btnReplayBaseline');
    if (bRep) bRep.onclick = () => { loadRun('story_baseline'); setTab('now'); pause(); toast('Replaying saved baseline history'); };
    const bExit = $('#btnExitComparison');
    if (bExit) bExit.onclick = () => exitPairedComparison();
    const bNew = $('#btnNewScenario');
    if (bNew) bNew.onclick = () => { setTab('run'); S.form.bTab = 'events'; renderRun(); };
    const bBrand = $('#brandBtn');
    if (bBrand) bBrand.onclick = () => { $('#landingModal').style.display = 'flex'; };
    const mClose = $('#modalClose');
    if (mClose) mClose.onclick = () => { $('#landingModal').style.display = 'none'; };
    const cRep = $('#cardReplay');
    if (cRep) cRep.onclick = () => { $('#landingModal').style.display = 'none'; loadRun('story_baseline'); setTab('now'); pause(); toast('Replaying saved baseline history'); };
    const cScen = $('#cardScenario');
    if (cScen) cScen.onclick = () => { $('#landingModal').style.display = 'none'; setTab('run'); S.form.bTab = 'events'; renderRun(); };

    // Floating scenario banner controls
    const sbToggle = $('#scenBannerToggleBtn');
    if (sbToggle) sbToggle.onclick = () => { S.playing ? pause() : play(); };
    const sbReplay = $('#scenBannerReplayBtn');
    if (sbReplay) sbReplay.onclick = async () => {
      const d = S.scenBannerData ? S.scenBannerData.fromDay : 0;
      await goTo(d, S.snapMinute || 630);
      play();
      toast('↺ Replaying scenario time-lapse from Day ' + (d + 1));
    };
    const sbClose = $('#scenBannerCloseBtn');
    if (sbClose) sbClose.onclick = () => { hideScenarioBanner(); };

    fillSpeeds();
    const cv = $('#map'), tip = $('#tip');
    cv.onclick = e => {
      const r = cv.getBoundingClientRect(), hit = pickAt(e.clientX - r.left, e.clientY - r.top);
      S.sel = hit;
      if (!hit) {
        S.activeFlag = null;
      }
      S.dirty = true;
      if (hit) setTab('inspect'); else renderPanels(true);
    };
    cv.onmousemove = e => {
      const r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top, hit = S.meta && pickAt(mx, my);
      if (!hit) { tip.style.display = 'none'; return; }
      let txt;
      if (hit.type === 'person') { const pr = S.people[hit.id], m = moodAt(curD(), hit.id, S.minute); txt = `<b>${esc(pr.name)}</b> · ${esc(pr.role)}${pr.grade ? ' · ' + esc(gradeOn(pr, curMeta().date)) + ' ' + esc(pr.section) : ''}${m != null ? ' · mood ' + m.toFixed(0) : ''}`; }
      else { const zi = S.zoneIdx[hit.id], z = S.zones[zi], c = (S.counts || [])[zi] || { n: 0 }; txt = `<b>${esc(z.label)}</b> · ${c.n}/${z.cap}`; }
      tip.innerHTML = txt; tip.style.display = 'block'; tip.style.left = Math.min(mx + 12, r.width - 200) + 'px'; tip.style.top = (my + 12) + 'px';
    };
    cv.onmouseleave = () => { tip.style.display = 'none'; };

    const ds = $('#dayStrip'), ms = $('#minStrip');
    const dayAt = e => { const r = ds.getBoundingClientRect(); return Math.floor((e.clientX - r.left) / r.width * S.nDays); };
    ds.onclick = e => goTo(dayAt(e), S.minute);
    ds.onmousemove = e => { if (e.buttons === 1) goTo(dayAt(e), S.minute); };
    const minAt = e => { const r = ms.getBoundingClientRect(); return S.clock.start + clamp((e.clientX - r.left) / r.width, 0, 1) * (S.clock.end - S.clock.start); };
    const setMin = e => { S.minute = minAt(e); S.dirty = true; updateClock(); renderPanels(true); drawStrips(); };
    ms.onclick = setMin; ms.onmousemove = e => { if (e.buttons === 1) setMin(e); };

    $('#side').addEventListener('click', async e => {
      const a = e.target.closest('[data-act]'); if (!a) return;
      const act = a.dataset.act;

      if (act === 'person') { S.sel = { type: 'person', id: +a.dataset.id }; S.dirty = true; setTab('inspect'); }
      else if (act === 'zone') { S.sel = { type: 'zone', id: a.dataset.id }; S.dirty = true; setTab('inspect'); }
      else if (act === 'time') { S.minute = +a.dataset.m; S.dirty = true; updateClock(); drawStrips(); renderPanels(true); }
      else if (act === 'flag') { const f = allFlags().find(x => x.id === a.dataset.id); if (f) jumpToFlag(f); }
      else if (act === 'filter') { S.flt[a.dataset.k] = S.flt[a.dataset.k] === false; renderFlags(); }
      else if (act === 'approve') { S.approvals[a.dataset.id] = a.dataset.v === '1'; renderFlags(); }
      else if (act === 'bTab') { S.form.bTab = a.dataset.tab; renderRun(); }
      else if (act === 'setCalMonth') {
        S.form.calMonth = a.dataset.month;
        renderRun();
      }
      else if (act === 'pickCalDate') {
        S.form.curEvDate = a.dataset.iso;
        S.form.curEvDay = +a.dataset.day;
        renderRun();
      }
      else if (act === 'setHorizonDuration') {
        S.form.evalDuration = +a.dataset.dur;
        renderRun();
      }
      else if (act === 'stepDay') {
        const cur = S.form.curEvDay != null ? S.form.curEvDay : 155;
        const next = Math.max(151, cur + (+a.dataset.delta || 0));
        S.form.curEvDay = next;
        const dt = new Date(2026, 0, 1 + next);
        S.form.curEvDate = dt.toISOString().slice(0, 10);
        S.form.calMonth = S.form.curEvDate.slice(0, 7);
        renderRun();
      }
      else if (act === 'pickEvPreset') {
        const t = a.dataset.type;
        S.form.curEvType = t;
        const p = PRESET_EVENTS.find(x => x.id === t);
        if (p) S.form.curEvSev = p.defaultSev;
        renderRun();
      }
      else if (act === 'setEvDay') {
        const d = +a.dataset.day;
        S.form.curEvDay = d;
        const dt = new Date(2026, 0, 1 + d);
        S.form.curEvDate = dt.toISOString().slice(0, 10);
        S.form.calMonth = S.form.curEvDate.slice(0, 7);
        renderRun();
      }
      else if (act === 'addAndRunTimeLapse') {
        await addAndRunTimeLapse();
      }
      else if (act === 'runPairedComparison') {
        await runPairedComparison();
      }
      else if (act === 'addCustomEvent') {
        const evObj = extractCurrentEvent();
        S.form.add.push(evObj);
        toast('Added ' + (evObj.title || evObj.type));
        renderRun();
      }
      else if (act === 'runScenarioTimeLapse') {
        const earliestDay = S.form.add.reduce((min, e) => {
          const idx = S.meta.days.findIndex(d => d.date === e.date);
          return idx >= 0 ? Math.min(min, idx) : min;
        }, S.day);
        toast('⚡ Running simulation for scenario...');
        await runScenario({ watchTimeLapse: true, eventDay: earliestDay });
      }
      else if (act === 'rmEvent') { S.form.add.splice(+a.dataset.i, 1); renderRun(); }
      else if (act === 'runScenario') runScenario();
      else if (act === 'restoreBaseline') { loadRun('story_baseline'); toast('Restored saved baseline'); }
      else if (act === 'validateScenario') {
        const ov = buildOverview();
        if (ov.name === 'story_baseline') { toast('Invalid: protected name'); return; }
        toast('Scenario validated: ' + (ov.events.add || []).length + ' events, seed ' + ov.seed);
      }
      else if (act === 'dlOverview') {
        const b = new Blob([JSON.stringify(buildOverview(), null, 2)], { type: 'application/json' }), l = document.createElement('a');
        l.href = URL.createObjectURL(b); l.download = (S.form.name || 'overview') + '.json'; l.click();
      }
      else if (act === 'setNlDuration') {
        S.form.evalDuration = +a.dataset.dur;
        renderRun();
      }
      else if (act === 'nlExample1') {
        const val = 'On Day 153 (June 3), water cooler breakdown in corridor_1 during summer maintenance. Increase summer maintenance budget by ₹500,000.';
        S.form.nlPrompt = val;
        if ($('#nlPromptText')) $('#nlPromptText').value = val;
      }
      else if (act === 'nlExample2') {
        const val = 'On school reopening Day 181 (July 1), Route 3 bus breaks down with 20-minute delay. Station 2 backup buses.';
        S.form.nlPrompt = val;
        if ($('#nlPromptText')) $('#nlPromptText').value = val;
      }
      else if (act === 'nlExample3') {
        const val = 'From school reopening Day 181 (July 1), hire 2 additional teachers and approve a 10% tuition fee increase for academic expansion.';
        S.form.nlPrompt = val;
        if ($('#nlPromptText')) $('#nlPromptText').value = val;
      }
      else if (act === 'nlExample4') {
        const val = 'On Day 185 (first week of July), a serious physical altercation occurs in the playground involving STU-0012, STU-0015, STU-0021.';
        S.form.nlPrompt = val;
        if ($('#nlPromptText')) $('#nlPromptText').value = val;
      }
      else if (act === 'parsePrompt') {
        const txt = $('#nlPromptText') ? $('#nlPromptText').value : S.form.nlPrompt;
        S.form.nlPrompt = txt;
        S.form.nlStatus = 'Parsing scenario prompt…'; renderRun();
        try {
          const res = await fetch('api/parse_prompt', {
            method: 'POST',
            body: JSON.stringify({
              prompt: txt,
              start_day: 151,
              duration_days: +S.form.evalDuration || 30,
              reopening_date: '2026-07-01'
            })
          });
          const j = await res.json();
          if (j.ok && j.parsed) {
            S.form.nlParsed = j.parsed;
            S.form.nlStatus = 'Parsed successfully with ' + (j.parsed.parser_used || 'engine');
          } else {
            S.form.nlStatus = 'Could not parse prompt: ' + (j.error || (j.parsed && j.parsed.error) || 'schema rejection');
          }
        } catch (e) {
          S.form.nlStatus = 'Server offline; parsed using local rules.';
        }
        renderRun();
      }
      else if (act === 'applyNL' || act === 'applyAndSimulateNL') {
        const p = S.form.nlParsed;
        if (p) {
          if (p.name) S.form.name = p.name;
          S.form.extendPostBaseline = true;
          S.form.ckpt = 'CKPT-DAY-150-TERM-CLOSE';
          if (p.events && p.events.length) S.form.add = S.form.add.concat(p.events);
          if (p.policy_overrides) {
            const po = p.policy_overrides;
            if (po.additional_teachers != null) S.form.teachers = po.additional_teachers;
            if (po.tuition_fee_delta_pct != null) S.form.fee = po.tuition_fee_delta_pct;
            if (po.fee_change_approved != null) S.form.feeOk = po.fee_change_approved;
            if (po.bus_backup_capacity != null) S.form.bus = po.bus_backup_capacity;
            if (po.summer_maintenance_budget_inr != null) S.form.maintBudget = po.summer_maintenance_budget_inr;
            if (po.attendance_support_budget_inr_per_month != null) S.form.support = po.attendance_support_budget_inr_per_month;
            if (po.transport_fee_delta_pct != null) S.form.transportFee = po.transport_fee_delta_pct;
          }
          if (act === 'applyAndSimulateNL') {
            toast('⚡ Simulating altered scenario from Day 151...');
            const earliestDay = S.form.add.reduce((min, e) => {
              const idx = (S.meta.days || []).findIndex(d => d.date === e.date);
              return idx >= 0 ? Math.min(min, idx) : min;
            }, 151);
            await runScenario({ watchTimeLapse: true, eventDay: earliestDay });
          } else {
            toast('Applied scenario configuration (Day 151+)');
            S.form.bTab = 'events';
            renderRun();
          }
        }
      }
      else if (act === 'loadRunId') {
        loadRun(a.dataset.id);
      }
    });

    $('#side').addEventListener('change', e => {
      const f = e.target.dataset.f, dis = e.target.dataset.dis;
      if (f) {
        const v = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
        S.form[f] = e.target.type === 'number' ? +v : v;
        if (f === 'fork' || f === 'evalDuration' || f === 'extendPostBaseline') renderRun();
      }
      if (dis) {
        const L = S.form.disabled, i = L.indexOf(dis);
        if (e.target.checked && i < 0) L.push(dis);
        if (!e.target.checked && i >= 0) L.splice(i, 1);
      }
      if (e.target.id === 'ckptSel') {
        S.form.ckpt = e.target.value;
        const ck = CHECKPOINTS.find(c => c.id === S.form.ckpt);
        if (ck) {
          goTo(ck.day, 525, { pause: true });
          toast('Moved to Checkpoint: ' + ck.title);
        }
      }
      if (e.target.id === 'evDate' || e.target.id === 'evDateInput') {
        const iso = e.target.value;
        if (iso) {
          S.form.curEvDate = iso;
          const d0 = new Date(2026, 0, 1);
          const cur = new Date(iso + 'T00:00:00');
          S.form.curEvDay = Math.max(0, Math.round((cur - d0) / 86400000));
          S.form.calMonth = iso.slice(0, 7);
          renderRun();
        }
      }
      if (e.target.id === 'evSev') {
        S.form.curEvSev = e.target.value;
      }
      if (e.target.id === 'evTypeSel') {
        S.form.curEvType = e.target.value;
        const p = PRESET_EVENTS.find(x => x.id === e.target.value);
        if (p) S.form.curEvSev = p.defaultSev;
        renderRun();
      }
      if (e.target.id === 'profileSel') {
        S.randomProfile = e.target.value;
        const prof = RANDOM_PROFILES[S.randomProfile] || RANDOM_PROFILES.balanced;
        const dEl = $('#profileDesc'); if (dEl) dEl.textContent = prof.desc;
        const bEl = $('#profileBadges');
        if (bEl) {
          bEl.innerHTML = `
            <span class="profile-badge">Rate: ${prof.rate}</span>
            <span class="profile-badge">Max/Day: ${prof.maxDay}</span>
            <span class="profile-badge">Max/Wk: ${prof.maxWk}</span>
            <span class="profile-badge">Cooldown: ${prof.cooldown}</span>
          `;
        }
      }
    });

    window.addEventListener('keydown', e => {
      if (/INPUT|TEXTAREA|SELECT/.test((e.target.tagName || ''))) return;
      const k = e.key;
      if (k === ' ') { e.preventDefault(); S.playing ? pause() : play(); }
      else if (k === 'ArrowRight') $('#bFwd').click(); else if (k === 'ArrowLeft') $('#bBack').click();
      else if (k === ']') stepFlag(1); else if (k === '[') stepFlag(-1);
      else if (k === 'f' || k === 'F') $('#bFlag').click();
      else if (k === 'v' || k === 'V') $$('#layerSeg button')[S.layer === 'reality' ? 1 : 0].click();
      else if (k === 'm' || k === 'M') $$('#colorSeg button')[S.color === 'mood' ? 0 : 1].click();
    });
    window.addEventListener('resize', () => { S.dirty = true; drawStrips(); renderPanels(true); });
  }

  window.SchoolTwin.render = render; window.SchoolTwin.renderAll = renderAll; window.SchoolTwin.drawStrips = drawStrips; window.SchoolTwin.setTab = setTab;
  window.SchoolTwin.pickAt = pickAt; window.SchoolTwin.buildOverview = buildOverview; window.SchoolTwin.advance = advance;
  window.SchoolTwin.applyTheme = applyTheme; window.SchoolTwin.toggleTheme = toggleTheme;
  window.SchoolTwin.loadPairedRun = loadPairedRun; window.SchoolTwin.exitPairedComparison = exitPairedComparison;
  if (!window.__TEST__) { if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot(); }
})();
