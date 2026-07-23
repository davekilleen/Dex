'use strict';

function meetingId(candidate) {
  return candidate?.meeting?.id || candidate?.id;
}

function beginEntityPhase(state, meetings) {
  if (!state.processedMeetings || typeof state.processedMeetings !== 'object') {
    state.processedMeetings = {};
  }
  for (const meeting of meetings) {
    const id = meetingId(meeting);
    if (!id) continue;
    state.processedMeetings[id] = {
      ...(state.processedMeetings[id] || {}),
      entity_phase: 'pending',
    };
  }
}

function completeEntityPhases(state, meetingIds) {
  for (const id of meetingIds || []) {
    if (!state.processedMeetings?.[id]) continue;
    state.processedMeetings[id].entity_phase = 'complete';
  }
}

function deadLetterMeetingIds(entries) {
  return new Set(
    (Array.isArray(entries) ? entries : [])
      .flatMap(entry => entry.meeting_ids || [entry.meeting_id])
      .filter(Boolean),
  );
}

function reconcileEntityPhases(state, entityWrite = {}) {
  completeEntityPhases(state, entityWrite.completed_meeting_ids);
  const deadIds = deadLetterMeetingIds(entityWrite.dead_lettered_ops);
  for (const id of deadIds) {
    const record = state.processedMeetings?.[id];
    if (!record) continue;
    const entry = (entityWrite.dead_lettered_ops || []).find(
      candidate => (candidate.meeting_ids || [candidate.meeting_id]).includes(id),
    );
    record.entity_phase = 'failed';
    record.entity_terminal = true;
    record.entity_error = entry?.reason
      || entry?.last_error
      || 'entity write failed permanently';
  }
  for (const id of entityWrite.completed_meeting_ids || []) {
    const record = state.processedMeetings?.[id];
    if (!record || deadIds.has(id)) continue;
    delete record.entity_terminal;
    delete record.entity_error;
  }
}

function retryableEntityMeetings(state) {
  return Object.values(state.processedMeetings || {})
    .filter(record => (
      record?.entity_phase === 'pending'
      || (record?.entity_phase === 'failed' && record.entity_terminal !== true)
    ) && record.entity_payload?.id)
    .map(record => record.entity_payload);
}

function entityWriteMessage(entityWrite = {}) {
  const dead = Array.isArray(entityWrite.dead_lettered_ops)
    ? entityWrite.dead_lettered_ops
    : [];
  if (dead.length > 0) {
    const noun = dead.length === 1 ? 'entity write' : 'entity writes';
    return `${dead.length} ${noun} failed permanently. Run /dex-doctor and inspect `
      + 'System/.dex/entity-dead-letter.jsonl for the affected page, meeting, and operation.';
  }
  if (entityWrite.ok === false) {
    return `Entity writes remain pending and will retry after backoff: ${
      entityWrite.error || 'engine operation did not apply'
    }`;
  }
  return null;
}

function retryEntityPhases(state, profile, {
  processEntityCreation,
  persistState,
  logger = () => {},
  now = new Date(),
  deadLetteredOps = [],
} = {}) {
  if (typeof processEntityCreation !== 'function') {
    throw new TypeError('processEntityCreation must be a function');
  }
  if (typeof persistState !== 'function') {
    throw new TypeError('persistState must be a function');
  }
  const meetings = retryableEntityMeetings(state);
  const emitted = new Set();
  const emit = (message) => {
    emitted.add(message);
    logger(message);
  };
  for (const meeting of meetings) {
    const record = state.processedMeetings[meeting.id];
    record.entity_phase = 'pending';
    delete record.entity_terminal;
  }
  let result;
  try {
    result = processEntityCreation(
      meetings,
      profile,
      message => emit(message),
      { now },
    );
    const currentDeadLetters = result.entity_write?.dead_lettered_ops || [];
    result.entity_write.dead_lettered_ops = [
      ...deadLetteredOps,
      ...currentDeadLetters,
    ];
    reconcileEntityPhases(state, result.entity_write);
  } catch (error) {
    for (const meeting of meetings) {
      const record = state.processedMeetings[meeting.id];
      record.entity_phase = 'failed';
      record.entity_terminal = false;
      record.entity_error = error.message;
    }
    result = {
      entity_write: {
        ok: false,
        completed_meeting_ids: [],
        dead_lettered_ops: [],
        error: error.message,
      },
    };
  }
  persistState(state);
  const message = entityWriteMessage(result.entity_write);
  if (message && !emitted.has(message)) emit(message);
  return result;
}

module.exports = {
  beginEntityPhase,
  completeEntityPhases,
  entityWriteMessage,
  reconcileEntityPhases,
  retryableEntityMeetings,
  retryEntityPhases,
};
