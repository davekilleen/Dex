/**
 * Todoist task-sync adapter for the unified API v1.
 *
 * State and loop prevention belong to the Python orchestrator. The Dex marker
 * in task descriptions is retained as a cheap second line of defence.
 */

const DEFAULT_API_BASE = 'https://api.todoist.com/api/v1';
const { setTimeout: sleep } = require('node:timers/promises');
const REQUEST_TIMEOUT_MS = 15_000;
const MAX_RETRIES = 3;
const DEFAULT_RETRY_DELAY_MS = 2_000;
const COMPLETION_WINDOW_MS = 89 * 24 * 60 * 60 * 1_000;
const DEX_ID_PATTERN = /\[dex:(task-\d{8}-\d{3})\]/;
const DEX_TO_TODOIST_PRIORITY = { P0: 4, P1: 3, P2: 2, P3: 1 };

const projectCache = new Map();

function apiBase(adapterConfig) {
  return String(adapterConfig.api_base || DEFAULT_API_BASE).replace(/\/$/, '');
}

function embedDexId(description, taskId) {
  const current = description || '';
  if (!taskId) return current;
  const marker = `[dex:${taskId}]`;
  if (current.includes(marker)) return current;
  return current ? `${current}\n${marker}` : marker;
}

function extractDexId(description) {
  const match = String(description || '').match(DEX_ID_PATTERN);
  return match ? match[1] : null;
}

function retryDelay(response, retryCount) {
  const value = response.headers.get('Retry-After');
  if (value !== null) {
    const seconds = Number(value);
    if (Number.isFinite(seconds) && seconds >= 0) return seconds * 1_000;
    const retryAt = Date.parse(value);
    if (Number.isFinite(retryAt)) return Math.max(0, retryAt - Date.now());
  }
  return DEFAULT_RETRY_DELAY_MS * (retryCount + 1);
}

async function apiRequest(endpoint, adapterConfig, options = {}, retryCount = 0) {
  if (!adapterConfig.api_key) throw new Error('Todoist API key not configured');

  const requestUrl = new URL(`${apiBase(adapterConfig)}${endpoint}`);
  for (const [name, value] of Object.entries(options.query || {})) {
    if (value !== null && value !== undefined && value !== '') {
      requestUrl.searchParams.set(name, String(value));
    }
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(requestUrl, {
      method: options.method || 'GET',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${adapterConfig.api_key}`,
        ...(options.body === undefined ? {} : { 'Content-Type': 'application/json' }),
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: controller.signal,
    });

    if (response.status === 429 && retryCount < MAX_RETRIES) {
      const delay = retryDelay(response, retryCount);
      await response.arrayBuffer();
      clearTimeout(timeout);
      if (delay > 0) await sleep(delay);
      return apiRequest(endpoint, adapterConfig, options, retryCount + 1);
    }

    const text = await response.text();
    if (!response.ok) {
      throw new Error(
        `Todoist API ${options.method || 'GET'} ${requestUrl.pathname} failed: ` +
          `${response.status} ${text || '(no body)'}`,
      );
    }
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  } catch (error) {
    if (error && error.name === 'AbortError') {
      throw new Error(`Todoist API request timed out after ${REQUEST_TIMEOUT_MS}ms`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function fetchPages(endpoint, adapterConfig, resultKey, query = {}) {
  const results = [];
  let cursor = null;
  const seenCursors = new Set();
  do {
    if (cursor) {
      if (seenCursors.has(cursor)) {
        throw new Error(`Todoist pagination repeated cursor: ${cursor}`);
      }
      seenCursors.add(cursor);
    }
    const page = await apiRequest(endpoint, adapterConfig, {
      query: { ...query, cursor },
    });
    if (Array.isArray(page)) {
      results.push(...page);
      cursor = null;
    } else {
      results.push(...((page && page[resultKey]) || []));
      cursor = (page && page.next_cursor) || null;
    }
  } while (cursor);
  return results;
}

async function getProjects(adapterConfig) {
  const key = `${apiBase(adapterConfig)}\u0000${adapterConfig.api_key || ''}`;
  if (!projectCache.has(key)) {
    const pending = fetchPages('/projects', adapterConfig, 'results').catch((error) => {
      projectCache.delete(key);
      throw error;
    });
    projectCache.set(key, pending);
  }
  return projectCache.get(key);
}

function configuredProjectName(dexTask, adapterConfig) {
  const pillarMap = adapterConfig.pillar_map || {};
  return pillarMap[dexTask.pillar] || adapterConfig.project || null;
}

async function resolveProjectId(projectName, adapterConfig) {
  if (!projectName) return null;
  const projects = await getProjects(adapterConfig);
  const match = projects.find(
    (project) => project.name === projectName || String(project.id) === String(projectName),
  );
  return match ? String(match.id) : null;
}

async function projectNamesById(adapterConfig) {
  try {
    const projects = await getProjects(adapterConfig);
    return new Map(projects.map((project) => [String(project.id), project.name]));
  } catch {
    return new Map();
  }
}

async function getCompletedTasks(sinceIso, untilIso, adapterConfig) {
  const completed = [];
  let windowStart = Date.parse(sinceIso);
  const end = Date.parse(untilIso);
  let windowSince = sinceIso;
  while (windowStart < end) {
    const windowEnd = Math.min(windowStart + COMPLETION_WINDOW_MS, end);
    const windowUntil = new Date(windowEnd).toISOString();
    completed.push(
      ...(await fetchPages(
        '/tasks/completed/by_completion_date',
        adapterConfig,
        'items',
        { since: windowSince, until: windowUntil },
      )),
    );
    windowStart = windowEnd;
    windowSince = windowUntil;
  }
  return completed;
}

function toExternal(dexTask, adapterConfig = {}) {
  return {
    content: dexTask.title,
    description: embedDexId(dexTask.context || '', dexTask.task_id),
    priority: DEX_TO_TODOIST_PRIORITY[dexTask.priority] || 2,
    due_string: dexTask.due || null,
    _project_name: configuredProjectName(dexTask, adapterConfig),
  };
}

function toDex(externalTask) {
  const due = externalTask.due;
  return {
    title: externalTask.title || externalTask.content || 'Untitled task',
    external_id: String(externalTask.external_id ?? externalTask.id ?? ''),
    project:
      externalTask.project || externalTask.project_name || externalTask._project_name || null,
    list: externalTask.list || externalTask.list_name || externalTask._list_name || null,
    due: due && typeof due === 'object' ? due.string || due.date || null : due || null,
    completed_at: externalTask.completed_at || null,
  };
}

function toDexWithProjectName(task, projectNames) {
  return toDex({
    ...task,
    _project_name: task.project_id
      ? projectNames.get(String(task.project_id)) || null
      : null,
  });
}

async function create(externalPayload, adapterConfig) {
  const body = {
    content: externalPayload.content,
    description: externalPayload.description || '',
    priority: externalPayload.priority,
  };
  const projectId = await resolveProjectId(externalPayload._project_name, adapterConfig);
  if (projectId) body.project_id = projectId;
  if (externalPayload.due_string) body.due_string = externalPayload.due_string;

  const created = await apiRequest('/tasks', adapterConfig, {
    method: 'POST',
    body,
  });
  if (!created || created.id === null || created.id === undefined) {
    throw new Error('Todoist create response did not include a task ID');
  }
  return String(created.id);
}

async function complete(externalId, adapterConfig) {
  await apiRequest(`/tasks/${encodeURIComponent(String(externalId))}/close`, adapterConfig, {
    method: 'POST',
  });
}

async function getChanges(sinceIso, adapterConfig) {
  if (!adapterConfig.api_key) return [];
  const sinceTime = Date.parse(sinceIso);
  if (!Number.isFinite(sinceTime)) return [];

  const changes = [];
  const projectNames = await projectNamesById(adapterConfig);

  try {
    const activeTasks = await fetchPages('/tasks', adapterConfig, 'results');
    for (const task of activeTasks) {
      const createdAt = Date.parse(task.created_at || task.added_at || '');
      if (!Number.isFinite(createdAt) || createdAt <= sinceTime) continue;
      if (extractDexId(task.description)) continue;
      const converted = toDexWithProjectName(task, projectNames);
      changes.push({ id: converted.external_id, action: 'created', task: converted });
    }
  } catch {
    // Active-task reads degrade independently from completion history.
  }

  try {
    const completedTasks = await getCompletedTasks(
      sinceIso,
      new Date().toISOString(),
      adapterConfig,
    );
    for (const task of completedTasks) {
      const completedAt = Date.parse(task.completed_at || '');
      if (!Number.isFinite(completedAt) || completedAt < sinceTime) continue;
      const converted = toDexWithProjectName(task, projectNames);
      changes.push({ id: converted.external_id, action: 'completed', task: converted });
    }
  } catch {
    // Completion history can be unavailable without suppressing active tasks.
  }

  return changes;
}

async function health(adapterConfig) {
  await fetchPages('/projects', adapterConfig, 'results');
  return { healthy: true };
}

module.exports = {
  toExternal,
  toDex,
  create,
  complete,
  getChanges,
  health,
};
