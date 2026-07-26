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

test('unavailable provider fails closed even when the caller sets the former optional escape hatch', async () => {
  const originalOptional = process.env.DEX_CM_PRESENCE_OPTIONAL;
  const provider = { available: false, verify: async () => true };
  process.env.DEX_CM_PRESENCE_OPTIONAL = '1';
  try {
    await assert.rejects(
      presence.assertPresence('linear:unavailable-denied', 'access-token', { provider }),
      { code: 'DEX_CM_PRESENCE_REQUIRED', category: 'presence_required' }
    );
  } finally {
    if (originalOptional === undefined) delete process.env.DEX_CM_PRESENCE_OPTIONAL;
    else process.env.DEX_CM_PRESENCE_OPTIONAL = originalOptional;
  }
});

test('successful grants are cached only for the same connection and operation for 60 seconds', async () => {
  let clock = 10_000;
  let prompts = 0;
  const provider = {
    available: true,
    async verify() {
      prompts += 1;
      return true;
    },
  };
  process.env.DEX_CM_PRESENCE_TTL_MS = '999999999';
  await presence.assertPresence('linear:cached', 'access-token', { provider, now: () => clock });
  clock += 59_999;
  await presence.assertPresence('linear:cached', 'access-token', { provider, now: () => clock });
  assert.equal(prompts, 1);

  await presence.assertPresence('linear:cached', 'full', { provider, now: () => clock });
  assert.equal(prompts, 2, 'a grant for one raw-export shape must not approve another');

  clock += 2;
  await presence.assertPresence('linear:cached', 'access-token', { provider, now: () => clock });
  assert.equal(prompts, 3, 'caller-controlled TTL environment must be ignored');
  delete process.env.DEX_CM_PRESENCE_TTL_MS;
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
  const second = presence.assertPresence('linear:concurrent', 'access-token', { provider });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(prompts, 1);
  approve(true);
  await Promise.all([first, second]);
});

test('caller-controlled command environment cannot become a production presence provider', () => {
  const originalCommand = process.env.DEX_CM_PRESENCE_CMD;
  try {
    process.env.DEX_CM_PRESENCE_CMD = `"${process.execPath}" -e "process.exit(0)"`;
    const provider = presence.resolveProvider();
    assert.equal(provider.available, false);
    assert.match(provider.reason, /signed|os-bound|unavailable/i);
  } finally {
    if (originalCommand === undefined) delete process.env.DEX_CM_PRESENCE_CMD;
    else process.env.DEX_CM_PRESENCE_CMD = originalCommand;
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
