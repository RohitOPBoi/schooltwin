// Visual verification harness: drives the real player in jsdom + node-canvas
// and writes PNG screenshots to tests/shots/. Manual tool — not part of npm test.
//   node tests/take_shots.js
const { JSDOM } = require('jsdom'); const fs = require('fs'); const path = require('path');
const ROOT = path.join(__dirname, '..'), SHOTS = path.join(__dirname, 'shots');
fs.mkdirSync(SHOTS, { recursive: true });

(async () => {
  const html = fs.readFileSync(path.join(ROOT, 'player/index.html'), 'utf8').replace('<script src="player.js"></script>', '');
  const w = new JSDOM(html, { runScripts: 'outside-only', pretendToBeVisual: true, url: 'http://localhost/?run=story_baseline' }).window;
  w.__TEST__ = true;
  const size = { map: [1000, 560], mapCtrl: [480, 500], mapTrt: [480, 500], dayStrip: [1000, 64], minStrip: [1000, 34] };
  Object.defineProperty(w.HTMLElement.prototype, 'clientWidth', { get() { return (size[this.id] || [330, 0])[0]; } });
  Object.defineProperty(w.HTMLElement.prototype, 'clientHeight', { get() { return (size[this.id] || [0, 120])[1]; } });
  w.fetch = async u => {
    const p = path.join(ROOT, u);
    if (u.startsWith('api/')) return { ok: false, status: 404, json: async () => ({}) };
    if (!fs.existsSync(p)) return { ok: false, status: 404, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => JSON.parse(fs.readFileSync(p, 'utf8')) };
  };
  w.eval(fs.readFileSync(path.join(ROOT, 'player/player.js'), 'utf8'));
  const T = w.SchoolTwin, S = T.S, doc = w.document;
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const shot = (name, ids) => {
    (ids || ['map']).forEach(id => {
      const cv = doc.getElementById(id);
      if (cv && cv.toDataURL) fs.writeFileSync(path.join(SHOTS, `${name}_${id}.png`), Buffer.from(cv.toDataURL('image/png').split(',')[1], 'base64'));
    });
  };
  const panelShot = name => {
    const el = doc.getElementById('side');
    fs.writeFileSync(path.join(SHOTS, name + '_panel.html'), `<link rel="stylesheet" href="../player/player.css">` + el.innerHTML);
  };

  await T.boot();
  const day = d => S.meta.days.findIndex(x => x.date === d);
  const at = async (d, m) => { await T.goTo(typeof d === 'string' ? day(d) : d, m, { pause: true }); T.render(); T.drawStrips(); };

  // 1. Baseline map, mid-morning, dark theme
  await at('2026-01-20', 600); shot('v7_dark_map', ['map', 'dayStrip', 'minStrip']);
  // 2. Incident moment on baseline (fight story event, day 19-ish) — find a flag with a zone
  const zf = S.meta.flags.find(f => f.zone && f.day > 30);
  if (zf) { await at(zf.day, zf.minute); shot('v7_incident_map', ['map']); }
  // 3. Light theme map
  T.applyTheme('light'); await wait(60); shot('v7_light_map', ['map']);
  T.applyTheme('dark'); await wait(60);
  // 4. Builder events tab (calendar with closed hatch + HUD)
  T.setTab('run'); S.form.bTab = 'events'; await wait(30); panelShot('v7_builder');
  // 5. Now panel
  T.setTab('now'); await wait(30); panelShot('v7_now');
  // 6. Paired comparison from the freshly generated pair (pass pair_meta directly:
  //    the jsdom harness has no API server for api/pair/meta)
  const pairMeta = JSON.parse(fs.readFileSync(path.join(ROOT, 'pack/e2e_verify_pair/pair_meta.json'), 'utf8'));
  await T.loadPairedRun(pairMeta); await wait(200);
  const evDay = S.meta.days.findIndex(d => d.date === '2026-07-15');
  if (evDay >= 0) await at(evDay, 620);
  shot('v7_paired_event_day', ['mapCtrl', 'mapTrt', 'dayStrip']);
  T.setTab('compare'); await wait(250); panelShot('v7_compare');
  console.log('shots written to tests/shots (v7_*)');
})();
