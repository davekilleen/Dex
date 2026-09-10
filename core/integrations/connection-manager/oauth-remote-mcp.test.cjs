'use strict';
/**
 * A remote MCP server is a different shape of provider: it issues no client
 * secret, the client id does not exist until registration, and the token must
 * be bound to the resource or it is refused. None of that may loosen the rule
 * that every origin is fixed at review time.
 */
const test = require('node:test');
const assert = require('node:assert');

const pinned = require('./pinned-providers.cjs');
const oauth = require('./oauth-flow.cjs');

const WISPR = {
  id: 'wispr',
  authorizationUrl: 'https://mcp-auth.wisprflow.com/oauth2/authorize',
  tokenUrl: 'https://mcp-auth.wisprflow.com/oauth2/token',
  registrationUrl: 'https://mcp-auth.wisprflow.com/oauth2/register',
  resource: 'https://api.wisprflow.ai/connect/mcp',
  defaultScopes: ['openid', 'offline_access'],
  usePkce: true,
};

test('registration is pinned like every other origin', () => {
  assert.equal(
    pinned.assertPinnedOrigin('wispr', 'registration', 'https://mcp-auth.wisprflow.com/oauth2/register'),
    'https://mcp-auth.wisprflow.com',
  );
  assert.throws(
    () => pinned.assertPinnedOrigin('wispr', 'registration', 'https://evil.example/register'),
    /OriginUnpinned/,
    'dynamic registration decides who the client is, never where it may talk',
  );
});

test('the authorization request carries the resource it is for', () => {
  const { url } = oauth.buildAuthorizationUrl(WISPR, {
    clientId: 'client_TEST',
    redirectUri: 'http://127.0.0.1:8765/callback',
  });
  const params = new URL(url).searchParams;
  assert.equal(params.get('resource'), WISPR.resource);
  assert.equal(params.get('code_challenge_method'), 'S256');
});

test('a provider with no resource is unchanged', () => {
  const { url } = oauth.buildAuthorizationUrl(
    { ...WISPR, id: undefined, resource: undefined },
    { clientId: 'c', redirectUri: 'http://127.0.0.1:8765/callback' },
  );
  assert.equal(new URL(url).searchParams.get('resource'), null);
});

test('registration refuses a provider that does not offer it', async () => {
  await assert.rejects(
    () => oauth.registerDynamicClient({ id: 'wispr' }, { redirectUri: 'http://127.0.0.1:8765/callback' }),
    /does not support dynamic client registration/,
  );
});

test('registration asks for a public client and returns its id', async () => {
  const originalFetch = global.fetch;
  let sent = null;
  global.fetch = async (url, init) => {
    sent = { url, body: JSON.parse(init.body) };
    return { ok: true, status: 200, text: async () => JSON.stringify({ client_id: 'client_NEW' }) };
  };
  try {
    const registration = await oauth.registerDynamicClient(WISPR, {
      redirectUri: 'http://127.0.0.1:8765/callback',
    });
    assert.equal(registration.client_id, 'client_NEW');
    assert.equal(sent.body.token_endpoint_auth_method, 'none', 'a local install cannot keep a secret');
    assert.deepEqual(sent.body.grant_types, ['authorization_code', 'refresh_token']);
    assert.equal(sent.body.scope, 'openid offline_access');
  } finally {
    global.fetch = originalFetch;
  }
});

test('a registration response without a client id is refused', async () => {
  const originalFetch = global.fetch;
  global.fetch = async () => ({ ok: true, status: 200, text: async () => JSON.stringify({}) });
  try {
    await assert.rejects(
      () => oauth.registerDynamicClient(WISPR, { redirectUri: 'http://127.0.0.1:8765/callback' }),
      /no client_id/,
    );
  } finally {
    global.fetch = originalFetch;
  }
});
