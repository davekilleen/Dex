'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const REPO_ROOT = path.resolve(__dirname, '../../..');
const ROLLBACK_SKILL = fs.readFileSync(
  path.join(REPO_ROOT, '.claude', 'skills', 'dex-rollback', 'SKILL.md'),
  'utf-8',
);
const UPDATE_SKILL = fs.readFileSync(
  path.join(REPO_ROOT, '.claude', 'skills', 'dex-update', 'SKILL.md'),
  'utf-8',
);

const SKILLS = [
  ['dex-rollback', ROLLBACK_SKILL],
  ['dex-update', UPDATE_SKILL],
];

// These are user-owned data roots. Lifecycle renderers must never turn any of
// them into a target for a direct write, restore, copy, or delete instruction.
const USER_DATA_PATHS = [
  '00-Inbox/',
  '01-Quarter_Goals/',
  '02-Week_Priorities/',
  '03-Tasks/',
  '04-Projects/',
  '05-Areas/',
  '06-Resources/',
  '07-Archives/',
];

const RAW_OPERATION_PATTERNS = [
  ['raw Git command', /\bgit\s+(?:add|apply|archive|branch|checkout|cherry-pick|clean|clone|commit|fetch|filter-branch|init|log|merge|mv|pull|push|rebase|reset|restore|revert|rm|show|stash|switch|tag|worktree)\b/i],
  ['raw file mutation command', /\b(?:rm|rmdir|unlink|shred|mv|cp|rsync|touch|truncate|tee|dd)\s+[^\n]+/i],
  ['find -delete bulk removal', /\bfind\b[^\n]*\s-delete\b/i],
  ['in-place sed mutation', /\bsed\s+[^\n]*(?:-i(?:\b|[^\s]*)|--in-place(?:\b|=[^\s]+))/i],
  ['shell output redirection', /^(?!\s*>)[^\n]*>{1,2}\s*[^\s>]/im],
];

const MANUAL_RESTORE_PATTERNS = [
  ['folder-copy restore', /\bcopy\b[^\n]*(?:folder|folders|vault|06-Resources|(?:old|previous|current)\s+Dex)/i],
  ['manual folder restore', /^(?=[^\n]*\b(?:copy|restore|replace|move|transfer)\b)(?=[^\n]*\b(?:folder|folders|vault)\b)(?=[^\n]*\b(?:from|into|with)\b)[^\n]+$/im],
  ['cross-install copy source', /\bfrom\s+(?:the\s+)?(?:old|previous|current)\s+Dex\b/i],
  ['resources replacement', /\breplace\s+`?06-Resources(?:\/Dex_System\/?)?`?/i],
];

const RAW_WRITE_OR_DELETE_TARGET = /\b(?:rm|rmdir|unlink|shred|mv|cp|rsync|touch|truncate|tee|dd)\b|\b(?:copy|move|delete|remove|replace|restore|overwrite|rewrite|edit)\b|\bsed\b[^\n]*(?:-i|--in-place)|\bfind\b[^\n]*-delete|\bgit\s+(?:checkout|clean|merge|pull|reset|restore|revert|rm|switch)\b|^(?!\s*>)[^\n]*>{1,2}\s*[^\s>]/i;

const ROLLBACK_SERVICE_OPERATIONS = new Set([
  'read_lifecycle_state',
  'rewind_adoption_by_receipt',
]);
const UPDATE_SERVICE_OPERATIONS = new Set([
  // Read-only post-update canary module (core/health/post_update.py): it only
  // calls read_lifecycle_state + build_inventory_and_plan and writes its own
  // receipt under System/.dex/health/ — never vault content.
  'post_update',
  'build_inventory_and_plan',
  'build_and_preview_adoption',
  'execute_approved_adoption',
  'build_and_preview_conflict_resolution',
  'execute_approved_conflict_resolution',
  'build_and_preview_topology_migration',
  'execute_approved_topology_migration',
  'read_lifecycle_state',
  'deliver_latest_release',
  'build_and_preview_delivered_release',
  'execute_approved_delivered_release',
  'build_and_preview_mcp_registration',
  'execute_approved_mcp_registration',
  // Capsule journey (Lane H): read-only customization-migration operations and the
  // authority fields the skill must reproduce verbatim. The CLI create/abandon writes
  // are human-confirmed and capsule-scoped; they never touch vault user files.
  'customization_assessment',
  'customization_count',
  'customization_migration',
  'customization_migration_status',
  'migration_status_to_dict',
  'preview_sha256',
  'capsule_id',
  'file_count',
  'byte_count',
  'transaction_id',
  // Rebuild doorway: deterministic adapter operations and authority fields used by
  // the human-confirmed stage, verification, activation, status, and rewind journey.
  'read_customization_capsule_section',
  'read_customization_capsule_blob',
  'validate_regeneration_candidate',
  'approval_token',
  'acknowledgement_token',
  'rewind_available',
  'rewindable',
]);

function assertInOrder(document, needles, label) {
  let cursor = 0;
  for (const needle of needles) {
    const index = document.indexOf(needle, cursor);
    assert.notEqual(index, -1, `${label} is missing or misorders: ${needle}`);
    cursor = index + needle.length;
  }
}

function matchingGuard(document, patterns) {
  return patterns.find(([, pattern]) => pattern.test(document));
}

function serviceOperations(document) {
  return new Set(document.match(/\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/g) || []);
}

function assertOnlyServiceOperations(document, allowedOperations, label) {
  const unexpected = [...serviceOperations(document)]
    .filter((operation) => !allowedOperations.has(operation))
    .sort();
  assert.deepEqual(unexpected, [], `${label} contains unapproved lifecycle operations`);
}

test('sacred user-data roots are never direct mutation targets', () => {
  for (const [label, document] of SKILLS) {
    for (const userPath of USER_DATA_PATHS) {
      const targetedMutation = document
        .split('\n')
        .find((line) => line.includes(userPath) && RAW_WRITE_OR_DELETE_TARGET.test(line));
      assert.equal(
        targetedMutation,
        undefined,
        `${label} must never target sacred user data ${userPath} with a raw mutation: ${targetedMutation}`,
      );
    }
  }
});

test('pure renderer skills contain no raw destructive or vault mutation mechanism', () => {
  for (const [label, document] of SKILLS) {
    for (const [operation, pattern] of RAW_OPERATION_PATTERNS) {
      assert.doesNotMatch(document, pattern, `${label} must not contain ${operation}`);
    }
    assert.doesNotMatch(
      document,
      /```(?:bash|sh|shell)\b/i,
      `${label} is a renderer and must not embed executable shell instructions`,
    );
  }
});

test('raw-operation guard catches alternate destructive instructions without flagging prose', () => {
  for (const instruction of [
    'git reset --hard HEAD~1',
    'Use git revert when the receipt refuses.',
    'rm -r "$VAULT_ROOT"',
    'cp -r "$OLD_VAULT" "$VAULT_ROOT"',
    'sed -i.bak s/old/new/ "$VAULT_ROOT/file.md"',
    'printf content > "$VAULT_ROOT/custom.md"',
    'Run awk \'{print}\' input > "$VAULT_ROOT/custom.md" to write the vault.',
  ]) {
    assert.ok(matchingGuard(instruction, RAW_OPERATION_PATTERNS), `guard missed: ${instruction}`);
  }
  assert.equal(
    matchingGuard('> 00-Inbox/ remains untouched.', RAW_OPERATION_PATTERNS),
    undefined,
    'a Markdown blockquote is not a shell redirect',
  );
  assert.equal(
    matchingGuard('Never use Git history as a substitute for a lifecycle receipt.', RAW_OPERATION_PATTERNS),
    undefined,
    'source-control boundary prose is not a Git command',
  );
});

test('manual folder-copy and resources-replacement restore procedures cannot return', () => {
  for (const [label, document] of SKILLS) {
    const forbiddenRestore = matchingGuard(document, MANUAL_RESTORE_PATTERNS);
    assert.equal(
      forbiddenRestore,
      undefined,
      `${label} must not prescribe ${forbiddenRestore?.[0]}`,
    );
  }
});

test('manual-restore guard catches alternate cross-install folder procedures', () => {
  for (const instruction of [
    '3. Copy these folders from OLD Dex.',
    'Copy each folder from previous Dex into the current vault.',
    'Replace 06-Resources/Dex_System/ with the downloaded copy.',
    'Restore every folder from the downloaded Dex into the vault.',
    'Replace every folder in the vault with files from the downloaded release.',
  ]) {
    assert.ok(matchingGuard(instruction, MANUAL_RESTORE_PATTERNS), `guard missed: ${instruction}`);
  }
});

test('rollback routes its only mutation through receipt-backed lifecycle rewind', () => {
  assertOnlyServiceOperations(ROLLBACK_SKILL, ROLLBACK_SERVICE_OPERATIONS, 'dex-rollback');
  assert.match(ROLLBACK_SKILL, /Every rewind goes through `core\.lifecycle\.service` version 1\.0\.0\./);
  assert.match(
    ROLLBACK_SKILL,
    /The only mutation operation this skill may request is `rewind_adoption_by_receipt`\./,
  );
  assert.match(ROLLBACK_SKILL, /There is no manual fallback and no file-by-file workaround\./);
  assert.match(ROLLBACK_SKILL, /The lifecycle service owns the mutation\./);

  assertInOrder(ROLLBACK_SKILL, [
    '1. Ask `read_lifecycle_state`',
    '4. Show the receipt’s transaction identifier and complete file list.',
    '5. Ask for explicit confirmation of that exact adoption and file list.',
    '6. Pass the unchanged adoption receipt and its exact acknowledgement token to `rewind_adoption_by_receipt`.',
    '7. Ask `read_lifecycle_state` again',
  ], 'rollback lifecycle route');
});

test('rollback boundaries preserve user data and refuse post-adoption drift', () => {
  assert.match(ROLLBACK_SKILL, /Never perform or recommend raw vault file operations\./);
  assert.match(ROLLBACK_SKILL, /Never use source-control history as a substitute for a lifecycle receipt\./);
  assert.match(
    ROLLBACK_SKILL,
    /Never overwrite a file that changed after adoption; render the refusal and route the decision back to the user\./,
  );
  assert.match(
    ROLLBACK_SKILL,
    /leave later user changes untouched by refusing if receipt-owned files drifted/,
  );
  assert.match(
    ROLLBACK_SKILL,
    /If the snapshot has aged out, a file changed after adoption,[\s\S]*stop\. Explain that no files were changed\./,
  );
  assert.match(ROLLBACK_SKILL, /restore the exact pre-adoption bytes for files that existed/);
  assert.match(ROLLBACK_SKILL, /remove only files that this receipt proves the adoption created/);
});

test('update mutation follows the immutable preview, approval, execute service route', () => {
  assertOnlyServiceOperations(UPDATE_SKILL, UPDATE_SERVICE_OPERATIONS, 'dex-update');
  assert.match(
    UPDATE_SKILL,
    /Every lifecycle operation goes through `core\.lifecycle\.service` version 1\.5\.0\./,
  );
  assert.match(UPDATE_SKILL, /Execution requires an explicit yes to that exact preview\./);
  // execute is gated on an UNCHANGED preview + token for BOTH the adoption route and the
  // conflict-resolution route (the #205 keep-both/take-theirs branch) — assert both.
  assert.match(UPDATE_SKILL, /Pass unchanged adoption previews and tokens to `execute_approved_adoption`/);
  assert.match(UPDATE_SKILL, /unchanged resolution previews and tokens to `execute_approved_conflict_resolution`/);
  assert.match(UPDATE_SKILL, /ask `deliver_latest_release`\s+through `core\.lifecycle\.service`/);
  assert.match(UPDATE_SKILL, /ask\s+`build_and_preview_delivered_release` through `core\.lifecycle\.service`/);
  assert.match(UPDATE_SKILL, /`execute_approved_delivered_release` with the same preview and approval token/);
  assert.match(UPDATE_SKILL, /Only after a fresh explicit yes, pass the unchanged preview and approval token to `execute_approved_mcp_registration`/);
  assert.match(UPDATE_SKILL, /The lifecycle service owns every mutation\./);

  assertInOrder(UPDATE_SKILL, [
    '1. Ask `build_and_preview_topology_migration`',
    '3. Ask `build_inventory_and_plan`',
    '5. For safe `adopt` items, ask `build_and_preview_adoption`',
    '7. Show every proposed file from each preview. Execution requires an explicit yes to that exact preview.',
    '8. Pass unchanged adoption previews and tokens to `execute_approved_adoption`',
    '9. Ask `read_lifecycle_state`',
  ], 'update preview-approval-execute route');
});

test('update explicitly forbids raw vault writes and leaves refused content untouched', () => {
  assert.match(
    UPDATE_SKILL,
    /it never edits, copies, renames, deletes, or merges vault files itself\./i,
  );
  assert.match(UPDATE_SKILL, /Never perform a raw vault write\./);
  assert.match(UPDATE_SKILL, /Never instruct the user to move files around as part of an update\./);
  assert.match(UPDATE_SKILL, /Do not fall back to direct file operations, Git mutation, an update script/);
  assert.match(
    UPDATE_SKILL,
    /If the service reports UNKNOWN, conflict, changed evidence, an unsafe path, or a rejected transaction, stop\.[\s\S]*leave the vault untouched\./,
  );
  assert.match(UPDATE_SKILL, /Your own content was not part of the write set\./);
});
