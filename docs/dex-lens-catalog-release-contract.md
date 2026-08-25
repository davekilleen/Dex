# The Dex Lens catalogue release contract

**Status:** in force. Every stable release must satisfy it; CI refuses the release
otherwise.

---

## In plain English

Dex Lens looks at the AI system someone has built for themselves and shows which
proven Dex capabilities would make it stronger. The list of capabilities it draws
on — the catalogue — is published by Dex Core as a signed file attached to each
release. heydex.ai fetches that file within about fifteen minutes of a release and
checks the signature before serving it to anyone.

That makes the file part of the release, not a nice-to-have alongside it. A
release that ships without it leaves every Lens user looking at the previous
release's catalogue, with nothing anywhere to say why. A release that ships one
the signature does not cover is worse: heydex.ai rejects it, and the same silent
staleness follows.

So the rule is short: **no signed catalogue, no release.**

---

## The rule

Every stable release **must** attach both of:

- `dex-lens-catalog-v<version>.json` — the signed catalogue envelope
- `dex-lens-catalog-v<version>.json.sha256` — its checksum sidecar

The envelope must be signed with the Ed25519 key held in the
`DEX_LENS_CATALOG_ED25519_PRIVATE_KEY_B64` repository secret, under key id
`dex-core-lens-1`.

**Key handling does not change and must not change.** The private key exists only
as that CI secret. It is never written to the repository, never printed, never
committed to a file in a build, and never exported from the release job. Where a
signature has to be *verified* rather than made, the verifying half is derived in
memory from the same secret (or supplied separately as a public key) and discarded
with the process.

---

## What enforces it

| Gate | Where | Refuses |
|---|---|---|
| `scripts/generate-dex-lens-catalog.py` | release job | a registry that cannot produce a trustworthy catalogue — stale source pins, unknown job or foundation references, a version with no CHANGELOG entry. It fails before it touches the signing key, so a broken registry never produces a signed file. |
| `scripts/check-lens-catalog-release-asset.py --dist dist` | release job, **before anything is attached** | a built catalogue that is missing, empty, does not match its checksum sidecar, is not the producer's canonical bytes, violates the vendored wire schema, is stamped for a different release, names a different signing key, is unsigned, or carries a signature that does not verify. This is the release-blocking gate. |
| `scripts/release_publish.py publish` | release job | a release where any asset — the catalogue included — is not attached, or does not read back byte-identical to what was built. It attaches, proves, and only then makes the release public. |
| `scripts/check-lens-catalog-release-asset.py --from-release` | release job, **after publishing** | the same checks against the bytes GitHub actually serves, so the claim is made about the released artefact and not only about the local copy. |
| the dry-run job in `ci.yml` | every PR touching the catalogue path | a change that would break generation or verification at release time. It signs with a throwaway key generated in the runner; the release key is never used on a pull request. |

There is no repository variable that switches any of this off. The earlier
`DEX_LENS_CATALOG_RELEASE_GATE_ENABLED` flag is gone: while it existed, a release
could ship with no catalogue at all and nothing would say so.

---

## When the gate fails

The failure message names the exact reason. The common ones:

- **"the signed Lens catalogue is missing"** — generation did not run or wrote
  elsewhere. Check the "Generate signed Dex Lens catalog" step above it in the log.
- **"the Lens catalogue is unsigned"** — the producer ran without `--sign`, or the
  signing secret was not in that step's environment.
- **"does not verify under the release signing key"** — the envelope was signed
  with a different key, or something altered it after signing. Do not paper over
  this by regenerating until it passes; find out what changed the bytes.
- **"violates the vendored wire schema"** — the emitted catalogue no longer matches
  `core/lens-catalog/schemas/dex-lens-catalogue-v2.schema.json`. If that is
  deliberate, the consumer's copy of the schema has to move first (see below).
- **"is stamped for … not this release"** — the catalogue in `dist/` was built for
  a different version. Rebuild it at the release commit.

None of these is a reason to publish anyway. A release with a broken catalogue is
the failure mode this contract exists to prevent.

---

## Per-entry change stamps

Each catalogue entry carries `changed_in_release`: the core release its content
last **materially** changed in.

Lens fingerprints entries locally so it can tell a returning user what changed
since they last looked. A machine seeing the catalogue for the first time has no
local history to compare against, and without a stamp it cannot say anything about
recency at all. The stamp closes that gap: it travels with the entry.

**Material** means anything that reaches the catalogue: the entry's value,
prerequisites, trade-offs, evidence, brief, compatibility, docs URL, job and
foundation references, and the pinned digest of the shipped skill behind it.
It excludes the release stamps themselves (`since_release`, `changed_in`,
`changed_in_release`), so restamping an entry is never itself a content change.

Rules, all checked:

- The producer requires every entry to carry a stamp naming a version CHANGELOG.md
  actually shipped, no earlier than the entry's `since_release` and no earlier than
  any version in its `changed_in` history.
- `scripts/check-lens-catalog-change-stamps.py` compares the registry against the
  base branch on every pull request and refuses a change that edits an entry's
  content while leaving its stamp where it was. It names the entries and the
  release version to use.

When you change an entry, set `changed_in_release` to the release the change ships
in — the newest version in CHANGELOG.md, which is the entry your own change adds.
Appending that version to `changed_in` as well keeps the full trail; the stamp is
what Lens reads.

**Where the stamps came from.** They were backfilled once, per entry, from the
registry's own git history: the release that shipped the commit where that entry's
material content last changed. They are accurate from that point forward because
the gate keeps them so. Nothing claims to reconstruct history from before the
registry existed.

---

## Changing the wire contract

`core/lens-catalog/schemas/dex-lens-catalogue-v2.schema.json` is the vendored copy
of the schema the consumer validates against, and it sets
`additionalProperties: false`. A field added here is therefore **not** a private
change: heydex.ai's own copy has to accept the field before Core publishes a
release carrying it, or verification succeeds and validation then rejects the
envelope.

So: coordinate the consumer's schema first, ship Core's second. `changed_in_release`
was added under exactly this constraint and needs that confirmation before the
first release carrying it goes out.

---

## Related

- `scripts/generate-dex-lens-catalog.py` — the producer
- `core/lens-catalog/registry.json` — the publisher-owned source of truth
- `core/tests/test_dex_lens_catalog_generation.py` — producer behaviour
- `core/tests/test_lens_catalog_release_gate.py` — both gates
- `docs/dex-lens-catalogue-wave-2-audit.md` — how the catalogue's contents were chosen
