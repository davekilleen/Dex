const test = require('node:test');
const assert = require('node:assert/strict');

const ADAPTER_PATH = require.resolve('../adapters/trello.cjs');

function loadAdapter() {
  delete require.cache[ADAPTER_PATH];
  return require(ADAPTER_PATH);
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function stubFetch(t, implementation) {
  const originalFetch = global.fetch;
  const calls = [];
  global.fetch = async (requestUrl, options) => {
    calls.push({ url: new URL(requestUrl), options });
    return implementation(calls.at(-1), calls.length - 1);
  };
  t.after(() => {
    global.fetch = originalFetch;
  });
  return calls;
}

test('health performs only a read-only member identity request', async (t) => {
  const calls = stubFetch(t, () => jsonResponse({ id: 'member-opaque' }));
  const adapter = loadAdapter();

  assert.deepEqual(await adapter.health({ api_key: 'key', token: 'token' }), { healthy: true });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.method, 'GET');
  assert.equal(calls[0].url.pathname, '/1/members/me');
  assert.equal(calls[0].url.searchParams.get('fields'), 'id');
});

test('create uses configured list_mapping and embeds the Dex marker', async (t) => {
  const calls = stubFetch(t, ({ url, options }) => {
    if (url.pathname === '/1/cards' && options.method === 'POST') {
      return jsonResponse({ id: 'trello-card-opaque' });
    }
    if (url.pathname === '/1/boards/board-1/labels') return jsonResponse([]);
    throw new Error(`unexpected request: ${options.method} ${url.pathname}`);
  });
  const adapter = loadAdapter();
  const config = {
    api_key: 'key',
    token: 'token',
    default_board: 'board-1',
    list_mapping: { backlog: 'list-backlog-opaque' },
  };
  const external = adapter.toExternal({
    title: 'Prepare launch',
    context: 'Customer-facing release',
    task_id: 'task-20260713-002',
    status: 'n',
    priority: 'P1',
  }, config);

  const id = await adapter.create(external, config);

  assert.equal(id, 'trello-card-opaque');
  assert.equal(calls.some(({ url }) => url.pathname.endsWith('/lists')), false);
  const createCall = calls.find(({ url }) => url.pathname === '/1/cards');
  assert.equal(createCall.url.searchParams.get('idList'), 'list-backlog-opaque');
  assert.equal(
    createCall.url.searchParams.get('desc'),
    'Customer-facing release\n\n[dex:task-20260713-002]',
  );
});

test('an unknown status falls back to list discovery instead of configured backlog', async (t) => {
  const calls = stubFetch(t, ({ url, options }) => {
    if (url.pathname === '/1/boards/board-1/lists') {
      return jsonResponse([{ id: 'discovered-backlog', name: 'Backlog' }]);
    }
    if (url.pathname === '/1/cards' && options.method === 'POST') {
      return jsonResponse({ id: 'trello-card-unknown-status' });
    }
    throw new Error(`unexpected request: ${options.method} ${url.pathname}`);
  });
  const adapter = loadAdapter();

  await adapter.create(
    {
      name: 'Unknown status',
      desc: '',
      _dexStatus: 'unknown',
      _dexPriority: '',
      _dexTaskId: '',
    },
    {
      api_key: 'key',
      token: 'token',
      default_board: 'board-1',
      list_mapping: { backlog: 'configured-backlog' },
    },
  );

  assert.ok(calls.some(({ url }) => url.pathname.endsWith('/lists')));
  const createCall = calls.find(({ url }) => url.pathname === '/1/cards');
  assert.equal(createCall.url.searchParams.get('idList'), 'discovered-backlog');
});

test('getChanges skips createCard actions whose description has a Dex marker', async (t) => {
  stubFetch(t, ({ url }) => {
    assert.equal(url.pathname, '/1/boards/board-1/actions');
    return jsonResponse([
      {
        type: 'createCard',
        data: {
          card: { id: 'dex-card', name: 'Dex card', desc: '[dex:task-20260713-003]' },
          list: { name: 'Backlog' },
        },
      },
      {
        type: 'createCard',
        data: {
          card: { id: 'external-card', name: 'External card', desc: 'From Trello' },
          list: { name: 'Backlog' },
        },
      },
    ]);
  });
  const adapter = loadAdapter();

  const changes = await adapter.getChanges('2026-07-13T09:00:00.000Z', {
    api_key: 'key',
    token: 'token',
    default_board: 'board-1',
  });

  assert.deepEqual(changes, [
    {
      id: 'external-card',
      action: 'created',
      task: {
        name: 'External card',
        desc: 'From Trello',
        listName: 'Backlog',
        labels: [],
      },
    },
  ]);
});

test('getChanges recognizes a configured Done list whose name is custom', async (t) => {
  stubFetch(t, ({ url }) => {
    assert.equal(url.pathname, '/1/boards/board-1/actions');
    return jsonResponse([
      {
        type: 'updateCard',
        data: {
          card: { id: 'shipped-card', name: 'Shipped externally' },
          listAfter: { id: 'list-shipped', name: 'Shipped' },
        },
      },
    ]);
  });
  const adapter = loadAdapter();

  const changes = await adapter.getChanges('2026-07-13T09:00:00.000Z', {
    api_key: 'key',
    token: 'token',
    default_board: 'board-1',
    list_mapping: { done: 'list-shipped' },
  });

  assert.deepEqual(changes, [
    {
      id: 'shipped-card',
      action: 'completed',
      task: { name: 'Shipped externally' },
    },
  ]);
});

test('toDex leaves pillar resolution to the orchestrator', () => {
  const adapter = loadAdapter();

  const converted = adapter.toDex({
    id: 'external-card',
    name: 'External card',
    desc: 'Created in Trello',
    board: { name: 'Thought Leadership' },
    listName: 'In Progress',
    labels: [{ color: 'orange' }],
  });

  assert.deepEqual(converted, {
    title: 'External card',
    pillar: null,
    priority: 'P1',
    status: 's',
    context: 'Created in Trello',
    source: 'trello',
    external_id: 'external-card',
  });
});
