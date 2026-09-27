'use strict';

/**
 * Meeting-intel entry point for the shared Granola locator.
 *
 * Installers should call the shared module:
 *   python3 -m core.integrations.granola_paths --json
 *   node core/integrations/granola_paths.cjs --json
 *
 * This file re-exports that locator so meeting-intel scripts can require()
 * a neighbor of granola-api-key.cjs.
 */

module.exports = require('../../../core/integrations/granola_paths.cjs');
