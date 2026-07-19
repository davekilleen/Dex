/**
 * Trello Task Sync Adapter
 *
 * Maps Dex tasks <-> Trello cards via the Trello REST API.
 * Trello's core concept: status = which LIST a card lives in (visual Kanban).
 * Moving a card to the "Done" list = completing it.
 *
 * Loaded dynamically by task-sync-bridge.cjs when trello is enabled in config.yaml.
 *
 * Mapping:
 *   Dex Pillar   -> Trello Board (or Label)
 *   Dex Project  -> Trello List
 *   Dex Task     -> Trello Card
 *   Dex Status   -> List position (Backlog / In Progress / Blocked / Done)
 *   Dex Priority -> Label color (red=P0, orange=P1, yellow=P2, green=P3)
 *   Dex task_id  -> Tracked via .sync-state.json
 *
 * Auth: API key + token from Trello Power-Up settings
 * Rate limit: 100 requests per 10 seconds
 */

const TRELLO_API = 'https://api.trello.com/1';

// ---------------------------------------------------------------------------
// Status mapping — Dex status codes -> Trello list names
// ---------------------------------------------------------------------------

const statusMap = {
  n: 'Backlog',
  s: 'In Progress',
  b: 'Blocked',
  d: 'Done',
};

// Reverse lookup: Trello list name -> Dex status code
const reverseStatusMap = {};
for (const [code, listName] of Object.entries(statusMap)) {
  reverseStatusMap[listName.toLowerCase()] = code;
}

// ---------------------------------------------------------------------------
// Priority mapping — Dex priority -> Trello label color
// ---------------------------------------------------------------------------

const priorityToColor = {
  P0: 'red',
  P1: 'orange',
  P2: 'yellow',
  P3: 'green',
};

const colorToPriority = {
  red: 'P0',
  orange: 'P1',
  yellow: 'P2',
  green: 'P3',
};

// ---------------------------------------------------------------------------
// Trello API helper — uses global fetch (Node 18+)
// ---------------------------------------------------------------------------

async function trelloFetch(endpoint, adapterConfig, options = {}) {
  const url = new URL(`${TRELLO_API}${endpoint}`);
  url.searchParams.set('key', adapterConfig.api_key);
  url.searchParams.set('token', adapterConfig.token);

  if (options.params) {
    for (const [k, v] of Object.entries(options.params)) {
      url.searchParams.set(k, v);
    }
  }

  const fetchOptions = {
    method: options.method || 'GET',
    headers: { 'Content-Type': 'application/json' },
  };

  if (options.body) {
    fetchOptions.body = JSON.stringify(options.body);
  }

  const response = await fetch(url.toString(), fetchOptions);

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Trello API ${response.status}: ${text}`);
  }

  return response.json();
}

// ---------------------------------------------------------------------------
// List ID resolution — find the list ID for a given status on a board
// ---------------------------------------------------------------------------

async function getListIdForStatus(boardId, status, adapterConfig) {
  const listMapping = adapterConfig.list_mapping || {};
  const dexStatusToMapKey = {
    n: 'backlog',
    s: 'in_progress',
    b: 'blocked',
    d: 'done',
  };
  const mapKey = dexStatusToMapKey[status];
  if (mapKey && listMapping[mapKey]) return listMapping[mapKey];

  const lists = await trelloFetch(`/boards/${boardId}/lists`, adapterConfig, {
    params: { filter: 'open' },
  });

  const targetName = statusMap[status] || 'Backlog';

  // Exact match first, then case-insensitive partial match
  const match =
    lists.find((l) => l.name === targetName) ||
    lists.find((l) => l.name.toLowerCase().includes(targetName.toLowerCase()));

  return match ? match.id : lists[0]?.id; // Fall back to first list
}

// ---------------------------------------------------------------------------
// Transform: Dex task -> Trello card format
// ---------------------------------------------------------------------------

function toExternal(dexTask, adapterConfig = {}) {
  return {
    name: dexTask.title,
    desc: dexTask.context || '',
    _dexStatus: dexTask.status || 'n',
    _dexPillar: dexTask.pillar || '',
    _dexPriority: dexTask.priority || 'P2',
    _dexTaskId: dexTask.task_id || '',
  };
}

// ---------------------------------------------------------------------------
// Transform: Trello card -> Dex task format
// ---------------------------------------------------------------------------

function toDex(trelloCard) {
  // Infer status from the card's list name
  const listName = (trelloCard.listName || trelloCard.list?.name || '').toLowerCase();
  let status = 'n';
  for (const [name, code] of Object.entries(reverseStatusMap)) {
    if (listName.includes(name)) {
      status = code;
      break;
    }
  }

  // Infer priority from label colors
  let priority = 'P2';
  if (trelloCard.labels && trelloCard.labels.length > 0) {
    for (const label of trelloCard.labels) {
      if (colorToPriority[label.color]) {
        priority = colorToPriority[label.color];
        break;
      }
    }
  }

  return {
    title: trelloCard.name || 'Untitled card',
    pillar: null,
    priority,
    status,
    context: trelloCard.desc || '',
    source: 'trello',
    external_id: trelloCard.id || '',
  };
}

// ---------------------------------------------------------------------------
// API: Create a card in Trello
// ---------------------------------------------------------------------------

async function create(externalTask, adapterConfig) {
  const boardId = adapterConfig.default_board;
  if (!boardId) {
    throw new Error('No default_board configured for Trello adapter');
  }

  // Find the right list for this task's status
  const listId = await getListIdForStatus(boardId, externalTask._dexStatus, adapterConfig);
  if (!listId) {
    throw new Error('Could not find a list on the Trello board');
  }

  const params = {
    name: externalTask.name,
    desc: `${externalTask.desc || ''}${
      externalTask._dexTaskId ? `\n\n[dex:${externalTask._dexTaskId}]` : ''
    }`,
    idList: listId,
    pos: 'top',
  };

  const card = await trelloFetch('/cards', adapterConfig, {
    method: 'POST',
    params,
  });

  // Add priority label if we can find it
  const color = priorityToColor[externalTask._dexPriority];
  if (color && card.id) {
    try {
      const labels = await trelloFetch(`/boards/${boardId}/labels`, adapterConfig);
      const label = labels.find((l) => l.color === color);
      if (label) {
        await trelloFetch(`/cards/${card.id}/idLabels`, adapterConfig, {
          method: 'POST',
          params: { value: label.id },
        });
      }
    } catch {
      // Non-critical — card was still created
    }
  }

  return card.id;
}

// ---------------------------------------------------------------------------
// API: Complete a card (move to Done list + archive)
// ---------------------------------------------------------------------------

async function complete(externalId, adapterConfig) {
  // Get the card to find its board
  const card = await trelloFetch(`/cards/${externalId}`, adapterConfig);
  const boardId = card.idBoard;

  // Find the Done list
  const doneListId = await getListIdForStatus(boardId, 'd', adapterConfig);
  if (doneListId) {
    // Move card to Done list
    await trelloFetch(`/cards/${externalId}`, adapterConfig, {
      method: 'PUT',
      params: { idList: doneListId },
    });
  }

  // Archive the card (closed = true in Trello)
  await trelloFetch(`/cards/${externalId}`, adapterConfig, {
    method: 'PUT',
    params: { closed: 'true' },
  });
}

// ---------------------------------------------------------------------------
// API: Get changes since last sync (via board activity feed)
// ---------------------------------------------------------------------------

async function getChanges(since, adapterConfig) {
  const boardId = adapterConfig.default_board;
  if (!boardId) return [];

  const sinceDate = new Date(since).toISOString();
  const changes = [];

  try {
    const actions = await trelloFetch(`/boards/${boardId}/actions`, adapterConfig, {
      params: {
        filter: 'createCard,updateCard',
        since: sinceDate,
        limit: '50',
      },
    });

    for (const action of actions) {
      if (action.type === 'createCard') {
        const description = action.data.card?.desc || '';
        if (description.includes('[dex:')) continue;

        changes.push({
          id: action.data.card?.id,
          action: 'created',
          task: {
            name: action.data.card?.name || '',
            desc: description,
            listName: action.data.list?.name || '',
            labels: [],
          },
        });
      } else if (action.type === 'updateCard' && action.data.listAfter) {
        // Card moved between lists — check if moved to Done
        const listName = (action.data.listAfter.name || '').toLowerCase();
        const configuredDoneListId = adapterConfig.list_mapping?.done;
        const movedToConfiguredDone =
          configuredDoneListId && action.data.listAfter.id === configuredDoneListId;
        if (
          movedToConfiguredDone ||
          listName.includes('done') ||
          listName.includes('complete')
        ) {
          changes.push({
            id: action.data.card?.id,
            action: 'completed',
            task: {
              name: action.data.card?.name || '',
            },
          });
        } else {
          changes.push({
            id: action.data.card?.id,
            action: 'updated',
            task: {
              name: action.data.card?.name || '',
              listName: action.data.listAfter.name || '',
            },
          });
        }
      }
    }
  } catch (err) {
    // Board activity may fail if access is restricted — degrade gracefully
    if (process.env.TASK_SYNC_DEBUG) {
      process.stderr.write(`[trello] getChanges error: ${err.message}\n`);
    }
  }

  return changes;
}

async function health(adapterConfig) {
  await trelloFetch('/members/me', adapterConfig, { params: { fields: 'id' } });
  return { healthy: true };
}

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

module.exports = {
  statusMap,
  toExternal,
  toDex,
  create,
  complete,
  getChanges,
  health,
};
