import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

// Exercise the component's actual handlers with deferred requests and React-style updates.
const source = readFileSync(new URL('./src/pages/Calendar.tsx', import.meta.url), 'utf8');
const ast = ts.createSourceFile('Calendar.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
function handler(name, bindings) {
  let declaration;
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(ast) === name) declaration = node;
    ts.forEachChild(node, visit);
  }
  visit(ast);
  assert.ok(declaration, `Missing production handler: ${name}`);
  const compiled = ts.transpile(`const ${declaration.getText(ast)};`, { target: ts.ScriptTarget.ES2022 });
  return new Function(...Object.keys(bindings), `${compiled}\nreturn ${name};`)(...Object.values(bindings));
}

function moveHarness(initial) {
  let plan = initial;
  const pending = [];
  const movePending = { current: false };
  const setPlan = update => { plan = typeof update === 'function' ? update(plan) : update; };
  const move = () => handler('moveWorkout', {
    plan, movePending, setPlan, selectedDate: null,
    setSelectedDate() {}, setEditMode() {},
    fetch: (_url, options) => new Promise((resolve, reject) => {
      pending.push({ body: JSON.parse(options.body), resolve, reject });
    }),
  });
  return { move, pending, setPlan, get plan() { return plan; } };
}

test('failed move preserves unrelated edits and new workouts', async () => {
  const a = { workout_type: 'Indoor Ride' };
  const h = moveHarness({ A: a, C: { workout_type: 'Easy Run' } });
  const request = h.move()('A', 'B');
  const edited = { workout_type: 'Long Run' };
  h.setPlan(prev => ({ ...prev, C: edited, D: { workout_type: 'Rest' } }));
  h.pending[0].resolve({ ok: false });
  await request;
  assert.equal(h.plan.A, a);
  assert.equal(h.plan.B, undefined);
  assert.equal(h.plan.C, edited);
  assert.equal(h.plan.D.workout_type, 'Rest');
});

test('another move is blocked until the pending request settles', async () => {
  const h = moveHarness({ A: { workout_type: 'Indoor Ride' }, C: { workout_type: 'Easy Run' } });
  const first = h.move()('A', 'B');
  await h.move()('C', 'D');
  assert.equal(h.pending.length, 1);
  h.pending[0].resolve({ ok: true });
  await first;
  const second = h.move()('C', 'D');
  assert.equal(h.pending.length, 2);
  h.pending[1].resolve({ ok: true });
  await second;
  assert.deepEqual(Object.keys(h.plan).sort(), ['B', 'D']);
});

test('network failure restores both swapped workouts and releases the move lock', async () => {
  const a = { workout_type: 'Indoor Ride', structure: { blocks: [{ kind: 'freeride', duration_s: 600 }] } };
  const b = { workout_type: 'Easy Run' };
  const h = moveHarness({ A: a, B: b });
  const request = h.move()('A', 'B');
  assert.deepEqual(h.pending[0].body.set[0].structure, a.structure);
  h.pending[0].reject(new Error('offline'));
  await request;
  assert.deepEqual(h.plan, { A: a, B: b });
  const retry = h.move()('A', 'B');
  assert.equal(h.pending.length, 2);
  h.pending[1].resolve({ ok: true });
  await retry;
  assert.equal(h.plan.B.structure, a.structure);
});

test('editing preserves structure unless the athlete explicitly removes it', async () => {
  const structure = { blocks: [{ kind: 'steady', duration_s: 3600, pct: 0.75 }] };
  for (const clear of [false, true]) {
    let body;
    const save = handler('saveWorkout', {
      selectedDate: '2026-10-30', selectedWorkout: { structure },
      form: { workout_type: 'Indoor Ride', duration_min: clear ? '30' : '60', clear_structure: clear },
      NO_DISTANCE_WORKOUT_TYPES: new Set(), ROUTE_CAPABLE_WORKOUT_TYPES: new Set(['Indoor Ride']),
      keepsStructure: () => true, kmFromInput: () => null, mFromInput: () => null,
      setPlan() {}, setEditMode() {},
      fetch: async (_url, options) => {
        body = JSON.parse(options.body);
        return { ok: true, json: async () => ({ workout: body }) };
      },
    });
    await save();
    assert.deepEqual(body.structure, clear ? null : structure);
    assert.equal(body.duration_min, clear ? 30 : 60);
  }
});
