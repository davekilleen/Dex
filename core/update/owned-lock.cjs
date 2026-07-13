'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

function fsyncDirectory(directory) {
  let descriptor;
  try {
    descriptor = fs.openSync(directory, 'r');
    fs.fsyncSync(descriptor);
  } finally {
    if (descriptor !== undefined) fs.closeSync(descriptor);
  }
}

function processIsRunning(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error.code === 'EPERM';
  }
}

function readSnapshot(lock) {
  let descriptor;
  try {
    descriptor = fs.openSync(lock, 'r');
    const stat = fs.fstatSync(descriptor);
    const raw = fs.readFileSync(descriptor, 'utf8');
    let payload = null;
    try {
      payload = JSON.parse(raw);
    } catch {
      // Malformed data has no live owner, but its exact bytes and inode still guard removal.
    }
    return { device: stat.dev, inode: stat.ino, payload, raw };
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  } finally {
    if (descriptor !== undefined) fs.closeSync(descriptor);
  }
}

function sameSnapshot(left, right) {
  return Boolean(
    left
    && right
    && left.device === right.device
    && left.inode === right.inode
    && left.raw === right.raw,
  );
}

function removeIfUnchanged(lock, observed) {
  const current = readSnapshot(lock);
  if (!sameSnapshot(observed, current)) return false;
  fs.unlinkSync(lock);
  fsyncDirectory(path.dirname(lock));
  return true;
}

function acquireOwnedLock(lock, kind, busyMessage) {
  fs.mkdirSync(path.dirname(lock), { recursive: true });
  const token = crypto.randomBytes(24).toString('hex');
  for (let attempt = 0; attempt < 32; attempt += 1) {
    let descriptor;
    try {
      descriptor = fs.openSync(lock, 'wx', 0o600);
      const payload = `${JSON.stringify({
        pid: process.pid,
        kind,
        token,
        at: new Date().toISOString(),
      })}\n`;
      fs.writeFileSync(descriptor, payload);
      fs.fsyncSync(descriptor);
      const stat = fs.fstatSync(descriptor);
      fs.closeSync(descriptor);
      descriptor = undefined;
      fsyncDirectory(path.dirname(lock));
      return () => {
        const current = readSnapshot(lock);
        if (
          current?.payload?.token === token
          && current.device === stat.dev
          && current.inode === stat.ino
        ) {
          fs.unlinkSync(lock);
          try {
            fsyncDirectory(path.dirname(lock));
          } catch {
            // Restore may have removed the now-empty runtime directory.
          }
        }
      };
    } catch (error) {
      if (descriptor !== undefined) fs.closeSync(descriptor);
      if (error.code !== 'EEXIST') throw error;
      const observed = readSnapshot(lock);
      if (!observed) continue;
      if (processIsRunning(observed.payload?.pid)) {
        throw new Error(busyMessage(observed.payload.pid));
      }
      if (!removeIfUnchanged(lock, observed)) continue;
    }
  }
  throw new Error('Dex could not safely acquire its update lock because ownership kept changing. Wait a moment, then retry.');
}

module.exports = { acquireOwnedLock };
