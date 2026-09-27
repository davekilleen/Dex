# Windows contained writes — design note (not an implementation)

**Status:** Design only. This document does not authorise changing hashes, relaxing
no-follow / exclusive-create / mode checks, or landing a Windows write path.

**Date:** 2026-09-27

**Scope:** `core/utils/credential_remediation.py`, `core/utils/integration_credentials.py`,
`core/utils/trust_registry.py`, and the three byte-identical
`protect_trust_registry.py` copies (`.claude/skills`, `.agents/skills`,
`packages/dex-agent-plugin`).

**Companion PR:** fail-closed refusal on Windows; POSIX writers unchanged.

---

## Why O_BINARY is not the fix

The reported Windows 11 / Git Bash (`OSTYPE=cygwin`) install failed on Dex 1.97.15. The
obvious CRT issue is that `os.open` without `O_BINARY` can translate LF to CRLF.

That is not the first failure. These modules walk vault paths with POSIX-only
`dir_fd`, `O_NOFOLLOW`, and `O_DIRECTORY`. On native Windows those flags and
`os.supports_dir_fd` are missing. The chain either raises `AttributeError` /
`NotImplementedError` (`fchmod`, `getuid`, `dir_fd`) or — worse —
`getattr(os, "O_NOFOLLOW", 0)` proceeds without no-follow.

Adding `O_BINARY` to a write that already cannot open a no-follow directory
descriptor does not create a safe writer. Adding `O_BINARY` to **reads** of
blessed MCP scripts or `System/trusted-mcps.yaml` would change the SHA-256 that
`protect_trust_registry.py` (three copies) and `TrustedMcpEntry.sha256` compare.
This design forbids that until a migration is reviewed.

---

## 1. Windows-safe, no-follow, race-safe directory chain

POSIX today (must stay the only live writer):

1. Open the vault root `O_RDONLY | O_DIRECTORY | O_NOFOLLOW`.
2. For each path component, `stat(..., follow_symlinks=False)` then `open(..., dir_fd=..., O_NOFOLLOW)`.
3. Exclusive-create a random same-directory temp (`O_CREAT | O_EXCL`, plus `O_NOFOLLOW` where the site already has it).
4. Write, `fchmod`, `fsync`, `os.replace` via `dir_fd`, `fsync` the directory, read back through the same no-follow fd.

Windows cannot use that API. A future implementation must be **as strong as**
that chain, not a pathname fallback:

1. Open each component with `FILE_FLAG_OPEN_REPARSE_POINT` (do not follow
   symlinks or junctions). Refuse `FILE_ATTRIBUTE_REPARSE_POINT`.
2. Hold a directory handle across the walk. Identify each handle with
   `GetFileInformationByHandle` (volume serial + file index), and compare
   before/after like today’s `(st_dev, st_ino)` pin.
3. Exclusive-create temps with `CREATE_NEW` on a 128-bit random name in the
   already-opened directory. Confirm the opened handle is still that name’s
   unfollowed identity **before** writing secret or hashed bytes.
4. Atomic replace must stay same-directory replace of that handle’s name.
   Do not write through a user-supplied path string after the walk.
5. `O_NOFOLLOW` on POSIX is never dropped. A Windows helper is an additional
   implementation, not an `#ifdef` that removes the POSIX flag.

Until that lands, Windows must **refuse** contained writes and reads that
depend on this chain.

---

## 2. Permission handling

POSIX `0600` / `0400` / `0700` are not Windows access control. The CRT maps
mode bits to the read-only attribute. A writable file often stats as `0o666`.

Honest options (pick one in a later reviewed change; do not mix them):

| Option | Meaning |
|---|---|
| Fail closed | Require the POSIX primitives (`fchmod`, owner-only mode, `getuid`). Windows refuses. **This is the current authorised behaviour.** |
| Windows ACL writer | After exclusive create, set a DACL that is owner-only (no Users/Everyone write), then verify with `GetSecurityInfo`. Do not treat `0o666` as `0o600`. |
| Dual assertion | On POSIX, keep exact `S_IMODE` / uid / gid. On Windows, assert the DACL and owner SID. Never skip both. |

Forbidden: skip the mode/owner check on Windows and still tell the user the
file is `0600`. Forbidden: accept group/other-writable POSIX bits on macOS or
Linux because Windows cannot enforce them.

---

## 3. Digest migration (trust registry)

Blessed identity is `sha256` of the bytes `os.read` returned from a no-follow
fd. `protect_trust_registry.py` exists in three places and must stay
byte-identical. Changing read or write text-mode changes every digest.

Options if a later change needs binary I/O on Windows:

1. **Re-bless (preferred).** Keep one hash. After switching both read and write
   to binary, every registry entry is invalid until the user re-blesses.
   `/create-mcp` and the three `protect_trust_registry` copies stay one
   algorithm. No silent accept of a second digest.
2. **Dual hash, fail closed.** Store `sha256` (current) and later
   `sha256_binary` only after an explicit registry schema bump. Recurring
   startup requires a match on the algorithm that produced the snapshot.
   Refuse mixed or missing fields. Heavier; only if re-bless is impossible.
3. **Line-ending normalize before hash.** Rejected. Two on-disk files would
   bless to one digest. That is an identity change, not a portability fix.

Do not land `O_BINARY` on trust-registry **reads** in the same change as
Windows writers. Do not change `protect_trust_registry.py` until the chosen
option is implemented in all three copies together.

Credential journals already hash exact image bytes in-process. A Windows
writer that emits different on-disk bytes than those images would fail
readback — another reason to refuse until the directory chain exists.

---

## What this PR implements

- POSIX: same flags, same mode/owner checks, same hashes, same exclusive
  create. The new availability check is true on macOS/Linux and returns
  without changing the open/write path.
- Windows (and any host missing `O_NOFOLLOW` / `dir_fd` / `fchmod`): fail
  closed with a logged reason (`os.name`, which primitive is missing). No
  secret or registry bytes in the log. No crash on `fchmod` / `getuid`.
- No `O_BINARY`, no digest change, no skipped POSIX control.
