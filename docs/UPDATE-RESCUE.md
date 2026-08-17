# Update rescue — when the normal update route refuses

This page is for any Dex install whose `/dex-update` cannot complete, and for the
assistant driving it. If you are the AI assistant inside a Dex vault reading this
because an update failed: follow this page exactly; do not improvise beyond it.

## Read this first: getting unstuck takes two runs, not one

The one-time bridge on this page does not bring a stuck install up to the newest
version of Dex. It brings it up to **v1.81.16, a release from 4 August 2026** —
the oldest version that can then update itself the normal way. That is on
purpose: the bridge aims at one exact release it can check thoroughly, rather
than at a moving target.

So a full rescue is two runs:

1. **The bridge** (this page) gets the install to v1.81.16 and gives it a working
   update route again. Expect up to three approval prompts.
2. **`/dex-update`** then takes it from v1.81.16 to the current release. This is
   the ordinary update everybody else uses, and it can be repeated any time.

Finishing step 1 and stopping there is safe: nothing is broken and no notes are
at risk — the install is simply behind. Run `/dex-update` when you are ready.

If you already know you only need step 2, you do not need this page at all.

## Who this applies to

**First, check the vault's shape — it decides the route.** If the vault contains a
`.dex/brain.git` folder, Dex's code already lives in its own private store and the
vault's own Git history has no release in it to merge — the Git fallback below
cannot work there, whatever version is installed, and its `git fetch upstream`
step will fail because the vault has no `upstream` remote. Skip straight to
"Lifecycle-era bridge" further down this page.

For a vault **without** `.dex/brain.git`:

- **Versions v1.68 through v1.77.2**: the guided update route in these versions has a
  defect (an internal version label that was never advanced) which makes it refuse
  before doing anything — often as an error mentioning
  `installed catalog release does not match the designated bridge release`, or a
  Python traceback from `core.lifecycle`. The fix ships in v1.78.0, but these
  versions cannot fetch it through the broken route. Use the fallback below once;
  after that, the guided route works.
- **Versions v1.62 through v1.74 that never show an update notice**: the version
  checker in these releases refused when too many release tags existed. The
  repository's tag list has been cleaned so these versions announce updates again.
  If a notice still never appears, use the fallback below.
- **Versions v1.74 through v1.79 whose `/dex-update` cannot fetch a new release**:
  these versions predate the delivered-release mechanism and need the one-time
  bridge — skip the Git fallback below and go straight to
  "Lifecycle-era bridge" further down this page.
- **Versions before v1.62**: use the one-time bridge — skip the Git fallback and go
  straight to "Lifecycle-era bridge" further down this page. These versions' own
  built-in update instructions describe the Git route, but their pre-merge safety
  check cannot approve today's releases, so that route stops with
  `blocked-query-mismatch` — and pushing past that refusal deletes the very files
  the check protects (see the warning below). The bridge recognises these exact
  older releases and carries their file-protection rules with it.

## The fallback route (safe, reversible, one time)

Run these from the vault root. Every step is reversible; the backup tag is the
undo point.

```bash
# 1. Save everything and create an undo point
git add -A && git commit -m "Auto-save before Dex update" || true
git tag backup-before-dex-update-$(date +%Y%m%d) || true

# 2. Fetch and merge the published release
git fetch upstream
git merge upstream/release --no-edit
```

**Stop immediately if any step reports `blocked-query-mismatch`.** That is the
pre-merge safety check saying it cannot vouch for this merge. Do not continue and
do not work around it: merging past this refusal silently deletes the personal
files the check exists to protect (files under `System/Session_Learnings/` and
`System/integrations/` have been lost this way). Leave the merge uncommitted (or
run `git merge --abort` if one started), and use the "Lifecycle-era bridge"
section further down this page instead — it reaches the same destination without
that gate.

Conflict rules, in order of precedence:
- Anything under `00-Inbox` … `07-Archives`, `System/user-profile.yaml`,
  `System/pillars.yaml`, `System/Session_Learnings/`: **keep the user's version**
  (`git checkout --ours -- <path>`). A "deleted in theirs, modified in yours"
  conflict on a user-data file means the release stopped shipping a template the
  user wrote in — ALWAYS keep the user's file on disk.
- `package-lock.json`, `package.json`, `uv.lock`: take the release's version
  (`git checkout --theirs -- <path>`), then re-run `npm install` afterwards.
- `CLAUDE.md`: take the release's version, then re-insert the user's
  `USER_EXTENSIONS` block content if the merge lost it.
- If `git add` refuses a resolved path as ignored, that's expected for retired
  templates — the file safely stays on disk; continue without `-f`.
- Anything else: keep the user's version and note it for the user.

Then: `git commit --no-edit` to complete the merge.

## After the merge — finish the job (required)

The merge lands the new code but does not engage it. Run `/dex-update` **again** —
the new version's guided route (topology check, adoption plan, receipts) now works
and completes the update properly. Then run `/dex-doctor`. Both are conversational;
the assistant drives, the user approves.

## Current guided route — no Git workaround

Once a vault has the delivered update route, `/dex-update` does not ask a person
to fetch or merge anything. First, `deliver_latest_release` through
`core.lifecycle.service` proves the newest published release in a disposable
cache, fetches only that pinned release into Dex's private brain store, and
proves the fetched bytes again. It does not change vault content.

Dex then asks `build_and_preview_delivered_release` through the same service
with that exact release identity, shows every write, and waits for a fresh yes.
Only `execute_approved_delivered_release` with the unchanged preview and token
can write. The transaction and ownership contract decide every vault-content
write and keep the receipt and rewind evidence. If delivery, preview, or
execution cannot be proved, it stops; do not substitute a manual Git command.

## Lifecycle-era bridge — the one-time route when the Git fallback can't apply

This is the supported route for releases before v1.62, for v1.74 through v1.79
(which predate the delivery mechanism that fetches a new Dex release), and for
any vault that already has a `.dex/brain.git` folder. These installs need one
**one-time bridge** before the normal `dex-update` experience can begin. The
bridge is intentionally not a raw Git merge: it fetches only the pre-pinned
foundation release, proves its annotated tag, commit, and tree, then uses that
foundation's existing topology and receipt-backed transaction service. It
recognises the exact published older releases (back to the earliest supported
trees) and carries their file-protection rules with it, so nothing a person
wrote is part of what it may replace.

The bridge now pins the exact public v1.81.16 foundation: its annotated
distribution tag, tag object, commit, and tree are all closed in the released
journey contract. That publication is not, by itself, proof that every historic
route works. Each supported route still needs an installed-fixture rehearsal,
preserved-user-file hashes, Doctor output, and path evidence before it counts as
accepted recovery.

Do not run repository source as a substitute for the released bridge. The
released artifact and journey contract must name the same immutable foundation
identity. A newer source commit, a mutable branch, or a similarly named tag is
not equivalent, and an older bridge must refuse rather than silently
substituting a newer release.

Download the versioned bridge and its checksum from the public v1.96.5 release,
verify the bytes, then run that exact artifact. Run this block from the vault
root. It keeps the downloaded files in a temporary folder outside the vault.

```bash
BRIDGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/dex-update-bridge.XXXXXX")"
curl -fL \
  "https://github.com/davekilleen/Dex/releases/download/v1.96.5/dex-update-bridge-v1.96.5.py" \
  -o "$BRIDGE_DIR/dex-update-bridge-v1.96.5.py"
curl -fL \
  "https://github.com/davekilleen/Dex/releases/download/v1.96.5/dex-update-bridge-v1.96.5.py.sha256" \
  -o "$BRIDGE_DIR/dex-update-bridge-v1.96.5.py.sha256"
(
  cd "$BRIDGE_DIR"
  shasum -a 256 -c "dex-update-bridge-v1.96.5.py.sha256"
)
python3 "$BRIDGE_DIR/dex-update-bridge-v1.96.5.py" --vault "$PWD"
```

It shows up to three independent previews and requires `APPLY` for each: the
one-time separation of Dex code from the user's notes (skipped when the vault
is already split), the exact files for the verified foundation release, and the
one-line registration of Dex's update-support tool. It never pushes, never uses
a branch, and stops before a user-file change if either proof or approval is
missing. Only a published bridge whose historical fixture proof is green may
say that later updates are the ordinary `/dex-update` route.

**What you should see.** The bridge narrates each stage on the terminal:
relaunching into Dex's installed runtime, checking the install, fetching the
pinned release, then building the exact preview (which can take a few minutes
on a large vault). If it stops, it prints one line starting
`Dex update bridge stopped safely:` explaining why, and that line names the
specific thing that stopped it — you should never have to guess, or read Dex's
code, to find out. A bridge that runs for minutes with **no output at all** is
wedged, not working — press Ctrl-C and report exactly what you ran and saw.

**Running it without answering.** To see how far it gets before you commit to
anything, start it with its input closed
(`python3 … --vault "$PWD" < /dev/null`). It reaches the first approval prompt,
cannot read an answer, and stops with one line saying so. Nothing it asked you
to approve is applied. The one thing a run like this does leave behind is
`System/migration-report-v2.md`, the preview report it writes for you to read —
that file is the preview, not the change.

**When it finishes.** The last line says stage one of two is complete, names the
version now installed, and tells you to run `/dex-update` next. Do that: the
install is working, but it is not yet on the current release.

**If the vault has been moved, copied, or renamed.** That is fine. Dex records
where the vault lives, and moving it makes that note stale; the bridge notices,
says so, updates the note, and carries on. It does not need the folder put back.

Windows is not part of this P0 bridge. Do not substitute an unverified PowerShell
or Git command; use the supported rescue path until a Windows bridge is
published.

## Special case: v1.62.0 refuses before the merge

Six of the seven published copies of v1.62.0 shipped a self-contradictory metadata
file that blocks the pre-merge safety step with
`local-only preservation transition version does not match package metadata`.
The one-line repair (safe: it corrects the file to describe the version you are
actually on):

```bash
python3 - <<'FIX'
import json
p = "System/.local-only-preservation-transition.json"
d = json.load(open(p))
d["release_version"] = json.load(open("package.json"))["version"]
json.dump(d, open(p, "w"), indent=2)
FIX
```

Then retry the fallback route from step 1.

## Hard rules for the assistant

- Never `git push`. Never force anything. Never delete or overwrite a file the user
  wrote. Never run destructive git commands (`reset --hard`, `clean`) on a vault.
- If any step fails in a way this page does not cover: stop, show the exact output,
  and tell the user to report it (github.com/davekilleen/Dex/issues) — a refusal is
  safer than an improvisation.
