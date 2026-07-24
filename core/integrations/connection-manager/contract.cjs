'use strict';

const CONTRACT_VERSION = '1.0.0';
const ENGINE_VERSION = '1.0.0';
const TOKEN_ENVELOPE_VERSION = 2;
const CONNECTION_STATUSES = Object.freeze([
  'connected',
  'expiring',
  'expired',
  'needs_reauth',
  'not_connected',
]);
const VERIFICATION_STATES = Object.freeze(['verified', 'unverified']);
const GET_TOKEN_EXIT_CODES = Object.freeze({
  ok: 0,
  not_connected: 2,
  needs_reauth: 3,
  error: 1,
});
const LOCK_PROTOCOL = Object.freeze({
  storeTimeoutMs: 10000,
  refreshTimeoutMs: 30000,
  unreadableStaleMs: 30000,
  hardStaleMs: 10 * 60 * 1000,
});

function buildConnectionsContract() {
  return {
    contract: 'dex.connections',
    version: CONTRACT_VERSION,
    engineVersion: ENGINE_VERSION,
    source: 'core/integrations/connection-manager/contract.cjs',
    schema: 'connections.schema.json',
    engine: {
      relativeRoot: 'core/integrations/connection-manager',
      manifest: 'connections-engine.manifest.json',
    },
    compatibility: {
      rule: 'Additive changes require a minor version. Breaking or removing any frozen field, value, invocation, or behavior requires a major version.',
      additive: 'minor',
      breaking: 'major',
    },
    ownership: {
      rule: 'Consumers are read-only and accessor-only. They MUST NOT write credential files or implement a writer. ALL mutations go through the connection-manager engine CLI.',
      consumerCapabilities: ['connect.cjs status --json', 'get-token.cjs <connection>'],
      mutationBoundary: 'core/integrations/connection-manager/connect.cjs',
    },
    cli: {
      getToken: {
        executable: 'get-token.cjs',
        invocation: ['node', 'get-token.cjs', '<connection>', '[--full | --access-token-only]'],
        connectionId: 'provider or provider:alias',
        modes: {
          defaultOAuth: {
            schema: '#/$defs/leastPrivilegeToken',
            output: '{access_token, expires_at}',
            leastPrivilege: true,
          },
          defaultClassB: {
            schema: '#/$defs/classBEnvelope',
            output: '{kind, baseUrl, headers, query}',
            note: 'Rendered request envelope; credentials may be embedded in headers, query, or baseUrl.',
          },
          full: {
            flag: '--full',
            schema: '#/$defs/fullToken',
            note: 'Full stored OAuth token. Explicit privileged mode.',
          },
          accessTokenOnly: {
            flag: '--access-token-only',
            schema: '#/$defs/accessTokenOnly',
            note: 'Raw OAuth bearer token or raw Class B secret. Explicit privileged mode.',
          },
        },
        exitCodes: GET_TOKEN_EXIT_CODES,
      },
      status: {
        executable: 'connect.cjs',
        invocation: ['node', 'connect.cjs', 'status', '--json'],
        schema: '#/$defs/statusOutput',
        statuses: CONNECTION_STATUSES,
        verificationStates: VERIFICATION_STATES,
      },
    },
    storage: {
      root: '{DEX_VAULT}/System/credentials',
      layout: {
        tokens: 'tokens/<connId with colon encoded as __>.json',
        ledger: 'ledger/<connection>.jsonl',
        registry: 'connections.json',
        oauthApps: 'oauth-apps.json',
        fallbackKey: '.dex-cm.key',
        gitignore: '.gitignore',
      },
      gitignoreGuard: {
        requiredRule: '*',
        exceptions: ['!.gitignore', '!README.md'],
      },
      tokenEnvelope: {
        schema: '#/$defs/tokenEnvelopeV2',
        fields: ['v', 'aad', 'iv', 'tag', 'data'],
        v: TOKEN_ENVELOPE_VERSION,
        aad: 'token:<connId>',
        encoding: 'iv, tag, and data are base64; AES-256-GCM binds aad',
      },
    },
    locks: {
      protocol: 'Exclusive lockfile creation (O_CREAT|O_EXCL); holder releases by unlink in finally; waiters never proceed unlocked.',
      fileShape: { pid: 'positive integer', createdAt: 'Unix epoch milliseconds' },
      store: '{credentialsRoot}/.dex-cm.lock',
      refresh: '{credentialsRoot}/.dex-cm.refresh-<connId with colon encoded as __>.lock',
      staleTakeover: {
        deadPid: 'immediate',
        unreadableLockfileOlderThanMs: LOCK_PROTOCOL.unreadableStaleMs,
        anyLockfileOlderThanMs: LOCK_PROTOCOL.hardStaleMs,
        method: 'unlink then re-race exclusive creation',
      },
      timeoutsMs: { store: LOCK_PROTOCOL.storeTimeoutMs, refresh: LOCK_PROTOCOL.refreshTimeoutMs },
    },
  };
}

function nullable(type) {
  return { type: [type, 'null'] };
}

function buildConnectionsSchema() {
  return {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    $id: 'https://heydex.ai/contracts/connections.schema.json',
    title: 'Dex connections consumer boundary',
    $defs: {
      leastPrivilegeToken: {
        type: 'object',
        additionalProperties: false,
        required: ['access_token', 'expires_at'],
        properties: {
          access_token: { type: 'string', minLength: 1 },
          expires_at: nullable('number'),
        },
      },
      classBEnvelope: {
        type: 'object',
        additionalProperties: false,
        required: ['kind', 'baseUrl', 'headers', 'query'],
        properties: {
          kind: { const: 'api_key' },
          baseUrl: nullable('string'),
          headers: { type: 'object', additionalProperties: { type: 'string' } },
          query: { type: 'object', additionalProperties: { type: 'string' } },
        },
      },
      fullToken: { type: 'object', minProperties: 1 },
      accessTokenOnly: { type: 'string' },
      verificationState: { enum: VERIFICATION_STATES },
      connectionStatus: { enum: CONNECTION_STATUSES },
      statusRow: {
        type: 'object',
        additionalProperties: false,
        required: [
          'service',
          'provider',
          'alias',
          'status',
          'expiresAt',
          'hasRefreshToken',
          'scopes',
          'lastRefreshedAt',
          'error',
          'verified',
          'verification',
          'lastVerifiedAt',
          'lastProbeAt',
        ],
        properties: {
          service: { type: 'string', minLength: 1 },
          provider: { type: 'string', minLength: 1 },
          alias: nullable('string'),
          status: { $ref: '#/$defs/connectionStatus' },
          expiresAt: nullable('number'),
          hasRefreshToken: { type: 'boolean' },
          scopes: { type: 'array', items: { type: 'string' } },
          lastRefreshedAt: nullable('string'),
          error: nullable('string'),
          message: { type: 'string' },
          verified: { type: 'boolean' },
          verification: { $ref: '#/$defs/verificationState' },
          lastVerifiedAt: nullable('string'),
          lastProbeAt: nullable('string'),
        },
      },
      registryNotice: {
        anyOf: [{ type: 'null' }, { type: 'object' }],
      },
      statusOutput: {
        type: 'object',
        additionalProperties: false,
        required: ['connections', 'registryNotice'],
        properties: {
          connections: { type: 'array', items: { $ref: '#/$defs/statusRow' } },
          registryNotice: { $ref: '#/$defs/registryNotice' },
        },
      },
      tokenEnvelopeV2: {
        type: 'object',
        additionalProperties: false,
        required: ['v', 'aad', 'iv', 'tag', 'data'],
        properties: {
          v: { const: TOKEN_ENVELOPE_VERSION },
          aad: { type: 'string', pattern: '^token:[A-Za-z0-9][A-Za-z0-9._-]*(?::[a-z0-9_-]+)?$' },
          iv: { type: 'string', contentEncoding: 'base64' },
          tag: { type: 'string', contentEncoding: 'base64' },
          data: { type: 'string', contentEncoding: 'base64' },
        },
      },
    },
  };
}

function fixtureStatus(status) {
  const connected = status !== 'not_connected';
  return {
    connections: [{
      service: `fixture-${status}`,
      provider: 'fixture',
      alias: null,
      status,
      expiresAt: ['expiring', 'expired'].includes(status) ? 1893456000000 : null,
      hasRefreshToken: status === 'expiring' || status === 'expired',
      scopes: connected ? ['read'] : [],
      lastRefreshedAt: connected ? '2030-01-01T00:00:00.000Z' : null,
      error: status === 'needs_reauth' ? 'invalid_grant' : null,
      verified: status === 'connected',
      verification: status === 'connected' ? 'verified' : 'unverified',
      lastVerifiedAt: status === 'connected' ? '2030-01-01T00:01:00.000Z' : null,
      lastProbeAt: status === 'connected' ? '2030-01-01T00:01:00.000Z' : null,
    }],
    registryNotice: null,
  };
}

function buildConnectionsFixtures() {
  return {
    'token.least-privilege.json': { access_token: 'FAKE-ACCESS-TOKEN', expires_at: 1893456000000 },
    'token.class-b-envelope.json': {
      kind: 'api_key',
      baseUrl: 'https://api.example.test',
      headers: { Authorization: 'FAKE-RENDERED-SECRET' },
      query: {},
    },
    'token.v2-envelope.json': {
      v: TOKEN_ENVELOPE_VERSION,
      aad: 'token:fixture',
      iv: 'MDEyMzQ1Njc4OWFi',
      tag: 'MDEyMzQ1Njc4OWFiY2RlZg==',
      data: 'RkFLRS1DSVBIRVJURVhU',
    },
    ...Object.fromEntries(CONNECTION_STATUSES.map((status) => [`status.${status}.json`, fixtureStatus(status)])),
  };
}

module.exports = {
  CONTRACT_VERSION,
  ENGINE_VERSION,
  TOKEN_ENVELOPE_VERSION,
  CONNECTION_STATUSES,
  VERIFICATION_STATES,
  GET_TOKEN_EXIT_CODES,
  LOCK_PROTOCOL,
  buildConnectionsContract,
  buildConnectionsSchema,
  buildConnectionsFixtures,
};
