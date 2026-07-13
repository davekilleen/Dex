/**
 * Jira Task Sync Adapter
 *
 * Maps Dex tasks <-> Jira issues via the Atlassian REST API v3.
 * Loaded dynamically by task-sync-bridge.cjs when jira (or atlassian)
 * is enabled in config.yaml with task_sync: true.
 *
 * Mapping:
 *   Dex Pillar      -> Jira Project (via pillar_map or default project_key)
 *   Dex P0/P1/P2/P3 -> Jira Priority Highest/High/Medium/Low
 *   Dex title        -> Jira Summary
 *   Dex context      -> Jira Description (ADF format)
 *   Dex status n     -> To Do (category "new")
 *   Dex status s     -> In Progress (category "indeterminate")
 *   Dex status b     -> Blocked (custom status or stays In Progress)
 *   Dex status d     -> Done (category "done")
 *   Dex task_id      -> Stored in issue description footer + .sync-state.json
 *
 * Auth: OAuth 2.0 token from System/.atlassian-oauth-token.json
 *       OR API token (email + token) from config.yaml
 * Rate limit: ~100 requests/minute (varies by Atlassian Cloud plan)
 *
 * IMPORTANT: Never delete issues — only transition status.
 * Confluence access is read-only (no write operations).
 */

const fs = require('fs');
const path = require('path');

// ---------------------------------------------------------------------------
// Status mapping — Dex status codes -> Jira status categories
// Jira uses workflow transitions, so actual status names vary per project.
// We map to category names and resolve to real statuses at runtime.
// ---------------------------------------------------------------------------

const statusMap = {
  n: 'To Do',
  s: 'In Progress',
  b: 'Blocked',      // May not exist; falls back to In Progress
  d: 'Done',
};

// Jira status categories for transition matching
const STATUS_CATEGORIES = {
  n: 'new',            // "To Do" category
  s: 'indeterminate',  // "In Progress" category
  b: 'indeterminate',  // Blocked is typically in the "In Progress" category
  d: 'done',           // "Done" category
};

// ---------------------------------------------------------------------------
// Priority mapping — Dex priorities <-> Jira priorities
// Jira: Highest > High > Medium > Low > Lowest
// ---------------------------------------------------------------------------

const DEX_TO_JIRA_PRIORITY = { P0: 'Highest', P1: 'High', P2: 'Medium', P3: 'Low' };
const JIRA_TO_DEX_PRIORITY = {
  Highest: 'P0', Critical: 'P0', Blocker: 'P0',
  High: 'P1',
  Medium: 'P2',
  Low: 'P3', Lowest: 'P3',
};

// ---------------------------------------------------------------------------
// Auth helper — read OAuth token or API token from config
// ---------------------------------------------------------------------------

function getAuth(adapterConfig) {
  const vaultRoot = process.env.CLAUDE_PROJECT_DIR || path.resolve(__dirname, '../../..');

  // Method 1: OAuth token file (preferred for Atlassian Cloud)
  const tokenPath = adapterConfig.token_path ||
    path.join(vaultRoot, 'System', '.atlassian-oauth-token.json');

  if (fs.existsSync(tokenPath)) {
    const tokenData = JSON.parse(fs.readFileSync(tokenPath, 'utf-8'));
    if (tokenData.access_token) {
      return {
        type: 'oauth',
        token: tokenData.access_token,
        cloudId: tokenData.cloud_id || adapterConfig.cloud_id,
      };
    }
  }

  // Method 2: API token from config.yaml (email + api_token)
  if (adapterConfig.email && adapterConfig.api_token) {
    const encoded = Buffer.from(`${adapterConfig.email}:${adapterConfig.api_token}`).toString('base64');
    return {
      type: 'basic',
      token: encoded,
      site: adapterConfig.site_url, // e.g., https://yourorg.atlassian.net
    };
  }

  throw new Error('Atlassian auth not configured. Run /atlassian-setup');
}

function getCloudId(adapterConfig) {
  const vaultRoot = process.env.CLAUDE_PROJECT_DIR || path.resolve(__dirname, '../../..');
  const tokenPath = adapterConfig.token_path ||
    path.join(vaultRoot, 'System', '.atlassian-oauth-token.json');

  if (fs.existsSync(tokenPath)) {
    const tokenData = JSON.parse(fs.readFileSync(tokenPath, 'utf-8'));
    return tokenData.cloud_id || adapterConfig.cloud_id;
  }
  return adapterConfig.cloud_id;
}

// ---------------------------------------------------------------------------
// API helpers — supports both OAuth (cloud API) and Basic auth (site URL)
// ---------------------------------------------------------------------------

function authHeaders(auth) {
  const headers = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  };

  if (auth.type === 'oauth') {
    headers['Authorization'] = `Bearer ${auth.token}`;
  } else {
    headers['Authorization'] = `Basic ${auth.token}`;
  }

  return headers;
}

function buildBaseUrl(auth) {
  if (auth.type === 'oauth' && auth.cloudId) {
    return `https://api.atlassian.com/ex/jira/${auth.cloudId}/rest/api/3`;
  } else if (auth.site) {
    // Direct site URL for API token auth
    const site = auth.site.replace(/\/$/, '');
    return `${site}/rest/api/3`;
  }
  throw new Error('Cannot determine Jira API base URL. Configure cloud_id or site_url.');
}

async function jiraGet(auth, apiPath) {
  const baseUrl = buildBaseUrl(auth);
  const url = `${baseUrl}${apiPath}`;
  const response = await fetch(url, {
    method: 'GET',
    headers: authHeaders(auth),
  });

  if (response.status === 429) {
    // Rate limited — respect Atlassian limits
    const retryAfter = response.headers.get('Retry-After') || '5';
    throw new Error(`Jira rate limited. Retry after ${retryAfter}s`);
  }

  if (!response.ok) {
    throw new Error(`Jira GET ${apiPath}: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

async function jiraPost(auth, apiPath, body) {
  const baseUrl = buildBaseUrl(auth);
  const url = `${baseUrl}${apiPath}`;
  const response = await fetch(url, {
    method: 'POST',
    headers: authHeaders(auth),
    body: JSON.stringify(body),
  });

  if (response.status === 429) {
    const retryAfter = response.headers.get('Retry-After') || '5';
    throw new Error(`Jira rate limited. Retry after ${retryAfter}s`);
  }

  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new Error(`Jira POST ${apiPath}: ${response.status} ${response.statusText} ${text}`);
  }
  if (response.status === 204) return {};
  return response.json();
}

// ---------------------------------------------------------------------------
// Pillar -> Jira project resolution
// ---------------------------------------------------------------------------

function resolveProjectKey(pillar, adapterConfig) {
  const pillarMap = adapterConfig.pillar_map || {};
  return pillarMap[pillar] || adapterConfig.project_key || null;
}

function inferPillarFromProject(projectKey, adapterConfig) {
  const pillarMap = adapterConfig.pillar_map || {};
  // Reverse lookup: find the pillar whose mapped project matches
  for (const [pillar, key] of Object.entries(pillarMap)) {
    if (key === projectKey) return pillar;
  }
  // Fallback: try to match common pillar keywords in project key/name
  const lower = (projectKey || '').toLowerCase();
  if (lower.includes('deal') || lower.includes('sales') || lower.includes('revenue')) return 'deal_support';
  if (lower.includes('thought') || lower.includes('content') || lower.includes('leadership')) return 'thought_leadership';
  if (lower.includes('product') || lower.includes('feedback')) return 'product_feedback';
  return 'deal_support'; // Safe default
}

// ---------------------------------------------------------------------------
// Workflow transition resolution
// Jira requires transition IDs to move issues between statuses.
// We discover available transitions at runtime to handle any workflow.
// ---------------------------------------------------------------------------

async function findTransition(auth, issueKey, targetCategory) {
  const data = await jiraGet(auth, `/issue/${issueKey}/transitions`);
  const transitions = data.transitions || [];

  // First try: exact category match
  for (const t of transitions) {
    const cat = (t.to && t.to.statusCategory && t.to.statusCategory.key) || '';
    if (cat === targetCategory) return t.id;
  }

  // Second try: name-based match for common statuses
  const nameMap = {
    new: ['to do', 'open', 'backlog', 'new'],
    indeterminate: ['in progress', 'in review', 'started', 'active'],
    done: ['done', 'closed', 'resolved', 'complete'],
  };
  const targetNames = nameMap[targetCategory] || [];
  for (const t of transitions) {
    const name = (t.to && t.to.name || '').toLowerCase();
    if (targetNames.some(n => name.includes(n))) return t.id;
  }

  return null;
}

// ---------------------------------------------------------------------------
// Transform: Dex task -> Jira issue format
// ---------------------------------------------------------------------------

function toExternal(dexTask) {
  return {
    summary: dexTask.title,
    priority: DEX_TO_JIRA_PRIORITY[dexTask.priority] || 'Medium',
    _pillar: dexTask.pillar,
    description: dexTask.context || '',
    _dexTaskId: dexTask.task_id || '',
    _status: dexTask.status || 'n',
  };
}

// ---------------------------------------------------------------------------
// Transform: Jira issue -> Dex task format
// ---------------------------------------------------------------------------

function toDex(jiraIssue) {
  const fields = jiraIssue.fields || jiraIssue;
  const priorityName = (fields.priority && fields.priority.name) || 'Medium';
  const priority = JIRA_TO_DEX_PRIORITY[priorityName] || 'P2';

  // Infer Dex status from Jira status category
  const statusCat = (fields.status && fields.status.statusCategory &&
    fields.status.statusCategory.key) || 'new';
  let status = 'n';
  if (statusCat === 'indeterminate') status = 's';
  else if (statusCat === 'done') status = 'd';

  const projectKey = (fields.project && fields.project.key) || '';

  return {
    title: fields.summary || 'Untitled issue',
    pillar: inferPillarFromProject(projectKey, {}),
    priority,
    status,
    source: 'jira',
    external_id: jiraIssue.key || jiraIssue.id,
  };
}

// ---------------------------------------------------------------------------
// API: Create an issue in Jira
// POST /rest/api/3/issue
// ---------------------------------------------------------------------------

async function create(externalTask, adapterConfig) {
  const auth = getAuth(adapterConfig);

  const projectKey = resolveProjectKey(externalTask._pillar, adapterConfig);
  if (!projectKey) throw new Error('No Jira project_key configured for this pillar');

  const issueType = adapterConfig.issue_type || 'Task';

  // Build description in Atlassian Document Format (ADF)
  const descriptionContent = [];

  // Add the task description if present
  if (externalTask.description) {
    descriptionContent.push({
      type: 'paragraph',
      content: [{ type: 'text', text: externalTask.description }],
    });
  }

  // Add Dex task ID footer for cross-reference
  if (externalTask._dexTaskId) {
    descriptionContent.push({
      type: 'paragraph',
      content: [
        { type: 'text', text: '---\nDex: ', marks: [{ type: 'em' }] },
        { type: 'text', text: externalTask._dexTaskId, marks: [{ type: 'code' }] },
      ],
    });
  }

  const body = {
    fields: {
      project: { key: projectKey },
      summary: externalTask.summary,
      issuetype: { name: issueType },
      priority: { name: externalTask.priority },
    },
  };

  // Only add description if we have content
  if (descriptionContent.length > 0) {
    body.fields.description = {
      type: 'doc',
      version: 1,
      content: descriptionContent,
    };
  }

  const result = await jiraPost(auth, '/issue', body);
  return result.key || result.id;
}

// ---------------------------------------------------------------------------
// API: Complete (transition to Done) an issue in Jira
// POST /rest/api/3/issue/{id}/transitions
//
// IMPORTANT: We never delete issues — only transition status.
// ---------------------------------------------------------------------------

async function complete(externalId, adapterConfig) {
  const auth = getAuth(adapterConfig);

  const transitionId = await findTransition(auth, externalId, 'done');
  if (!transitionId) {
    throw new Error(`No "Done" transition found for ${externalId}. Check Jira workflow.`);
  }

  await jiraPost(auth, `/issue/${externalId}/transitions`, {
    transition: { id: transitionId },
  });
}

// ---------------------------------------------------------------------------
// API: Get changes since last sync via JQL
// GET /rest/api/3/search with JQL `updated >= "since"`
// ---------------------------------------------------------------------------

async function getChanges(since, adapterConfig) {
  const auth = getAuth(adapterConfig);

  const projectKey = adapterConfig.project_key;
  if (!projectKey) return [];

  const changes = [];

  // JQL: issues updated since last sync in the configured project
  // Format date as YYYY-MM-DD for JQL compatibility
  const sinceDate = since.slice(0, 10);
  const jql = `project = "${projectKey}" AND updated >= "${sinceDate}" ORDER BY updated DESC`;
  const encoded = encodeURIComponent(jql);

  try {
    const data = await jiraGet(
      auth,
      `/search?jql=${encoded}&maxResults=50&fields=summary,status,priority,project,created,updated,assignee`
    );

    const sinceTime = new Date(since).getTime();

    for (const issue of (data.issues || [])) {
      const fields = issue.fields || {};
      const updatedTime = new Date(fields.updated).getTime();
      const createdTime = new Date(fields.created).getTime();

      const statusCat = (fields.status && fields.status.statusCategory &&
        fields.status.statusCategory.key) || 'new';

      if (createdTime > sinceTime) {
        // Newly created issue
        changes.push({
          id: issue.key,
          action: 'created',
          task: { ...fields, key: issue.key, id: issue.id },
        });
      } else if (statusCat === 'done' && updatedTime > sinceTime) {
        // Recently completed
        changes.push({
          id: issue.key,
          action: 'completed',
          task: { ...fields, key: issue.key, id: issue.id },
        });
      } else if (updatedTime > sinceTime) {
        // Updated (status change, field edit, etc.)
        changes.push({
          id: issue.key,
          action: 'updated',
          task: { ...fields, key: issue.key, id: issue.id },
        });
      }
    }
  } catch {
    // JQL query failed — degrade gracefully
  }

  return changes;
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
};
