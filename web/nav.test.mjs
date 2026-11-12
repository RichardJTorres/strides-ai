import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const source = readFileSync(new URL('./src/nav.ts', import.meta.url), 'utf8');
const compiled = ts.transpile(source, { module: ts.ModuleKind.ES2022 });
const nav = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

const route = (tab, param = null) => ({ tab, param });

test('plain tabs, the default and unknown tabs', () => {
  assert.deepEqual(nav.parseHash('#activities'), route('activities'));
  assert.deepEqual(nav.parseHash(''), route('chat'));
  assert.deepEqual(nav.parseHash('#'), route('chat'));
  assert.deepEqual(nav.parseHash('#nope/123'), route('chat'));
});

test('legacy #charts resolves to analytics', () => {
  assert.deepEqual(nav.parseHash('#charts'), route('analytics'));
});

test('valid parameters are kept', () => {
  assert.deepEqual(nav.parseHash('#activities/18164805508'), route('activities', '18164805508'));
  assert.deepEqual(nav.parseHash('#calendar/2026-11-10'), route('calendar', '2026-11-10'));
  assert.deepEqual(nav.parseHash('#analytics/progress'), route('analytics', 'progress'));
});

test('invalid parameters are dropped, not passed on', () => {
  assert.deepEqual(nav.parseHash('#activities/abc'), route('activities'));
  assert.deepEqual(nav.parseHash('#activities/12/34'), route('activities'));
  assert.deepEqual(nav.parseHash('#calendar/2026-1-1'), route('calendar'));
  assert.deepEqual(nav.parseHash('#calendar/'), route('calendar'));
  assert.deepEqual(nav.parseHash('#analytics/<script>'), route('analytics'));
  assert.deepEqual(nav.parseHash('#settings/anything'), route('settings'));
});

test('hrefFor round-trips through parseHash', () => {
  assert.equal(nav.hrefFor('calendar'), '#calendar');
  assert.equal(nav.hrefFor('calendar', null), '#calendar');
  assert.equal(nav.hrefFor('activities', 42), '#activities/42');
  assert.deepEqual(nav.parseHash(nav.hrefFor('calendar', '2026-11-10')), route('calendar', '2026-11-10'));
});
