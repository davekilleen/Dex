'use strict';

const ORIGIN_KINDS = new Set(['authorization', 'token', 'refresh', 'api', 'verification']);

function deepFreeze(value) {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
  for (const child of Object.values(value)) deepFreeze(child);
  return Object.freeze(value);
}

const REVIEWED_PROVIDERS = deepFreeze({
  google: {
    authorizationOrigin: 'https://accounts.google.com',
    tokenOrigin: 'https://oauth2.googleapis.com',
    refreshOrigin: 'https://oauth2.googleapis.com',
    apiOrigins: ['https://www.googleapis.com'],
    verificationOrigin: 'https://www.googleapis.com',
    tenant: null,
  },
  linear: {
    apiOrigins: ['https://api.linear.app'],
    verificationOrigin: 'https://api.linear.app',
    tenant: null,
  },
});

let testPins = null;

class OriginUnpinnedError extends Error {
  constructor(providerId, kind, urlString) {
    super(`Refusing credential-bearing ${kind} request for '${providerId}': destination is not a reviewed HTTPS origin.`);
    this.name = 'OriginUnpinnedError';
    this.code = 'DEX_CM_ORIGIN_UNPINNED';
    this.exitCode = 1;
    this.providerId = providerId;
    this.kind = kind;
    this.url = urlString;
  }
}

function registry() {
  return testPins ? { ...REVIEWED_PROVIDERS, ...testPins } : REVIEWED_PROVIDERS;
}

function isVetted(providerId) {
  return Object.prototype.hasOwnProperty.call(registry(), providerId);
}

function pinnedOriginsFor(providerId) {
  return registry()[providerId] || null;
}

function tenantMatches(pin, kind, url) {
  if (!pin.tenant || (kind !== 'api' && kind !== 'verification')) return false;
  const suffix = String(pin.tenant.pinnedSuffix || '').toLowerCase();
  const labelPattern = new RegExp(pin.tenant.labelPattern);
  const suffixWithDot = `.${suffix}`;
  if (!url.hostname.endsWith(suffixWithDot)) return false;
  const label = url.hostname.slice(0, -suffixWithDot.length);
  return !label.includes('.') && labelPattern.test(label);
}

function assertPinnedOrigin(providerId, kind, urlString) {
  if (!ORIGIN_KINDS.has(kind)) throw new OriginUnpinnedError(providerId, kind, urlString);
  const pin = pinnedOriginsFor(providerId);
  let url;
  try {
    url = new URL(urlString);
  } catch {
    throw new OriginUnpinnedError(providerId, kind, urlString);
  }
  if (!pin || url.protocol !== 'https:') throw new OriginUnpinnedError(providerId, kind, urlString);

  const expected =
    kind === 'api'
      ? pin.apiOrigins
      : pin[`${kind}Origin`]
        ? [pin[`${kind}Origin`]]
        : [];
  if ((Array.isArray(expected) && expected.includes(url.origin)) || tenantMatches(pin, kind, url)) return url.origin;
  throw new OriginUnpinnedError(providerId, kind, urlString);
}

function __setPinnedForTest(map) {
  if (!process.env.NODE_TEST_CONTEXT) {
    throw new Error('__setPinnedForTest is available only under the Node test runner.');
  }
  testPins = map ? deepFreeze({ ...map }) : null;
}

module.exports = {
  isVetted,
  pinnedOriginsFor,
  assertPinnedOrigin,
  __setPinnedForTest,
  OriginUnpinnedError,
};
