import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

// Execute the actual UI handler with a stubbed HTTP boundary. No robot calls.
const source = readFileSync(new URL('../app/page.tsx', import.meta.url), 'utf8');
const tree = ts.createSourceFile('page.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let handler;
function visit(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(tree) === 'startRecording') {
    handler = node.initializer.getText(tree);
  }
  ts.forEachChild(node, visit);
}
visit(tree);
assert.ok(handler, 'Start trial handler must exist');
const code = ts.transpileModule(`const run = ${handler};`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText;

async function start(mode, automation) {
  const calls = [];
  const messages = [];
  const busy = [];
  const context = vm.createContext({
    workspaceMode: mode, status: { capture_mode: 'automatic_streams', automation },
    participant: mode === 'qualification' ? 'Q01' : 'P01', vacuum: 60,
    startInFlight: { current: false },
    setStartBusy: value => busy.push(value),
    setMessage: value => messages.push(value),
    post: async (url, body) => calls.push({ url, body }),
  });
  vm.runInContext(code, context);
  await vm.runInContext("run({block:'A', withinBlockTrial:1, controller:'fixed_zone', event:'clean'})", context);
  assert.equal(context.startInFlight.current, false);
  assert.deepEqual(busy, [true, false]);
  return { calls, messages };
}

for (const mode of ['participant_study', 'qualification']) {
  for (const automation of [undefined, { enabled: false }]) {
    test(`${mode} refuses a disabled or unknown automatic service`, async () => {
      const result = await start(mode, automation);
      assert.equal(result.calls.length, 0, 'must not send a manual trial request');
      assert.match(result.messages[0], /Automatic trials.*disabled|Automatic trials.*unavailable/i);
    });
  }
  test(`${mode} requests automatic operation when supported`, async () => {
    const result = await start(mode, { enabled: true, supported_collection_modes: [mode] });
    assert.equal(result.calls.length, 1);
    assert.equal(result.calls[0].url, '/api/protocol/start');
    assert.equal(result.calls[0].body.automatic, true);
  });
}

test('an older qualification-only service cannot start a participant trial', async () => {
  const result = await start('participant_study', { enabled: true, supported_collection_modes: ['qualification'] });
  assert.equal(result.calls.length, 0);
  assert.match(result.messages[0], /does not support/);
});

test('model development remains a non-automatic capture', async () => {
  const result = await start('model_development', { enabled: false });
  assert.equal(result.calls.length, 1);
  assert.equal(result.calls[0].body.automatic, false);
});
