const test = require('node:test');
const assert = require('node:assert/strict');
const childProcess = require('node:child_process');

const ADAPTER_PATH = require.resolve('../adapters/things.cjs');

function loadAdapter() {
  delete require.cache[ADAPTER_PATH];
  return require(ADAPTER_PATH);
}

function stubAppleScript(t, responder) {
  const originalExecSync = childProcess.execSync;
  const originalSpawnSync = childProcess.spawnSync;
  const calls = [];

  childProcess.execSync = () => {
    throw new Error('execSync must not be used for AppleScript');
  };
  childProcess.spawnSync = (command, args, options) => {
    calls.push({ command, args, options });
    return responder(command, args, options, calls.length - 1);
  };
  t.after(() => {
    childProcess.execSync = originalExecSync;
    childProcess.spawnSync = originalSpawnSync;
  });

  return calls;
}

test('toExternal honors area_mapping and formats an unmapped pillar as an area', () => {
  const adapter = loadAdapter();

  const mapped = adapter.toExternal(
    { title: 'Map me', pillar: 'pillar_1', priority: 'P1' },
    { area_mapping: { pillar_1: 'Product Delivery' } },
  );
  const fallback = adapter.toExternal(
    { title: 'Format me', pillar: 'customer_success', priority: 'P2' },
    {},
  );

  assert.equal(mapped.area, 'Product Delivery');
  assert.equal(mapped.list, 'today');
  assert.equal(fallback.area, 'Customer Success');
  assert.equal(fallback.list, 'anytime');
});

test('toDex leaves an unknown Things area unresolved', () => {
  const adapter = loadAdapter();

  const converted = adapter.toDex({
    id: 'things-opaque-A',
    name: 'External task',
    area: 'Operations',
    tags: ['P1'],
  });

  assert.equal(converted.pillar, null);
  assert.equal(converted.priority, 'P1');
});

test('create passes AppleScript as argv and schedules Today without shell quoting', async (t) => {
  const calls = stubAppleScript(t, () => ({
    status: 0,
    stdout: 'things-opaque-B\n',
    stderr: '',
  }));
  const adapter = loadAdapter();

  const id = await adapter.create({
    title: "Dave's follow-up",
    notes: "Don't lose the context",
    area: 'Customers',
    list: 'today',
  }, {});

  assert.equal(id, 'things-opaque-B');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].command, 'osascript');
  assert.equal(calls[0].args[0], '-e');
  assert.equal(calls[0].args.length, 2);
  assert.match(calls[0].args[1], /name:"Dave's follow-up"/);
  assert.match(calls[0].args[1], /move newTask to list "Today"/);
  assert.doesNotMatch(calls[0].args[1], /scheduled date/);
  assert.match(calls[0].args[1], /in area "Customers"/);
  assert.equal(calls[0].options.timeout, 10_000);
});

test('complete passes an opaque ID to osascript without a shell', async (t) => {
  const calls = stubAppleScript(t, () => ({ status: 0, stdout: '', stderr: '' }));
  const adapter = loadAdapter();

  await adapter.complete("things-id-with-'apostrophe", {});

  assert.equal(calls.length, 1);
  assert.equal(calls[0].command, 'osascript');
  assert.deepEqual(calls[0].args.slice(0, 1), ['-e']);
  assert.match(calls[0].args[1], /things-id-with-'apostrophe/);
  assert.equal(calls[0].options.timeout, 10_000);
});

test('create reports the specified fallback when osascript exits without stderr', async (t) => {
  stubAppleScript(t, () => ({ status: 1, stdout: '', stderr: '' }));
  const adapter = loadAdapter();

  await assert.rejects(
    adapter.create({ title: 'Fail safely', list: 'anytime' }, {}),
    /Things 3 create failed: osascript failed/,
  );
});

test('getChanges filters Logbook by since and preserves the Inbox Dex-marker skip', async (t) => {
  const calls = stubAppleScript(t, (_command, args) => {
    const script = args[1];
    if (script.includes('Logbook')) {
      return {
        status: 0,
        stdout: [
          'things-old|||Old completion|||2026-07-13T08:59:59.000Z',
          'things-new|||New completion|||2026-07-13T09:00:00.000Z',
          'things-unknown|||Unknown completion|||not-a-date',
        ].join('\n'),
        stderr: '',
      };
    }
    if (script.includes('Inbox')) {
      return {
        status: 0,
        stdout: [
          'things-dex|||Dex-created|||dex-task-id: task-20260713-001',
          'things-inbound|||Inbox-created|||Captured on phone',
        ].join('\n'),
        stderr: '',
      };
    }
    throw new Error(`unexpected AppleScript: ${script}`);
  });
  const adapter = loadAdapter();

  const changes = await adapter.getChanges('2026-07-13T09:00:00.000Z', {});

  assert.equal(calls.length, 2);
  assert.ok(calls.every((call) => call.command === 'osascript'));
  assert.ok(calls.every((call) => call.args[0] === '-e' && call.args.length === 2));
  assert.match(calls[0].args[1], /if status of t is completed then/);
  assert.match(calls[0].args[1], /completedAt is greater than or equal to sinceDate/);
  assert.match(calls[0].args[1], /\(completion date of t as string\)/);
  assert.deepEqual(
    changes.map(({ id, action }) => ({ id, action })),
    [
      { id: 'things-new', action: 'completed' },
      { id: 'things-unknown', action: 'completed' },
      { id: 'things-inbound', action: 'created' },
    ],
  );
});
