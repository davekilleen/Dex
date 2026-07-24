'use strict';

const crypto = require('node:crypto');
const childProcess = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const { loadPaths } = require('../../.claude/hooks/paths.cjs');
const { resolveDexPythonStatus } = require('./dex-python.cjs');
const { resolveEntityPath } = require('./entity-identity.cjs');
const {
  RELATIONSHIP_TYPES,
  fold,
  mergeFrontmatterText,
  parseEntityPage,
  readFrontmatterField,
  relationshipEdgeKey,
  renderRelationships,
  renderUpdateLog,
  replaceMachineRegion,
} = require('./entity-pages.cjs');

const STORE_VERSION = 1;
const LOCK_RETRIES = 20;
const LOCK_DELAY_MS = 50;
const LOCK_STALE_MS = 30_000;
const MAX_ATTEMPTS = 5;
const MAX_TARGET_MISSING_ATTEMPTS = 5;
const MAX_TRANSIENT_ATTEMPTS = 15;
const MAX_TRANSIENT_AGE_MS = 7 * 24 * 60 * 60 * 1000;
const BACKOFF_BASE_MS = 30 * 60 * 1000;
const BACKOFF_MAX_MS = 24 * 60 * 60 * 1000;
const CLI_CHUNK_SIZE = 50;
const REGION_HEADINGS = {
  'recent-interactions': 'Recent Interactions',
  'key-contacts': 'Key Contacts',
  'meeting-history': 'Meeting History',
  'context-summary': 'Key Context',
  'related-tasks': 'Related Tasks',
  relationships: 'Relationships',
  'update-log': 'Update Log',
};
const REGION_ORDER = [
  'recent-interactions',
  'key-contacts',
  'meeting-history',
  'context-summary',
  'related-tasks',
  'relationships',
  'update-log',
  'page-metadata',
];
const CLI_KEYS = new Set([
  'op',
  'path',
  'content',
  'allowed_root',
  'base_fingerprint',
  'replacement_content',
  'field_changes',
  'ensure_regions',
  'region_projections',
  'relationship_removed_keys',
]);
const deadLetterIndexCache = new Map();

function pendingStorePath(vaultRoot) {
  const configured = loadPaths();
  const configuredRoot = path.resolve(configured.VAULT_ROOT);
  const configuredPending = configured.ENTITY_PENDING_FILE
    || path.join(configured.DEX_RUNTIME_DIR, 'entity-pending.json');
  const relative = path.relative(
    configuredRoot,
    path.resolve(configuredPending),
  );
  return path.join(path.resolve(vaultRoot), relative);
}

function deadLetterPath(vaultRoot) {
  return path.join(
    path.dirname(pendingStorePath(vaultRoot)),
    'entity-dead-letter.jsonl',
  );
}

function loadDeadLetters(vaultRoot) {
  try {
    return fs.readFileSync(deadLetterPath(vaultRoot), 'utf8')
      .split(/\r?\n/)
      .filter(line => line.trim())
      .flatMap((line) => {
        try {
          return [JSON.parse(line)];
        } catch (_) {
          return [];
        }
      });
  } catch (error) {
    if (error.code === 'ENOENT') return [];
    throw error;
  }
}

function deadLetterFileSignature(filePath) {
  try {
    const stat = fs.statSync(filePath);
    return `${stat.size}:${stat.mtimeMs}`;
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
}

function stableValue(value) {
  if (Array.isArray(value)) return value.map(stableValue);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, stableValue(value[key])]),
    );
  }
  return value;
}

function fingerprintText(value) {
  return crypto.createHash('sha256').update(value, 'utf8').digest('hex');
}

function batchId(scope, ops, meetingIds) {
  return crypto.createHash('sha256').update(JSON.stringify(stableValue({
    scope,
    ops,
    meeting_ids: [...new Set(meetingIds)].sort(),
  }))).digest('hex');
}

function emptyStore() {
  return { version: STORE_VERSION, batches: [] };
}

function loadPendingStore(vaultRoot) {
  const filePath = pendingStorePath(vaultRoot);
  try {
    const parsed = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    if (parsed?.version !== STORE_VERSION || !Array.isArray(parsed.batches)) {
      throw new Error(`Unsupported entity pending store: ${filePath}`);
    }
    return parsed;
  } catch (error) {
    if (error.code === 'ENOENT') return emptyStore();
    throw error;
  }
}

function atomicWriteJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const temporary = path.join(
    path.dirname(filePath),
    `.${path.basename(filePath)}.${process.pid}.${Date.now()}.tmp`,
  );
  try {
    fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
    fs.renameSync(temporary, filePath);
  } catch (error) {
    try { fs.unlinkSync(temporary); } catch (_) { /* already absent */ }
    throw error;
  }
}

function atomicWriteText(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const temporary = path.join(
    path.dirname(filePath),
    `.${path.basename(filePath)}.${process.pid}.${Date.now()}.tmp`,
  );
  try {
    fs.writeFileSync(temporary, value, 'utf8');
    fs.renameSync(temporary, filePath);
  } catch (error) {
    try { fs.unlinkSync(temporary); } catch (_) { /* already absent */ }
    throw error;
  }
}

function savePendingStore(vaultRoot, store) {
  const filePath = pendingStorePath(vaultRoot);
  if (store.batches.length === 0) {
    try { fs.unlinkSync(filePath); } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    return;
  }
  atomicWriteJson(filePath, store);
}

function wait(milliseconds) {
  const buffer = new SharedArrayBuffer(4);
  Atomics.wait(new Int32Array(buffer), 0, 0, milliseconds);
}

function withPendingLock(vaultRoot, callback) {
  const filePath = pendingStorePath(vaultRoot);
  const lockPath = `${filePath}.lock`;
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  let handle;
  for (let attempt = 0; attempt <= LOCK_RETRIES; attempt += 1) {
    try {
      handle = fs.openSync(lockPath, 'wx');
      fs.writeFileSync(handle, `${process.pid}\n${new Date().toISOString()}\n`);
      break;
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      try {
        if (Date.now() - fs.statSync(lockPath).mtimeMs > LOCK_STALE_MS) {
          fs.unlinkSync(lockPath);
          continue;
        }
      } catch (statError) {
        if (statError.code === 'ENOENT') continue;
        throw statError;
      }
      if (attempt === LOCK_RETRIES) {
        throw new Error(`Timed out waiting for lock: ${lockPath}`);
      }
      wait(LOCK_DELAY_MS);
    }
  }

  try {
    return callback();
  } finally {
    if (handle !== undefined) fs.closeSync(handle);
    try { fs.unlinkSync(lockPath); } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }
}

function cliOperation(operation) {
  return Object.fromEntries(
    Object.entries(operation).filter(([key]) => CLI_KEYS.has(key)),
  );
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function compareStrings(left, right) {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

function regionRank(slug) {
  const rank = REGION_ORDER.indexOf(slug);
  return rank < 0 ? REGION_ORDER.length : rank;
}

function ensureRegion(text, slug) {
  if (text.includes(`<!-- dex:auto:${slug} -->`)) return text;
  const heading = REGION_HEADINGS[slug] || slug.replace(/-/g, ' ')
    .replace(/\b\w/g, character => character.toUpperCase());
  const headingMatch = new RegExp(
    `^##[ \\t]+${escapeRegExp(heading)}[ \\t]*$`,
    'm',
  ).exec(text);
  const managed = `<!-- dex:auto:${slug} -->\n<!-- /dex:auto -->`;
  if (headingMatch) {
    const prefix = text.slice(0, headingMatch.index + headingMatch[0].length)
      .replace(/[\r\n]+$/, '');
    const suffix = text.slice(headingMatch.index + headingMatch[0].length)
      .replace(/^[\r\n]+/, '');
    return suffix
      ? `${prefix}\n\n${managed}\n\n${suffix}`
      : `${prefix}\n\n${managed}\n`;
  }

  const insertionPoints = REGION_ORDER
    .filter(laterSlug => regionRank(laterSlug) > regionRank(slug))
    .map(laterSlug => REGION_HEADINGS[laterSlug])
    .filter(Boolean)
    .map(laterHeading => new RegExp(
      `^##[ \\t]+${escapeRegExp(laterHeading)}[ \\t]*$`,
      'm',
    ).exec(text))
    .filter(Boolean)
    .map(match => match.index);
  const section = `## ${heading}\n\n${managed}`;
  if (insertionPoints.length > 0) {
    const insertion = Math.min(...insertionPoints);
    const prefix = text.slice(0, insertion).replace(/[\r\n]+$/, '');
    const suffix = text.slice(insertion).replace(/^[\r\n]+/, '');
    return `${prefix}\n\n${section}\n\n${suffix}`;
  }
  const prefix = text.replace(/[\r\n]+$/, '');
  return prefix ? `${prefix}\n\n${section}\n` : `${section}\n`;
}

function appendLegacyInteraction(original, line) {
  const headings = [
    /^## Recent Interactions\s*$/m,
    /^## Recent Meetings\s*$/m,
    /^## Meetings\s*$/m,
  ];
  for (const heading of headings) {
    const match = heading.exec(original);
    if (!match) continue;
    const insertion = match.index + match[0].length;
    const suffix = original.slice(insertion);
    return `${original.slice(0, insertion)}\n${line}${suffix.startsWith('\n') ? '' : '\n'}${suffix}`;
  }
  return `${original.replace(/\s*$/, '')}\n\n${line}\n`;
}

function mergeTouchRecords(latest, touches) {
  const merged = [];
  const seen = new Set();
  for (const touch of [
    ...readFrontmatterField(latest, 'touches'),
    ...touches,
  ]) {
    if (!touch || typeof touch !== 'object') continue;
    const sourceId = touch.source && typeof touch.source === 'object'
      ? touch.source.id
      : null;
    const key = `${String(touch.ts || '').slice(0, 10)}\0${touch.type || ''}\0${sourceId || ''}`;
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(touch);
  }
  merged.sort((left, right) => (
    compareStrings(String(left.ts || ''), String(right.ts || ''))
    || compareStrings(String(left.type || ''), String(right.type || ''))
    || compareStrings(
      String(left.source?.id || ''),
      String(right.source?.id || ''),
    )
  ));
  return {
    merged,
    lastTouched: merged.reduce(
      (latestTouch, touch) => (
        String(touch.ts || '') > latestTouch ? String(touch.ts) : latestTouch
      ),
      '',
    ),
    rendered: renderUpdateLog({ touches: merged }),
  };
}

function materializeHookIntent(operation, latest, intent) {
  const interaction = intent.interaction;
  if (!interaction || typeof interaction.path !== 'string'
      || typeof interaction.line !== 'string'
      || !/^\d{4}-\d{2}-\d{2}$/.test(interaction.date || '')) {
    throw new Error(`Invalid hook mutation intent for ${operation.path}`);
  }
  const entity = parseEntityPage(operation.path);
  const titleMatch = /^-\s+\[([^\]]+)\]\(/.exec(interaction.line);
  const touch = {
    ts: interaction.date,
    type: 'meeting',
    direction: 'none',
    source: {
      id: typeof interaction.source_id === 'string' && interaction.source_id.trim()
        ? interaction.source_id.trim()
        : path.basename(interaction.path, '.md'),
      title: titleMatch?.[1]?.trim() || path.basename(interaction.path, '.md'),
    },
  };
  const { merged, lastTouched, rendered } = mergeTouchRecords(latest, [touch]);
  const fieldChanges = {
    ...(!entity.last_interaction || interaction.date > entity.last_interaction
      ? { last_interaction: interaction.date }
      : {}),
    touches: merged,
    last_touched: lastTouched,
  };
  const baseFingerprint = fingerprintText(latest);
  let materialized;
  let target;
  if (latest.includes('<!-- dex:auto:recent-interactions -->')) {
    const region = /<!-- dex:auto:recent-interactions -->\r?\n?([\s\S]*?)<!-- \/dex:auto -->/
      .exec(latest);
    const existing = region
      ? region[1].split(/\r?\n/)
        .map(line => line.trim())
        .filter(line => line.startsWith('- '))
      : [];
    const additions = latest.includes(interaction.path)
      ? existing
      : [interaction.line, ...existing];
    const projection = additions.sort((left, right) => {
      const leftDate = left.match(/\d{4}-\d{2}-\d{2}\s*$/)?.[0] || '';
      const rightDate = right.match(/\d{4}-\d{2}-\d{2}\s*$/)?.[0] || '';
      return rightDate.localeCompare(leftDate);
    }).slice(0, 20).join('\n');
    const withRegion = replaceMachineRegion(
      latest,
      'recent-interactions',
      projection,
    );
    target = mergeFrontmatterText(operation.path, withRegion, fieldChanges);
    if (target !== null) {
      target = ensureRegion(target, 'update-log');
      target = replaceMachineRegion(target, 'update-log', rendered);
    }
    materialized = {
      op: 'mutate',
      path: operation.path,
      base_fingerprint: baseFingerprint,
      ensure_regions: ['update-log'],
      field_changes: fieldChanges,
      region_projections: {
        'recent-interactions': projection,
        'update-log': rendered,
      },
    };
  } else {
    const replacement = latest.includes(interaction.path)
      ? latest
      : appendLegacyInteraction(latest, interaction.line);
    target = mergeFrontmatterText(operation.path, replacement, fieldChanges);
    if (target !== null) {
      target = ensureRegion(target, 'update-log');
      target = replaceMachineRegion(target, 'update-log', rendered);
    }
    materialized = {
      op: 'mutate',
      path: operation.path,
      base_fingerprint: baseFingerprint,
      replacement_content: replacement,
      ensure_regions: ['update-log'],
      field_changes: fieldChanges,
      region_projections: { 'update-log': rendered },
    };
  }
  if (target !== null) materialized.target_fingerprint = fingerprintText(target);
  return materialized;
}

function materializeGardenerIntent(operation, latest, intent) {
  if (typeof intent.region_projection !== 'string') {
    throw new Error(`Invalid gardener mutation intent for ${operation.path}`);
  }
  const withRegion = ensureRegion(latest, 'context-summary');
  const target = replaceMachineRegion(
    withRegion,
    'context-summary',
    intent.region_projection,
  );
  return {
    op: 'mutate',
    path: operation.path,
    base_fingerprint: fingerprintText(latest),
    ensure_regions: ['context-summary'],
    region_projections: {
      'context-summary': intent.region_projection,
    },
    target_fingerprint: fingerprintText(target),
  };
}

function materializeTouchIntent(operation, latest, intent) {
  const touches = intent.touches;
  const valid = Array.isArray(touches)
    && touches.length > 0
    && touches.every(touch => (
      touch
      && typeof touch === 'object'
      && /^\d{4}-\d{2}-\d{2}$/.test(touch.ts || '')
      && ['meeting', 'mention'].includes(touch.type)
      && touch.source
      && typeof touch.source === 'object'
      && typeof touch.source.id === 'string'
      && touch.source.id.trim()
    ));
  if (!valid) {
    throw new Error(`Invalid touch-log mutation intent for ${operation.path}`);
  }

  const { merged, lastTouched, rendered } = mergeTouchRecords(latest, touches);
  const fieldChanges = {
    touches: merged,
    last_touched: lastTouched,
  };
  const withRegion = ensureRegion(latest, 'update-log');
  const withProjection = replaceMachineRegion(
    withRegion,
    'update-log',
    rendered,
  );
  const target = mergeFrontmatterText(
    operation.path,
    withProjection,
    fieldChanges,
  );
  const materialized = {
    op: 'mutate',
    path: operation.path,
    base_fingerprint: fingerprintText(latest),
    ensure_regions: ['update-log'],
    field_changes: fieldChanges,
    region_projections: { 'update-log': rendered },
  };
  if (target !== null) {
    materialized.target_fingerprint = fingerprintText(target);
  }
  return materialized;
}

function regionContent(text, slug) {
  const match = new RegExp(
    `<!-- dex:auto:${escapeRegExp(slug)} -->\\r?\\n?([\\s\\S]*?)<!-- \\/dex:auto -->`,
  ).exec(text);
  return match ? match[1].replace(/^[\r\n]+|[\r\n]+$/g, '') : '';
}

function materializeRelationshipIntent(operation, latest, intent) {
  const candidates = intent.relationships;
  const valid = Array.isArray(candidates)
    && candidates.length > 0
    && candidates.every(relationship => (
      relationship
      && !Array.isArray(relationship)
      && typeof relationship === 'object'
      && RELATIONSHIP_TYPES.includes(relationship.type)
      && typeof relationship.target_ref === 'string'
      && relationship.target_ref.trim()
      && relationship.confidence === 'suggested'
      && relationship.source
      && !Array.isArray(relationship.source)
      && typeof relationship.source === 'object'
      && typeof relationship.source.kind === 'string'
      && relationship.source.kind.trim()
      && typeof relationship.source.id === 'string'
      && relationship.source.id.trim()
      && /^\d{4}-\d{2}-\d{2}$/.test(relationship.source.date || '')
    ));
  if (!valid) {
    throw new Error(`Invalid relationship mutation intent for ${operation.path}`);
  }

  const incoming = candidates.map(relationship => ({
    type: relationship.type,
    target: relationship.target_ref.trim(),
    status: 'suggested',
    source: {
      kind: relationship.source.kind.trim(),
      id: relationship.source.id.trim(),
    },
    date: relationship.source.date,
  }));
  const current = readFrontmatterField(latest, 'relationships') || [];
  const rawRemovedKeys = intent.removed_edge_keys ?? [];
  const removedKeys = Array.isArray(rawRemovedKeys)
    ? rawRemovedKeys.map(normaliseEdgeKey)
    : null;
  if (removedKeys === null) {
    throw new Error(`Invalid relationship mutation intent for ${operation.path}`);
  }
  const removed = new Set(removedKeys);
  const byEdge = new Map();
  for (const relationship of current) {
    const key = relationshipEdgeKey(relationship);
    if (!removed.has(key) || relationship.status === 'confirmed') {
      byEdge.set(key, relationship);
    }
  }
  const dedupedIncoming = new Map();
  for (const relationship of incoming) {
    const key = relationshipEdgeKey(relationship);
    if (!dedupedIncoming.has(key)) dedupedIncoming.set(key, relationship);
  }
  for (const [key, relationship] of dedupedIncoming) {
    const existing = byEdge.get(key);
    if (!existing || existing.status !== 'confirmed') byEdge.set(key, relationship);
  }
  return materializeRelationshipFields(
    operation,
    latest,
    [...byEdge.values()],
    { relationships: [...byEdge.values()] },
    removedKeys,
  );
}

function normaliseEdgeKey(value) {
  if (typeof value !== 'string' || !value.includes('::')) {
    throw new Error('relationship edge_key must be a stable edge key');
  }
  const separator = value.indexOf('::');
  const type = value.slice(0, separator);
  const target = value.slice(separator + 2);
  if (!RELATIONSHIP_TYPES.includes(type) || !target) {
    throw new Error('relationship edge_key must be a stable edge key');
  }
  return `${type}::${fold(target)}`;
}

function materializeRelationshipActionIntent(operation, latest, intent) {
  let edgeKey;
  try {
    edgeKey = normaliseEdgeKey(intent.edge_key);
  } catch (_) {
    throw new Error(`Invalid relationship mutation intent for ${operation.path}`);
  }
  const current = readFrontmatterField(latest, 'relationships') || [];
  const found = current.some(relationship => relationshipEdgeKey(relationship) === edgeKey);
  if (!found) {
    throw new Error(`Invalid relationship mutation intent for ${operation.path}`);
  }
  if (intent.kind === 'confirm_relationship') {
    const proposed = current.map(relationship => (
      relationshipEdgeKey(relationship) === edgeKey
        ? { ...relationship, status: 'confirmed' }
        : relationship
    ));
    return materializeRelationshipFields(
      operation,
      latest,
      proposed,
      { relationships: proposed },
      [],
    );
  }
  if (intent.kind !== 'dismiss_relationship'
      || !/^\d{4}-\d{2}-\d{2}$/.test(intent.date || '')) {
    throw new Error(`Invalid relationship mutation intent for ${operation.path}`);
  }
  const proposed = current.filter(
    relationship => relationshipEdgeKey(relationship) !== edgeKey,
  );
  const dismissed = readFrontmatterField(
    latest,
    'dex_dismissed_relationships',
  ) || [];
  if (!dismissed.some(entry => entry.key === edgeKey)) {
    dismissed.push({ key: edgeKey, date: intent.date });
  }
  return materializeRelationshipFields(
    operation,
    latest,
    proposed,
    {
      relationships: proposed,
      dex_dismissed_relationships: dismissed,
    },
    [edgeKey],
  );
}

function materializeRelationshipFields(
  operation,
  latest,
  candidates,
  fieldChanges,
  removedKeys,
) {
  const rank = new Map(RELATIONSHIP_TYPES.map((type, index) => [type, index]));
  const proposed = [...candidates].sort((left, right) => (
    rank.get(left.type) - rank.get(right.type)
    || compareStrings(fold(left.target), fold(right.target))
    || compareStrings(left.target, right.target)
    || compareStrings(left.date, right.date)
  ));
  const changes = { ...fieldChanges, relationships: proposed };

  const preview = mergeFrontmatterText(
    operation.path,
    latest,
    changes,
    { relationshipRemovedKeys: removedKeys },
  );
  const effective = preview === null
    ? []
    : (readFrontmatterField(preview, 'relationships') || []);
  const provenance = renderUpdateLog({
    relationshipProvenance: effective.map(relationship => ({
      date: relationship.date,
      type: relationship.type,
      target_ref: relationship.target,
    })),
  });
  const updateLines = [...new Set([
    ...regionContent(latest, 'update-log').split(/\r?\n/),
    ...provenance.split(/\r?\n/),
  ].filter(Boolean))].sort(compareStrings);
  const relationshipsProjection = renderRelationships(effective);
  const materialized = {
    op: 'mutate',
    path: operation.path,
    base_fingerprint: fingerprintText(latest),
    field_changes: changes,
    relationship_removed_keys: removedKeys,
    ensure_regions: ['relationships', 'update-log'],
    region_projections: {
      relationships: relationshipsProjection,
      'update-log': updateLines.join('\n'),
    },
  };
  if (preview !== null) {
    let target = ensureRegion(preview, 'relationships');
    target = ensureRegion(target, 'update-log');
    target = replaceMachineRegion(
      target,
      'relationships',
      relationshipsProjection,
    );
    target = replaceMachineRegion(target, 'update-log', updateLines.join('\n'));
    materialized.target_fingerprint = fingerprintText(target);
  }
  return materialized;
}

function materializeOperation(operation, vaultRoot) {
  if (operation.op === 'create') {
    return { operation, materialized: operation };
  }
  if (operation.op !== 'mutate' || !operation.intent) {
    throw new Error(`Mutation operation has no declarative intent: ${operation.path}`);
  }
  let effective = operation;
  let latest;
  try {
    latest = fs.readFileSync(effective.path, 'utf8');
  } catch (originalError) {
    const retargeted = resolveEntityPath(vaultRoot, operation.entity_identity);
    if (!retargeted || retargeted === operation.path) {
      const error = new Error(
        `Target page missing or unreadable: ${operation.path} (${originalError.message})`,
      );
      error.code = originalError.code;
      error.failure_kind = 'target_missing';
      throw error;
    }
    effective = { ...operation, path: retargeted };
    try {
      latest = fs.readFileSync(effective.path, 'utf8');
    } catch (retargetError) {
      const error = new Error(
        `Retargeted page is unreadable: ${effective.path} (${retargetError.message})`,
      );
      error.code = retargetError.code;
      error.failure_kind = 'target_missing';
      throw error;
    }
  }
  if (effective.intent.kind === 'hook-interaction') {
    return {
      operation: effective,
      materialized: materializeHookIntent(effective, latest, effective.intent),
    };
  }
  if (effective.intent.kind === 'gardener-summary') {
    return {
      operation: effective,
      materialized: materializeGardenerIntent(effective, latest, effective.intent),
    };
  }
  if (effective.intent.kind === 'touch-log') {
    return {
      operation: effective,
      materialized: materializeTouchIntent(effective, latest, effective.intent),
    };
  }
  if (effective.intent.kind === 'relationship') {
    return {
      operation: effective,
      materialized: materializeRelationshipIntent(
        effective,
        latest,
        effective.intent,
      ),
    };
  }
  if (['confirm_relationship', 'dismiss_relationship'].includes(effective.intent.kind)) {
    return {
      operation: effective,
      materialized: materializeRelationshipActionIntent(
        effective,
        latest,
        effective.intent,
      ),
    };
  }
  throw new Error(`Unsupported mutation intent: ${effective.intent.kind}`);
}

function applied(operation, result) {
  if (!result || result.path !== operation.path) return false;
  if (['created', 'updated', 'noop'].includes(result.status)) return true;
  return ['exists', 'conflict'].includes(result.status)
    && typeof operation.target_fingerprint === 'string'
    && result.fingerprint === operation.target_fingerprint;
}

function completedMeetingIds(
  completedBatches,
  remainingBatches,
  deadLettered = [],
) {
  const blocked = new Set(
    [
      ...remainingBatches.flatMap((batch) => batch.meeting_ids || []),
      ...deadLettered.flatMap((entry) => entry.meeting_ids || []),
    ],
  );
  return [...new Set(
    completedBatches.flatMap((batch) => batch.meeting_ids || []),
  )].filter((meetingId) => !blocked.has(meetingId)).sort();
}

function failure(error, extra = {}) {
  return {
    ok: false,
    completed_meeting_ids: [],
    completed_batches: [],
    results: [],
    error: error instanceof Error ? error.message : String(error),
    ...extra,
  };
}

function operationWithoutLifecycle(operation) {
  const {
    attempts: _legacyAttempts,
    permanent_attempts: _permanentAttempts,
    transient_attempts: _transientAttempts,
    target_missing_attempts: _targetMissingAttempts,
    backoff_attempts: _backoffAttempts,
    first_attempt_at: _firstAttemptAt,
    last_attempt_at: _lastAttemptAt,
    next_attempt_at: _nextAttemptAt,
    last_error: _lastError,
    ...declarative
  } = operation;
  return declarative;
}

function operationKey(operation) {
  return JSON.stringify(stableValue(operationWithoutLifecycle(operation)));
}

function retryDelayMs(attempts) {
  return Math.min(
    BACKOFF_MAX_MS,
    BACKOFF_BASE_MS * (2 ** Math.max(0, attempts - 1)),
  );
}

function deadLetterId(batch, operation) {
  return crypto.createHash('sha256').update(JSON.stringify(stableValue({
    batch_id: batch.id,
    operation: operationWithoutLifecycle(operation),
  }))).digest('hex');
}

function deadLetterIds(vaultRoot) {
  const filePath = deadLetterPath(vaultRoot);
  const signature = deadLetterFileSignature(filePath);
  const cached = deadLetterIndexCache.get(filePath);
  if (cached?.signature === signature) return cached.ids;
  const ids = new Set(
    loadDeadLetters(vaultRoot)
      .map(entry => entry?.dead_letter_id)
      .filter(Boolean),
  );
  deadLetterIndexCache.set(filePath, { signature, ids });
  return ids;
}

function appendDeadLetters(vaultRoot, entries) {
  if (entries.length === 0) return;
  const filePath = deadLetterPath(vaultRoot);
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const existing = new Set(deadLetterIds(vaultRoot));
  const additions = entries.filter((entry) => {
    if (existing.has(entry.dead_letter_id)) return false;
    existing.add(entry.dead_letter_id);
    return true;
  });
  if (additions.length === 0) return;
  fs.appendFileSync(
    filePath,
    additions.map(entry => `${JSON.stringify(entry)}\n`).join(''),
    'utf8',
  );
  deadLetterIndexCache.set(filePath, {
    signature: deadLetterFileSignature(filePath),
    ids: existing,
  });
}

function compactDeadLetters(vaultRoot, resolvedIds) {
  if (resolvedIds.size === 0) return;
  const filePath = deadLetterPath(vaultRoot);
  let lines;
  try {
    lines = fs.readFileSync(filePath, 'utf8').split(/\r?\n/);
  } catch (error) {
    if (error.code === 'ENOENT') return;
    throw error;
  }
  const kept = [];
  const keptIds = new Set();
  for (const line of lines) {
    if (!line.trim()) continue;
    try {
      const entry = JSON.parse(line);
      if (resolvedIds.has(entry?.dead_letter_id)) continue;
      if (entry?.dead_letter_id) keptIds.add(entry.dead_letter_id);
    } catch (_) {
      // A torn historic line is not an entry, but compaction must not erase it.
    }
    kept.push(line);
  }
  if (kept.length === 0) {
    try { fs.unlinkSync(filePath); } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  } else {
    atomicWriteText(filePath, `${kept.join('\n')}\n`);
  }
  deadLetterIndexCache.set(filePath, {
    signature: deadLetterFileSignature(filePath),
    ids: keptIds,
  });
}

function requeueDeadLetters(vaultRoot) {
  const root = path.resolve(vaultRoot);
  return withPendingLock(root, () => {
    const entries = loadDeadLetters(root).filter(
      entry => entry && typeof entry === 'object'
        && entry.dead_letter_id
        && entry.op
        && typeof entry.op === 'object',
    );
    if (entries.length === 0) {
      return { requeued: 0, dead_letter_ids: [] };
    }
    const store = loadPendingStore(root);
    const requeuedIds = new Set();
    for (const entry of entries) {
      let batch = store.batches.find(candidate => candidate.id === entry.batch_id);
      if (!batch) {
        batch = {
          id: entry.batch_id,
          scope: entry.scope || 'default',
          meeting_ids: [],
          ops: [],
          ...(entry.metadata ? { metadata: entry.metadata } : {}),
        };
        store.batches.push(batch);
      }
      batch.meeting_ids = [...new Set([
        ...(batch.meeting_ids || []),
        ...(entry.meeting_ids || [entry.meeting_id]).filter(Boolean),
      ])].sort();
      const operation = operationWithoutLifecycle(entry.op);
      if (!batch.ops.some(candidate => operationKey(candidate) === operationKey(operation))) {
        batch.ops.push(operation);
      }
      requeuedIds.add(entry.dead_letter_id);
    }
    savePendingStore(root, store);
    compactDeadLetters(root, requeuedIds);
    return {
      requeued: requeuedIds.size,
      dead_letter_ids: [...requeuedIds].sort(),
    };
  });
}

function materializationFailureClass(error) {
  const message = error instanceof Error ? error.message : String(error);
  return /^(Invalid hook mutation intent|Invalid gardener mutation intent|Invalid touch-log mutation intent|Invalid relationship mutation intent|Unsupported mutation intent|Mutation operation has no declarative intent)/.test(
    message,
  )
    ? 'permanent'
    : 'transient';
}

function settleSelected(vaultRoot, selected, outcomes, now = new Date()) {
  return withPendingLock(vaultRoot, () => {
    const latest = loadPendingStore(vaultRoot);
    const completed = [];
    const deadLettered = [];
    const attemptedAt = now.toISOString();
    const outcomeMaps = new Map(selected.map(batch => [
      batch.id,
      batch.ops.reduce((byOperation, operation, index) => {
        const key = operationKey(operation);
        if (!byOperation.has(key)) byOperation.set(key, []);
        byOperation.get(key).push(outcomes.get(batch.id)?.[index] || null);
        return byOperation;
      }, new Map()),
    ]));

    for (const batch of latest.batches) {
      const batchOutcomes = outcomeMaps.get(batch.id);
      if (!batchOutcomes) continue;
      const originalOps = batch.ops;
      const originalEffects = batch.metadata?.effects;
      const alignedEffects = Array.isArray(originalEffects)
        && originalEffects.length === originalOps.length;
      const remainingOps = [];
      const remainingEffects = [];
      const appliedOps = [];
      const appliedEffects = [];
      for (const [index, operation] of originalOps.entries()) {
        const queuedOutcomes = batchOutcomes.get(operationKey(operation));
        const outcome = queuedOutcomes?.shift() || null;
        if (!outcome) {
          remainingOps.push(operation);
          if (alignedEffects) remainingEffects.push(originalEffects[index]);
          continue;
        }
        if (outcome.applied) {
          appliedOps.push(operationWithoutLifecycle(outcome.operation || operation));
          if (alignedEffects) appliedEffects.push(originalEffects[index]);
          continue;
        }
        const nextOperation = outcome.operation || operation;
        const permanentAttempts = Number.isInteger(operation.permanent_attempts)
          ? operation.permanent_attempts
          : 0;
        const transientAttempts = Number.isInteger(operation.transient_attempts)
          ? operation.transient_attempts
          : 0;
        const targetMissingAttempts = Number.isInteger(operation.target_missing_attempts)
          ? operation.target_missing_attempts
          : 0;
        const backoffAttempts = (Number.isInteger(operation.backoff_attempts)
          ? operation.backoff_attempts
          : 0) + 1;
        const isPermanent = outcome.failure_class === 'permanent';
        const isTargetMissing = outcome.failure_kind === 'target_missing';
        const nextPermanentAttempts = permanentAttempts + (isPermanent ? 1 : 0);
        const nextTransientAttempts = transientAttempts + (isPermanent ? 0 : 1);
        const nextTargetMissingAttempts = targetMissingAttempts
          + (isTargetMissing ? 1 : 0);
        const firstAttemptAt = operation.first_attempt_at || attemptedAt;
        const firstAttemptTime = new Date(firstAttemptAt).getTime();
        const transientAgeExceeded = !Number.isNaN(firstAttemptTime)
          && now.getTime() - firstAttemptTime >= MAX_TRANSIENT_AGE_MS;
        const terminalMissing = isTargetMissing
          && nextTargetMissingAttempts >= MAX_TARGET_MISSING_ATTEMPTS;
        const terminalRejected = isPermanent
          && nextPermanentAttempts >= MAX_ATTEMPTS;
        const terminalTransient = !isPermanent
          && !isTargetMissing
          && (
            nextTransientAttempts >= MAX_TRANSIENT_ATTEMPTS
            || transientAgeExceeded
          );
        if (!terminalMissing && !terminalRejected && !terminalTransient) {
          remainingOps.push({
            ...operationWithoutLifecycle(nextOperation),
            permanent_attempts: nextPermanentAttempts,
            transient_attempts: nextTransientAttempts,
            target_missing_attempts: nextTargetMissingAttempts,
            backoff_attempts: backoffAttempts,
            first_attempt_at: firstAttemptAt,
            last_attempt_at: attemptedAt,
            next_attempt_at: new Date(
              now.getTime() + retryDelayMs(backoffAttempts),
            ).toISOString(),
            last_error: outcome.error || 'entity mutation was not applied',
          });
          if (alignedEffects) remainingEffects.push(originalEffects[index]);
          continue;
        }
        const declarative = operationWithoutLifecycle(nextOperation);
        const reason = terminalMissing
          ? `target page missing after ${nextTargetMissingAttempts} identity lookup attempts`
          : terminalTransient
            ? `infrastructure failure persisted for ${nextTransientAttempts} attempts since `
              + `${firstAttemptAt}: ${outcome.error || 'entity engine unavailable'}`
            : (outcome.error || 'entity engine rejected the operation');
        deadLettered.push({
          dead_letter_id: deadLetterId(batch, declarative),
          dead_lettered_at: attemptedAt,
          batch_id: batch.id,
          scope: batch.scope,
          meeting_id: (batch.meeting_ids || [])[0] || null,
          meeting_ids: batch.meeting_ids || [],
          op_type: declarative.op,
          entity_path: declarative.path,
          entity_identity: declarative.entity_identity || null,
          failure_class: 'permanent',
          permanent_attempts: nextPermanentAttempts,
          transient_attempts: nextTransientAttempts,
          target_missing_attempts: nextTargetMissingAttempts,
          op: declarative,
          ...(batch.metadata ? { metadata: batch.metadata } : {}),
          reason,
          last_error: outcome.error || reason,
        });
      }
      batch.ops = remainingOps;
      if (alignedEffects) {
        batch.metadata = {
          ...batch.metadata,
          effects: remainingEffects,
        };
      }
      if (appliedOps.length > 0) {
        const completedBatch = {
          ...batch,
          ops: appliedOps,
        };
        if (alignedEffects) {
          completedBatch.metadata = {
            ...batch.metadata,
            effects: appliedEffects,
          };
        }
        completed.push(completedBatch);
      }
    }

    latest.batches = latest.batches.filter(
      batch => batch.ops.length > 0,
    );
    // Dead-letter append is idempotent by batch+operation identity. If the
    // process dies before the store save, replay skips the duplicate record.
    appendDeadLetters(vaultRoot, deadLettered);
    savePendingStore(vaultRoot, latest);
    return {
      completed,
      remaining: latest.batches,
      deadLettered,
    };
  });
}

function flushEntityOps({
  vaultRoot,
  ops = [],
  meetingIds = [],
  scope = 'default',
  scopes = null,
  metadata = null,
  env = process.env,
  spawnSync = childProcess.spawnSync,
  now = new Date(),
} = {}) {
  const root = path.resolve(vaultRoot);
  const nowDate = now instanceof Date ? now : new Date(now);
  if (Number.isNaN(nowDate.getTime())) {
    return failure('now must be a valid date');
  }
  const selectedScopes = new Set(scopes || [scope]);
  let currentBatch = null;
  let selected;
  let selectedBatchCount = 0;
  let deferredOperationCount = 0;
  try {
    ({
      currentBatch,
      selected,
      selectedBatchCount,
      deferredOperationCount,
    } = withPendingLock(root, () => {
      const store = loadPendingStore(root);
      let batch = null;
      if (ops.length > 0 || meetingIds.length > 0) {
        const id = batchId(scope, ops, meetingIds);
        batch = store.batches.find((candidate) => candidate.id === id);
        if (!batch) {
          batch = {
            id,
            scope,
            meeting_ids: [...new Set(meetingIds)].sort(),
            ops,
            ...(metadata === null ? {} : { metadata }),
          };
          store.batches.push(batch);
        }
      }
      savePendingStore(root, store);
      const scoped = store.batches.filter(
        candidate => selectedScopes.has(candidate.scope),
      );
      const due = scoped.map((candidate) => ({
        ...candidate,
        ops: candidate.ops.filter((operation) => {
          if (!operation.next_attempt_at) return true;
          const next = new Date(operation.next_attempt_at);
          return Number.isNaN(next.getTime()) || next <= nowDate;
        }),
      })).filter(candidate => candidate.ops.length > 0
        || store.batches.find(stored => stored.id === candidate.id)?.ops.length === 0);
      return {
        currentBatch: batch === null
          ? null
          : JSON.parse(JSON.stringify(batch)),
        selected: JSON.parse(JSON.stringify(due)),
        selectedBatchCount: scoped.length,
        deferredOperationCount: scoped.reduce(
          (count, candidate) => count + candidate.ops.length,
          0,
        ) - due.reduce(
          (count, candidate) => count + candidate.ops.length,
          0,
        ),
      };
    }));
  } catch (error) {
    return failure(error);
  }

  const failedSelected = (
    error,
    failureClass = 'transient',
    status = {},
  ) => {
    const message = error instanceof Error ? error.message : String(error);
    const outcomes = new Map(selected.map(batch => [
      batch.id,
      batch.ops.map(() => ({
        applied: false,
        error: message,
        failure_class: failureClass,
      })),
    ]));
    try {
      const settled = settleSelected(root, selected, outcomes, nowDate);
      return failure(error, {
        batch_id: currentBatch?.id || null,
        dead_lettered_ops: settled.deadLettered,
        ...status,
      });
    } catch (settlementError) {
      return failure(
        `${message}; failed to persist retry state: ${settlementError.message}`,
        { batch_id: currentBatch?.id || null },
      );
    }
  };

  const pendingOperationCount = selected.reduce(
    (count, batch) => count + batch.ops.length,
    0,
  );
  if (pendingOperationCount === 0) {
    if (selectedBatchCount > 0 && deferredOperationCount > 0) {
      return failure('Entity writes are waiting for their retry window', {
        batch_id: currentBatch?.id || null,
        dead_lettered_ops: [],
      });
    }
    let completed;
    let remaining;
    try {
      ({ completed, remaining } = withPendingLock(root, () => {
        const latest = loadPendingStore(root);
        const selectedIds = new Set(selected.map((batch) => batch.id));
        const done = latest.batches.filter((batch) => selectedIds.has(batch.id));
        latest.batches = latest.batches.filter((batch) => !selectedIds.has(batch.id));
        savePendingStore(root, latest);
        return { completed: done, remaining: latest.batches };
      }));
    } catch (error) {
      return failure(error);
    }
    return {
      ok: true,
      completed_meeting_ids: completedMeetingIds(completed, remaining),
      completed_batches: completed,
      results: [],
      batch_id: currentBatch?.id || null,
    };
  }

  const pythonStatus = resolveDexPythonStatus(root, env);
  const interpreter = pythonStatus.path;
  if (!interpreter) {
    return failedSelected(
      pythonStatus.user_message,
      'transient',
      pythonStatus,
    );
  }

  const snapshotOutcomes = new Map(selected.map(batch => [
    batch.id,
    batch.ops.map(() => null),
  ]));
  const materializedEntries = [];
  const materializationErrors = [];
  for (const batch of selected) {
    for (const [index, operation] of batch.ops.entries()) {
      try {
        const materialized = materializeOperation(operation, root);
        materializedEntries.push({
          batchId: batch.id,
          index,
          operation: materialized.operation,
          materialized: materialized.materialized,
        });
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        snapshotOutcomes.get(batch.id)[index] = {
          applied: false,
          error: message,
          failure_class: materializationFailureClass(error),
          failure_kind: error.failure_kind || 'materialization',
        };
        materializationErrors.push(message);
      }
    }
  }

  const failMaterialized = (error) => {
    const message = error instanceof Error ? error.message : String(error);
    for (const entry of materializedEntries) {
      snapshotOutcomes.get(entry.batchId)[entry.index] = {
        applied: false,
        error: message,
        operation: entry.operation,
        failure_class: 'transient',
      };
    }
    try {
      const settled = settleSelected(root, selected, snapshotOutcomes, nowDate);
      return failure(error, {
        batch_id: currentBatch?.id || null,
        dead_lettered_ops: settled.deadLettered,
      });
    } catch (settlementError) {
      return failure(
        `${message}; failed to persist retry state: ${settlementError.message}`,
        { batch_id: currentBatch?.id || null },
      );
    }
  };

  if (materializedEntries.length === 0) {
    return failMaterialized(
      materializationErrors[0] || 'No entity operation could be materialized',
    );
  }

  const batchResults = new Map();
  const executionErrors = [];
  for (let offset = 0; offset < materializedEntries.length; offset += CLI_CHUNK_SIZE) {
    const chunk = materializedEntries.slice(offset, offset + CLI_CHUNK_SIZE);
    const markChunkTransient = (error) => {
      const message = error instanceof Error ? error.message : String(error);
      executionErrors.push(message);
      for (const entry of chunk) {
        snapshotOutcomes.get(entry.batchId)[entry.index] = {
          applied: false,
          error: message,
          operation: entry.operation,
          failure_class: 'transient',
          failure_kind: 'infrastructure',
        };
      }
    };
    let execution;
    try {
      execution = spawnSync(
        interpreter,
        ['-m', 'core.entity_engine.cli'],
        {
          cwd: root,
          encoding: 'utf8',
          // `core` ships inside a real vault (importable from cwd=root), but when the
          // engine lives separately (tests, split-repo layouts) DEX_REPO_ROOT points at
          // it — put both on PYTHONPATH so `-m core.entity_engine.cli` always resolves.
          env: {
            ...env,
            VAULT_PATH: root,
            PYTHONPATH: [env.DEX_REPO_ROOT, root, env.PYTHONPATH]
              .filter(Boolean)
              .join(path.delimiter),
          },
          input: JSON.stringify({
            ops: chunk.map(entry => cliOperation(entry.materialized)),
          }),
          maxBuffer: (1024 * 1024) + (chunk.length * 128 * 1024),
          timeout: 30_000 + (chunk.length * 1000),
        },
      );
    } catch (error) {
      markChunkTransient(error);
      continue;
    }
    if (execution.error || execution.status !== 0 || execution.signal) {
      const signal = execution.signal ? ` (signal ${execution.signal})` : '';
      markChunkTransient(
        execution.error
          || execution.stderr
          || `Entity CLI exited ${execution.status}${signal}`,
      );
      continue;
    }

    let response;
    try {
      if (typeof execution.stdout !== 'string' || !execution.stdout.trim()) {
        throw new Error('Entity CLI returned empty stdout');
      }
      response = JSON.parse(execution.stdout);
      if (!Array.isArray(response.results)
          || response.results.length !== chunk.length) {
        throw new Error('Entity CLI returned an invalid result count');
      }
    } catch (error) {
      markChunkTransient(error);
      continue;
    }

    for (const [resultIndex, entry] of chunk.entries()) {
      const result = response.results[resultIndex];
      if (!batchResults.has(entry.batchId)) batchResults.set(entry.batchId, []);
      batchResults.get(entry.batchId).push({ index: entry.index, result });
      const wasApplied = applied(entry.materialized, result);
      const targetMissing = !wasApplied && result?.status === 'missing';
      snapshotOutcomes.get(entry.batchId)[entry.index] = {
        applied: wasApplied,
        operation: entry.operation,
        error: result?.status
          ? `Entity CLI returned ${result.status}`
          : 'Entity CLI returned no result',
        failure_class: wasApplied ? null : targetMissing ? 'transient' : 'permanent',
        failure_kind: wasApplied ? null : targetMissing ? 'target_missing' : 'op_rejected',
      };
    }
  }

  let completed;
  let remaining;
  let deadLettered;
  try {
    ({ completed, remaining, deadLettered } = settleSelected(
      root,
      selected,
      snapshotOutcomes,
      nowDate,
    ));
  } catch (error) {
    return failure(error, { batch_id: currentBatch?.id || null });
  }
  const completedIds = new Set(completed.map((batch) => batch.id));
  const remainingIds = new Set(remaining.map((batch) => batch.id));
  const deadLetteredIds = new Set(
    deadLettered.map((entry) => entry.batch_id),
  );
  const scopedRemaining = remaining.some(
    batch => selectedScopes.has(batch.scope),
  );

  return {
    ok: !scopedRemaining && selected.every((batch) => completedIds.has(batch.id)
      && !remainingIds.has(batch.id)
      && !deadLetteredIds.has(batch.id)),
    completed_meeting_ids: completedMeetingIds(
      completed,
      remaining,
      deadLettered,
    ),
    completed_batches: completed,
    results: currentBatch
      ? (batchResults.get(currentBatch.id) || [])
        .sort((left, right) => left.index - right.index)
        .map(item => item.result)
      : [],
    batch_id: currentBatch?.id || null,
    dead_lettered_ops: deadLettered,
    ...((executionErrors[0] || materializationErrors[0])
      ? { error: executionErrors[0] || materializationErrors[0] }
      : {}),
  };
}

module.exports = {
  fingerprintText,
  flushEntityOps,
  loadDeadLetters,
  loadPendingStore,
  deadLetterPath,
  pendingStorePath,
  requeueDeadLetters,
  resultApplied: applied,
  withPendingLock,
};
