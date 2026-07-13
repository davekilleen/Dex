#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');

const OPERATIONS = new Set(['create', 'complete', 'get_changes']);
const SERVICE_NAME = /^[a-z][a-z0-9_-]*$/;

function emit(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

async function main() {
  const [, , service, operation] = process.argv;
  if (!service || !SERVICE_NAME.test(service)) {
    throw new Error('Invalid adapter service name');
  }
  if (!OPERATIONS.has(operation)) {
    throw new Error(`Unsupported adapter operation: ${operation || '(missing)'}`);
  }

  const adapterPath = path.join(__dirname, `${service}.cjs`);
  if (path.dirname(adapterPath) !== __dirname || !fs.existsSync(adapterPath)) {
    throw new Error(`Adapter not found for service: ${service}`);
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
      throw new Error(`Adapter ${service} does not export create and toExternal`);
    }
    result = await adapter.create(adapter.toExternal(args || {}, config), config);
  } else if (operation === 'complete') {
    if (typeof adapter.complete !== 'function') {
      throw new Error(`Adapter ${service} does not export complete`);
    }
    result = await adapter.complete(args, config);
  } else {
    if (typeof adapter.getChanges !== 'function') {
      throw new Error(`Adapter ${service} does not export getChanges`);
    }
    const changes = await adapter.getChanges(args, config);
    result = Array.isArray(changes)
      ? changes.filter((change) => change && ['created', 'completed'].includes(change.action))
      : [];
  }

  emit({ ok: true, result });
}

main().catch((error) => {
  emit({ ok: false, error: error instanceof Error ? error.message : String(error) });
  process.exitCode = 1;
});
