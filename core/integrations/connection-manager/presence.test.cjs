'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const presence = require('./presence.cjs');

test.afterEach(() => presence.setPresenceProvider(null));

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

test('an injected presence provider is used by assertPresence', async () => {
  const calls = [];
  let hostDetections = 0;
  presence.setPresenceProvider({
    available: true,
    async verify(request) {
      calls.push(request);
      return true;
    },
  });
  try {
    await presence.assertPresence('linear:injected', 'access-token', {
      now: () => 1_000,
      detectHostBroker: async () => {
        hostDetections += 1;
        return { reachable: false, authenticated: false };
      },
    });
  } finally {
    presence.setPresenceProvider(null);
  }

  assert.deepEqual(calls, [{ connId: 'linear:injected', op: 'access-token' }]);
  assert.equal(hostDetections, 0);
});

test('an injected denying provider still refuses the operation', async () => {
  let prompts = 0;
  let hostDetections = 0;
  presence.setPresenceProvider({
    available: true,
    async verify() {
      prompts += 1;
      return false;
    },
  });

  await assert.rejects(
    presence.assertPresence('linear:injected-denied', 'connect', {
      detectHostBroker: async () => {
        hostDetections += 1;
        return { reachable: false, authenticated: false };
      },
    }),
    { code: 'DEX_CM_PRESENCE_REQUIRED', category: 'presence_required' }
  );
  assert.equal(prompts, 1);
  assert.equal(hostDetections, 0);
});

test('a malformed injected provider without available fails closed', async () => {
  let prompts = 0;
  let hostDetections = 0;
  presence.setPresenceProvider({
    async verify() {
      prompts += 1;
      return true;
    },
  });

  await assert.rejects(
    presence.assertPresence('linear:malformed-injected', 'access-token', {
      detectHostBroker: async () => {
        hostDetections += 1;
        return { reachable: false, authenticated: false };
      },
    }),
    { code: 'DEX_CM_PRESENCE_REQUIRED', category: 'presence_required' }
  );
  assert.equal(prompts, 0);
  assert.equal(hostDetections, 0);
});

test('clearing an injected provider restores command-based resolution', () => {
  const originalCommand = process.env.DEX_CM_PRESENCE_CMD;
  const injected = { available: true, verify: async () => true };
  process.env.DEX_CM_PRESENCE_CMD = `"${process.execPath}" -e "process.exit(0)"`;
  try {
    presence.setPresenceProvider(injected);
    assert.equal(presence.resolveProvider(), injected);

    presence.setPresenceProvider(null);
    assert.equal(presence.resolveProvider().kind, 'command');
  } finally {
    if (originalCommand === undefined) delete process.env.DEX_CM_PRESENCE_CMD;
    else process.env.DEX_CM_PRESENCE_CMD = originalCommand;
  }
});

test('malformed injections install a fail-closed unavailable sentinel', () => {
  const originalCommand = process.env.DEX_CM_PRESENCE_CMD;
  process.env.DEX_CM_PRESENCE_CMD = `"${process.execPath}" -e "process.exit(0)"`;
  try {
    for (const malformed of [
      { available: true },
      { available: false, verify: async () => true },
    ]) {
      presence.setPresenceProvider(malformed);
      assert.equal(presence.resolveProvider().available, false);
      assert.equal(presence.resolveProvider().kind, 'unavailable');
    }
  } finally {
    if (originalCommand === undefined) delete process.env.DEX_CM_PRESENCE_CMD;
    else process.env.DEX_CM_PRESENCE_CMD = originalCommand;
  }
});

test('full exports remain one-shot with an injected provider', async () => {
  let prompts = 0;
  presence.setPresenceProvider({
    available: true,
    async verify() {
      prompts += 1;
      return true;
    },
  });

  await presence.assertPresence('google:injected-full', 'full', { now: () => 1_000 });
  await presence.assertPresence('google:injected-full', 'full', { now: () => 1_000 });

  assert.equal(prompts, 2);
});

test('standalone CLI allows connect when no host, command, or injection exists', async () => {
  const originalCommand = process.env.DEX_CM_PRESENCE_CMD;
  delete process.env.DEX_CM_PRESENCE_CMD;
  presence.setPresenceProvider(null);
  try {
    const provider = await presence.resolveProvider({
      detectHostBroker: async () => ({ reachable: false, authenticated: false }),
    });
    assert.equal(provider.kind, 'standalone');
    assert.equal(provider.standalone, true);

    await presence.assertPresence('linear:standalone', 'connect', {
      detectHostBroker: async () => ({ reachable: false, authenticated: false }),
    });
  } finally {
    if (originalCommand === undefined) delete process.env.DEX_CM_PRESENCE_CMD;
    else process.env.DEX_CM_PRESENCE_CMD = originalCommand;
  }
});

test('reachable authenticated host broker keeps presence enforcement fail-closed', async () => {
  const originalCommand = process.env.DEX_CM_PRESENCE_CMD;
  let detections = 0;
  delete process.env.DEX_CM_PRESENCE_CMD;
  presence.setPresenceProvider(null);
  const detectHostBroker = async () => {
    detections += 1;
    return { reachable: true, authenticated: true };
  };
  try {
    const provider = await presence.resolveProvider({ detectHostBroker });
    assert.equal(provider.available, false);
    assert.equal(provider.kind, 'unavailable');

    await assert.rejects(
      presence.assertPresence('linear:desktop-hosted', 'connect', { detectHostBroker }),
      { code: 'DEX_CM_PRESENCE_REQUIRED', category: 'presence_required' }
    );
    assert.equal(detections, 2);
  } finally {
    if (originalCommand === undefined) delete process.env.DEX_CM_PRESENCE_CMD;
    else process.env.DEX_CM_PRESENCE_CMD = originalCommand;
  }
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

test('optional presence remains available under the Node test runner', async (t) => {
  const originalOptional = process.env.DEX_CM_PRESENCE_OPTIONAL;
  const provider = { available: false, verify: async () => true };
  t.mock.method(console, 'error', () => {});
  process.env.DEX_CM_PRESENCE_OPTIONAL = '1';
  try {
    await presence.assertPresence('linear:test-optional', 'access-token', { provider });
  } finally {
    if (originalOptional === undefined) delete process.env.DEX_CM_PRESENCE_OPTIONAL;
    else process.env.DEX_CM_PRESENCE_OPTIONAL = originalOptional;
  }
});

test('production fails closed when only the optional presence switch is set', async () => {
  const originalOptional = process.env.DEX_CM_PRESENCE_OPTIONAL;
  const originalTestContext = process.env.NODE_TEST_CONTEXT;
  const originalInsecureFlag = process.env.DEX_CM_ALLOW_INSECURE_PRESENCE;
  const provider = { available: false, verify: async () => true };
  process.env.DEX_CM_PRESENCE_OPTIONAL = '1';
  delete process.env.NODE_TEST_CONTEXT;
  delete process.env.DEX_CM_ALLOW_INSECURE_PRESENCE;
  try {
    await assert.rejects(
      presence.assertPresence('linear:production-optional-denied', 'access-token', { provider }),
      { code: 'DEX_CM_PRESENCE_REQUIRED', category: 'presence_required' }
    );
  } finally {
    if (originalOptional === undefined) delete process.env.DEX_CM_PRESENCE_OPTIONAL;
    else process.env.DEX_CM_PRESENCE_OPTIONAL = originalOptional;
    if (originalTestContext === undefined) delete process.env.NODE_TEST_CONTEXT;
    else process.env.NODE_TEST_CONTEXT = originalTestContext;
    if (originalInsecureFlag === undefined) delete process.env.DEX_CM_ALLOW_INSECURE_PRESENCE;
    else process.env.DEX_CM_ALLOW_INSECURE_PRESENCE = originalInsecureFlag;
  }
});

test('the explicit insecure build flag enables optional presence only for development', async (t) => {
  const originalOptional = process.env.DEX_CM_PRESENCE_OPTIONAL;
  const originalTestContext = process.env.NODE_TEST_CONTEXT;
  const originalInsecureFlag = process.env.DEX_CM_ALLOW_INSECURE_PRESENCE;
  const provider = { available: false, verify: async () => true };
  t.mock.method(console, 'error', () => {});
  process.env.DEX_CM_PRESENCE_OPTIONAL = '1';
  process.env.DEX_CM_ALLOW_INSECURE_PRESENCE = '1';
  delete process.env.NODE_TEST_CONTEXT;
  try {
    await presence.assertPresence('linear:development-optional', 'access-token', { provider });
  } finally {
    if (originalOptional === undefined) delete process.env.DEX_CM_PRESENCE_OPTIONAL;
    else process.env.DEX_CM_PRESENCE_OPTIONAL = originalOptional;
    if (originalTestContext === undefined) delete process.env.NODE_TEST_CONTEXT;
    else process.env.NODE_TEST_CONTEXT = originalTestContext;
    if (originalInsecureFlag === undefined) delete process.env.DEX_CM_ALLOW_INSECURE_PRESENCE;
    else process.env.DEX_CM_ALLOW_INSECURE_PRESENCE = originalInsecureFlag;
  }
});

test('full exports are one-shot while access-token grants stay cached for 60 seconds', async () => {
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
  await presence.assertPresence('linear:cached', 'full', { provider, now: () => clock });
  assert.equal(prompts, 3, 'a full refresh-token export must always require a fresh prompt');

  clock += 2;
  await presence.assertPresence('linear:cached', 'access-token', { provider, now: () => clock });
  assert.equal(prompts, 4, 'caller-controlled TTL environment must be ignored');
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

test('concurrent full exports each require their own presence prompt', async () => {
  const approvals = [];
  const provider = {
    available: true,
    verify() {
      return new Promise((resolve) => approvals.push(resolve));
    },
  };
  let firstApproved = false;
  let secondApproved = false;

  const first = presence
    .assertPresence('linear:concurrent-full', 'full', { provider })
    .then(() => {
      firstApproved = true;
    });
  const second = presence
    .assertPresence('linear:concurrent-full', 'full', { provider })
    .then(() => {
      secondApproved = true;
    });

  try {
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(approvals.length, 2);

    approvals[0](true);
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(firstApproved, true);
    assert.equal(secondApproved, false);

    approvals[1](true);
    await Promise.all([first, second]);
    assert.equal(secondApproved, true);
  } finally {
    for (const approve of approvals) approve(true);
    await Promise.allSettled([first, second]);
  }
});

test('concurrent checks are shared only for the same connection and operation', async () => {
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

  const access = presence.assertPresence('linear:concurrent-op-scope', 'access-token', { provider });
  const full = presence.assertPresence('linear:concurrent-op-scope', 'full', { provider });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(prompts, 2);
  approve(true);
  await Promise.all([access, full]);
});

test('the standalone command presence seam remains available without an injected provider', async () => {
  const originalCommand = process.env.DEX_CM_PRESENCE_CMD;
  let hostDetections = 0;
  const detectHostBroker = async () => {
    hostDetections += 1;
    return { reachable: true, authenticated: true };
  };
  try {
    presence.setPresenceProvider(null);
    process.env.DEX_CM_PRESENCE_CMD = `"${process.execPath}" -e "process.exit(0)"`;
    const provider = presence.resolveProvider({ detectHostBroker });
    assert.equal(provider.available, true);
    assert.equal(provider.kind, 'command');
    assert.equal(await provider.verify(), true);
    await presence.assertPresence('linear:command-provider', 'access-token', { detectHostBroker });
    assert.equal(hostDetections, 0);
  } finally {
    if (originalCommand === undefined) delete process.env.DEX_CM_PRESENCE_CMD;
    else process.env.DEX_CM_PRESENCE_CMD = originalCommand;
  }
});

test('ambiguous host broker state remains fail-closed', async () => {
  const originalCommand = process.env.DEX_CM_PRESENCE_CMD;
  delete process.env.DEX_CM_PRESENCE_CMD;
  try {
    const provider = await presence.resolveProvider({
      detectHostBroker: async () => ({ reachable: true, authenticated: false }),
    });
    assert.equal(provider.available, false);
    assert.match(provider.reason, /could not safely prove/i);
  } finally {
    if (originalCommand !== undefined) process.env.DEX_CM_PRESENCE_CMD = originalCommand;
  }
});
