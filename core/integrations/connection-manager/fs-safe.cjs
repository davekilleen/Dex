'use strict';
/**
 * fs-safe.cjs — crash-safe filesystem primitives for the connection manager.
 *
 * writeFileAtomic(filePath, data, { mode }) — temp-file + rename in the SAME
 * directory, so a crash mid-write can never leave a truncated/partial file at
 * the real path: readers see the old contents or the new contents, never a mix.
 * The temp file is created fresh on every write, so the requested mode (0600)
 * is applied every time — unlike fs.writeFileSync, whose `mode` only applies
 * when the target file is first created, never on overwrite.
 *
 * Stale `.tmp` files from a crashed writer are inert: they live in the
 * credentials directory (gitignored with `*`) and are never read back.
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

module.exports = { writeFileAtomic };
