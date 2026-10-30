import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

// Compile the production module in memory, as units.test.mjs does.
const source = readFileSync(new URL('./src/pages/activityLabels.ts', import.meta.url), 'utf8');
const compiled = ts.transpile(source, { module: ts.ModuleKind.ES2022 });
const L = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

const act = (i, over = {}) => ({
  date: `2026-09-${String(1 + (i % 28)).padStart(2, '0')}`,
  sport_type: 'Run',
  distance_m: 8000,
  moving_time_s: 2400,
  elevation_gain_m: 80,
  climb_m_per_km: null,
  avg_pace_s_per_km: 360,
  avg_hr: 140,
  ...over,
});

// Eight runs between 6 and 10 km.
const history = [6, 7, 8, 8, 8, 9, 10, 8].map((km, i) => act(i, { distance_m: km * 1000 }));

test('sportGroup mirrors the backend type sets', () => {
  assert.equal(L.sportGroup('TrailRun'), 'run');
  assert.equal(L.sportGroup('GravelRide'), 'ride');
  assert.equal(L.sportGroup('WeightTraining'), 'other');
  assert.equal(L.sportGroup(null), 'other');
});

test('run climb tiers; Hilly starts at the existing high-elevation flag', () => {
  const text = (r) => L.climbLabel(r, 'run').text;
  assert.equal(text(0), 'Flat');
  assert.equal(text(7.9), 'Flat');
  assert.equal(text(8), 'Rolling');
  assert.equal(text(L.HIGH_CLIMB_M_PER_KM - 0.01), 'Rolling');
  assert.equal(text(L.HIGH_CLIMB_M_PER_KM), 'Hilly');
  assert.equal(text(40), 'Mountainous');
});

test('HIGH_CLIMB_M_PER_KM is 100 ft/mi', () => {
  assert.ok(Math.abs(L.HIGH_CLIMB_M_PER_KM - 18.94) < 0.01);
});

test('rides use gentler tiers than runs', () => {
  assert.equal(L.climbLabel(13, 'ride').text, 'Hilly');
  assert.equal(L.climbLabel(13, 'run').text, 'Rolling');
});

test('climb label is null for missing data or non-cardio sports', () => {
  assert.equal(L.climbLabel(null, 'run'), null);
  assert.equal(L.climbLabel(20, 'other'), null);
});

test('climbRate falls back to gain / distance', () => {
  assert.equal(L.climbRate(act(0, { climb_m_per_km: 12 })), 12);
  assert.equal(L.climbRate(act(0, { elevation_gain_m: 160, distance_m: 8000 })), 20);
  assert.equal(L.climbRate(act(0, { elevation_gain_m: null })), null);
  assert.equal(L.climbRate(act(0, { distance_m: 0 })), null);
});

test('baseline needs MIN_BASELINE activities', () => {
  assert.equal(L.buildBaselines(history.slice(0, 5)).run, undefined);
  const b = L.buildBaselines(history).run.distance_m;
  assert.equal(b.n, 8);
  assert.equal(b.median, 8000);
});

test('baselines are per sport group', () => {
  const rides = Array.from({ length: 6 }, (_, i) => act(i, { sport_type: 'Ride', distance_m: 40000 }));
  const b = L.buildBaselines([...history, ...rides]);
  assert.equal(b.run.distance_m.median, 8000);
  assert.equal(b.ride.distance_m.median, 40000);
});

test('old activities fall out of the window when enough recent ones exist', () => {
  const old = Array.from({ length: 6 }, () => act(0, { date: '2025-01-05', distance_m: 20000 }));
  const b = L.buildBaselines([...old, ...history]);
  assert.equal(b.run.distance_m.median, 8000);
});

test('relative labels around the typical band', () => {
  const b = L.buildBaselines(history).run.distance_m;
  const text = (m) => L.relativeLabel(m, b, 'run').text;
  assert.equal(text(8000), 'Typical');
  assert.equal(text(2000), 'Very short');
  assert.equal(text(5500), 'Short');
  assert.equal(text(10500), 'Long');
  assert.equal(text(21000), 'Very long');
  assert.equal(L.relativeLabel(21000, b, 'run').tone, 'red');
});

test('relative label is null without a baseline or value', () => {
  assert.equal(L.relativeLabel(8000, undefined, 'run'), null);
  assert.equal(L.relativeLabel(0, { n: 8, p25: 1, median: 2, p75: 3 }, 'run'), null);
  assert.equal(L.relativeLabel(null, { n: 8, p25: 1, median: 2, p75: 3 }, 'run'), null);
});

test('labelsFor combines distance, time, elevation and climb', () => {
  const baselines = L.buildBaselines(history);
  const long = act(0, { distance_m: 21000, elevation_gain_m: 800 });
  const labels = L.labelsFor(long, baselines);
  assert.equal(labels.distance.text, 'Very long');
  assert.equal(labels.climb.text, 'Hilly'); // 800 m / 21 km ≈ 38 m/km
  assert.equal(L.labelsFor(act(0, { sport_type: 'Yoga' }), baselines).distance, null);
});

// Pace (s/km, lower = faster) and HR baselines: 8 runs, pace 330-390, HR 130-150.
const paceHr = [330, 345, 360, 360, 360, 375, 390, 360].map((p, i) =>
  act(i, { avg_pace_s_per_km: p, avg_hr: 130 + (i % 5) * 5 }),
);

test('pace labels are inverted: lower s/km is faster', () => {
  const b = L.buildBaselines(paceHr).run.avg_pace_s_per_km;
  const lab = (p) => L.spreadLabel(p, b, 'run', L.PACE_WORDS);
  assert.equal(lab(360).text, 'Typical');
  assert.equal(lab(335).text, 'Fast');
  assert.equal(lab(300).text, 'Very fast');
  assert.equal(lab(385).text, 'Slow');
  assert.equal(lab(450).text, 'Very slow');
  assert.match(lab(300).detail, /faster/);
  assert.equal(lab(450).tone, 'default'); // pace is not judged
});

test('HR labels tint the high side', () => {
  const b = L.buildBaselines(paceHr).run.avg_hr;
  const lab = (v) => L.spreadLabel(v, b, 'run', L.HR_WORDS);
  assert.equal(lab(140).text, 'Typical');
  assert.equal(lab(128).text, 'Low');
  assert.equal(lab(147).text, 'High');
  assert.equal(lab(147).tone, 'yellow');
  assert.equal(lab(175).text, 'Very high');
  assert.equal(lab(175).tone, 'red');
});

test('"very" needs at least 10% from the median even outside the fence', () => {
  const tight = { n: 8, p25: 100, median: 100, p75: 100 };
  assert.equal(L.spreadLabel(105, tight, 'run', L.HR_WORDS).text, 'High');
  assert.equal(L.spreadLabel(115, tight, 'run', L.HR_WORDS).text, 'Very high');
});

test('pace / HR labels are null without data, baseline or cardio sport', () => {
  const b = L.buildBaselines(paceHr).run;
  assert.equal(L.spreadLabel(null, b.avg_hr, 'run', L.HR_WORDS), null);
  assert.equal(L.spreadLabel(140, undefined, 'run', L.HR_WORDS), null);
  assert.equal(L.spreadLabel(140, b.avg_hr, 'other', L.HR_WORDS), null);
  assert.equal(L.labelsFor(act(0, { avg_hr: null }), L.buildBaselines(paceHr)).hr, null);
});

test('plannedClimbRate needs both a positive distance and gain', () => {
  assert.equal(L.plannedClimbRate(30, 450), 15);
  for (const [d, e] of [[null, 450], [30, null], [0, 450], [30, 0], [undefined, undefined]]) {
    assert.equal(L.plannedClimbRate(d, e), null);
  }
});

test('plannedClimbRate feeds the ride terrain tiers at their boundaries', () => {
  const tier = (rate) => L.climbLabel(rate, 'ride').text;
  assert.equal(tier(L.plannedClimbRate(10, 49)), 'Flat');
  assert.equal(tier(L.plannedClimbRate(10, 50)), 'Rolling');
  assert.equal(tier(L.plannedClimbRate(10, 120)), 'Hilly');
  assert.equal(tier(L.plannedClimbRate(10, 250)), 'Mountainous');
});
