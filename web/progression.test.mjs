import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

// The Progression card's data shaping (src/progress/progression.ts), tested on its own.
const source = readFileSync(new URL('./src/progress/progression.ts', import.meta.url), 'utf8');
const compiled = ts.transpile(source, { module: ts.ModuleKind.ES2022 });
const p = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

const peak = (id, value, name = `ride ${id}`, date = '2026-10-04') => ({ activity_id: id, date, name, value });
const month = (m, hours, longest, most_climb, in_progress = false) => ({
  month: m, activities: longest ? 1 : 0, hours, distance_m: longest?.value ?? 0, climb_m: most_climb?.value ?? 0,
  climb_m_per_km: null, longest, most_climb, in_progress,
});
const progression = {
  sport: 'ride', as_of: '2026-11-25', first_date: '2025-12-02', omitted: 0,
  months: [
    month('2026-11', 14.3, peak(3, 45720), peak(3, 1042), true),
    month('2026-10', 27.1, peak(2, 99600, 'North bend'), peak(4, 1177, 'Nutmeg')),
    month('2026-01', 0, null, null),
    month('2025-12', 4.0, peak(1, 34900), peak(1, 385)),
  ],
};

test('month labels are fixed, not locale formatted', () => {
  assert.equal(p.monthLabel('2026-11'), "Nov '26");
  assert.equal(p.monthLabel('2025-01'), "Jan '25");
  assert.equal(p.monthLabel('nonsense'), 'nonsense');
});

test('rows run oldest first, with the chosen peak converted and empty months kept as null', () => {
  const rows = p.chartRows(progression, 'longest', (m) => m / 1000);
  assert.deepEqual(rows.map((r) => r.month), ['2025-12', '2026-01', '2026-10', '2026-11']);
  assert.deepEqual(rows.map((r) => r.peak), [34.9, null, 99.6, 45.72]);
  assert.equal(rows[2].peakName, 'North bend');
  assert.equal(rows[1].peakId, null);
  assert.deepEqual(rows.map((r) => r.inProgress), [false, false, false, true]);
  const climb = p.chartRows(progression, 'most_climb', (m) => m);
  assert.equal(climb[2].peakName, 'Nutmeg');
  assert.equal(climb[2].peak, 1177);
  assert.deepEqual(progression.months.map((m) => m.month)[0], '2026-11'); // input not mutated
});

test('the coach draft names the sport and the span shown', () => {
  const rows = p.chartRows(progression, 'longest', (m) => m);
  assert.match(p.coachDraft('ride', rows), /^Looking at my monthly riding progression \(Dec '25 to Nov '26\)/);
  assert.match(p.coachDraft('run', []), /^Looking at my monthly running progression: /);
});
