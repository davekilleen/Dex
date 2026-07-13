const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');

const ADAPTER_PATH = require.resolve('../adapters/todoist.cjs');

function loadAdapter() {
  delete require.cache[ADAPTER_PATH];
  return require(ADAPTER_PATH);
}

async function startStub(t, handler) {
  const server = http.createServer(handler);
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const address = server.address();
  return `http://127.0.0.1:${address.port}/api/v1`;
}

async function readJson(request) {
  let body = '';
  for await (const chunk of request) body += chunk;
  return body ? JSON.parse(body) : null;
}

function json(response, status, payload, headers = {}) {
  response.writeHead(status, { 'Content-Type': 'application/json', ...headers });
  response.end(JSON.stringify(payload));
}

test('create embeds the Dex marker and resolves project, priority, and due date', async (t) => {
  let postedTask = null;
  const apiBase = await startStub(t, async (request, response) => {
    assert.equal(request.headers.authorization, 'Bearer test-token');
    if (request.method === 'GET' && request.url === '/api/v1/projects') {
      json(response, 200, {
        results: [{ id: 'proj_opaque_A9', name: 'Delivery' }],
        next_cursor: null,
      });
      return;
    }
    if (request.method === 'POST' && request.url === '/api/v1/tasks') {
      postedTask = await readJson(request);
      json(response, 200, { id: 'task_opaque_Z7' });
      return;
    }
    json(response, 404, { error: 'unexpected route' });
  });
  const adapter = loadAdapter();
  const config = {
    api_key: 'test-token',
    api_base: apiBase,
    project: 'Inbox fallback',
    pillar_map: { delivery: 'Delivery' },
  };
  const payload = adapter.toExternal(
    {
      title: 'Publish release notes',
      task_id: 'task-20260712-001',
      pillar: 'delivery',
      priority: 'P0',
      context: 'Keep the summary concise.',
      due: '2026-07-18',
    },
    config,
  );

  const externalId = await adapter.create(payload, config);

  assert.equal(externalId, 'task_opaque_Z7');
  assert.deepEqual(postedTask, {
    content: 'Publish release notes',
    description: 'Keep the summary concise.\n[dex:task-20260712-001]',
    priority: 4,
    project_id: 'proj_opaque_A9',
    due_string: '2026-07-18',
  });
});

test('toExternal preserves the locked P0 through P3 priority mapping', () => {
  const adapter = loadAdapter();
  assert.deepEqual(
    ['P0', 'P1', 'P2', 'P3'].map((priority) =>
      adapter.toExternal({ title: priority, priority }, {}).priority,
    ),
    [4, 3, 2, 1],
  );
});

test('complete closes an opaque task ID instead of deleting it', async (t) => {
  const requests = [];
  const apiBase = await startStub(t, async (request, response) => {
    requests.push({ method: request.method, url: request.url, body: await readJson(request) });
    json(response, 200, null);
  });
  const adapter = loadAdapter();

  await adapter.complete('6XGgmFVcrG5RRjVr', {
    api_key: 'test-token',
    api_base: apiBase,
  });

  assert.deepEqual(requests, [
    {
      method: 'POST',
      url: '/api/v1/tasks/6XGgmFVcrG5RRjVr/close',
      body: null,
    },
  ]);
});

test('getChanges filters by since, skips Dex markers, and returns completed events', async (t) => {
  const since = '2026-07-12T09:00:00.000Z';
  let completedQuery = null;
  const apiBase = await startStub(t, (request, response) => {
    const requestUrl = new URL(request.url, 'http://stub.test');
    if (requestUrl.pathname === '/api/v1/projects') {
      json(response, 200, {
        results: [{ id: 'project_A', name: 'External Inbox' }],
        next_cursor: null,
      });
      return;
    }
    if (requestUrl.pathname === '/api/v1/tasks') {
      json(response, 200, {
        results: [
          {
            id: 'older_A',
            content: 'Older task',
            created_at: '2026-07-12T08:59:59.000Z',
            description: '',
          },
          {
            id: 'dex_A',
            content: 'Dex task',
            created_at: '2026-07-12T09:01:00.000Z',
            description: '[dex:task-20260712-003]',
          },
          {
            id: 'external_A',
            content: 'External task',
            created_at: '2026-07-12T09:02:00.000Z',
            description: 'Created on mobile',
            project_id: 'project_A',
            due: { date: '2026-07-20' },
          },
        ],
        next_cursor: null,
      });
      return;
    }
    if (requestUrl.pathname === '/api/v1/tasks/completed/by_completion_date') {
      completedQuery = requestUrl.searchParams;
      json(response, 200, {
        items: [
          {
            id: 'completed_A',
            content: 'Finished externally',
            completed_at: '2026-07-12T09:03:00.000Z',
            project_id: 'project_A',
          },
        ],
        next_cursor: null,
      });
      return;
    }
    json(response, 404, { error: 'unexpected route' });
  });
  const adapter = loadAdapter();

  const changes = await adapter.getChanges(since, {
    api_key: 'test-token',
    api_base: apiBase,
  });

  assert.deepEqual(
    changes.map(({ id, action }) => ({ id, action })),
    [
      { id: 'external_A', action: 'created' },
      { id: 'completed_A', action: 'completed' },
    ],
  );
  assert.deepEqual(changes[0].task, {
    title: 'External task',
    external_id: 'external_A',
    project: 'External Inbox',
    list: null,
    due: '2026-07-20',
    completed_at: null,
  });
  assert.equal(changes[1].task.external_id, 'completed_A');
  assert.equal(changes[1].task.completed_at, '2026-07-12T09:03:00.000Z');
  assert.equal(completedQuery.get('since'), since);
  assert.ok(Date.parse(completedQuery.get('until')) >= Date.parse(since));
});

test('429 responses honor Retry-After and retry without changing opaque IDs', async (t) => {
  let attempts = 0;
  const apiBase = await startStub(t, async (request, response) => {
    assert.equal(request.method, 'POST');
    assert.equal(request.url, '/api/v1/tasks');
    await readJson(request);
    attempts += 1;
    if (attempts === 1) {
      json(response, 429, { error: 'rate limited' }, { 'Retry-After': '0' });
      return;
    }
    json(response, 200, { id: 'opaque_retry_A' });
  });
  const adapter = loadAdapter();
  const config = { api_key: 'test-token', api_base: apiBase };

  const id = await adapter.create(
    adapter.toExternal({ title: 'Retry me', task_id: 'task-20260712-009' }, config),
    config,
  );

  assert.equal(id, 'opaque_retry_A');
  assert.equal(attempts, 2);
});

test('toDex returns raw external fields without pillar inference', () => {
  const adapter = loadAdapter();
  const converted = adapter.toDex({
    id: 'opaque_A',
    content: 'External title',
    _project_name: 'External Inbox',
    due: { string: 'next Monday' },
    completed_at: null,
  });

  assert.deepEqual(converted, {
    title: 'External title',
    external_id: 'opaque_A',
    project: 'External Inbox',
    list: null,
    due: 'next Monday',
    completed_at: null,
  });
  assert.equal(Object.hasOwn(converted, 'pillar'), false);
});

test('pagination stops before requesting a repeated cursor', async (t) => {
  const originalFetch = global.fetch;
  t.after(() => {
    global.fetch = originalFetch;
  });
  const taskRequests = [];
  global.fetch = async (requestUrl) => {
    const url = new URL(requestUrl);
    if (url.pathname.endsWith('/projects')) {
      return new Response(JSON.stringify({ results: [], next_cursor: null }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (url.pathname.endsWith('/tasks')) {
      taskRequests.push(url.searchParams.get('cursor'));
      if (taskRequests.length > 2) throw new Error('requested a repeated cursor');
      return new Response(JSON.stringify({ results: [], next_cursor: 'same-cursor' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (url.pathname.endsWith('/tasks/completed/by_completion_date')) {
      return new Response(JSON.stringify({ items: [], next_cursor: null }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    throw new Error(`unexpected URL: ${url}`);
  };
  const adapter = loadAdapter();

  const changes = await adapter.getChanges('2026-07-12T09:00:00.000Z', {
    api_key: 'test-token',
    api_base: 'https://stub.invalid/api/v1',
  });

  assert.deepEqual(changes, []);
  assert.deepEqual(taskRequests, [null, 'same-cursor']);
});

test('completed-task history is split into API-safe time windows', async (t) => {
  const originalFetch = global.fetch;
  t.after(() => {
    global.fetch = originalFetch;
  });
  const completionWindows = [];
  global.fetch = async (requestUrl) => {
    const url = new URL(requestUrl);
    if (url.pathname.endsWith('/projects') || url.pathname.endsWith('/tasks')) {
      return new Response(JSON.stringify({ results: [], next_cursor: null }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    if (url.pathname.endsWith('/tasks/completed/by_completion_date')) {
      completionWindows.push({
        since: url.searchParams.get('since'),
        until: url.searchParams.get('until'),
      });
      return new Response(JSON.stringify({ items: [], next_cursor: null }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    }
    throw new Error(`unexpected URL: ${url}`);
  };
  const adapter = loadAdapter();
  const since = new Date(Date.now() - 200 * 24 * 60 * 60 * 1_000).toISOString();

  await adapter.getChanges(since, {
    api_key: 'test-token',
    api_base: 'https://history-stub.invalid/api/v1',
  });

  assert.ok(completionWindows.length >= 3);
  assert.equal(completionWindows[0].since, since);
  for (let index = 0; index < completionWindows.length; index += 1) {
    const window = completionWindows[index];
    assert.ok(Date.parse(window.until) - Date.parse(window.since) <= 89 * 24 * 60 * 60 * 1_000);
    if (index > 0) assert.equal(window.since, completionWindows[index - 1].until);
  }
});
