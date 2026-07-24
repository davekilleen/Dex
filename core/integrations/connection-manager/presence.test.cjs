'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const presence = require('./presence.cjs');

test('B1 requires presence only for privileged raw exports and first connect', () => {
  assert.equal(presence.requiresPresence('access-token'), true);
  assert.equal(presence.requiresPresence('full'), true);
  assert.equal(presence.requiresPresence('connect'), true);
  assert.equal(presence.requiresPresence('rendered'), false);
  assert.equal(presence.requiresPresence('get-token-default'), false);
  assert.equal(presence.requiresPresence('status'), false);
});

test('unprivileged operations return without consulting the provider', async () => {
  let prompts = 0;
  const provider = {
    available: true,
    async verify() {
      prompts += 1;
      return true;
    },
  };

  for (const op of ['rendered', 'get-token-default', 'status']) {
    await presence.assertPresence(`unprivileged-${op}`, op, { provider });
  }

  assert.equal(prompts, 0);
});

test('privileged operations require an approving provider', async () => {
  const calls = [];
  const provider = {
    available: true,
    async verify(request) {
      calls.push(request);
      return true;
    },
  };

  await presence.assertPresence('linear:approved', 'access-token', { provider, now: () => 1_000 });
  await presence.assertPresence('google:approved', 'full', { provider, now: () => 1_000 });

  assert.deepEqual(calls, [
    { connId: 'linear:approved', op: 'access-token' },
    { connId: 'google:approved', op: 'full' },
  ]);
});

test('provider denial throws the typed presence-required error', async () => {
  const provider = { available: true, verify: async () => false };

  await assert.rejects(
    presence.assertPresence('linear:denied', 'access-token', { provider }),
    (error) =>
      error.code === 'DEX_CM_PRESENCE_REQUIRED' &&
      error.category === 'presence_required' &&
      /presence/i.test(error.message)
  );
});

test('unavailable provider fails closed unless the explicit optional escape hatch is set', async (t) => {
  const originalOptional = process.env.DEX_CM_PRESENCE_OPTIONAL;
  const warnings = [];
  t.mock.method(console, 'error', (message) => warnings.push(message));
  const provider = { available: false, verify: async () => true };

  delete process.env.DEX_CM_PRESENCE_OPTIONAL;
  await assert.rejects(
    presence.assertPresence('linear:unavailable-denied', 'access-token', { provider }),
    { code: 'DEX_CM_PRESENCE_REQUIRED', category: 'presence_required' }
  );

  process.env.DEX_CM_PRESENCE_OPTIONAL = '1';
  await presence.assertPresence('linear:unavailable-optional', 'access-token', { provider });
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /not verified/i);

  if (originalOptional === undefined) delete process.env.DEX_CM_PRESENCE_OPTIONAL;
  else process.env.DEX_CM_PRESENCE_OPTIONAL = originalOptional;
});

test('optional mode never converts an explicit denial into approval', async () => {
  const originalOptional = process.env.DEX_CM_PRESENCE_OPTIONAL;
  process.env.DEX_CM_PRESENCE_OPTIONAL = '1';
  try {
    await assert.rejects(
      presence.assertPresence('linear:explicit-denial', 'access-token', {
        provider: { available: true, verify: async () => false },
      }),
      { code: 'DEX_CM_PRESENCE_REQUIRED', category: 'presence_required' }
    );
  } finally {
    if (originalOptional === undefined) delete process.env.DEX_CM_PRESENCE_OPTIONAL;
    else process.env.DEX_CM_PRESENCE_OPTIONAL = originalOptional;
  }
});

test('successful grants are cached per connection until the configured TTL expires', async () => {
  const originalTtl = process.env.DEX_CM_PRESENCE_TTL_MS;
  process.env.DEX_CM_PRESENCE_TTL_MS = '100';
  let clock = 10_000;
  let prompts = 0;
  const provider = {
    available: true,
    async verify() {
      prompts += 1;
      return true;
    },
  };
  try {
    await presence.assertPresence('linear:cached', 'access-token', { provider, now: () => clock });
    clock += 99;
    await presence.assertPresence('linear:cached', 'full', { provider, now: () => clock });
    assert.equal(prompts, 1);

    clock += 2;
    await presence.assertPresence('linear:cached', 'access-token', { provider, now: () => clock });
    assert.equal(prompts, 2);
  } finally {
    if (originalTtl === undefined) delete process.env.DEX_CM_PRESENCE_TTL_MS;
    else process.env.DEX_CM_PRESENCE_TTL_MS = originalTtl;
  }
});

test('concurrent privileged calls share one in-flight presence prompt', async () => {
  let prompts = 0;
  let approve;
  const approval = new Promise((resolve) => {
    approve = resolve;
  });
  const provider = {
    available: true,
    async verify() {
      prompts += 1;
      return approval;
    },
  };

  const first = presence.assertPresence('linear:concurrent', 'access-token', { provider });
  const second = presence.assertPresence('linear:concurrent', 'full', { provider });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(prompts, 1);
  approve(true);
  await Promise.all([first, second]);
});

test('command provider argv-splits without a shell and maps exit status to presence', async () => {
  const originalCommand = process.env.DEX_CM_PRESENCE_CMD;
  const originalTimeout = process.env.DEX_CM_PRESENCE_TIMEOUT_MS;
  try {
    process.env.DEX_CM_PRESENCE_CMD = `"${process.execPath}" -e "process.exit(0)"`;
    let provider = presence.resolveProvider();
    assert.equal(provider.available, true);
    assert.equal(await provider.verify({ connId: 'linear:command-ok', op: 'access-token' }), true);

    process.env.DEX_CM_PRESENCE_CMD = `"${process.execPath}" -e "process.exit(7)"`;
    provider = presence.resolveProvider();
    assert.equal(await provider.verify({ connId: 'linear:command-denied', op: 'access-token' }), false);

    process.env.DEX_CM_PRESENCE_TIMEOUT_MS = '20';
    process.env.DEX_CM_PRESENCE_CMD = `"${process.execPath}" -e "setTimeout(() => {}, 1000)"`;
    provider = presence.resolveProvider();
    assert.equal(await provider.verify({ connId: 'linear:command-timeout', op: 'access-token' }), false);
  } finally {
    if (originalCommand === undefined) delete process.env.DEX_CM_PRESENCE_CMD;
    else process.env.DEX_CM_PRESENCE_CMD = originalCommand;
    if (originalTimeout === undefined) delete process.env.DEX_CM_PRESENCE_TIMEOUT_MS;
    else process.env.DEX_CM_PRESENCE_TIMEOUT_MS = originalTimeout;
  }
});

test('the platform default is honestly unavailable when no signed helper is configured', () => {
  const originalCommand = process.env.DEX_CM_PRESENCE_CMD;
  delete process.env.DEX_CM_PRESENCE_CMD;
  try {
    const provider = presence.resolveProvider();
    assert.equal(provider.available, false);
    assert.match(provider.reason, /signed|biometric|unavailable/i);
  } finally {
    if (originalCommand !== undefined) process.env.DEX_CM_PRESENCE_CMD = originalCommand;
  }
});
