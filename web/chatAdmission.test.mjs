import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

// Compile the production helper in memory; no browser or provider dependencies.
const source = readFileSync(new URL('./src/pages/chatAdmission.ts', import.meta.url), 'utf8');
const compiled = ts.transpile(source, { module: ts.ModuleKind.ES2022 });
const { handleChatAdmission } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

for (const status of [400, 409]) {
  test(`HTTP ${status} preserves the draft and selected attachments`, () => {
    const attachment = { name: 'training.csv' };
    const state = { draft: 'My question', files: [attachment], previews: ['blob:preview'] };
    let error = '';
    const accepted = handleChatAdmission({ ok: false, status }, () => {
      state.draft = ''; state.files = []; state.previews = [];
    }, message => { error = message; });
    assert.equal(accepted, false);
    assert.equal(state.draft, 'My question');
    assert.deepEqual(state.files, [attachment]);
    assert.deepEqual(state.previews, ['blob:preview']);
    assert.match(error, status === 409 ? /already responding.*retry/ : /try again/);
  });
}
test('accepted stream clears the composer exactly once', () => {
  let clears = 0;
  assert.equal(handleChatAdmission({ ok: true, status: 200 }, () => { clears++; }, () => assert.fail()), true);
  assert.equal(clears, 1);
});
