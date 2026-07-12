'use strict';

function getMeetingProcessingMode(meetingProcessing) {
  const mode = typeof meetingProcessing === 'string'
    ? meetingProcessing
    : meetingProcessing?.mode;
  return mode === 'manual' || mode === 'automatic' ? mode : 'automatic';
}

module.exports = { getMeetingProcessingMode };
