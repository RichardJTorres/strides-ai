import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

// The calendar's workout taxonomy is defined in strides_ai/kinds.py; the frontend mirrors it in
// constants.ts. Both are checked against tests/fixtures/taxonomy.json so they cannot drift.
const fixture = JSON.parse(readFileSync(new URL('../tests/fixtures/taxonomy.json', import.meta.url), 'utf8'));
const source = readFileSync(new URL('./src/pages/calendar/constants.ts', import.meta.url), 'utf8');
const js = ts.transpile(source.replace(/import type[^\n]*\n/, ''), { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS });
const mod = { exports: {} };
new Function('module', 'exports', js)(mod, mod.exports);
const c = mod.exports;

test('workout types match the backend taxonomy', () => {
  const [run, ride, other] = c.WORKOUT_TYPE_GROUPS.map(g => [...g.types].sort());
  assert.deepEqual(run, fixture.workout_types.run);
  assert.deepEqual(ride, fixture.workout_types.ride);
  assert.deepEqual(other, [...fixture.workout_types.other].sort());
});

test('route, structure and unscored sets match', () => {
  assert.deepEqual([...c.ROUTE_CAPABLE_WORKOUT_TYPES].sort(), fixture.route_capable);
  assert.deepEqual(c.WORKOUT_TYPE_GROUPS[1].types.filter(c.keepsStructure).sort(), fixture.structure_capable);
  assert.deepEqual([...c.NO_DISTANCE_WORKOUT_TYPES].sort(), fixture.unscored_workout_types);
});
