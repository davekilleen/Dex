---
name: dex-rollback
description: Undo the last Dex update if something went wrong
---

## What This Command Does

**Restores Dex to the version before your last update.** Use this if something broke after updating.

**When to use:**
- Feature you relied on stopped working
- Data looks wrong after update
- System feels unstable
- Want to go back for any reason

**Safe to use:** Your notes, tasks, and projects are never at risk.

---

## Process

### Step 1: Check if Rollback is Possible

**A. Verify Git repository**

Run: `git --version`

If Git not found:
```
❌ Git not detected

Rollback requires Git. Your data is safe, but automated rollback isn't available.

**To manually restore:**
1. If you have a backup folder, copy your data back
2. Or re-download Dex and copy your folders (00-07, System/)

[Show manual restore guide]
```

**B. Check for backup tag**

Run: `git tag | grep backup-before`

If no backup found:
```
❌ No backup found

Looks like you haven't updated recently, or the backup wasn't created.

Your current version: v1.3.0

Options:
[Download previous version manually]
[Cancel]
```

**C. Identify what version to restore to**

Run: `git tag | grep backup-before | tail -1`

Example: `backup-before-v1.3.0` means restore to before v1.3.0 update.

---

### Step 2: Confirm Rollback

```
🔙 Rollback Dex Update

You're about to restore Dex to the version before your last update.

Current version: v1.3.0
Will restore to: v1.2.0 (last backup)

**What happens:**
✓ Dex features restored to v1.2.0
✓ Your notes, tasks, projects stay as they are
✓ Any new skills from v1.3.0 will be removed

**This is safe:**
• Your data folders (00-07) are not affected
• Your configuration (user-profile, pillars) stays
• You can update again later if you want

[Confirm rollback]
[Cancel]
```

---

### Step 3: Save Current State

**Snapshot the newer release's shipped manifest before saving or resetting anything:**

```bash
# Run this and the Step 5 cleanup block with bash or zsh; Step 5 uses process substitution.
[ -f package.json ] && [ -d .claude ] || { echo "run from the vault root"; exit 1; }

ROLLBACK_RELEASE_REF=""
for candidate in upstream/release origin/release; do
  candidate_base="$(git merge-base HEAD "$candidate" 2>/dev/null || true)"
  if [ -n "$candidate_base" ] \
    && git cat-file -e "$candidate_base:System/.installed-files.manifest" 2>/dev/null; then
    ROLLBACK_RELEASE_REF="$candidate_base"
    break
  fi
done

if [ -n "$ROLLBACK_RELEASE_REF" ]; then
  ROLLBACK_STATE_DIR=""
  if candidate_state_dir="$(mktemp -d "${TMPDIR:-/tmp}/dex-rollback.XXXXXX")" \
    && chmod 700 "$candidate_state_dir" \
    && (umask 077
      git show "$ROLLBACK_RELEASE_REF:System/.installed-files.manifest" \
        > "$candidate_state_dir/new.manifest" \
      && printf '%s\n' "$ROLLBACK_RELEASE_REF" > "$candidate_state_dir/new-release"
    ); then
    ROLLBACK_STATE_DIR="$candidate_state_dir"
    printf 'Saved verified newer release state: %q\n' "$ROLLBACK_STATE_DIR"
  else
    if [ -n "${candidate_state_dir:-}" ] \
      && [ -d "$candidate_state_dir" ] \
      && [ ! -L "$candidate_state_dir" ]; then
      rm -f -- "$candidate_state_dir/new.manifest" "$candidate_state_dir/new-release"
      rmdir -- "$candidate_state_dir" 2>/dev/null || true
    fi
    echo "Could not safely snapshot the installed release manifest — file cleanup will be skipped"
  fi
else
  ROLLBACK_STATE_DIR=""
  echo "Could not verify the installed release manifest — file cleanup will be skipped"
fi
```

Keep the exact `ROLLBACK_STATE_DIR` value printed above for Step 5 (if commands run in separate shell invocations, substitute that exact value there; never search `/tmp` with a glob). This must happen before `git reset --hard`: after the reset, `HEAD` belongs to the older release. The manifest comes from the installed release commit shared with `upstream/release` (or the legacy `origin/release` fallback), never from the user's working tree or merge commit.

Before rolling back, save any uncommitted changes:

```
💾 Saving current state...
```

Run:
```bash
if ! git add .; then
  echo "Couldn't prepare your uncommitted changes for saving — rollback stopped to protect them; fix the Git error above, then retry"
  exit 1
fi

if git diff --cached --quiet; then
  echo "Nothing to save; continuing rollback"
elif ! git commit -m "Auto-save before rollback to v1.2.0"; then
  git reset
  echo "Couldn't save your uncommitted changes — rollback stopped to protect them; fix the commit error above, then retry"
  exit 1
fi
```

Only after the save succeeds (or Git verifies there is nothing to save), create a "before rollback" tag in case they want to undo the rollback:

```bash
git tag before-rollback-$(date +%Y%m%d-%H%M%S)
```

```
✓ Current state saved
```

---

### Step 4: Perform Rollback

```
🔄 Rolling back to v1.2.0...
```

Run:
```bash
git reset --hard backup-before-v1.3.0
```

This restores all Dex files to the state before update.

**Note:** User data folders (00-07) remain untouched because:
1. They're gitignored (not tracked)
2. `git reset` only affects tracked files

---

### Step 5: Cleanup

**A. Remove files added by the newer version (manifest-based)**

Compare the newer manifest snapshot from Step 3 with the restored release's shipped manifest. `ROLLBACK_STATE_DIR` below is the exact private temp path printed in Step 3:

```bash
# Requires bash or zsh because this block uses process substitution.
[ -f package.json ] && [ -d .claude ] || { echo "run from the vault root"; exit 1; }

ROLLBACK_STATE_DIR="[exact private temp path printed in Step 3]"

rollback_has_symlink_parent() {
  local remaining="$1"
  local prefix=""
  local component
  while [ "${remaining#*/}" != "$remaining" ]; do
    component="${remaining%%/*}"
    remaining="${remaining#*/}"
    prefix="${prefix:+$prefix/}$component"
    [ -L "$prefix" ] && return 0
  done
  return 1
}

ROLLBACK_NEW_RELEASE=""
ROLLBACK_OLD_RELEASE=""
if [ -n "$ROLLBACK_STATE_DIR" ] \
  && [ -d "$ROLLBACK_STATE_DIR" ] \
  && [ ! -L "$ROLLBACK_STATE_DIR" ] \
  && [ -f "$ROLLBACK_STATE_DIR/new.manifest" ] \
  && [ ! -L "$ROLLBACK_STATE_DIR/new.manifest" ] \
  && [ -f "$ROLLBACK_STATE_DIR/new-release" ] \
  && [ ! -L "$ROLLBACK_STATE_DIR/new-release" ]; then
  ROLLBACK_NEW_RELEASE="$(cat "$ROLLBACK_STATE_DIR/new-release")"
fi

for candidate in upstream/release origin/release; do
  candidate_base="$(git merge-base HEAD "$candidate" 2>/dev/null || true)"
  if [ -n "$candidate_base" ] \
    && git cat-file -e "$candidate_base:System/.installed-files.manifest" 2>/dev/null; then
    ROLLBACK_OLD_RELEASE="$candidate_base"
    break
  fi
done

if [ -n "$ROLLBACK_NEW_RELEASE" ] \
  && [ -n "$ROLLBACK_OLD_RELEASE" ] \
  && git merge-base --is-ancestor "$ROLLBACK_OLD_RELEASE" "$ROLLBACK_NEW_RELEASE" \
  && git cat-file -e "$ROLLBACK_NEW_RELEASE:System/.installed-files.manifest" 2>/dev/null \
  && git show "$ROLLBACK_NEW_RELEASE:System/.installed-files.manifest" \
    | cmp -s - "$ROLLBACK_STATE_DIR/new.manifest"; then
  (umask 077
    git show "$ROLLBACK_OLD_RELEASE:System/.installed-files.manifest" \
      > "$ROLLBACK_STATE_DIR/old.manifest"
  )
  # Files in new manifest but NOT in restored manifest = added by update
  comm -23 \
    <(LC_ALL=C sort "$ROLLBACK_STATE_DIR/new.manifest") \
    <(LC_ALL=C sort "$ROLLBACK_STATE_DIR/old.manifest") \
  | while IFS= read -r f; do
      case "/$f/" in
        *"//"*|*"/./"*|*"/../"*)
          echo "  Skipped unsafe manifest path: $f"
          continue
          ;;
      esac
      if git cat-file -e "HEAD:$f" 2>/dev/null; then
        echo "  Preserved path tracked by the restored state: $f"
        continue
      fi
      if [ -L "$f" ] || rollback_has_symlink_parent "$f"; then
        echo "  Skipped symlinked path: $f"
        continue
      fi
      if [ ! -f "$f" ]; then
        continue
      fi
      entry="$(git ls-tree "$ROLLBACK_NEW_RELEASE" -- "$f")"
      metadata="${entry%%$'\t'*}"
      mode="${metadata%% *}"
      expected_blob="${metadata##* }"
      case "$mode" in
        100644|100755) ;;
        *) echo "  Skipped non-regular release path: $f"; continue ;;
      esac
      actual_blob="$(git hash-object -- "$f" 2>/dev/null || true)"
      if [ -n "$expected_blob" ] && [ "$actual_blob" = "$expected_blob" ]; then
        rm -- "$f"
        echo "  Removed: $f"
      else
        echo "  Preserved modified or unverified path: $f"
      fi
    done
  echo "✓ Cleaned up files added by the update"
else
  echo "ℹ️  Verified release manifests unavailable — skipping file cleanup (safe to ignore)"
fi
if [ -n "$ROLLBACK_STATE_DIR" ] && [ -d "$ROLLBACK_STATE_DIR" ] && [ ! -L "$ROLLBACK_STATE_DIR" ]; then
  rm -f -- \
    "$ROLLBACK_STATE_DIR/new.manifest" \
    "$ROLLBACK_STATE_DIR/old.manifest" \
    "$ROLLBACK_STATE_DIR/new-release"
  rmdir -- "$ROLLBACK_STATE_DIR" 2>/dev/null || true
fi
```

Both inputs are read from immutable release commits, and cleanup refuses restored paths, symlink traversal, and files that no longer match the newer release blob. **Never regenerate either manifest from the user's working tree:** doing so could misclassify user files as update-added and delete them.

**B. Reinstall dependencies for the restored version**

```
📦 Cleaning up...
```

Run:
```bash
npm install
pip3 install -r core/mcp/requirements.txt
```

This ensures dependencies match the older version.

**C. Remove migration markers (if exist)**

```bash
rm -f .migration-v*-complete
rm -f .migration-version
```

---

### Step 6: Verification

```
✓ Rollback complete! Now testing...
```

Run Dex's quick doctor with safe healing, then its isolated end-to-end journeys using the same restored venv interpreter:

```bash
.venv/bin/python core/utils/doctor.py --heal
.venv/bin/python core/utils/smoke.py --json
```

Keep and inspect smoke JSON even when it exits `1` for a `BROKEN` journey. Exit `2` is a harness failure and must be reported as `UNKNOWN`. Add the corresponding `summary` counts from both reports and render every bucket:

```
Verification
✓ OK: N
○ OFF: N
✗ BROKEN: N
? UNKNOWN: N
```

`OFF` is informational. If there are no `BROKEN` or `UNKNOWN` results:

```
✅ Rollback verified successfully!
```

If a customization is `BROKEN`, name its exact path and do not recommend another rollback or update:

```
⚠️ Rollback completed, but one of your customizations needs attention

Fix your customization: [exact path]
[Exact doctor or smoke detail]

Dex will not change releases for a customization problem.
```

Customization failures include `-custom` skills, `custom-*` MCP entries, the `USER_EXTENSIONS` block, and user-owned YAML/integration files. **Never recommend `/dex-update` or another `/dex-rollback` for these findings.**

If an unmodified Dex-owned file or journey is `BROKEN`, name the exact check and offer the documented update path:

```
❌ Rollback verification failed in Dex-owned code

[Exact check and detail]

Your data is safe. You may want to:
[Report this issue]
[Run /dex-update to return to the newer release]
[Continue anyway]
```

If there are only `UNKNOWN` results, say the rollback completed but could not be fully verified, list each unknown detail, and do not declare verification successful.

---

### Step 7: Summary

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Rolled Back: v1.3.0 → v1.2.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Dex restored to: v1.2.0
Your data: All preserved (notes, tasks, projects)

You're back to the version from before your last update.

**What now?**
• Everything should work as before
• You can try updating again later with /dex-update
• If issues persist, try /setup to verify configuration

**Want to report what went wrong?**
[Open issue on GitHub] — Help improve future updates
```

---

## Undo Rollback (Advanced)

If user rolled back by mistake and wants to go forward again:

```
Did you roll back by mistake?

We saved your state before rollback. You can restore it:

[Restore to v1.3.0] — Undo this rollback
[Stay on v1.2.0] — Keep rollback
```

If user chooses restore:

```bash
RESTORE_TAG=$(git tag | grep before-rollback | tail -1)
git reset --hard $RESTORE_TAG
```

---

## Manual Rollback (No Git)

If Git not available or no backup tags:

```
📥 Manual Rollback Method

To restore an older version without Git:

1. **Download your desired version:**
   
   For v1.2.0:
   https://github.com/davekilleen/dex/releases/tag/v1.2.0
   
   Click "Source code (zip)"

2. **Copy your data:**
   
   From CURRENT Dex, copy to DOWNLOADED Dex:
   
   ✓ System/user-profile.yaml
   ✓ System/pillars.yaml
   ✓ 00-Inbox/
   ✓ 01-Quarter_Goals/
   ✓ 02-Week_Priorities/
   ✓ 03-Tasks/
   ✓ 04-Projects/
   ✓ 05-Areas/
   ✓ 07-Archives/
   ✓ .env (if exists)

3. **Replace folders:**
   
   • Move current Dex folder to trash (or rename to dex-old)
   • Rename downloaded folder to 'dex'
   • Open in Cursor

4. **Verify:**
   
   Run /setup to check everything works

[See version history] — All Dex releases
[Copy instructions]
```

---

## Rollback Limitations

**What rollback restores:**
- ✓ Dex skills
- ✓ MCP servers
- ✓ Core features
- ✓ Documentation

**What rollback preserves (doesn't touch):**
- ✓ Your notes (00-Inbox, 04-Projects, 05-Areas)
- ✓ Your tasks (03-Tasks/)
- ✓ Your configuration (user-profile, pillars)
- ✓ Your API keys (.env)

**What you might lose:**
- ⚠️ New features added since v1.2.0
- ⚠️ Bug fixes introduced in v1.3.0
- ⚠️ New skills that came with update

---

## Troubleshooting

### "Rollback completed but /daily-plan doesn't work"

Likely MCP servers need restart:

1. Close Cursor completely
2. Reopen your Dex folder
3. Try /daily-plan again

### "My tasks look different after rollback"

Your task data is unchanged. What might look different:
- Task display format (if update changed rendering)
- Task sorting (if update changed logic)

**Your actual tasks are safe.** Check `03-Tasks/Tasks.md` directly - everything is there.

### "Can I rollback multiple versions?"

Yes, if backups exist:

```bash
git tag | grep backup-before
```

Shows all available backups:
```
backup-before-v1.1.0
backup-before-v1.2.0
backup-before-v1.3.0
```

To rollback to specific version:
```bash
git reset --hard backup-before-v1.1.0
```

But easier: tell `/dex-rollback` which version you want, and it handles it.

---

## Prevention Better Than Cure

**To avoid needing rollback:**

1. **Read release notes before updating**
   - Run `/dex-whats-new` first
   - Check for breaking changes warning
   - Understand what's changing

2. **Update during low-stakes time**
   - Not right before important meeting
   - Not during crunch deadline
   - Give yourself time to test

3. **Test after updating**
   - Run `/daily-plan`
   - Open a person page
   - Check key workflows

4. **Keep regular backups**
   - Use Time Machine (Mac) or File History (Windows)
   - Or manually copy Dex folder weekly

---

## Related Commands

- `/dex-update` - Update to latest version
- `/dex-whats-new` - Check what's available
- `/setup` - Verify Dex configuration

---

## Philosophy

**Rollback should be:**
- One command away
- Always available
- Completely safe
- No data loss ever

**User confidence:**
"I can try updates knowing I can undo them instantly"

**No shame in rolling back:**
Updates should improve things. If they don't for you, rolling back is the right choice. Help us by reporting what went wrong.

## Track Usage (Silent)

Update `System/usage_log.md` to mark Dex rollback as used.

**Analytics (Silent):**

Call `track_event` with event_name `dex_rollback_completed` and properties:
- `restored_version`

This only fires if the user has opted into analytics. No action needed if it returns "analytics_disabled".
