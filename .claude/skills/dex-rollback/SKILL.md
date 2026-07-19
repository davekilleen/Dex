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

**Safe to use:** Rollback explicitly snapshots and restores your user-owned files before changing Dex. Some files in 00-07 are tracked by Git, so this protection is required rather than assumed.

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
✓ Your latest notes, tasks, projects are snapshotted and restored
✓ Any new skills from v1.3.0 will be removed

**This is safe:**
• Some files in 00-07 are tracked, so every hard reset protects all eight data folders first
• Your configuration (user-profile, pillars) is protected in the same snapshot
• If restoration conflicts, rollback stops and keeps both versions in a timestamped rescue folder
• You can update again later if you want

[Confirm rollback]
[Cancel]
```

---

### Step 3: Save and Protect Current State

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

Next, protect all user-owned content. This includes every folder from `00-Inbox/` through `07-Archives/`, because tracked planning files such as tasks, quarterly goals, and weekly priorities would otherwise be replaced by a hard reset.

```
💾 Saving current state...
```

Run Step 4's single protected shell block. It snapshots user data before the auto-save. If staging or committing fails, rollback aborts before any tag or reset and reapplies the stash without dropping it. Only a verified save (including a verified nothing-to-save result) may create the undo tag, reset, restore the tracked snapshot, and finally reapply uncommitted and untracked user files.

---

### Step 4: Perform Rollback

```
🔄 Rolling back to v1.2.0...
```

Run this entire block in one shell invocation so the snapshot references cannot be lost between commands:
```bash
ROLLBACK_STATE_DIR="[exact private temp path printed in Step 3]"
DEX_ROLLBACK_TARGET="backup-before-v1.3.0"
DEX_LOCAL_ONLY_ROOT="System/.dex/local-only-preservation"
DEX_LOCAL_ONLY_RUNTIME="$DEX_LOCAL_ONLY_ROOT/runtime"
DEX_LOCAL_ONLY_JOURNAL="$DEX_LOCAL_ONLY_ROOT/journal"
DEX_CURRENT_LOCAL_ONLY_PHASE=$(PYTHONPATH="$DEX_LOCAL_ONLY_RUNTIME" python3 \
  "$DEX_LOCAL_ONLY_RUNTIME/core/migrations/preserve_local_only_paths.py" transition \
  --repo "$PWD") || exit 1
DEX_TARGET_TRANSITION="$DEX_LOCAL_ONLY_RUNTIME/rollback-target-transition.json"
DEX_TARGET_PACKAGE="$DEX_LOCAL_ONLY_RUNTIME/rollback-target-package.json"
if git cat-file -e \
  "$DEX_ROLLBACK_TARGET:System/.local-only-preservation-transition.json" 2>/dev/null; then
  git show "$DEX_ROLLBACK_TARGET:System/.local-only-preservation-transition.json" \
    > "$DEX_TARGET_TRANSITION" || exit 1
  git show "$DEX_ROLLBACK_TARGET:package.json" > "$DEX_TARGET_PACKAGE" || exit 1
  DEX_TARGET_LOCAL_ONLY_PHASE=$(PYTHONPATH="$DEX_LOCAL_ONLY_RUNTIME" python3 \
    "$DEX_LOCAL_ONLY_RUNTIME/core/migrations/preserve_local_only_paths.py" transition \
    --repo "$PWD" --transition "$DEX_TARGET_TRANSITION" \
    --package "$DEX_TARGET_PACKAGE") || exit 1
else
  DEX_TARGET_TRACKED_COUNT=0
  for DEX_LOCAL_ONLY_PATH in \
    System/Session_Learnings/2026-01-29.md \
    System/Session_Learnings/2026-01-30.md \
    System/integrations/slack.yaml; do
    git cat-file -e "$DEX_ROLLBACK_TARGET:$DEX_LOCAL_ONLY_PATH" 2>/dev/null \
      && DEX_TARGET_TRACKED_COUNT=$((DEX_TARGET_TRACKED_COUNT + 1))
  done
  case "$DEX_TARGET_TRACKED_COUNT" in
    3) DEX_TARGET_LOCAL_ONLY_PHASE="bootstrap-legacy" ;;
    0) DEX_TARGET_LOCAL_ONLY_PHASE="untrack-legacy" ;;
    *) echo "Rollback stopped: target has a partial local-only transition"; exit 1 ;;
  esac
fi
DEX_LOCAL_ONLY_REWIND_REQUIRED=false
case "$DEX_CURRENT_LOCAL_ONLY_PHASE:$DEX_TARGET_LOCAL_ONLY_PHASE" in
  untrack-v1:bootstrap-v1|untrack-v1:bootstrap-legacy)
    DEX_LOCAL_ONLY_REWIND_REQUIRED=true
    [ -f "$DEX_LOCAL_ONLY_JOURNAL/journal.json" ] || {
      echo "Rollback stopped: this target tracks local-only paths but the preservation journal is unavailable"
      exit 1
    }
    PYTHONPATH="$DEX_LOCAL_ONLY_RUNTIME" python3 \
      "$DEX_LOCAL_ONLY_RUNTIME/core/migrations/preserve_local_only_paths.py" capture-rewind \
      --repo "$PWD" --journal "$DEX_LOCAL_ONLY_JOURNAL" \
      --policy "$DEX_LOCAL_ONLY_RUNTIME/tracked-ignored-policy.yaml" || exit 1
    ;;
  bootstrap-v1:bootstrap-v1|bootstrap-v1:bootstrap-legacy|\
  bootstrap-v1:untrack-v1|bootstrap-v1:untrack-legacy|\
  untrack-v1:untrack-v1|untrack-v1:untrack-legacy) ;;
  *) echo "Rollback stopped: current and target local-only transitions are unsupported"; exit 1 ;;
esac
DEX_USER_DATA_PATHS=(
  "00-Inbox/" "01-Quarter_Goals/" "02-Week_Priorities/" "03-Tasks/"
  "04-Projects/" "05-Areas/" "06-Resources/" "07-Archives/"
  "System/user-profile.yaml" "System/pillars.yaml" "System/Session_Learnings/"
)
DEX_USER_DATA_STASH_PATHS=(
  ":(top,glob)00-Inbox/**" ":(top,glob)01-Quarter_Goals/**"
  ":(top,glob)02-Week_Priorities/**" ":(top,glob)03-Tasks/**"
  ":(top,glob)04-Projects/**" ":(top,glob)05-Areas/**"
  ":(top,glob)06-Resources/**" ":(top,glob)07-Archives/**"
  ":(top)System/user-profile.yaml" ":(top)System/pillars.yaml"
  ":(top,glob)System/Session_Learnings/**"
  ":(top,exclude)System/Session_Learnings/2026-01-29.md"
  ":(top,exclude)System/Session_Learnings/2026-01-30.md"
)
DEX_USER_DATA_SOURCE=$(git rev-parse HEAD)
DEX_INDEX_TREE_BEFORE=$(git write-tree) || {
  echo "Rollback stopped: Git could not snapshot the original staged state"
  exit 1
}
DEX_DATA_STASH_BEFORE=$(git rev-parse -q --verify refs/stash 2>/dev/null || true)

git stash push --all \
  -m "dex-user-data-before-rollback-$(date +%Y%m%d-%H%M%S)" \
  -- "${DEX_USER_DATA_STASH_PATHS[@]}" || true

DEX_DATA_STASH_AFTER=$(git rev-parse -q --verify refs/stash 2>/dev/null || true)
if [ -n "$DEX_DATA_STASH_AFTER" ] && [ "$DEX_DATA_STASH_AFTER" != "$DEX_DATA_STASH_BEFORE" ]; then
  DEX_DATA_STASH_REF='stash@{0}'
  DEX_DATA_STASH_OID="$DEX_DATA_STASH_AFTER"
else
  DEX_DATA_STASH_REF=""
  DEX_DATA_STASH_OID=""
  if ! git diff --quiet -- "${DEX_USER_DATA_PATHS[@]}" || \
     ! git diff --cached --quiet -- "${DEX_USER_DATA_PATHS[@]}" || \
     [ -n "$(git ls-files --others --exclude-standard -- "${DEX_USER_DATA_PATHS[@]}")" ] || \
     [ -n "$(git ls-files --others --ignored --exclude-standard -- "${DEX_USER_DATA_PATHS[@]}")" ]; then
    echo "Rollback stopped: changed user data remains outside the snapshot, so no reset ran"
    exit 1
  fi
fi

if ! git add .; then
  git read-tree "$DEX_INDEX_TREE_BEFORE"
  [ -z "$DEX_DATA_STASH_OID" ] || git stash apply --index "$DEX_DATA_STASH_OID"
  echo "Rollback stopped: Git could not prepare the current state, so no reset ran"
  exit 1
fi
if git diff --cached --quiet; then
  echo "Nothing to save; continuing rollback"
elif ! git commit -m "Auto-save before rollback to v1.2.0"; then
  git reset
  git read-tree "$DEX_INDEX_TREE_BEFORE"
  [ -z "$DEX_DATA_STASH_OID" ] || git stash apply --index "$DEX_DATA_STASH_OID"
  echo "Rollback stopped: Git could not save the current state, so no reset ran"
  exit 1
fi

DEX_BEFORE_ROLLBACK_TAG="before-rollback-$(date +%Y%m%d-%H%M%S)"
if ! git tag "$DEX_BEFORE_ROLLBACK_TAG"; then
  [ -z "$DEX_DATA_STASH_OID" ] || git stash apply "$DEX_DATA_STASH_OID"
  echo "Rollback stopped: the undo tag could not be created, so no reset ran"
  exit 1
fi

dex_export_user_data_rescue() {
  DEX_RESCUE_DIR="System/rollback-rescue/$(date +%Y%m%d-%H%M%S)-$$"
  if ! mkdir -p "$DEX_RESCUE_DIR/committed-before-reset" \
      "$DEX_RESCUE_DIR/stashed-tracked" "$DEX_RESCUE_DIR/stashed-untracked"; then
    echo "Automatic rescue export failed: could not create $DEX_RESCUE_DIR"
    return 1
  fi

  DEX_RESCUE_ARCHIVE="$DEX_RESCUE_DIR/.committed.tar"
  if ! git archive --format=tar -o "$DEX_RESCUE_ARCHIVE" \
      "$DEX_USER_DATA_SOURCE" -- "${DEX_USER_DATA_PATHS[@]}" || \
     ! tar -xf "$DEX_RESCUE_ARCHIVE" -C "$DEX_RESCUE_DIR/committed-before-reset"; then
    echo "Automatic rescue export failed. The committed snapshot remains at $DEX_USER_DATA_SOURCE"
    return 1
  fi
  rm -f "$DEX_RESCUE_ARCHIVE"

  if [ -n "$DEX_DATA_STASH_OID" ]; then
    DEX_RESCUE_ARCHIVE="$DEX_RESCUE_DIR/.stashed.tar"
    if ! git archive --format=tar -o "$DEX_RESCUE_ARCHIVE" \
        "$DEX_DATA_STASH_OID" -- "${DEX_USER_DATA_PATHS[@]}" || \
       ! tar -xf "$DEX_RESCUE_ARCHIVE" -C "$DEX_RESCUE_DIR/stashed-tracked"; then
      echo "Automatic rescue export failed. The latest snapshot remains in $DEX_DATA_STASH_REF ($DEX_DATA_STASH_OID)"
      return 1
    fi
    rm -f "$DEX_RESCUE_ARCHIVE"

    DEX_UNTRACKED_STASH=$(git rev-parse -q --verify "$DEX_DATA_STASH_OID^3" 2>/dev/null || true)
    if [ -n "$DEX_UNTRACKED_STASH" ]; then
      DEX_RESCUE_ARCHIVE="$DEX_RESCUE_DIR/.untracked.tar"
      if ! git archive --format=tar -o "$DEX_RESCUE_ARCHIVE" "$DEX_UNTRACKED_STASH" || \
         ! tar -xf "$DEX_RESCUE_ARCHIVE" -C "$DEX_RESCUE_DIR/stashed-untracked"; then
        echo "Automatic rescue export failed. Untracked data remains in $DEX_DATA_STASH_REF ($DEX_UNTRACKED_STASH)"
        return 1
      fi
      rm -f "$DEX_RESCUE_ARCHIVE"
    fi
  fi
}

if ! git reset --hard "$DEX_ROLLBACK_TARGET"; then
  echo "Rollback stopped: the reset failed. User data remains at $DEX_USER_DATA_SOURCE and in $DEX_DATA_STASH_REF"
  exit 1
fi
if ! git restore --source="$DEX_USER_DATA_SOURCE" --staged --worktree -- "${DEX_USER_DATA_PATHS[@]}"; then
  if dex_export_user_data_rescue; then
    echo "Rollback stopped: the committed snapshot was exported to $DEX_RESCUE_DIR"
  else
    echo "Do not continue: use commit $DEX_USER_DATA_SOURCE and $DEX_DATA_STASH_REF to recover user data"
  fi
  exit 2
fi
if [ -n "$DEX_DATA_STASH_REF" ] && ! git stash pop "$DEX_DATA_STASH_REF"; then
  if dex_export_user_data_rescue; then
    echo "Rollback stopped for review: both user-data versions are preserved in $DEX_RESCUE_DIR"
    echo "The latest snapshot also remains in $DEX_DATA_STASH_REF"
  else
    echo "Do not continue: the latest snapshot remains in $DEX_DATA_STASH_REF ($DEX_DATA_STASH_OID)"
  fi
  exit 2
fi
if ! git reset -- "${DEX_USER_DATA_PATHS[@]}"; then
  echo "User data was restored, but Git could not clear its staged state; review git status before continuing"
  exit 2
fi
if [ "$DEX_LOCAL_ONLY_REWIND_REQUIRED" = true ]; then
  PYTHONPATH="$DEX_LOCAL_ONLY_RUNTIME" python3 \
    "$DEX_LOCAL_ONLY_RUNTIME/core/migrations/preserve_local_only_paths.py" rewind \
    --repo "$PWD" --journal "$DEX_LOCAL_ONLY_JOURNAL" \
    --target-phase "$DEX_TARGET_LOCAL_ONLY_PHASE" \
    --policy "$DEX_LOCAL_ONLY_RUNTIME/tracked-ignored-policy.yaml" || {
      echo "Rollback stopped: local-only files remain protected in $DEX_LOCAL_ONLY_JOURNAL"
      exit 2
    }
fi
```

This restores Dex files to the state before the update, then restores the user's latest tracked, uncommitted, and untracked content.

**Why the restore is explicit:** Some files in 00-07 are tracked even when their folders also appear in `.gitignore`. A hard reset does affect those files, so safety comes from the snapshot-and-restore sequence above, not from ignore rules.

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
      case "$f" in
        00-Inbox/*|01-Quarter_Goals/*|02-Week_Priorities/*|03-Tasks/*|\
        04-Projects/*|05-Areas/*|06-Resources/*|07-Archives/*|\
        System/user-profile.yaml|System/pillars.yaml|System/Session_Learnings/*)
          echo "  Preserved restored user data: $f"
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

Both inputs are read from immutable release commits. Cleanup explicitly refuses every user-data path restored in Step 4, then also refuses paths tracked by the restored release, symlink traversal, and files that no longer match the newer release blob. The user-data guard runs first, so cleanup can never delete a file the protected restore just wrote, even if its contents happen to match a newer-release blob. **Never regenerate either manifest from the user's working tree:** doing so could misclassify user files as update-added and delete them.

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

The protected reset keeps a recoverable copy of your user data. You may want to:
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
Your data: Pre-rollback snapshot restored (notes, tasks, projects)

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
DEX_ROLLBACK_TARGET="$RESTORE_TAG"
DEX_USER_DATA_PATHS=(
  "00-Inbox/" "01-Quarter_Goals/" "02-Week_Priorities/" "03-Tasks/"
  "04-Projects/" "05-Areas/" "06-Resources/" "07-Archives/"
  "System/user-profile.yaml" "System/pillars.yaml" "System/Session_Learnings/"
)
DEX_USER_DATA_SOURCE=$(git rev-parse HEAD)
DEX_DATA_STASH_BEFORE=$(git rev-parse -q --verify refs/stash 2>/dev/null || true)
DEX_USER_DATA_STASH_PATHS=(
  ":(top,glob)00-Inbox/**" ":(top,glob)01-Quarter_Goals/**"
  ":(top,glob)02-Week_Priorities/**" ":(top,glob)03-Tasks/**"
  ":(top,glob)04-Projects/**" ":(top,glob)05-Areas/**"
  ":(top,glob)06-Resources/**" ":(top,glob)07-Archives/**"
  ":(top)System/user-profile.yaml" ":(top)System/pillars.yaml"
  ":(top,glob)System/Session_Learnings/**"
)
git stash push --all \
  -m "dex-user-data-before-undo-rollback-$(date +%Y%m%d-%H%M%S)" \
  -- "${DEX_USER_DATA_STASH_PATHS[@]}" || true
DEX_DATA_STASH_AFTER=$(git rev-parse -q --verify refs/stash 2>/dev/null || true)
if [ -n "$DEX_DATA_STASH_AFTER" ] && [ "$DEX_DATA_STASH_AFTER" != "$DEX_DATA_STASH_BEFORE" ]; then
  DEX_DATA_STASH_REF='stash@{0}'
  DEX_DATA_STASH_OID="$DEX_DATA_STASH_AFTER"
else
  DEX_DATA_STASH_REF=""
  DEX_DATA_STASH_OID=""
  if ! git diff --quiet -- "${DEX_USER_DATA_PATHS[@]}" || \
     ! git diff --cached --quiet -- "${DEX_USER_DATA_PATHS[@]}" || \
     [ -n "$(git ls-files --others --exclude-standard -- "${DEX_USER_DATA_PATHS[@]}")" ] || \
     [ -n "$(git ls-files --others --ignored --exclude-standard -- "${DEX_USER_DATA_PATHS[@]}")" ]; then
    echo "Undo stopped: changed user data remains outside the snapshot, so no reset ran"
    exit 1
  fi
fi

dex_export_user_data_rescue() {
  DEX_RESCUE_DIR="System/rollback-rescue/$(date +%Y%m%d-%H%M%S)-$$"
  if ! mkdir -p "$DEX_RESCUE_DIR/committed-before-reset" \
      "$DEX_RESCUE_DIR/stashed-tracked" "$DEX_RESCUE_DIR/stashed-untracked"; then
    echo "Automatic rescue export failed: could not create $DEX_RESCUE_DIR"
    return 1
  fi
  DEX_RESCUE_ARCHIVE="$DEX_RESCUE_DIR/.committed.tar"
  if ! git archive --format=tar -o "$DEX_RESCUE_ARCHIVE" \
      "$DEX_USER_DATA_SOURCE" -- "${DEX_USER_DATA_PATHS[@]}" || \
     ! tar -xf "$DEX_RESCUE_ARCHIVE" -C "$DEX_RESCUE_DIR/committed-before-reset"; then
    echo "Automatic rescue export failed. The committed snapshot remains at $DEX_USER_DATA_SOURCE"
    return 1
  fi
  rm -f "$DEX_RESCUE_ARCHIVE"
  if [ -n "$DEX_DATA_STASH_OID" ]; then
    DEX_RESCUE_ARCHIVE="$DEX_RESCUE_DIR/.stashed.tar"
    if ! git archive --format=tar -o "$DEX_RESCUE_ARCHIVE" \
        "$DEX_DATA_STASH_OID" -- "${DEX_USER_DATA_PATHS[@]}" || \
       ! tar -xf "$DEX_RESCUE_ARCHIVE" -C "$DEX_RESCUE_DIR/stashed-tracked"; then
      echo "Automatic rescue export failed. The latest snapshot remains in $DEX_DATA_STASH_REF ($DEX_DATA_STASH_OID)"
      return 1
    fi
    rm -f "$DEX_RESCUE_ARCHIVE"
    DEX_UNTRACKED_STASH=$(git rev-parse -q --verify "$DEX_DATA_STASH_OID^3" 2>/dev/null || true)
    if [ -n "$DEX_UNTRACKED_STASH" ]; then
      DEX_RESCUE_ARCHIVE="$DEX_RESCUE_DIR/.untracked.tar"
      if ! git archive --format=tar -o "$DEX_RESCUE_ARCHIVE" "$DEX_UNTRACKED_STASH" || \
         ! tar -xf "$DEX_RESCUE_ARCHIVE" -C "$DEX_RESCUE_DIR/stashed-untracked"; then
        echo "Automatic rescue export failed. Untracked data remains in $DEX_DATA_STASH_REF ($DEX_UNTRACKED_STASH)"
        return 1
      fi
      rm -f "$DEX_RESCUE_ARCHIVE"
    fi
  fi
}

if ! git reset --hard "$DEX_ROLLBACK_TARGET"; then
  echo "Undo stopped: the reset failed. User data remains at $DEX_USER_DATA_SOURCE and in $DEX_DATA_STASH_REF"
  exit 1
fi
if ! git restore --source="$DEX_USER_DATA_SOURCE" --staged --worktree -- "${DEX_USER_DATA_PATHS[@]}"; then
  if dex_export_user_data_rescue; then
    echo "Undo stopped: the committed snapshot was exported to $DEX_RESCUE_DIR"
  else
    echo "Do not continue: use commit $DEX_USER_DATA_SOURCE and $DEX_DATA_STASH_REF to recover user data"
  fi
  exit 2
fi
if [ -n "$DEX_DATA_STASH_REF" ] && ! git stash pop "$DEX_DATA_STASH_REF"; then
  if dex_export_user_data_rescue; then
    echo "Undo stopped for review: both user-data versions are preserved in $DEX_RESCUE_DIR"
    echo "The latest snapshot also remains in $DEX_DATA_STASH_REF"
  else
    echo "Do not continue: the latest snapshot remains in $DEX_DATA_STASH_REF ($DEX_DATA_STASH_OID)"
  fi
  exit 2
fi
if ! git reset -- "${DEX_USER_DATA_PATHS[@]}"; then
  echo "User data was restored, but Git could not clear its staged state; review git status before continuing"
  exit 2
fi
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
   ✓ 06-Resources/ (copy the entire folder, including root-level files)
   ✓ Then replace 06-Resources/Dex_System/ with the copy from the downloaded Dex so shipped documentation stays current
   ✓ 07-Archives/
   ✓ System/Session_Learnings/
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

**What rollback snapshots and restores:**
- ✓ Your notes (00-Inbox, 04-Projects, 05-Areas)
- ✓ Your tasks (03-Tasks/)
- ✓ Your goals and weekly priorities (01-Quarter_Goals/, 02-Week_Priorities/)
- ✓ Your resources, learnings, and reviews (06-Resources/)
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

The protected reset restores the task snapshot taken immediately before rollback. What might look different:
- Task display format (if update changed rendering)
- Task sorting (if update changed logic)

**Verify the restored task snapshot:** Check `03-Tasks/Tasks.md` directly. If rollback reported a restore conflict, also check the timestamped `System/rollback-rescue/` folder before continuing.

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
DEX_ROLLBACK_TARGET="backup-before-v1.1.0"
DEX_LOCAL_ONLY_ROOT="System/.dex/local-only-preservation"
DEX_LOCAL_ONLY_RUNTIME="$DEX_LOCAL_ONLY_ROOT/runtime"
DEX_LOCAL_ONLY_JOURNAL="$DEX_LOCAL_ONLY_ROOT/journal"
DEX_CURRENT_LOCAL_ONLY_PHASE=$(PYTHONPATH="$DEX_LOCAL_ONLY_RUNTIME" python3 \
  "$DEX_LOCAL_ONLY_RUNTIME/core/migrations/preserve_local_only_paths.py" transition \
  --repo "$PWD") || exit 1
DEX_TARGET_TRANSITION="$DEX_LOCAL_ONLY_RUNTIME/rollback-target-transition.json"
DEX_TARGET_PACKAGE="$DEX_LOCAL_ONLY_RUNTIME/rollback-target-package.json"
if git cat-file -e \
  "$DEX_ROLLBACK_TARGET:System/.local-only-preservation-transition.json" 2>/dev/null; then
  git show "$DEX_ROLLBACK_TARGET:System/.local-only-preservation-transition.json" \
    > "$DEX_TARGET_TRANSITION" || exit 1
  git show "$DEX_ROLLBACK_TARGET:package.json" > "$DEX_TARGET_PACKAGE" || exit 1
  DEX_TARGET_LOCAL_ONLY_PHASE=$(PYTHONPATH="$DEX_LOCAL_ONLY_RUNTIME" python3 \
    "$DEX_LOCAL_ONLY_RUNTIME/core/migrations/preserve_local_only_paths.py" transition \
    --repo "$PWD" --transition "$DEX_TARGET_TRANSITION" \
    --package "$DEX_TARGET_PACKAGE") || exit 1
else
  DEX_TARGET_TRACKED_COUNT=0
  for DEX_LOCAL_ONLY_PATH in \
    System/Session_Learnings/2026-01-29.md \
    System/Session_Learnings/2026-01-30.md \
    System/integrations/slack.yaml; do
    git cat-file -e "$DEX_ROLLBACK_TARGET:$DEX_LOCAL_ONLY_PATH" 2>/dev/null \
      && DEX_TARGET_TRACKED_COUNT=$((DEX_TARGET_TRACKED_COUNT + 1))
  done
  case "$DEX_TARGET_TRACKED_COUNT" in
    3) DEX_TARGET_LOCAL_ONLY_PHASE="bootstrap-legacy" ;;
    0) DEX_TARGET_LOCAL_ONLY_PHASE="untrack-legacy" ;;
    *) echo "Rollback stopped: target has a partial local-only transition"; exit 1 ;;
  esac
fi
DEX_LOCAL_ONLY_REWIND_REQUIRED=false
case "$DEX_CURRENT_LOCAL_ONLY_PHASE:$DEX_TARGET_LOCAL_ONLY_PHASE" in
  untrack-v1:bootstrap-v1|untrack-v1:bootstrap-legacy)
    DEX_LOCAL_ONLY_REWIND_REQUIRED=true
    [ -f "$DEX_LOCAL_ONLY_JOURNAL/journal.json" ] || exit 1
    PYTHONPATH="$DEX_LOCAL_ONLY_RUNTIME" python3 \
      "$DEX_LOCAL_ONLY_RUNTIME/core/migrations/preserve_local_only_paths.py" capture-rewind \
      --repo "$PWD" --journal "$DEX_LOCAL_ONLY_JOURNAL" \
      --policy "$DEX_LOCAL_ONLY_RUNTIME/tracked-ignored-policy.yaml" || exit 1
    ;;
  bootstrap-v1:*|untrack-v1:untrack-v1|untrack-v1:untrack-legacy) ;;
  *) echo "Rollback stopped: current and target local-only transitions are unsupported"; exit 1 ;;
esac
DEX_USER_DATA_PATHS=(
  "00-Inbox/" "01-Quarter_Goals/" "02-Week_Priorities/" "03-Tasks/"
  "04-Projects/" "05-Areas/" "06-Resources/" "07-Archives/"
  "System/user-profile.yaml" "System/pillars.yaml" "System/Session_Learnings/"
)
DEX_USER_DATA_SOURCE=$(git rev-parse HEAD)
DEX_DATA_STASH_BEFORE=$(git rev-parse -q --verify refs/stash 2>/dev/null || true)
DEX_USER_DATA_STASH_PATHS=(
  ":(top,glob)00-Inbox/**" ":(top,glob)01-Quarter_Goals/**"
  ":(top,glob)02-Week_Priorities/**" ":(top,glob)03-Tasks/**"
  ":(top,glob)04-Projects/**" ":(top,glob)05-Areas/**"
  ":(top,glob)06-Resources/**" ":(top,glob)07-Archives/**"
  ":(top)System/user-profile.yaml" ":(top)System/pillars.yaml"
  ":(top,glob)System/Session_Learnings/**"
  ":(top,exclude)System/Session_Learnings/2026-01-29.md"
  ":(top,exclude)System/Session_Learnings/2026-01-30.md"
)
git stash push --all \
  -m "dex-user-data-before-version-rollback-$(date +%Y%m%d-%H%M%S)" \
  -- "${DEX_USER_DATA_STASH_PATHS[@]}" || true
DEX_DATA_STASH_AFTER=$(git rev-parse -q --verify refs/stash 2>/dev/null || true)
if [ -n "$DEX_DATA_STASH_AFTER" ] && [ "$DEX_DATA_STASH_AFTER" != "$DEX_DATA_STASH_BEFORE" ]; then
  DEX_DATA_STASH_REF='stash@{0}'
  DEX_DATA_STASH_OID="$DEX_DATA_STASH_AFTER"
else
  DEX_DATA_STASH_REF=""
  DEX_DATA_STASH_OID=""
  if ! git diff --quiet -- "${DEX_USER_DATA_PATHS[@]}" || \
     ! git diff --cached --quiet -- "${DEX_USER_DATA_PATHS[@]}" || \
     [ -n "$(git ls-files --others --exclude-standard -- "${DEX_USER_DATA_PATHS[@]}")" ] || \
     [ -n "$(git ls-files --others --ignored --exclude-standard -- "${DEX_USER_DATA_PATHS[@]}")" ]; then
    echo "Rollback stopped: changed user data remains outside the snapshot, so no reset ran"
    exit 1
  fi
fi

dex_export_user_data_rescue() {
  DEX_RESCUE_DIR="System/rollback-rescue/$(date +%Y%m%d-%H%M%S)-$$"
  if ! mkdir -p "$DEX_RESCUE_DIR/committed-before-reset" \
      "$DEX_RESCUE_DIR/stashed-tracked" "$DEX_RESCUE_DIR/stashed-untracked"; then
    echo "Automatic rescue export failed: could not create $DEX_RESCUE_DIR"
    return 1
  fi
  DEX_RESCUE_ARCHIVE="$DEX_RESCUE_DIR/.committed.tar"
  if ! git archive --format=tar -o "$DEX_RESCUE_ARCHIVE" \
      "$DEX_USER_DATA_SOURCE" -- "${DEX_USER_DATA_PATHS[@]}" || \
     ! tar -xf "$DEX_RESCUE_ARCHIVE" -C "$DEX_RESCUE_DIR/committed-before-reset"; then
    echo "Automatic rescue export failed. The committed snapshot remains at $DEX_USER_DATA_SOURCE"
    return 1
  fi
  rm -f "$DEX_RESCUE_ARCHIVE"
  if [ -n "$DEX_DATA_STASH_OID" ]; then
    DEX_RESCUE_ARCHIVE="$DEX_RESCUE_DIR/.stashed.tar"
    if ! git archive --format=tar -o "$DEX_RESCUE_ARCHIVE" \
        "$DEX_DATA_STASH_OID" -- "${DEX_USER_DATA_PATHS[@]}" || \
       ! tar -xf "$DEX_RESCUE_ARCHIVE" -C "$DEX_RESCUE_DIR/stashed-tracked"; then
      echo "Automatic rescue export failed. The latest snapshot remains in $DEX_DATA_STASH_REF ($DEX_DATA_STASH_OID)"
      return 1
    fi
    rm -f "$DEX_RESCUE_ARCHIVE"
    DEX_UNTRACKED_STASH=$(git rev-parse -q --verify "$DEX_DATA_STASH_OID^3" 2>/dev/null || true)
    if [ -n "$DEX_UNTRACKED_STASH" ]; then
      DEX_RESCUE_ARCHIVE="$DEX_RESCUE_DIR/.untracked.tar"
      if ! git archive --format=tar -o "$DEX_RESCUE_ARCHIVE" "$DEX_UNTRACKED_STASH" || \
         ! tar -xf "$DEX_RESCUE_ARCHIVE" -C "$DEX_RESCUE_DIR/stashed-untracked"; then
        echo "Automatic rescue export failed. Untracked data remains in $DEX_DATA_STASH_REF ($DEX_UNTRACKED_STASH)"
        return 1
      fi
      rm -f "$DEX_RESCUE_ARCHIVE"
    fi
  fi
}

if ! git reset --hard "$DEX_ROLLBACK_TARGET"; then
  echo "Rollback stopped: the reset failed. User data remains at $DEX_USER_DATA_SOURCE and in $DEX_DATA_STASH_REF"
  exit 1
fi
if ! git restore --source="$DEX_USER_DATA_SOURCE" --staged --worktree -- "${DEX_USER_DATA_PATHS[@]}"; then
  if dex_export_user_data_rescue; then
    echo "Rollback stopped: the committed snapshot was exported to $DEX_RESCUE_DIR"
  else
    echo "Do not continue: use commit $DEX_USER_DATA_SOURCE and $DEX_DATA_STASH_REF to recover user data"
  fi
  exit 2
fi
if [ -n "$DEX_DATA_STASH_REF" ] && ! git stash pop "$DEX_DATA_STASH_REF"; then
  if dex_export_user_data_rescue; then
    echo "Rollback stopped for review: both user-data versions are preserved in $DEX_RESCUE_DIR"
    echo "The latest snapshot also remains in $DEX_DATA_STASH_REF"
  else
    echo "Do not continue: the latest snapshot remains in $DEX_DATA_STASH_REF ($DEX_DATA_STASH_OID)"
  fi
  exit 2
fi
if ! git reset -- "${DEX_USER_DATA_PATHS[@]}"; then
  echo "User data was restored, but Git could not clear its staged state; review git status before continuing"
  exit 2
fi
if [ "$DEX_LOCAL_ONLY_REWIND_REQUIRED" = true ]; then
  PYTHONPATH="$DEX_LOCAL_ONLY_RUNTIME" python3 \
    "$DEX_LOCAL_ONLY_RUNTIME/core/migrations/preserve_local_only_paths.py" rewind \
    --repo "$PWD" --journal "$DEX_LOCAL_ONLY_JOURNAL" \
    --target-phase "$DEX_TARGET_LOCAL_ONLY_PHASE" \
    --policy "$DEX_LOCAL_ONLY_RUNTIME/tracked-ignored-policy.yaml" || exit 2
fi
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
- Explicit about tracked user data
- Able to stop safely and keep both versions when restoration conflicts

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
