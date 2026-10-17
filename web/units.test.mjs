import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

// Compile the production module in memory, as chatAdmission.test.mjs does.
const source = readFileSync(new URL('./src/units.ts', import.meta.url), 'utf8');
const compiled = ts.transpile(source, { module: ts.ModuleKind.ES2022 });
const units = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

// Same fixture the Python registry is tested against — the two must never drift.
const cases = JSON.parse(
  readFileSync(new URL('../tests/fixtures/unit_cases.json', import.meta.url), 'utf8'),
);

const close = (actual, expected) =>
  assert.ok(Math.abs(actual - expected) <= Math.abs(expected) * 1e-5 + 1e-9, `${actual} ≉ ${expected}`);

for (const c of cases.convert) {
  test(`convert ${c.qty} matches the shared fixture`, () => {
    close(units.convert(c.si, c.qty, 'metric'), c.metric);
    close(units.convert(c.si, c.qty, 'imperial'), c.imperial);
  });

  test(`toSI round-trips ${c.qty}`, () => {
    for (const system of ['metric', 'imperial']) {
      close(units.toSI(units.convert(c.si, c.qty, system), c.qty, system), c.si);
    }
  });
}

for (const c of cases.format) {
  test(`format ${c.qty} ${c.si} matches the shared fixture`, () => {
    assert.equal(units.formatValue(c.si, c.qty, 'metric'), c.metric);
    assert.equal(units.formatValue(c.si, c.qty, 'imperial'), c.imperial);
  });
}

test('missing values render the empty marker', () => {
  assert.equal(units.formatValue(null, 'distance', 'imperial'), '—');
  assert.equal(units.formatValue(undefined, 'distance', 'imperial', { empty: '' }), '');
  assert.equal(units.toSI(Number.NaN, 'distance', 'metric'), null);
});

test('speed is derived from stored pace', () => {
  assert.equal(units.formatSpeedFromPace(360, 'metric'), '10.0 km/h');
  assert.equal(units.formatSpeedFromPace(360, 'imperial'), '6.2 mph');
  assert.equal(units.formatSpeedFromPace(0, 'metric'), '—');
});

test('parseUnitSystem falls back to metric', () => {
  assert.equal(units.parseUnitSystem('imperial'), 'imperial');
  assert.equal(units.parseUnitSystem('furlongs'), 'metric');
  assert.equal(units.parseUnitSystem(undefined), 'metric');
});

test('chart unit param maps to the charts API vocabulary', () => {
  assert.equal(units.chartUnitParam('imperial'), 'miles');
  assert.equal(units.chartUnitParam('metric'), 'km');
});
