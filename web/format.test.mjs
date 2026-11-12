import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const source = readFileSync(new URL('./src/ui/format.ts', import.meta.url), 'utf8');
const compiled = ts.transpile(source, { module: ts.ModuleKind.ES2022 });
const f = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

test('formatDuration', () => {
  assert.equal(f.formatDuration(3900), '1h 05m');
  assert.equal(f.formatDuration(3600), '1h 00m');
  assert.equal(f.formatDuration(2700), '45m');
  assert.equal(f.formatDuration(60), '1m');
  assert.equal(f.formatDuration(59), '59s');
  assert.equal(f.formatDuration(0), '0s');
  assert.equal(f.formatDuration(3570), '1h 00m'); // 59.5 min rounds up into the hour
});

test('formatDuration rejects missing or impossible values', () => {
  for (const bad of [null, undefined, NaN, Infinity, -1]) assert.equal(f.formatDuration(bad), '—');
  assert.equal(f.formatDuration(null, ''), '');
});

test('formatDate reads a date-only string as a local calendar day', () => {
  // en-US pins the wording; the day must not shift whatever timezone the test runs in.
  assert.equal(f.formatDate('2026-06-01', 'long', 'en-US'), 'Jun 1, 2026');
  assert.equal(f.formatDate('2026-06-01', 'short', 'en-US'), 'Jun 1');
  assert.equal(f.formatDate('2026-06-01', 'weekday', 'en-US'), 'Mon, Jun 1');
  assert.equal(f.formatDate('2026-01-01', 'long', 'en-US'), 'Jan 1, 2026');
});

test('formatDate rejects missing or unparseable input', () => {
  for (const bad of [null, undefined, '', 'not a date']) assert.equal(f.formatDate(bad), '—');
});
