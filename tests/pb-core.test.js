'use strict';
// node --test tests/pb-core.test.js
const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('../web/pb-core.js');

const row = (id, time, status, domain, ip, name) => ({ id, time, status, domain: domain || 'example.org', client: { ip: ip || '192.168.1.21', name: name || null } });

test('classify follows what Pi-hole does with the query', () => {
  for (const s of ['GRAVITY', 'REGEX', 'DENYLIST', 'EXTERNAL_BLOCKED_NULL', 'GRAVITY_CNAME', 'SPECIAL_DOMAIN', 'DBBUSY']) assert.equal(C.classify(s), 'blocked', s);
  for (const s of ['FORWARDED', 'RETRIED', 'RETRIED_DNSSEC']) assert.equal(C.classify(s), 'allowed', s);
  for (const s of ['CACHE', 'CACHE_STALE']) assert.equal(C.classify(s), 'memory', s);
  for (const s of ['IN_PROGRESS', 'UNKNOWN', 'SOMETHING_NEW', '', null, undefined]) assert.equal(C.classify(s), 'pending', String(s));
  assert.equal(C.classify('gravity'), 'blocked', 'case does not matter');
});

test('names: app by longest suffix, tidy unknown domains, hidden values', () => {
  const map = { 'youtube.com': 'youtube', 'googlevideo.com': 'youtube', 'ig.me': 'instagram' };
  assert.equal(C.appFor('r4---sn-abc.googlevideo.com', map), 'youtube');
  assert.equal(C.appFor('WWW.YouTube.com.', map), 'youtube');
  assert.equal(C.appFor('notyoutube.com', map), null);
  assert.equal(C.appFor('com', map), null);
  assert.equal(C.appFor('toString.example', map), null, 'no prototype lookups');
  assert.equal(C.baseDomain('r4---sn-abc.googlevideo.com'), 'googlevideo.com');
  assert.equal(C.baseDomain('www.bahrain.com.bh'), 'bahrain.com.bh');
  assert.equal(C.baseDomain('apple.com'), 'apple.com');
  assert.equal(C.baseDomain(''), '');
  assert.ok(C.isHiddenDomain('hidden') && C.isHiddenDomain('') && !C.isHiddenDomain('a.com'));
  assert.ok(C.isHiddenClient('0.0.0.0') && C.isHiddenClient('::') && !C.isHiddenClient('192.168.1.2'));
});

test('numbers', () => {
  assert.equal(C.formatCount(12345.6, 'en-GB'), '12,346');
  assert.equal(C.formatCount(undefined), '0');
  assert.equal(C.percent(0, 0), 0);
  assert.equal(C.percent(1, 3), 33);
  assert.equal(C.percent(1, 30), 3.3, 'one decimal below 10 %');
  assert.equal(C.percent(5, 5), 100);
});

test('feed: the first response only primes it, later ones give each new query once, oldest first', () => {
  const f = new C.Feed({ length: 5 });
  assert.match(f.url(), /length=20$/);
  assert.deepEqual(f.ingest({ queries: [row(10, 1000.5, 'FORWARDED'), row(9, 999, 'GRAVITY')], cursor: 10 }), [], 'priming gives no events');
  assert.equal(f.from, 998, 'from = newest server time - 2 s overlap');
  assert.equal(f.url(), '/api/queries?from=998&length=5');
  const events = f.ingest({ queries: [row(12, 1003, 'GRAVITY', 'www.youtube.com'), row(11, 1001, 'FORWARDED'), row(10, 1000.5, 'FORWARDED')], cursor: 12 });
  assert.deepEqual(events.map(e => e.id), [11, 12], 'newest-first input, oldest-first output, primed row not repeated');
  assert.equal(events[1].kind, 'blocked');
  assert.equal(events[1].domain, 'www.youtube.com');
  assert.deepEqual(f.ingest({ queries: [row(12, 1003, 'GRAVITY'), row(11, 1001, 'FORWARDED')], cursor: 12 }), [], 'nothing twice');
  assert.equal(f.from, 1001);
});

test('feed uses the server clock: the phone clock is never consulted', () => {
  const realNow = Date.now;
  Date.now = () => { throw new Error('the phone clock must not be used'); };
  try {
    const f = new C.Feed();
    f.ingest({ queries: [row(1, 5000, 'CACHE')], cursor: 1 });
    assert.equal(f.from, 4998);
    f.ingest({ queries: [row(2, 5010, 'CACHE')], cursor: 2 });
    assert.equal(f.from, 5008);
  } finally { Date.now = realNow; }
});

test('feed: queries still in progress are skipped now and delivered later with their final status', () => {
  const f = new C.Feed();
  f.ingest({ queries: [row(1, 100, 'FORWARDED')], cursor: 1 });
  assert.deepEqual(f.ingest({ queries: [row(2, 101, 'IN_PROGRESS')], cursor: 2 }), []);
  const later = f.ingest({ queries: [row(2, 101, 'GRAVITY')], cursor: 2 });
  assert.equal(later.length, 1);
  assert.equal(later[0].kind, 'blocked');
  assert.deepEqual(f.ingest({ queries: [row(2, 101, 'GRAVITY')], cursor: 2 }), [], 'and then only once');
});

test('feed: privacy level 3 (no queries, null cursor), hidden domains/clients, and a full page', () => {
  const f = new C.Feed({ length: 2 });
  f.ingest({ queries: [], cursor: null });
  assert.equal(f.privacy, true);
  assert.equal(f.url(), '/api/queries?from=0&length=2', 'it keeps asking, politely');
  f.ingest({ queries: [], cursor: 7 });
  assert.equal(f.privacy, false, 'an empty log is not the same as hidden queries');
  const ev = f.ingest({ queries: [row(8, 10, 'GRAVITY', 'hidden', '0.0.0.0'), row(9, 11, 'FORWARDED', 'hidden', '0.0.0.0')], cursor: 9 });
  assert.equal(f.truncated, true, 'a full page means some queries were probably not shown');
  assert.ok(ev[0].hiddenDomain && ev[0].hiddenClient);
  assert.deepEqual(f.ingest({ queries: 'not an array' }), []);
  assert.deepEqual(f.ingest(null), []);
});

test('feed: remembers only the last `keep` ids', () => {
  const f = new C.Feed({ keep: 3, length: 100 });
  f.ingest({ queries: [row(1, 1, 'CACHE')], cursor: 1 });
  f.ingest({ queries: [row(5, 5, 'CACHE'), row(4, 4, 'CACHE'), row(3, 3, 'CACHE'), row(2, 2, 'CACHE')], cursor: 5 });
  assert.ok(Object.keys(f.seen).length <= 3);
});

test('pacer: gentle rate, interesting queries first, bounded queue', () => {
  const p = new C.Pacer({ gap: 400, max: 3 });
  const ev = (id, kind, app, child) => ({ id, kind, app, child });
  p.push([ev(1, 'memory'), ev(2, 'allowed'), ev(3, 'blocked', 'youtube', true)]);
  assert.equal(p.next(0).id, 3, 'blocked app query of a child first');
  assert.equal(p.next(100), null, 'too soon');
  assert.equal(p.next(400).id, 2);
  assert.equal(p.next(800).id, 1);
  assert.equal(p.next(1200), null, 'empty');
  p.push([ev(4, 'memory'), ev(5, 'memory'), ev(6, 'blocked', 'tiktok'), ev(7, 'allowed', 'roblox')]);
  assert.equal(p.queue.length, 3);
  assert.equal(p.dropped, 1);
  assert.ok(!p.queue.some(e => e.id === 4 || e.id === 5) || p.queue.length === 3);
  assert.ok(p.queue.some(e => e.id === 6) && p.queue.some(e => e.id === 7), 'the dull ones are dropped, not the apps');
  assert.ok(C.priority({ kind: 'blocked', app: 'x', child: true }) > C.priority({ kind: 'memory' }));
});

test('pacer never exceeds the rate no matter how much traffic arrives', () => {
  const p = new C.Pacer({ gap: 380, max: 10 });
  let shown = 0;
  for (let t = 0; t < 10000; t += 16) {                          // ten seconds at 60 frames per second
    p.push([{ id: t, kind: 'allowed' }, { id: t + 1, kind: 'blocked' }]);        // 125 queries per second
    if (p.next(t)) shown++;
  }
  assert.ok(shown <= 27, 'at most about 2.6 packets a second, got ' + shown);
  assert.ok(shown >= 20);
  assert.ok(p.queue.length <= 10);
});

test('wires: right angles, 8-bit style, and a row of devices meets on one bus', () => {
  const w = C.elbow({ x: 20, y: 0 }, { x: 100, y: 100 });
  assert.equal(w.d, 'M20 0L20 50L100 50L100 100', 'down to the halfway line, across, down');
  assert.equal(w.total, 180);
  assert.deepEqual(C.pointAt(w, 0), { x: 20, y: 0 });
  assert.deepEqual(C.pointAt(w, 1), { x: 100, y: 100 });
  assert.deepEqual(C.pointAt(w, 50 / 180), { x: 20, y: 50 }, 'the first corner');
  assert.deepEqual(C.pointAt(w, 90 / 180), { x: 60, y: 50 }, 'halfway along the bus');
  assert.deepEqual(C.pointAt(w, 7), { x: 100, y: 100 }, 'clamped');
  const a = C.elbow({ x: 10, y: 0 }, { x: 100, y: 100 }), b = C.elbow({ x: 190, y: 0 }, { x: 100, y: 100 });
  assert.equal(a.pts[1].y, b.pts[1].y, 'two devices in one row cross on the same line');
  assert.deepEqual(a.pts[3], b.pts[3], 'and enter the box at the same point');
  const h = C.elbow({ x: 0, y: 10 }, { x: 60, y: 10 });
  assert.equal(h.d, 'M0 10L30 10L30 10L60 10', 'a level wire is straight');
  assert.deepEqual(C.pointAt(h, 0.5), { x: 30, y: 10 });
  const v = C.elbow({ x: 400, y: 0 }, { x: 100, y: 90 }, 'v');
  assert.equal(v.d, 'M400 0L400 45L100 45L100 90', 'told to start downwards, it does, even when the wire is wider than tall');
  const z = C.elbow({ x: 5, y: 5 }, { x: 5, y: 5 });
  assert.deepEqual(C.pointAt(z, 0.5), { x: 5, y: 5 }, 'a wire of no length stays put');
});

test('traces: printed-circuit routing with 45-degree corners, at an even speed', () => {
  const t = C.trace([{ x: 0, y: 0 }, { x: 0, y: 40 }, { x: 60, y: 40 }], 10);
  assert.equal(t.d, 'M0 0L0 30L10 40L60 40', 'the corner is cut at 45 degrees');
  assert.ok(Math.abs(t.total - (30 + Math.SQRT2 * 10 + 50)) < 1e-9, 'true length, diagonal included');
  assert.deepEqual(C.pointAt(t, 0), { x: 0, y: 0 });
  assert.deepEqual(C.pointAt(t, 1), { x: 60, y: 40 });
  const onDiag = C.pointAt(t, (30 + Math.SQRT2 * 5) / t.total);
  assert.ok(Math.abs(onDiag.x - 5) < 1e-9 && Math.abs(onDiag.y - 35) < 1e-9, 'halfway along the diagonal');
  const short = C.trace([{ x: 0, y: 0 }, { x: 0, y: 6 }, { x: 40, y: 6 }], 10);
  assert.equal(short.d, 'M0 0L0 3L3 6L40 6', 'a short run is never cut by more than half');
  const straight = C.trace([{ x: 5, y: 5 }, { x: 5, y: 50 }], 8);
  assert.equal(straight.d, 'M5 5L5 50');
  const loop = C.trace([{ x: 100, y: 50 }, { x: 10, y: 50 }, { x: 10, y: 5 }, { x: 70, y: 5 }, { x: 70, y: 20 }], 6);
  assert.equal(loop.pts.length, 8, 'three corners, each cut in two points');
});

test('wires: S-curves with exact ends, and points along them', () => {
  const w = C.wire({ x: 0, y: 0 }, { x: 100, y: 40 });
  assert.equal(w.d, 'M0 0C50 0 50 40 100 40');
  assert.deepEqual(C.pointAt(w, 0), { x: 0, y: 0 });
  assert.deepEqual(C.pointAt(w, 1), { x: 100, y: 40 });
  const mid = C.pointAt(w, 0.5);
  assert.ok(Math.abs(mid.x - 50) < 1e-9 && Math.abs(mid.y - 20) < 1e-9);
  const v = C.wire({ x: 10, y: 0 }, { x: 30, y: 200 });
  assert.equal(v.d, 'M10 0C10 100 30 100 30 200', 'a mostly vertical wire leaves vertically');
  assert.deepEqual(C.pointAt(v, -3), { x: 10, y: 0 }, 'clamped');
  let last = -1;
  for (let i = 0; i <= 20; i++) { const e = C.easeInOut(i / 20); assert.ok(e >= last); last = e; }
  assert.equal(C.easeInOut(0), 0);
  assert.equal(C.easeInOut(1), 1);
});

// ------------------------------------------------------------------ the poller, driven by a fake clock
function fakeClock() {
  const c = { t: 0, q: [], id: 0 };
  c.now = () => c.t;
  c.setTimeout = (f, ms) => { const id = ++c.id; c.q.push({ id, at: c.t + ms, f }); return id; };
  c.clearTimeout = (id) => { c.q = c.q.filter(x => x.id !== id); };
  c.advance = async (ms) => {                      // run everything due up to t + ms, letting promises settle in between
    const end = c.t + ms;
    for (;;) {
      c.q.sort((a, b) => a.at - b.at);
      const next = c.q[0];
      if (!next || next.at > end) break;
      c.q.shift(); c.t = next.at; next.f();
      for (let i = 0; i < 5; i++) await Promise.resolve();
    }
    c.t = end;
  };
  return c;
}

test('poller: tasks start staggered, repeat after finishing, and never overlap', async () => {
  const clk = fakeClock(), calls = [];
  let inFlight = 0, maxInFlight = 0;
  const slow = (name) => () => { calls.push([name, clk.t]); inFlight++; maxInFlight = Math.max(maxInFlight, inFlight);
    return new Promise(res => clk.setTimeout(() => { inFlight--; res(); }, 100)); };
  const p = new C.Poller({ tasks: [{ name: 'a', every: 1000, run: slow('a') }, { name: 'b', every: 5000, run: slow('b') }], ...clk, stagger: 250 });
  p.start();
  await clk.advance(2600);
  assert.deepEqual(calls.filter(c => c[0] === 'a').map(c => c[1]), [0, 1100, 2200], 'next run is `every` ms after the previous one FINISHED');
  assert.deepEqual(calls.filter(c => c[0] === 'b').map(c => c[1]), [250]);
  assert.ok(maxInFlight <= 2);
  p.stop();
  const n = calls.length;
  await clk.advance(20000);
  assert.equal(calls.length, n, 'nothing runs after stop');
});

test('poller: failures back off and recover, and are reported', async () => {
  const clk = fakeClock(), errors = [], oks = [];
  let fail = true, runs = 0;
  const p = new C.Poller({ tasks: [{ name: 'q', every: 1000, run: () => { runs++; return fail ? Promise.reject(new Error('down')) : Promise.resolve(); } }],
    ...clk, onError: (n, e, f) => errors.push([n, e.message, f, clk.t]), onOk: n => oks.push([n, clk.t]) });
  p.start();
  await clk.advance(0);                                   // fails at 0 -> next after 2000
  await clk.advance(2000);                                // fails at 2000 -> next after 4000
  await clk.advance(4000);                                // fails at 6000 -> next after 8000
  assert.deepEqual(errors.map(e => e[3]), [0, 2000, 6000]);
  assert.deepEqual(errors.map(e => e[2]), [1, 2, 3]);
  fail = false;
  await clk.advance(8000);                                // succeeds at 14000
  assert.deepEqual(oks, [['q', 14000]]);
  await clk.advance(1000);
  assert.equal(runs, 5, 'back to the normal rhythm: every 1000 ms');
  for (let i = 0; i < 12; i++) { fail = true; await clk.advance(40000); }
  assert.ok(Math.max.apply(null, errors.map(e => e[3])) > 0);
  const gaps = errors.slice(-3).map((e, i, a) => i ? e[3] - a[i - 1][3] : 0).slice(1);
  assert.ok(gaps.every(g => g <= 30000 + 1), 'backoff is capped at 30 s, got ' + gaps);
});

test('poller: pauses while the page is hidden and catches up when it is visible again', async () => {
  const clk = fakeClock(); let visible = true, runs = 0;
  const p = new C.Poller({ tasks: [{ name: 'q', every: 1000, run: () => { runs++; return Promise.resolve(); } }], ...clk, visible: () => visible });
  p.start();
  await clk.advance(2500);
  const before = runs;
  visible = false;
  await clk.advance(60000);
  assert.ok(runs - before <= 1, 'at most the run that was already due when it was hidden');
  const frozen = runs;
  visible = true;
  p.wake();
  await clk.advance(0);
  assert.equal(runs, frozen + 1, 'wake() runs what is due at once');
  await clk.advance(1000);
  assert.equal(runs, frozen + 2);
});

test('poller: a task that throws synchronously is treated as a failure, not a crash', async () => {
  const clk = fakeClock(), errors = [];
  const p = new C.Poller({ tasks: [{ name: 'x', every: 500, run: () => { throw new Error('boom'); } }], ...clk, onError: (n, e) => errors.push(e.message) });
  p.start();
  await clk.advance(100);
  assert.deepEqual(errors, ['boom']);
});

// ------------------------------------------------------------------ numbers and device states
test('topByApp groups domains by app, pools unknown ones as `other`, and never invents a label', () => {
  const map = { 'youtube.com': 'youtube', 'googlevideo.com': 'youtube', 'tiktok.com': 'tiktok' };
  const top = C.topByApp([
    { domain: 'r1.googlevideo.com', count: 40 }, { domain: 'www.youtube.com', count: 10 }, { domain: 'ads.example.net', count: 30 },
    { domain: 'tracker.example.org', count: 25 }, { domain: 'api.tiktok.com', count: 20 }, { domain: 'hidden', count: 99 }], map);
  assert.deepEqual(top, [{ app: 'youtube', count: 50 }, { app: 'tiktok', count: 20 }, { app: null, count: 55 }],
    'apps biggest first, then everything else together; hidden domains are skipped');
  assert.deepEqual(C.topByApp([{ domain: 'a.com', count: 5 }], map, 0), [{ app: null, count: 5 }], 'the limit cuts apps, never the "everything else" row');
  assert.deepEqual(C.topByApp(undefined, map), []);
  assert.equal(C.topByApp([{ domain: 'www.youtube.com', count: 1 }, { domain: 'api.tiktok.com', count: 2 }], map, 1).length, 1);
});

test('topByApp credits only the apps blocked for children: a tracker on an allowed app\'s domain is "other"', () => {
  const map = { 'youtube.com': 'youtube', 'netflix.com': 'netflix' };
  const rows = [{ domain: 'www.youtube.com', count: 7 }, { domain: 'logs.netflix.com', count: 30 }];
  assert.deepEqual(C.topByApp(rows, map, 5, ['youtube']), [{ app: 'youtube', count: 7 }, { app: null, count: 30 }]);
  assert.deepEqual(C.topByApp(rows, map, 5, []), [{ app: null, count: 37 }], 'no app blocked: nothing is credited to an app');
  assert.equal(C.topByApp(rows, map, 5).length, 2, 'without a filter every app counts (the old behaviour)');
});

test('Feed: a row stamped later than the box clock cannot pin `from` in the future', () => {
  const feed = new C.Feed();
  feed.ingest({ queries: [{ id: 1, time: 1000, status: 'FORWARDED', domain: 'a.com', client: { ip: '1.1.1.1' } }] }, 1001);   // primes
  feed.ingest({ queries: [{ id: 2, time: 1000 + 3600, status: 'FORWARDED', domain: 'b.com', client: { ip: '1.1.1.1' } }] }, 1005);
  assert.ok(feed.from <= 1005, 'from is capped by the box clock (' + feed.from + ')');
  const evs = feed.ingest({ queries: [{ id: 3, time: 1006, status: 'FORWARDED', domain: 'c.com', client: { ip: '1.1.1.1' } }] }, 1007);
  assert.equal(evs.length, 1, 'and the next real query still arrives');
});

test('hourly: 144 ten-minute slots become 24 hourly buckets counted back from the newest slot', () => {
  const slots = [];
  for (let i = 0; i < 144; i++) slots.push({ timestamp: 1000000 + i * 600, total: 10, blocked: i < 6 ? 5 : 0 });
  const h = C.hourly({ history: slots });
  assert.equal(h.length, 24);
  assert.ok(h.every(b => b.total === 60), 'six slots of 10 per hour');
  assert.equal(h[0].blocked, 30, 'the oldest hour holds the first six blocked slots');
  assert.equal(h[23].blocked, 0);
  assert.ok(h[0].t < h[1].t && h[1].t < h[23].t, 'oldest first');
  const sparse = C.hourly({ history: [{ timestamp: 5000, total: 3, blocked: 1 }] });
  assert.equal(sparse[23].total, 3);
  assert.equal(sparse.reduce((a, b) => a + b.total, 0), 3);
  assert.equal(C.hourly(null).length, 24);
  assert.ok(C.hourly({ history: [] }).every(b => b.total === 0));
});

test('deviceState: protection problems outrank everything, then what the box is doing', () => {
  const base = { serverNow: 100000, lastQuery: 99900, paused: false, offline: false, shadowed: false, recent: false };
  const st = o => C.deviceState(Object.assign({}, base, o));
  assert.equal(st({}), 'active', 'asked something 100 s ago');
  assert.equal(st({ lastQuery: 99000 }), 'quiet');
  assert.equal(st({ paused: true }), 'paused');
  assert.equal(st({ offline: true, paused: true }), 'offline', 'the internet being off is the bigger fact');
  assert.equal(st({ shadowed: true, paused: true, offline: true }), 'overridden', 'not protected beats everything');
  assert.equal(st({ lastQuery: 100000 - 90000 }), 'unreachable', 'silent for more than 24 hours');
  assert.equal(st({ lastQuery: 0 }), 'unreachable', 'never seen');
  assert.equal(st({ lastQuery: 0, recent: true }), 'active', 'but a query we just watched proves it reaches the box');
  assert.equal(st({ lastQuery: undefined }), 'unreachable');
  // the box cannot tell (privacy level, or the device list failed): never claim "not seen"
  assert.equal(st({ unknown: true, lastQuery: 0 }), 'unknown');
  assert.equal(st({ unknown: true, lastQuery: 0, recent: true }), 'active', 'a query we watched is still proof');
  assert.equal(st({ unknown: true, lastQuery: 0, paused: true }), 'paused', 'what the page itself set is still known');
  assert.equal(st({ unknown: true, lastQuery: 0, offline: true }), 'offline');
  assert.equal(st({ unknown: true, lastQuery: 0, shadowed: true }), 'overridden', 'and a rule that overrides is still the worst news');
});

test('learned rules are read exactly as the box reads them (tests/fixtures/learned-rule-cases.json)', () => {
  const cases = JSON.parse(require('node:fs').readFileSync(require('node:path').join(__dirname, 'fixtures', 'learned-rule-cases.json'), 'utf8')).cases;
  assert.ok(cases.length >= 5);
  for (const c of cases) assert.deepEqual(C.learnedRules(c.domains), c.expected, c.name);
  assert.deepEqual(C.learnedRules(null), []);
  assert.equal(C.regexZone('(^|\\.)tiktok-minis\\.us$'), 'tiktok-minis.us');
  assert.equal(C.regexZone('^.*$'), null);
});

// ------------------------------------------------------------------ the savings card (pb-ledger, docs/maintainers/architecture.md)
const IDS = ['tiktok', 'roblox', 'youtube', 'netflix'];
const ledgerJSON = (over) => JSON.stringify(Object.assign({
  v: 1, at: 1793050000, today: '2026-10-26', since: '2026-03-02', keptSince: '2026-10-26', adLists: 1,
  days: [
    { d: '2026-10-20', ads: 13102, apps: { tiktok: 50, roblox: 40 }, offSec: 36000, kept: 1 },
    { d: '2026-10-26', ads: 14208, apps: { tiktok: 61, youtube: 27 }, offSec: 3600, kept: null },
    { d: '2026-10-23', ads: 16920, apps: { roblox: 30 }, offSec: null, kept: 0 },
  ],
  tot: { ads: 3100000, apps: { tiktok: 12840, roblox: 9115 }, offSec: 6854400, nights: 238, nightsKept: 231 },
}, over || {}));

test('parseLedger: a good ledger, days oldest first, gaps stay gaps', () => {
  const L = C.parseLedger(ledgerJSON(), IDS);
  assert.deepEqual(L.days.map((r) => r.d), ['2026-10-20', '2026-10-23', '2026-10-26']);
  assert.equal(L.today, '2026-10-26');
  assert.equal(L.since, '2026-03-02');
  assert.equal(L.adLists, 1);
  assert.deepEqual(L.days[1], { d: '2026-10-23', ads: 16920, apps: { roblox: 30 }, offSec: null, kept: 0 });
  assert.deepEqual(L.tot, { ads: 3100000, apps: { tiktok: 12840, roblox: 9115 }, offSec: 6854400, nights: 238, nightsKept: 231 });
});

test('parseLedger: anything unexpected is dropped, never shown', () => {
  for (const bad of [undefined, '', 'nope', '[]', '{"v":2}', ledgerJSON({ v: '1' }), ledgerJSON({ at: 0 }), ledgerJSON({ today: '2026-02-30' }), ledgerJSON({ today: 'today' })]) {
    assert.equal(C.parseLedger(bad, IDS), null, String(bad));
  }
  const L = C.parseLedger(ledgerJSON({
    since: 'last year', keptSince: '2026-13-01', adLists: -1,
    days: [
      { d: '2026-10-27', ads: 5 },                                  // after today
      { d: '2026-10-19', ads: 5 },                                  // more than a week back
      { d: '2026-10-25', ads: 1.5, apps: { tiktok: -2, roblox: '9', evil: 9, toString: 3, youtube: 4 }, offSec: -1, kept: true },
      { d: '2026-10-25', ads: 99 },                                 // the same day twice: the first one counts
      'garbage', null,
    ],
    tot: { ads: 1e13, apps: [], nights: 3, nightsKept: 9 },
  }), IDS);
  assert.equal(L.since, null);
  assert.equal(L.keptSince, null);
  assert.equal(L.adLists, null);
  assert.deepEqual(L.days, [{ d: '2026-10-25', ads: null, apps: { youtube: 4 }, offSec: null, kept: null }]);
  assert.deepEqual(L.tot, { ads: null, apps: {}, offSec: null, nights: 3, nightsKept: 3 }, 'kept nights never exceed nights');
});

test('parseLedger: at most 8 apps, biggest first', () => {
  const ids = 'abcdefghij'.split('');
  const apps = {}; ids.forEach((k, i) => { apps[k] = i + 1; });
  const L = C.parseLedger(ledgerJSON({ days: [{ d: '2026-10-26', ads: 1, apps }] }), ids);
  assert.deepEqual(Object.keys(L.days[0].apps), ['j', 'i', 'h', 'g', 'f', 'e', 'd', 'c']);
});

test('savings: today, the week and since, with the estimates', () => {
  const L = C.parseLedger(ledgerJSON(), IDS);
  const today = C.savings(L, 'today');
  assert.equal(today.ads, 14208);
  assert.deepEqual(today.apps, [{ app: 'tiktok', count: 61 }, { app: 'youtube', count: 27 }]);
  assert.equal(today.waitSec, 14208 * 50 / 1000);
  assert.equal(today.bytes, 14208 * 10000);
  assert.equal(today.days, 1);
  const week = C.savings(L, 'week');
  assert.equal(week.ads, 13102 + 16920 + 14208);
  assert.equal(week.offSec, 36000 + 3600, 'an unknown day does not count as zero, it just adds nothing');
  assert.deepEqual(week.apps.slice(0, 2), [{ app: 'tiktok', count: 111 }, { app: 'roblox', count: 70 }]);
  assert.deepEqual([week.nights, week.nightsKept], [2, 1]);
  assert.equal(week.days, 3);
  const since = C.savings(L, 'since');
  assert.equal(since.ads, 3100000);
  assert.deepEqual([since.nights, since.nightsKept], [238, 231]);
  assert.equal(C.savings(null, 'week').ads, null);
  const unknown = C.savings(C.parseLedger(ledgerJSON({ days: [{ d: '2026-10-26', ads: null }] }), IDS), 'today');
  assert.equal(unknown.ads, null);
  assert.equal(unknown.waitSec, null, 'no ads number, no estimate');
});

test('ledgerWeek: seven days ending today, missing ones are null', () => {
  const L = C.parseLedger(ledgerJSON(), IDS);
  const w = C.ledgerWeek(L);
  assert.deepEqual(w.map((x) => x.d), ['2026-10-20', '2026-10-21', '2026-10-22', '2026-10-23', '2026-10-24', '2026-10-25', '2026-10-26']);
  assert.deepEqual(w.map((x) => x.ads), [13102, null, null, 16920, null, null, 14208]);
  assert.equal(C.weekday('2026-10-26'), 1, 'a Monday');
  assert.equal(C.weekday('2026-10-25'), 0, 'a Sunday');
  assert.equal(C.weekday('nope'), -1);
  assert.deepEqual(C.ledgerWeek(null), []);
});

test('durationParts and sizeParts', () => {
  assert.deepEqual(C.durationParts(29), { m: 0 });
  assert.deepEqual(C.durationParts(12 * 60), { m: 12 });
  assert.deepEqual(C.durationParts(82 * 60), { h: 1, m: 22 });
  assert.deepEqual(C.durationParts(9 * 3600 + 59 * 60), { h: 9, m: 59 });
  assert.deepEqual(C.durationParts(43.4 * 3600), { h: 43 });
  assert.equal(C.durationParts(null), null);
  assert.deepEqual(C.sizeParts(142e6), { value: 142, unit: 'MB' });
  assert.deepEqual(C.sizeParts(984e6), { value: 1, unit: 'GB' });
  assert.deepEqual(C.sizeParts(3.24e9), { value: 3.2, unit: 'GB' });
  assert.deepEqual(C.sizeParts(31e9), { value: 31, unit: 'GB' });
  assert.deepEqual(C.sizeParts(2.5e12), { value: 2.5, unit: 'TB' });
  assert.deepEqual(C.sizeParts(0), { value: 0, unit: 'MB' });
  assert.equal(C.sizeParts(-1), null);
});

test('moneyFor: only with a price the parent typed', () => {
  assert.equal(C.moneyFor(2e9, 0.5), 1);
  assert.equal(C.moneyFor(2e9, '0,5'), 1, 'a comma works as the decimal mark');
  for (const p of [0, -1, 'abc', '', null, undefined, 1e7]) assert.equal(C.moneyFor(2e9, p), null, String(p));
  assert.equal(C.moneyFor(null, 1), null);
});

test('parseAmount: any keypad, any decimal mark', () => {
  const cases = [['0.5', 0.5], ['0,5', 0.5], ['٠٫٥', 0.5], ['۰٫۵', 0.5], ['0٫5', 0.5], ['١', 1], ['1٫5', 1.5], ['1,000', 1000], ['10,000', 10000],
    ['1.000,5', 1000.5], ['1,000.5', 1000.5], ['1٬000', 1000], [' 2 ', 2], ['0,125', 0.125], ['2,5', 2.5], ['1,2,3', 123], ['abc', null], ['', null],
    ['-1', null], ['1e3', null], [3, 3], [null, null]];
  for (const [input, want] of cases) assert.equal(C.parseAmount(input), want, JSON.stringify(input));
  assert.equal(C.moneyFor(2e9, '٠٫٥'), 1, 'an Arabic-Indic price works');
  assert.equal(C.moneyFor(1e9, '1,000'), 1000, 'a thousands comma is not a decimal mark');
});

test('nextWallTime: the next time the box clock shows HH:MM', () => {
  const at = (iso) => Date.parse(iso) / 1000;
  // The box is in Bahrain (+03:00). 21:40 there; morning is 06:30 the next day.
  assert.equal(C.nextWallTime(at('2026-10-26T18:40:00Z'), '06:30', 180), at('2026-10-27T03:30:00Z'));
  // 02:00 at night: 06:30 is later the same night.
  assert.equal(C.nextWallTime(at('2026-10-26T23:00:00Z'), '06:30', 180), at('2026-10-27T03:30:00Z'));
  // Less than a minute away counts as tomorrow.
  assert.equal(C.nextWallTime(at('2026-10-27T03:29:30Z'), '06:30', 180), at('2026-10-28T03:30:00Z'));
  assert.equal(C.nextWallTime(at('2026-10-26T18:40:00Z'), '6:30', 180), null);
  assert.equal(C.utcOffsetMinutes('+03:00'), 180);
  assert.equal(C.utcOffsetMinutes('-0530'), -330);
  assert.equal(C.utcOffsetMinutes('Z'), 0);
  assert.equal(C.utcOffsetMinutes('+25:00'), null);
  assert.equal(C.utcOffsetMinutes(null), null);
});

// ------------------------------------------------------------------ bedtime as the box sees it (bin/sinko in_schedule, Controller.tick)
const SC = { enabled: true, start: '21:00', end: '06:30', days: [0, 1, 2, 3, 4] };     // Sunday to Thursday nights
const BH = 180;                                                                          // the box in Bahrain, UTC+03:00
const at = (iso) => Date.parse(iso) / 1000;                                             // ISO with the box's own +03:00

test('inBedtime follows in_schedule: a night belongs to the day it starts', () => {
  assert.equal(C.inBedtime(SC, at('2026-10-26T22:00:00+03:00'), BH), true, 'Monday 22:00');
  assert.equal(C.inBedtime(SC, at('2026-10-27T05:00:00+03:00'), BH), true, 'Tuesday 05:00 is Monday night');
  assert.equal(C.inBedtime(SC, at('2026-10-27T06:30:00+03:00'), BH), false, 'the end minute is not bedtime');
  assert.equal(C.inBedtime(SC, at('2026-10-30T22:00:00+03:00'), BH), false, 'Friday night is not a bedtime night');
  assert.equal(C.inBedtime(SC, at('2026-10-31T05:00:00+03:00'), BH), false, 'nor is early Saturday');
  assert.equal(C.inBedtime(SC, at('2026-10-30T05:00:00+03:00'), BH), true, 'early Friday is Thursday night');
  assert.equal(C.inBedtime(Object.assign({}, SC, { enabled: false }), at('2026-10-26T22:00:00+03:00'), BH), false);
  assert.equal(C.inBedtime(Object.assign({}, SC, { start: '06:30' }), at('2026-10-26T22:00:00+03:00'), BH), false, 'start == end is never');
  const day = { enabled: true, start: '13:00', end: '15:00', days: [1] };
  assert.equal(C.inBedtime(day, at('2026-10-26T14:00:00+03:00'), BH), true, 'a window inside one day');
  assert.equal(C.inBedtime(day, at('2026-10-26T15:00:00+03:00'), BH), false);
});

test('comesBack: what the panel promises is what the box will do', () => {
  const now = at('2026-10-26T20:30:00+03:00');          // Monday evening, bedtime at 21:00
  // a break that ends inside bedtime stays off until bedtime ends
  assert.deepEqual(C.comesBack('break', SC, now, now + 3600, BH), { at: at('2026-10-27T06:30:00+03:00'), bedtime: true });
  // a break that ends before bedtime ends when it says
  assert.deepEqual(C.comesBack('break', SC, now, now + 1200, BH), { at: now + 1200, bedtime: false });
  // free time cut short by bedtime
  assert.deepEqual(C.comesBack('free', SC, now, now + 7200, BH), { at: at('2026-10-26T21:00:00+03:00'), bedtime: true });
  assert.deepEqual(C.comesBack('free', SC, now, now + 600, BH), { at: now + 600, bedtime: false });
  // switched off by hand: the box turns it on when the next bedtime window ends
  assert.deepEqual(C.comesBack('off', SC, now, null, BH), { at: at('2026-10-27T06:30:00+03:00'), bedtime: true });
  assert.deepEqual(C.comesBack('off', Object.assign({}, SC, { enabled: false }), now, null, BH), { at: null, bedtime: false });
  // during bedtime, a break that ends after bedtime ends at its own time
  const night = at('2026-10-27T05:00:00+03:00');
  assert.deepEqual(C.comesBack('break', SC, night, night + 7200, BH), { at: night + 7200, bedtime: false });
  // Friday evening: the next window is Sunday night
  const fri = at('2026-10-30T20:00:00+03:00');
  assert.deepEqual(C.comesBack('off', SC, fri, null, BH), { at: at('2026-11-02T06:30:00+03:00'), bedtime: true });
});
