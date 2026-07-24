#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { readJson, validateAgainstSchema } from './connections-contract-validation.mjs';

function flags(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 2) out[argv[i].replace(/^--/, '')] = argv[i + 1];
  return out;
}

const args = flags(process.argv.slice(2));
if (!args.contract) throw new Error('missing --contract');
if (!process.env.DEX_VAULT) throw new Error('DEX_VAULT is required');

const contract = readJson(args.contract);
const schemaPath = args.schema || path.join(path.dirname(args.contract), contract.schema);
const schema = readJson(schemaPath);
if (contract.contract !== 'dex.connections') throw new Error('foreign contract is not dex.connections');
if (!contract.ownership.rule.includes('ALL mutations go through')) throw new Error('contract lacks the engine-only mutation rule');
const engineRoot = args['engine-root'] || path.resolve(path.dirname(args.contract), '../../..', contract.engine.relativeRoot);
const connection = args.connection || 'linear';

function invoke(executable, cliArgs) {
  const result = spawnSync(process.execPath, [path.join(engineRoot, executable), ...cliArgs], {
    env: process.env,
    encoding: 'utf8',
  });
  if (result.status !== contract.cli.getToken.exitCodes.ok) {
    throw new Error(`${executable} failed (${result.status}): ${result.stderr}`);
  }
  return result.stdout;
}

const status = JSON.parse(invoke(contract.cli.status.executable, ['status', '--json']));
validateAgainstSchema(status, schema.$defs.statusOutput, schema);
const row = status.connections.find((candidate) => candidate.service === connection);
if (!row) throw new Error(`status did not include ${connection}`);

const rendered = JSON.parse(invoke(contract.cli.getToken.executable, [connection]));
validateAgainstSchema(rendered, schema.$defs.classBEnvelope, schema);
if (rendered.kind !== 'api_key') throw new Error('expected a Class B rendered envelope');

fs.accessSync(process.env.DEX_VAULT, fs.constants.R_OK);
console.log(`connections consumer smoke passed (contract ${contract.version}, ${connection})`);
