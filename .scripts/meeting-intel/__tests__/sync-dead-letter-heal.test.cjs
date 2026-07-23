'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  retryDeadLetteredEntityWork,
} = require('../sync-from-granola.cjs');

test('sync heal command requeues dead-lettered entity work', (t) => {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-sync-dead-letter-'));
  t.after(() => fs.rmSync(vault, { recursive: true, force: true }));
  const runtime = path.join(vault, 'System', '.dex');
  fs.mkdirSync(runtime, { recursive: true });
  const operation = {
    op: 'create',
    path: path.join(
      vault,
      '05-Areas',
      'People',
      'External',
      'Jane_Example.md',
    ),
    content: '# Jane Example\n',
    allowed_root: vault,
  };
  fs.writeFileSync(
    path.join(runtime, 'entity-dead-letter.jsonl'),
    `${JSON.stringify({
      dead_letter_id: 'example-dead-letter',
      batch_id: 'example-batch',
      scope: 'creation',
      meeting_id: 'meeting-1',
      meeting_ids: ['meeting-1'],
      op: operation,
    })}\n`,
  );

  const result = retryDeadLetteredEntityWork(vault);

  assert.equal(result.requeued, 1);
  const pending = JSON.parse(
    fs.readFileSync(path.join(runtime, 'entity-pending.json'), 'utf8'),
  );
  assert.deepEqual(pending.batches[0].ops, [operation]);
  assert.equal(
    fs.existsSync(path.join(runtime, 'entity-dead-letter.jsonl')),
    false,
  );
});
