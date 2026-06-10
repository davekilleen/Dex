'use strict';
/**
 * fs-safe.cjs: crash-safe filesystem primitives for the connection manager.
 *
 * writeFileAtomic(filePath, data, { mode }): temp-file + rename in the SAME
 * directory, so a crash mid-write can never leave a truncated/partial file at
 * the real path: readers see the old contents or the new contents, never a mix.
 * The temp file is created fresh on every write, so the requested mode (0600)
 * is applied every time, unlike fs.writeFileSync, whose `mode` only applies
 * when the target file is first created, never on overwrite.
 *
 * Stale `.tmp` files from a crashed writer are inert: they live in the
 * credentials directory (gitignored with `*`) and are never read back.
 *
 * withLockSync / withLock: a dependency-free cross-process mutex built on
 * exclusive lockfile creation (open with O_CREAT|O_EXCL, atomic on every
 * filesystem Node supports). Semantics:
 *
 *  - The lockfile contains JSON { pid, createdAt }. Holding the file = holding
 *    the lock. Release = unlink (always in a finally, so a throw releases too).
 *  - Waiters poll (25-50ms). Sync callers block via Atomics.wait; async callers
 *    poll on setTimeout so they never block the event loop while waiting.
 *  - Staleness: a lock whose holder PID is no longer alive is stolen
 *    immediately (covers kill -9 / crashed processes). An unreadable lockfile
 *    older than 30s, or ANY lockfile older than 10 minutes, is also stolen
 *    (backstop for PID reuse and clock weirdness). Steal = unlink + re-race;
 *    O_EXCL guarantees exactly one stealer wins.
 *  - Acquisition times out (default 10s) with a clear error rather than ever
 *    proceeding unlocked.
 *  - Reentrant per (process, lockfile path): nested withLock calls on the same
 *    path run immediately. This makes the lock a CROSS-PROCESS mutex; within a
 *    process, Node's single thread serializes the (synchronous) critical
 *    sections that mutate store files.
 *  - Scope: same-machine processes only. PID liveness checks are host-local,
 *    so a credentials dir on shared/synced storage is not protected across
 *    hosts (the 10-minute backstop is the only guard there).
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

/**
 * Atomically write `data` to `filePath`:
 *   1. write to `.<basename>.<pid>.<rand>.tmp` in the same directory (fresh file, exact mode)
 *   2. fsync the temp file so the data is on disk before it becomes visible
 *   3. rename over the real path (atomic on POSIX)
 */
function writeFileAtomic(filePath, data, { mode = 0o600 } = {}) {
  const dir = path.dirname(filePath);
  const tmp = path.join(dir, `.${path.basename(filePath)}.${process.pid}.${crypto.randomBytes(4).toString('hex')}.tmp`);
  const fd = fs.openSync(tmp, 'wx', mode);
  try {
    fs.writeSync(fd, data);
    fs.fchmodSync(fd, mode); // exact permissions regardless of umask
    fs.fsyncSync(fd); // data hits disk before the rename publishes it
  } finally {
    fs.closeSync(fd);
  }
  // Test-only fault injection: simulate a crash BETWEEN the temp write and the
  // rename (the window the atomic path exists to protect). Never set outside tests.
  if (process.env.DEX_CM_TEST_CRASH_BEFORE_RENAME === '1') {
    process.exit(42);
  }
  try {
    fs.renameSync(tmp, filePath);
  } catch (err) {
    try {
      fs.unlinkSync(tmp);
    } catch {
      /* best effort */
    }
    throw err;
  }
}

// ---- Cross-process lock ------------------------------------------------------

const ACQUIRE_TIMEOUT_MS = 10_000; // default wait for the lock before erroring
const UNREADABLE_STALE_MS = 30_000; // unreadable lockfile older than this is stale
const HARD_STALE_MS = 10 * 60 * 1000; // absolute backstop: no lock lives longer

// Reentrancy bookkeeping: how many times THIS process currently holds each lock path.
const _heldDepth = new Map();

function pidAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return err.code === 'EPERM'; // exists but owned by someone else
  }
}

/** One non-blocking acquisition attempt. Returns true if we now hold the lock. */
function tryAcquire(lockPath) {
  try {
    const fd = fs.openSync(lockPath, 'wx', 0o600);
    try {
      fs.writeSync(fd, JSON.stringify({ pid: process.pid, createdAt: Date.now() }));
    } finally {
      fs.closeSync(fd);
    }
    return true;
  } catch (err) {
    if (err.code !== 'EEXIST') throw err;
  }
  // Lock exists. Decide whether it is stale enough to steal.
  let ageMs = null;
  let holderPid = null;
  try {
    ageMs = Date.now() - fs.statSync(lockPath).mtimeMs;
    holderPid = Number(JSON.parse(fs.readFileSync(lockPath, 'utf8')).pid) || null;
  } catch {
    // Race (deleted between attempts) or unreadable content; handled below.
  }
  const stale =
    (holderPid !== null && !pidAlive(holderPid)) ||
    (holderPid === null && ageMs !== null && ageMs > UNREADABLE_STALE_MS) ||
    (ageMs !== null && ageMs > HARD_STALE_MS);
  if (stale) {
    try {
      fs.unlinkSync(lockPath);
    } catch {
      /* someone else stole it first */
    }
  }
  return false;
}

function sleepSync(ms) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

function pollDelay() {
  return 25 + Math.floor(Math.random() * 25); // jitter so contenders don't lock-step
}

function timeoutError(lockPath, timeoutMs) {
  return new Error(
    `Could not lock the connection store within ${timeoutMs}ms (another Dex process is holding ${path.basename(lockPath)}). ` +
      'Try again in a moment.'
  );
}

function acquireSync(lockPath, timeoutMs) {
  fs.mkdirSync(path.dirname(lockPath), { recursive: true, mode: 0o700 });
  const start = Date.now();
  while (!tryAcquire(lockPath)) {
    if (Date.now() - start > timeoutMs) throw timeoutError(lockPath, timeoutMs);
    sleepSync(pollDelay());
  }
}

async function acquireAsync(lockPath, timeoutMs) {
  fs.mkdirSync(path.dirname(lockPath), { recursive: true, mode: 0o700 });
  const start = Date.now();
  while (!tryAcquire(lockPath)) {
    if (Date.now() - start > timeoutMs) throw timeoutError(lockPath, timeoutMs);
    await new Promise((resolve) => setTimeout(resolve, pollDelay()));
  }
}

function release(lockPath) {
  try {
    fs.unlinkSync(lockPath);
  } catch {
    /* already gone (stolen as stale after a long pause); nothing to release */
  }
}

/** Run `fn` while holding the cross-process lock at `lockPath` (synchronous). */
function withLockSync(lockPath, fn, { timeoutMs = ACQUIRE_TIMEOUT_MS } = {}) {
  if ((_heldDepth.get(lockPath) || 0) > 0) return fn(); // reentrant within this process
  acquireSync(lockPath, timeoutMs);
  _heldDepth.set(lockPath, 1);
  try {
    return fn();
  } finally {
    _heldDepth.set(lockPath, 0);
    release(lockPath);
  }
}

/** Run async `fn` while holding the cross-process lock at `lockPath` (waiters don't block the event loop). */
async function withLock(lockPath, fn, { timeoutMs = ACQUIRE_TIMEOUT_MS } = {}) {
  if ((_heldDepth.get(lockPath) || 0) > 0) return fn(); // reentrant within this process
  await acquireAsync(lockPath, timeoutMs);
  _heldDepth.set(lockPath, 1);
  try {
    return await fn();
  } finally {
    _heldDepth.set(lockPath, 0);
    release(lockPath);
  }
}

module.exports = { writeFileAtomic, withLockSync, withLock };
