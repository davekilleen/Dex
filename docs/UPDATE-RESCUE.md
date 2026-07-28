# Update rescue — when the normal update route refuses

This page is for any Dex install whose `/dex-update` cannot complete, and for the
assistant driving it. If you are the AI assistant inside a Dex vault reading this
because an update failed: follow this page exactly; do not improvise beyond it.

## Who this applies to

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
- **Versions before v1.62**: your built-in update instructions already use the
  fallback route; follow your own `/dex-update` skill as written.

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
