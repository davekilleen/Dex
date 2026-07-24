'use strict';
/**
 * Connection Manager — local-first OAuth + token management for Dex.
 * Catalog-hybrid: provider config from Nango's open-source catalog (@nangohq/providers),
 * runtime + on-device encrypted token store owned by Dex. No Docker, no relay, no cloud.
 *
 */

const catalog = require('./catalog.cjs');
const store = require('./token-store.cjs');
const oauth = require('./oauth-flow.cjs');
const health = require('./health.cjs');

module.exports = {
  ...catalog,
  ...oauth,
  // token store
  saveToken: store.saveToken,
  loadToken: store.loadToken,
  deleteToken: store.deleteToken,
  listConnections: store.listConnections,
  getOAuthApp: store.getOAuthApp,
  credentialsDir: store.credentialsDir,
  // health / refresh
  connectionHealth: health.connectionHealth,
  allConnectionsHealth: health.allConnectionsHealth,
  ensureFreshToken: health.ensureFreshToken,
  probeConnection: health.probeConnection,
  probeConnections: health.probeConnections,
};
