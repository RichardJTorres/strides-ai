import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const source = readFileSync(new URL('./src/pages/calendar/grid.ts', import.meta.url), 'utf8');
const compiled = ts.transpile(source, { module: ts.ModuleKind.ES2022 });
const grid = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

test('buildGrid renders whole Monday-Sunday weeks around the month', () => {
  const cells = grid.buildGrid(new Date(2026, 10, 1)); // November 2026 starts on a Sunday
  assert.equal(cells.length, 42);
  assert.equal(cells[0].dateStr, '2026-10-26'); // the Monday before
  assert.equal(cells.at(-1).dateStr, '2026-12-06');
  assert.equal(cells.filter(c => c.inCurrentMonth).length, 30);
  for (const week of grid.chunkWeeks(cells)) {
    assert.equal(week.length, 7);
    assert.equal(week[0].date.getDay(), 1);
    assert.equal(week[6].date.getDay(), 0);
  }
});

test('buildGrid needs no padding when the month starts on a Monday', () => {
  const cells = grid.buildGrid(new Date(2026, 5, 1)); // June 2026 starts on a Monday
  assert.equal(cells[0].dateStr, '2026-06-01');
  assert.equal(cells.at(-1).dateStr, '2026-07-05');
  assert.equal(cells.length, 35);
});

test('buildGrid pads the start of a month that begins mid-week', () => {
  const cells = grid.buildGrid(new Date(2026, 9, 1)); // October 2026 starts on a Thursday
  assert.equal(cells[0].dateStr, '2026-09-28');
  assert.equal(cells[0].inCurrentMonth, false);
  assert.equal(cells.find(c => c.inCurrentMonth).dateStr, '2026-10-01');
});

test('weekFrom crosses month and year boundaries', () => {
  assert.deepEqual(grid.weekFrom('2026-12-28').map(c => c.dateStr), [
    '2026-12-28', '2026-12-29', '2026-12-30', '2026-12-31', '2027-01-01', '2027-01-02', '2027-01-03',
  ]);
});

test('splitActivities matches activities to the entries they were scored against', () => {
  const a = { id: 1 }, b = { id: 2 }, c = { id: 3 };
  const acts = { D: [a, b, c] };
  const plan = { D: [{ id: 10 }, { id: 11 }] };
  const comp = { 10: { matched_activity_id: 2 }, 11: { matched_activity_id: 3 } };
  assert.deepEqual(grid.splitActivities(plan, acts, comp, 'D'), { byEntry: { 10: b, 11: c }, others: [a] });
  assert.deepEqual(grid.splitActivities({}, acts, comp, 'D'), { byEntry: {}, others: [a, b, c] });
  assert.deepEqual(grid.splitActivities(plan, acts, {}, 'D'), { byEntry: {}, others: [a, b, c] });
});

test('dayCompliance summarizes a day from its scored entries only', () => {
  const plan = { D: [{ id: 1 }, { id: 2 }, { id: 3 }] };
  const comp = {
    1: { status: 'completed' }, 2: { status: 'unscored' }, 3: { status: 'modified' },
  };
  assert.equal(grid.dayCompliance(plan, comp, 'D').status, 'modified'); // a shortened one outranks
  assert.equal(grid.dayCompliance(plan, { 1: { status: 'completed' }, 2: { status: 'unscored' } }, 'D').status, 'completed');
  assert.equal(grid.dayCompliance(plan, { 2: { status: 'unscored' } }, 'D'), undefined);
  assert.equal(grid.dayCompliance({}, comp, 'D'), undefined);
});

test('groupByDate keeps several entries per day in order', () => {
  const plan = grid.groupByDate([{ id: 1, date: 'A' }, { id: 2, date: 'A' }, { id: 3, date: 'B' }]);
  assert.deepEqual(plan.A.map(e => e.id), [1, 2]);
  assert.deepEqual(plan.B.map(e => e.id), [3]);
});

test('summarizeWeek totals workout distance and tallies per-entry statuses', () => {
  const cells = grid.weekFrom('2026-11-02');
  const plan = {
    '2026-11-02': [
      { id: 1, kind: 'workout', distance_km: 10 },
      { id: 7, kind: 'race', distance_km: 21.1 }, // a race is not training volume
    ],
    '2026-11-03': [{ id: 2, kind: 'rest', distance_km: 99 }], // rest distance never counts
    '2026-11-04': [{ id: 3, kind: 'workout' }], // no distance
    '2026-11-05': [{ id: 4, kind: 'workout', distance_km: 5 }],
  };
  const activities = {
    '2026-11-02': [{ distance_m: 8000 }, { distance_m: null }],
    '2026-11-08': [{ distance_m: 2500 }],
    '2026-11-09': [{ distance_m: 50000 }], // outside the week
  };
  const compliance = {
    1: { status: 'modified' }, 2: { status: 'unscored' }, 7: { status: 'unscored' },
    4: { status: 'completed' },
  };
  const s = grid.summarizeWeek(cells, plan, activities, compliance);
  assert.equal(s.plannedKm, 15);
  assert.equal(s.actualKm, 10.5);
  assert.deepEqual([s.completed, s.modified, s.missed, s.upcoming], [1, 1, 0, 0]);
  assert.equal(s.cells, cells);
});

test('weekBreakdown and rangeLength', () => {
  assert.equal(grid.weekBreakdown({ completed: 3, modified: 1, missed: 0 }), '3 as planned · 1 shortened');
  assert.equal(grid.weekBreakdown({ completed: 0, modified: 0, missed: 0 }), '');
  assert.equal(grid.rangeLength({ start: '2026-11-10', end: '2026-11-10' }), 1);
  assert.equal(grid.rangeLength({ start: '2026-10-30', end: '2026-11-02' }), 4); // across DST end
});

test('buildGrid can start weeks on Sunday', () => {
  const nov = grid.buildGrid(new Date(2026, 10, 1), 'sunday'); // November 2026 starts on a Sunday
  assert.equal(nov[0].dateStr, '2026-11-01'); // no padding
  assert.equal(nov.length, 35);
  const oct = grid.buildGrid(new Date(2026, 9, 1), 'sunday'); // October 2026 starts on a Thursday
  assert.equal(oct[0].dateStr, '2026-09-27'); // the Sunday before
  for (const week of grid.chunkWeeks(oct)) {
    assert.equal(week[0].date.getDay(), 0);
    assert.equal(week[6].date.getDay(), 6);
  }
});

test('isPerfectWeek needs every scored workout completed as planned', () => {
  const w = (completed, modified = 0, missed = 0, upcoming = 0) => ({ completed, modified, missed, upcoming });
  assert.equal(grid.isPerfectWeek(w(4)), true);
  assert.equal(grid.isPerfectWeek(w(0)), false); // nothing scored
  assert.equal(grid.isPerfectWeek(w(3, 1)), false); // shortened
  assert.equal(grid.isPerfectWeek(w(3, 0, 1)), false); // missed
  assert.equal(grid.isPerfectWeek(w(3, 0, 0, 1)), false); // still to come
});
