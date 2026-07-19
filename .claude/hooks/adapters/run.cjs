#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');

const OPERATIONS = new Set(['create', 'complete', 'get_changes']);
const SERVICE_NAME = /^[a-z][a-z0-9_-]*$/;
const ALIASES_PATH = path.join(__dirname, 'service-aliases.json');

function emit(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function loadServiceAliases(aliasesPath = ALIASES_PATH) {
  if (!fs.existsSync(aliasesPath)) return {};
  let payload;
  try {
    payload = JSON.parse(fs.readFileSync(aliasesPath, 'utf8'));
  } catch (error) {
    throw new Error(`Invalid task-sync service aliases: ${error.message}`);
  }
  if (!payload || Array.isArray(payload) || typeof payload !== 'object') {
    throw new Error('Task-sync service aliases must contain an object');
  }
  for (const [requested, adapter] of Object.entries(payload)) {
    if (!SERVICE_NAME.test(requested) || typeof adapter !== 'string' || !SERVICE_NAME.test(adapter)) {
      throw new Error(`Invalid adapter alias for service: ${requested}`);
    }
    if (requested === adapter) {
      throw new Error(`Self-referential adapter alias: ${requested}`);
    }
  }
  const chained = Object.values(payload).find((target) => Object.hasOwn(payload, target));
  if (chained) {
    throw new Error(`Task-sync service aliases must be one hop; chained or cyclic target: ${chained}`);
  }
  return payload;
}

function resolveAdapterService(service, aliases = loadServiceAliases()) {
  if (!service || !SERVICE_NAME.test(service)) {
    throw new Error('Invalid adapter service name');
  }
  return Object.hasOwn(aliases, service) ? aliases[service] : service;
}

async function main() {
  const [, , service, operation] = process.argv;
  const adapterService = resolveAdapterService(service);
  if (!OPERATIONS.has(operation)) {
    throw new Error(`Unsupported adapter operation: ${operation || '(missing)'}`);
  }

  const adapterPath = path.join(__dirname, `${adapterService}.cjs`);
  if (path.dirname(adapterPath) !== __dirname || !fs.existsSync(adapterPath)) {
    throw new Error(
      `Adapter unavailable for requested service '${service}': expected '${adapterService}.cjs'`,
    );
  }

  const input = fs.readFileSync(0, 'utf8').trim();
  if (!input) throw new Error('Adapter runner expected a JSON payload on stdin');
  const payload = JSON.parse(input);
  const config = payload && payload.config && typeof payload.config === 'object'
    ? payload.config
    : {};
  const args = payload ? payload.args : undefined;
  const adapter = require(adapterPath);

  let result;
  if (operation === 'create') {
    if (typeof adapter.toExternal !== 'function' || typeof adapter.create !== 'function') {
      throw new Error(`Adapter ${adapterService} does not export create and toExternal`);
    }
    result = await adapter.create(adapter.toExternal(args || {}, config), config);
  } else if (operation === 'complete') {
    if (typeof adapter.complete !== 'function') {
      throw new Error(`Adapter ${adapterService} does not export complete`);
    }
    result = await adapter.complete(args, config);
  } else {
    if (typeof adapter.getChanges !== 'function') {
      throw new Error(`Adapter ${adapterService} does not export getChanges`);
    }
    const changes = await adapter.getChanges(args, config);
    result = Array.isArray(changes)
      ? changes.filter((change) => change && ['created', 'completed'].includes(change.action))
      : [];
  }

  emit({ ok: true, result });
}

if (require.main === module) {
  main().catch((error) => {
    emit({ ok: false, error: error instanceof Error ? error.message : String(error) });
    process.exitCode = 1;
  });
}

module.exports = { loadServiceAliases, resolveAdapterService };
