'use strict';

function stripCheckbox(text) {
  return String(text || '').replace(/^\s*[-*]\s+\[[ xX]\]\s*/, '').trim();
}

function assignedPerson(text) {
  const stripped = stripCheckbox(text);
  const withColon = stripped.match(/^@\[?([^\]\n]+?)\]?\s*:/);
  if (withColon) return withColon[1].trim();
  const bare = stripped.match(/^@([^\s@:[]+)/);
  if (bare) return bare[1].trim();
  return null;
}

function isOwnerAssignment(name, ownerName) {
  if (!name || !ownerName) return false;
  const assigned = name.toLowerCase();
  const owner = String(ownerName).trim().toLowerCase();
  if (!owner) return false;
  const first = owner.split(/\s+/)[0];
  return assigned === owner || assigned === first;
}

function routeBucket(text, ownerName) {
  const name = assignedPerson(text);
  if (!name) return 'me';
  return isOwnerAssignment(name, ownerName) ? 'me' : 'others';
}

function isCheckbox(line) {
  return /^\s*[-*]\s+\[[ xX]\]\s+/.test(line);
}

function routeAtMentionActionItems(markdown, ownerName = '') {
  const lines = String(markdown || '').split('\n');
  const prefix = [];
  const forMe = [];
  const forOthers = [];
  const suffix = [];
  let region = 'prefix';
  let sawActionItems = false;
  let sawForMe = false;

  for (const line of lines) {
    if (/^##\s+Action Items\s*$/i.test(line)) {
      sawActionItems = true;
      prefix.push(line);
      region = 'action-items';
      continue;
    }
    if (sawActionItems && region !== 'suffix' && /^##\s+\S/.test(line)) {
      region = 'suffix';
      suffix.push(line);
      continue;
    }
    if (region === 'action-items' || region === 'for-me' || region === 'for-others') {
      if (/^###\s+For Me\s*$/i.test(line)) {
        sawForMe = true;
        region = 'for-me';
        continue;
      }
      if (/^###\s+For Others\s*$/i.test(line)) {
        region = 'for-others';
        continue;
      }
      if (region === 'for-me') {
        if (isCheckbox(line) && routeBucket(line, ownerName) === 'others') {
          forOthers.push(line);
        } else {
          forMe.push(line);
        }
        continue;
      }
      if (region === 'for-others') {
        forOthers.push(line);
        continue;
      }
      prefix.push(line);
      continue;
    }
    if (region === 'suffix') suffix.push(line);
    else prefix.push(line);
  }

  if (!sawActionItems || !sawForMe) return markdown;

  while (forMe.length && forMe[forMe.length - 1].trim() === '') forMe.pop();
  while (forOthers.length && forOthers[forOthers.length - 1].trim() === '') forOthers.pop();

  const out = [...prefix];
  out.push('### For Me');
  if (forMe.length) out.push(...forMe);
  out.push('');
  out.push('### For Others');
  if (forOthers.length) out.push(...forOthers);
  if (suffix.length) {
    out.push('');
    out.push(...suffix);
  }
  return out.join('\n');
}

module.exports = {
  assignedPerson,
  routeBucket,
  routeAtMentionActionItems,
};
