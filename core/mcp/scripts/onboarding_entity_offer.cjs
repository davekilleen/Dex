#!/usr/bin/env node
'use strict';

const path = require('node:path');

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const {
  processEntityCreation,
} = require(path.join(
  REPO_ROOT,
  '.scripts/meeting-intel/lib/entity-creation.cjs',
));
const {
  acceptSuggestion,
  dismissSuggestion,
  listSuggestions,
  suppressSuggestion,
} = require(path.join(
  REPO_ROOT,
  '.scripts/meeting-intel/lib/suggestion-actions.cjs',
));

const MAX_ONBOARDING_SUGGESTIONS = 5;

function failure(code, message) {
  return { ok: false, error: { code, message } };
}

function prepare(payload) {
  const meetings = Array.isArray(payload.meetings) ? payload.meetings : [];
  const suppliedProfile = payload.profile;
  if (!suppliedProfile || typeof suppliedProfile !== 'object' || Array.isArray(suppliedProfile)) {
    return failure('invalid_profile', 'profile must be an object');
  }

  const profile = {
    ...suppliedProfile,
    entity_creation: { mode: 'suggest' },
  };
  const result = processEntityCreation(meetings, profile);
  const eligibleIds = new Set([
    ...result.suggested.map(item => item.id),
    ...result.companies_suggested.map(item => item.id),
  ]);
  const listed = listSuggestions();
  if (!Array.isArray(listed)) return listed;

  const suggestions = listed
    .filter(item => eligibleIds.has(item.id))
    .sort((left, right) => {
      const kindOrder = Number(left.kind === 'company') - Number(right.kind === 'company');
      if (kindOrder !== 0) return kindOrder;
      const leftMeetings = Number.parseInt(left.reason.match(/\d+/)?.[0] || '0', 10);
      const rightMeetings = Number.parseInt(right.reason.match(/\d+/)?.[0] || '0', 10);
      return rightMeetings - leftMeetings || left.name.localeCompare(right.name);
    })
    .slice(0, MAX_ONBOARDING_SUGGESTIONS);
  return { ok: true, suggestions };
}

function respond(payload) {
  const action = payload.action;
  if (!['yes', 'no', 'never'].includes(action)) {
    return failure('invalid_action', 'action must be yes, no, or never');
  }
  const ids = [...new Set(
    (Array.isArray(payload.suggestion_ids) ? payload.suggestion_ids : [])
      .filter(id => typeof id === 'string' && id),
  )];
  if (ids.length === 0 || ids.length > MAX_ONBOARDING_SUGGESTIONS) {
    return failure(
      'invalid_suggestion_ids',
      `suggestion_ids must contain between 1 and ${MAX_ONBOARDING_SUGGESTIONS} ids`,
    );
  }

  const actionFunction = {
    yes: acceptSuggestion,
    no: dismissSuggestion,
    never: suppressSuggestion,
  }[action];
  const expectedStatus = {
    yes: 'accepted',
    no: 'dismissed',
    never: 'suppressed',
  }[action];
  const results = ids.map(id => {
    const result = actionFunction(id);
    if (result?.ok === false) {
      return { id, status: 'failed', error: result.error };
    }
    return {
      id,
      status: expectedStatus,
      ...(result?.page_path ? { page_path: result.page_path } : {}),
      ...(typeof result?.created === 'boolean' ? { created: result.created } : {}),
      ...(typeof result?.existing === 'boolean' ? { existing: result.existing } : {}),
    };
  });
  return {
    ok: results.every(result => result.status !== 'failed'),
    action,
    results,
  };
}

function run(payload) {
  if (payload.command === 'prepare') return prepare(payload);
  if (payload.command === 'respond') return respond(payload);
  return failure('invalid_command', 'command must be prepare or respond');
}

let input = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  try {
    const parsed = JSON.parse(input || '{}');
    process.stdout.write(`${JSON.stringify(run(parsed))}\n`);
  } catch (error) {
    process.stdout.write(`${JSON.stringify(failure('bridge_failed', error.message))}\n`);
    process.exitCode = 1;
  }
});
