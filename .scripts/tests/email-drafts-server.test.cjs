/**
 * HTTP tests for the email-drafts dashboard server.
 *
 * Spawns the real server against a throwaway data dir (EMAIL_DRAFTS_DATA_DIR)
 * on a test port, so the user's live drafts queue is never touched. Push
 * endpoints that shell out to PowerShell/Outlook are only exercised on their
 * validation paths (no recipient, nothing queued).
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const SERVER = path.join(__dirname, '..', 'email-drafts', 'server.cjs');
const PORT = 14747;
const BASE = `http://127.0.0.1:${PORT}`;

let child;
let dataDir;

function seedDrafts(drafts) {
  fs.mkdirSync(dataDir, { recursive: true });
  fs.writeFileSync(path.join(dataDir, 'drafts.json'), JSON.stringify(drafts, null, 2));
}

function readDrafts() {
  return JSON.parse(fs.readFileSync(path.join(dataDir, 'drafts.json'), 'utf8'));
}

test.before(async () => {
  dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-drafts-'));
  seedDrafts([
    { id: 'd1', to: 'jane@acme.com', cc: '', subject: 'Quote follow-up', body: 'Hi Jane', status: 'queued' },
    { id: 'd2', to: '', subject: 'Needs address', body: 'Hi', status: 'needs_email' },
  ]);

  child = spawn('node', [SERVER], {
    env: { ...process.env, EMAIL_DRAFTS_DATA_DIR: dataDir, EMAIL_DRAFTS_PORT: String(PORT) },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('server did not start')), 5000);
    child.stdout.on('data', (d) => {
      if (d.toString().includes('running at')) {
        clearTimeout(timer);
        resolve();
      }
    });
    child.on('exit', (code) => reject(new Error(`server exited early (${code})`)));
  });
});

test.after(() => {
  if (child) child.kill();
});

test('GET /api/drafts returns the seeded queue', async () => {
  const res = await fetch(`${BASE}/api/drafts`);
  assert.equal(res.status, 200);
  const drafts = await res.json();
  assert.deepEqual(drafts.map((d) => d.id), ['d1', 'd2']);
});

test('PUT edits only editable fields and persists', async () => {
  const res = await fetch(`${BASE}/api/drafts/d1`, {
    method: 'PUT',
    body: JSON.stringify({ subject: 'Updated subject', status: 'hacked', id: 'evil' }),
  });
  assert.equal(res.status, 200);
  const updated = await res.json();
  assert.equal(updated.subject, 'Updated subject');
  assert.equal(updated.id, 'd1');          // id not editable
  assert.equal(updated.status, 'queued');  // status not editable
  assert.equal(readDrafts()[0].subject, 'Updated subject');
});

test('PUT setting a recipient promotes needs_email to queued', async () => {
  const res = await fetch(`${BASE}/api/drafts/d2`, {
    method: 'PUT',
    body: JSON.stringify({ to: 'bob@globex.com' }),
  });
  assert.equal(res.status, 200);
  const updated = await res.json();
  assert.equal(updated.status, 'queued');
});

test('PUT unknown draft returns 404', async () => {
  const res = await fetch(`${BASE}/api/drafts/nope`, {
    method: 'PUT',
    body: JSON.stringify({ subject: 'x' }),
  });
  assert.equal(res.status, 404);
});

test('POST push without recipient returns 400', async () => {
  // Reset d2 to have no recipient again
  const drafts = readDrafts();
  drafts.find((d) => d.id === 'd2').to = '';
  seedDrafts(drafts);

  const res = await fetch(`${BASE}/api/drafts/d2/push`, { method: 'POST' });
  assert.equal(res.status, 400);
  const body = await res.json();
  assert.match(body.error, /No recipient/);
});

test('POST push-all with nothing queued is a no-op', async () => {
  const drafts = readDrafts().map((d) => ({ ...d, status: 'pushed' }));
  seedDrafts(drafts);

  const res = await fetch(`${BASE}/api/drafts/push-all`, { method: 'POST' });
  assert.equal(res.status, 200);
  assert.deepEqual(await res.json(), { pushed: 0, results: [] });
});

test('DELETE removes a draft; unknown id is 404', async () => {
  const res = await fetch(`${BASE}/api/drafts/d2`, { method: 'DELETE' });
  assert.equal(res.status, 200);
  assert.deepEqual(readDrafts().map((d) => d.id), ['d1']);

  const missing = await fetch(`${BASE}/api/drafts/d2`, { method: 'DELETE' });
  assert.equal(missing.status, 404);
});

test('serves the dashboard and blocks path traversal', async () => {
  const index = await fetch(`${BASE}/`);
  assert.equal(index.status, 200);
  assert.match(index.headers.get('content-type'), /text\/html/);

  const traversal = await fetch(`${BASE}/..%2f..%2fserver.cjs`);
  assert.notEqual(traversal.status, 200);
});

test('invalid JSON body is handled, not a crash', async () => {
  const res = await fetch(`${BASE}/api/drafts/d1`, { method: 'PUT', body: '{oops' });
  assert.equal(res.status, 500);
  const body = await res.json();
  assert.match(body.error, /Invalid JSON/);
});
