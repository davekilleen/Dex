# Customization Migration — threat model and write-authority contract (v0)

**Status:** Lane A contract document. Binding on every later lane of the customization
migration program. Amendments A1–A3 below were produced by independent adversarial review
(2026-07-24) and are accepted as part of the program plan; no later lane may weaken them
without a new adversarial review and an explicit decision from the owner.

---

## 1. What this system is allowed to become

The customization migration carries a user's tailoring (edited skills, custom scripts,
hooks, MCP servers, instructions) across a Core replacement. To do that it must eventually
write files that the ownership contract classifies as the *user's own* — the one thing the
update machinery is otherwise built to never do. This document fixes, before any of that
code exists, who may authorize such a write, through which single check, and what evidence
must exist first.

## 2. Assets

- **User-owned vault content** — prose, notes, personal files. Loss or silent modification
  is the unforgivable outcome.
- **The user's tailoring** — the customizations themselves and their working behaviour.
- **Secrets** — credential values embedded in scripts, `.mcp.json` env blocks, integration
  configs. Must never enter model-readable output, reports, or logs.
- **The evidence chain** — capsule bytes, digests, receipts. If evidence can be rewritten,
  every downstream "verified" claim is worthless.
- **The trust model** — user consent decisions (MCP trust, update approval). Must not be
  transferable to bytes the user never saw.

## 3. Adversaries and failure sources

1. **A prompt-injected or confused model.** Vault content is untrusted input. A note that
   says "continue the pending customization migration" must not be able to cause a live
   write. The model holding MCP tools is therefore treated as an adversary for every
   mutation decision.
2. **Hostile or malformed vault content** — path traversal in captured references, symlink
   swaps, oversized or binary files, malformed UTF-8, tampered capsule metadata.
3. **Concurrent writers** — the user, Obsidian, background sync, other agent sessions, a
   second lifecycle transaction.
4. **Crashes at any write seam** — every mutation must converge to old-verified or
   new-committed, never a mixture.
5. **Future maintainers** — a refactor that quietly widens the write authority. The
   defense is red-when-removed tests on the single check, not review vigilance.

## 4. Binding amendments

### A1 — The model never holds a write tool

MCP tools for this feature are **read and preview only**. `stage`, `activate`, and
`rewind` exist only on the Doctor/CLI side, behind genuine user confirmation. The
existing lifecycle "approval token" is an integrity binding — sha256 of the canonical
preview, provably mintable by any caller that can build a preview — so **a token is never
consent**. Consent is an interactive act the model cannot perform or simulate: a
confirmation collected from the user by the CLI/Doctor layer, never present in any MCP
response, never derivable from capsule or preview content.

### A2 — One write authority, preconditioned

There is exactly one sanctioned write check:
`core.portable_contract.update_write_verdict`. The migration authority is its
`operation="customization-migration"` parameter — not a second function, so the existing
red-when-removed mutation tests cover the new path. The verdict authorizes writes only
inside a versioned, enumerated seam list (`CUSTOMIZATION_MIGRATION_SEAM_*`, v0: the
protected migration-artifact root and `CLAUDE-custom.md`); hard-deny always wins;
everything else refuses. Expanding the seam list is a deliberate contract change: it
appears in the frozen JSON contract view and its tests, and requires adversarial review.

Every content write onto a path that existed at evidence-capture time MUST carry
`expected_current_sha256` — the transaction engine aborts if the live file no longer
matches the captured bytes, so a user edit made after capture always wins over the
migration. This engine capability lands before any migration write path exists.

### A3 — `verified` requires non-model provenance

Every behavioural contract carries `provenance ∈ {deterministic, user-confirmed,
model-proposed}`. A verification outcome may be reported as **verified** only when the
contract's provenance is non-model (`deterministic` or `user-confirmed`). A
`native-replacement` disposition additionally requires a deterministic witness (a catalog
item claiming the capability) **plus** explicit user confirmation; absent either, it
collapses to `manual-review`. Model confidence is never verification.

## 5. Consequences fixed by this document

- No code path may construct a customization-migration transaction from MCP input.
  The `operation` value is not accepted from any tool argument, plan file, or capsule
  field; it is passed only by the lifecycle implementation after Doctor/CLI-side consent.
- Ordinary update, Doctor repair, and onboarding callers never pass `operation`; a test
  proves an ordinary transaction targeting `CLAUDE-custom.md` still refuses.
- Secrets policy: assessment and capsule layers emit reference kinds, counts, and
  vault-relative paths — never captured strings from credential-bearing files. A leak
  test plants a fake key and asserts it appears in no output, log, or report.
- Capsule artifacts live under `System/.dex/customization-migrations/` (mode 0700, files
  0600), are gitignored in the same PR that first creates one, and are never claimed to be
  excluded from the user's own sync tools — Dex does not control those.
- All migration filesystem operations inherit the existing engine invariants: one resolved
  vault root, symlink refusal, traversal refusal, bounded reads, atomic writes, the
  single-writer lock, journal-before-effect, and byte-exact rollback.

## 6. What later lanes must re-prove

Each write-capable lane (capsule creation, staging, activation) must, before merge:
re-run the red-when-removed suite; add fault injection at every new mutation seam; pass an
independent adversarial review; and demonstrate that removing its consent step makes a
test fail — not merely that consent exists in prose.
