import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

// The calendar's write behaviour is tested through the pure helpers in entryOps.ts: what a move
// does to the plan, what a drag sends, what each form saves, and what accepting a block changes.
const source = readFileSync(new URL('./src/pages/calendar/entryOps.ts', import.meta.url), 'utf8')
  .replace(/import type[^\n]*\n/, '');
const compiled = ts.transpile(source, { module: ts.ModuleKind.ES2022 });
const ops = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

const ride = { id: 1, date: 'A', kind: 'workout', workout_type: 'Indoor Ride', structure: { blocks: [{ kind: 'freeride', duration_s: 600 }] } };
const run = { id: 2, date: 'B', kind: 'workout', workout_type: 'Easy Run' };
const race = { id: 3, date: 'B', kind: 'race', workout_type: 'Running Race', title: 'Fall 10K' };

test('a move puts the entry on the target day beside what is already there', () => {
  const plan = ops.applyMove({ A: [ride], B: [run, race] }, 1, 'B');
  assert.equal(plan.A, undefined); // the emptied day disappears
  assert.deepEqual(plan.B.map(e => e.id), [1, 2, 3]); // nothing displaced, order by id
  assert.equal(plan.B[0].date, 'B');
  assert.equal(plan.B[0].structure, ride.structure); // the rest of the entry is untouched
});

test('moving to the same day or an unknown entry changes nothing', () => {
  const plan = { A: [ride] };
  assert.equal(ops.applyMove(plan, 1, 'A'), plan);
  assert.equal(ops.applyMove(plan, 99, 'B'), plan);
});

test('a drag is a date-only patch', () => {
  assert.deepEqual(ops.datePatch('2026-10-30'), { date: '2026-10-30' });
});

test('the server reason is shown for a refused write, else the fallback', async () => {
  const res = body => ({ json: async () => body });
  assert.equal(await ops.failureMessage(res({ detail: 'Already has a run' }), 'x'), 'Already has a run');
  assert.equal(await ops.failureMessage(res({}), 'fallback'), 'fallback');
  assert.equal(await ops.failureMessage({ json: async () => { throw new Error(); } }, 'fallback'), 'fallback');
  assert.equal(await ops.failureMessage(undefined, 'fallback'), 'fallback');
});

const form = (over = {}) => ({
  workout_type: 'Indoor Ride', title: '', sport: 'run', goal_time: '', priority: '',
  result_activity_id: '', description: '', distance: '', elevation: '', duration_min: '60',
  intensity: 'easy', route_url: '', clear_structure: false, ...over,
});
const ctx = (over = {}) => ({
  existing: null, kmFromInput: v => (v ? Number(v) : null), mFromInput: v => (v ? Number(v) : null),
  routeCapable: t => t === 'Indoor Ride', noDistance: t => t === 'Yoga', keepsStructure: t => t === 'Indoor Ride', ...over,
});

test('editing a workout keeps its structure unless the athlete removes it', () => {
  const kept = ops.buildEntryBody('workout', 'D', form(), ctx({ existing: ride }));
  assert.equal('structure' in kept, false); // a patch that omits it leaves it alone
  assert.equal('duration_min' in kept, false); // the structure decides the duration
  const cleared = ops.buildEntryBody('workout', 'D', form({ clear_structure: true, duration_min: '30' }), ctx({ existing: ride }));
  assert.equal(cleared.structure, null);
  assert.equal(cleared.duration_min, 30);
});

test('creating sends kind and date; editing does not', () => {
  const created = ops.buildEntryBody('workout', '2026-10-30', form({ route_url: 'https://strava.com/routes/2' }), ctx());
  assert.equal(created.kind, 'workout');
  assert.equal(created.date, '2026-10-30');
  assert.equal(created.route_url, 'https://strava.com/routes/2');
  const edited = ops.buildEntryBody('workout', 'D', form(), ctx({ existing: run }));
  assert.equal('kind' in edited, false);
  assert.equal('date' in edited, false);
});

test('a race form saves name, sport, goal and priority', () => {
  const body = ops.buildEntryBody('race', 'D', form({
    title: 'Fall Half', sport: 'run', goal_time: '1:45:00', priority: 'A', distance: '21.1',
    route_url: 'https://strava.com/routes/9',
  }), ctx());
  assert.deepEqual(
    [body.kind, body.title, body.sport, body.goal_time_s, body.priority, body.distance_km],
    ['race', 'Fall Half', 'run', 6300, 'A', 21.1],
  );
  assert.equal(body.route_url, 'https://strava.com/routes/9');
});

test('an unparseable goal time is kept as text, never dropped', () => {
  const body = ops.buildEntryBody('race', 'D', form({ goal_time: 'sub 4' }), ctx());
  assert.equal(body.goal_time_s, null);
  assert.equal(body.goal_text, 'sub 4');
  assert.equal(ops.parseGoalTime('3:30:00'), 12600);
  assert.equal(ops.parseGoalTime('45:00'), 2700);
  assert.equal(ops.parseGoalTime('1:75:00'), null);
  assert.equal(ops.formatGoalTime(6300), '1:45:00');
  assert.equal(ops.formatGoalTime(2700), '45:00');
});

test('a race result link is only sent when editing', () => {
  const create = ops.buildEntryBody('race', 'D', form({ result_activity_id: '7' }), ctx());
  assert.equal('result_activity_id' in create, false);
  const edit = ops.buildEntryBody('race', 'D', form({ result_activity_id: '7' }), ctx({ existing: race }));
  assert.equal(edit.result_activity_id, 7);
  assert.equal(ops.buildEntryBody('race', 'D', form(), ctx({ existing: race })).result_activity_id, null);
});

test('travel and rest entries save only their label and notes', () => {
  assert.deepEqual(ops.buildEntryBody('travel', 'D', form({ title: 'Flight', description: ' hotel ' }), ctx()),
    { kind: 'travel', date: 'D', title: 'Flight', notes: 'hotel' });
  assert.deepEqual(ops.buildEntryBody('rest', 'D', form(), ctx()), { kind: 'rest', date: 'D', notes: null });
});

test('accepting a block replaces only the workouts in range, in one change set', () => {
  const plan = {
    '2026-11-02': [{ id: 1, kind: 'workout', date: '2026-11-02', workout_type: 'Easy Run' }, { id: 2, kind: 'race', date: '2026-11-02' }],
    '2026-11-03': [{ id: 3, kind: 'rest', date: '2026-11-03' }],
    '2026-11-20': [{ id: 4, kind: 'workout', date: '2026-11-20' }], // outside the range
  };
  const generated = [{ date: '2026-11-02', workout_type: 'Tempo Run' }];
  const range = { start: '2026-11-01', end: '2026-11-10' };
  const replace = ops.generationOps(generated, plan, range, 'replace');
  assert.deepEqual(replace.replaced.map(e => e.id), [1]);
  assert.deepEqual(replace.ops, [{ op: 'delete', id: 1 }, { op: 'create', date: '2026-11-02', workout_type: 'Tempo Run' }]);
  const append = ops.generationOps(generated, plan, range, 'append');
  assert.deepEqual(append.replaced, []);
  assert.deepEqual(append.ops.map(o => o.op), ['create']);
});

test('each accept attempt gets its own idempotency key', () => {
  assert.notEqual(ops.newRequestId(), ops.newRequestId());
});
