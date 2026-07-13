/**
 * Things 3 Task Sync Adapter
 *
 * Maps Dex tasks <-> Things 3 via AppleScript (no API key, no network).
 * macOS only. Loaded dynamically by task-sync-bridge.cjs when things is
 * enabled in config.yaml.
 *
 * Mapping:
 *   Dex Pillar       -> Things Area
 *   Dex Week Priority -> Things Project
 *   P0/P1            -> Today list
 *   P2/P3            -> Anytime
 *   Dex title        -> Things task name
 *   Dex status n/s/b -> Open
 *   Dex status d     -> Completed
 *   Dex task_id      -> Tracked via .sync-state.json
 *
 * Auth: none (local AppleScript — works offline)
 * Rate limit: n/a (local process calls)
 */

// ---------------------------------------------------------------------------
// Status mapping — Dex status codes -> Things 3 status
// Things has no in-progress or blocked concept; everything is open or done.
// ---------------------------------------------------------------------------

const statusMap = {
  n: 'open',      // Not started -> Open
  s: 'open',      // Started -> Open (Things has no "in progress")
  b: 'open',      // Blocked -> Open (Things has no "blocked")
  d: 'completed', // Done -> Completed
};

// ---------------------------------------------------------------------------
// Priority mapping — Dex priority -> Things list placement
// P0/P1 go to Today (high urgency), P2/P3 go to Anytime (normal)
// ---------------------------------------------------------------------------

function thingsListForPriority(priority) {
  if (priority === 'P0' || priority === 'P1') return 'today';
  return 'anytime';
}

// ---------------------------------------------------------------------------
// Pillar <-> Area mapping
// Users can customize in config.yaml under things.area_mapping
// ---------------------------------------------------------------------------

function pillarToArea(pillar, adapterConfig) {
  const mapping = (adapterConfig && adapterConfig.area_mapping) || {};
  if (mapping[pillar]) return mapping[pillar];

  const defaults = {
    deal_support: 'Deal Support',
    thought_leadership: 'Thought Leadership',
    product_feedback: 'Product Feedback',
  };
  return defaults[pillar] || pillar || 'Inbox';
}

function areaToPillar(areaName) {
  const name = (areaName || '').toLowerCase().replace(/\s+/g, '_');
  if (name.includes('deal') || name.includes('sales') || name.includes('revenue')) return 'deal_support';
  if (name.includes('thought') || name.includes('leadership') || name.includes('content')) return 'thought_leadership';
  if (name.includes('product') || name.includes('feedback')) return 'product_feedback';
  return 'deal_support'; // Default pillar
}

// ---------------------------------------------------------------------------
// Tag <-> Priority mapping
// ---------------------------------------------------------------------------

function tagsToPriority(tags) {
  const tagSet = new Set((tags || []).map(t => t.toUpperCase()));
  if (tagSet.has('P0')) return 'P0';
  if (tagSet.has('P1')) return 'P1';
  if (tagSet.has('P2')) return 'P2';
  if (tagSet.has('P3')) return 'P3';
  return 'P2'; // Default priority
}

// ---------------------------------------------------------------------------
// Transform: Dex task -> Things 3 task format
// ---------------------------------------------------------------------------

function toExternal(dexTask) {
  return {
    title: dexTask.title,
    area: pillarToArea(dexTask.pillar),
    project: dexTask.week_priority || null,
    list: thingsListForPriority(dexTask.priority),
    notes: formatNotes(dexTask),
    tags: [dexTask.priority],
  };
}

// ---------------------------------------------------------------------------
// Transform: Things 3 task -> Dex task format
// ---------------------------------------------------------------------------

function toDex(thingsTask) {
  return {
    title: thingsTask.title || thingsTask.name || 'Untitled task',
    pillar: areaToPillar(thingsTask.area || thingsTask.areaName || ''),
    priority: tagsToPriority(thingsTask.tags || []),
    status: thingsTask.status === 'completed' ? 'd' : 'n',
    source: 'things',
    external_id: thingsTask.id || '',
  };
}

// ---------------------------------------------------------------------------
// API: Create a task in Things 3 via AppleScript
// ---------------------------------------------------------------------------

async function create(externalTask, adapterConfig) {
  const { execSync } = require('child_process');

  const params = {
    title: externalTask.title,
    notes: externalTask.notes || '',
    area: externalTask.area || null,
    project: externalTask.project || null,
    list: externalTask.list || 'anytime',
  };

  try {
    const script = buildCreateScript(params);
    const result = execSync(`osascript -e '${script}'`, {
      encoding: 'utf-8',
      timeout: 10000,
    }).trim();
    // Things returns the task ID on creation
    return result || `things-${Date.now()}`;
  } catch (err) {
    throw new Error(`Things 3 create failed: ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// API: Complete a task in Things 3
// ---------------------------------------------------------------------------

async function complete(externalId, adapterConfig) {
  const { execSync } = require('child_process');
  try {
    const script = `tell application "Things3" to complete to do id "${escapeAS(externalId)}"`;
    execSync(`osascript -e '${script}'`, {
      encoding: 'utf-8',
      timeout: 10000,
    });
  } catch (err) {
    throw new Error(`Things 3 complete failed: ${err.message}`);
  }
}

// ---------------------------------------------------------------------------
// API: Get changes since last sync
// Checks Logbook for recently completed tasks, Inbox for new ones.
// ---------------------------------------------------------------------------

async function getChanges(since, adapterConfig) {
  const { execSync } = require('child_process');
  const changes = [];

  // 1. Recently completed tasks from Logbook
  try {
    const logbookScript = `
tell application "Things3"
  set output to ""
  repeat with t in to dos of list "Logbook"
    set taskId to id of t
    set taskName to name of t
    set output to output & taskId & "|||" & taskName & "\\n"
  end repeat
  return output
end tell`;
    const logbookResult = execSync(`osascript -e '${logbookScript.replace(/'/g, "'\\''")}'`, {
      encoding: 'utf-8',
      timeout: 15000,
    }).trim();

    if (logbookResult) {
      for (const line of logbookResult.split('\n')) {
        const [id, title] = line.split('|||');
        if (id && title) {
          changes.push({
            id: id.trim(),
            action: 'completed',
            task: { title: title.trim(), status: 'completed' },
          });
        }
      }
    }
  } catch {
    // Logbook query failed — continue gracefully
  }

  // 2. New tasks from Inbox (not originating from Dex)
  try {
    const inboxScript = `
tell application "Things3"
  set output to ""
  repeat with t in to dos of list "Inbox"
    set taskId to id of t
    set taskName to name of t
    set taskNotes to notes of t
    set output to output & taskId & "|||" & taskName & "|||" & taskNotes & "\\n"
  end repeat
  return output
end tell`;
    const inboxResult = execSync(`osascript -e '${inboxScript.replace(/'/g, "'\\''")}'`, {
      encoding: 'utf-8',
      timeout: 15000,
    }).trim();

    if (inboxResult) {
      for (const line of inboxResult.split('\n')) {
        const parts = line.split('|||');
        if (parts[0] && parts[1]) {
          // Skip tasks that came from Dex (have dex-task-id in notes)
          if (parts[2] && parts[2].includes('dex-task-id:')) continue;
          changes.push({
            id: parts[0].trim(),
            action: 'created',
            task: {
              title: parts[1].trim(),
              notes: (parts[2] || '').trim(),
            },
          });
        }
      }
    }
  } catch {
    // Inbox query failed — return what we have
  }

  return changes;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatNotes(dexTask) {
  const parts = [];
  if (dexTask.context) parts.push(dexTask.context);
  if (dexTask.task_id) parts.push(`\n---\ndex-task-id: ${dexTask.task_id}`);
  return parts.join('\n');
}

function buildCreateScript(params) {
  let props = `name:"${escapeAS(params.title)}"`;
  if (params.notes) props += `, notes:"${escapeAS(params.notes)}"`;

  if (params.area) {
    return `tell application "Things3"
  set newTask to make new to do with properties {${props}} in area "${escapeAS(params.area)}"
  return id of newTask
end tell`;
  } else if (params.project) {
    return `tell application "Things3"
  set newTask to make new to do with properties {${props}} in project "${escapeAS(params.project)}"
  return id of newTask
end tell`;
  } else {
    return `tell application "Things3"
  set newTask to make new to do with properties {${props}}
  return id of newTask
end tell`;
  }
}

function escapeAS(str) {
  return (str || '').replace(/\\/g, '\\\\').replace(/"/g, '\\"');
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
