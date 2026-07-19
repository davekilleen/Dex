#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');

const OPERATIONS = new Set(['create', 'complete', 'get_changes']);
const SERVICE_NAME = /^[a-z][a-z0-9_-]*$/;
const ALIASES_PATH = path.join(__dirname, 'service-aliases.json');

function emit(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function parseAliasObject(source) {
  const payload = JSON.parse(source);
  if (!payload || Array.isArray(payload) || typeof payload !== 'object') {
    throw new Error('Task-sync service aliases must contain an object');
  }
  const keys = new Set();
  let offset = 0;
  const skipWhitespace = () => {
    while (/\s/.test(source[offset] || '')) offset += 1;
  };
  const readString = () => {
    skipWhitespace();
    if (source[offset] !== '"') throw new Error('Task-sync service aliases must map strings to strings');
    const start = offset;
    for (offset += 1; offset < source.length; offset += 1) {
      if (source[offset] === '\\') {
        offset += 1;
      } else if (source[offset] === '"') {
        offset += 1;
        return JSON.parse(source.slice(start, offset));
      }
    }
    throw new Error('Unterminated string in task-sync service aliases');
  };

  skipWhitespace();
  offset += 1; // JSON.parse already proved this is an object.
  skipWhitespace();
  while (source[offset] !== '}') {
    const key = readString();
    if (keys.has(key)) throw new Error(`Duplicate service alias: ${key}`);
    keys.add(key);
    skipWhitespace();
    if (source[offset] !== ':') throw new Error('Invalid task-sync service aliases');
    offset += 1;
    readString();
    skipWhitespace();
    if (source[offset] === ',') {
      offset += 1;
      continue;
    }
    if (source[offset] !== '}') throw new Error('Invalid task-sync service aliases');
  }
  return payload;
}

function loadServiceAliases(aliasesPath = ALIASES_PATH) {
  if (!fs.existsSync(aliasesPath)) return {};
  let payload;
  try {
    payload = parseAliasObject(fs.readFileSync(aliasesPath, 'utf8'));
  } catch (error) {
    throw new Error(`Invalid task-sync service aliases: ${error.message}`);
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
  const [, , firstArgument, secondArgument] = process.argv;
  const resolvingOnly = firstArgument === '--resolve-adapter';
  const service = resolvingOnly ? secondArgument : firstArgument;
  const operation = resolvingOnly ? undefined : secondArgument;
  const adapterService = resolveAdapterService(service);
  const adapterPath = path.join(__dirname, `${adapterService}.cjs`);
  if (path.dirname(adapterPath) !== __dirname || !fs.existsSync(adapterPath)) {
    throw new Error(
      `Adapter unavailable for requested service '${service}': expected '${adapterService}.cjs'`,
    );
  }
  if (resolvingOnly) {
    emit({ ok: true, requested_service: service, adapter_service: adapterService });
    return;
  }
  if (!OPERATIONS.has(operation)) {
    throw new Error(`Unsupported adapter operation: ${operation || '(missing)'}`);
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
