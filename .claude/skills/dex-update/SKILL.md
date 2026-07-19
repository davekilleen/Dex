---
name: dex-update
description: Safely update Dex with one command (handles everything automatically)
---

## What This Command Does

**For non-technical users:** Updates Dex to the latest version automatically. No command line knowledge needed - just run the command and follow the prompts.

**When to use:**
- After `/dex-whats-new` shows new version available
- When you want the latest features and bug fixes

**What it handles:**
- Downloads updates automatically
- Protects and restores user data before any hard-reset recovery; some files in 00-07 are tracked, so Dex never relies on `.gitignore` for safety
- Preserves protected user blocks and user-owned MCP entries
- Resolves conflicts with a guided choice (no manual merge editor)
- Shows clear progress and confirmation

**Time:** 2-5 minutes

---

## Process

### Step 1: Pre-Check

**A. Check if Git is available**

Try running basic git command:
```bash
git --version
```

**If Git not found:**
```
❌ Git not detected

Dex updates require Git. Here's how to install:

**Mac:** 
1. Open Terminal (Cmd+Space, type "Terminal")
2. Run: xcode-select --install
3. Click Install when prompted
4. Come back here when done

**Windows:**
1. Download from: https://git-scm.com/download/win
2. Run installer with default options
3. Restart Cursor
4. Try /dex-update again

[Skip update] — I'll do this later
```

If user skips, exit gracefully.

---

**B. Check current setup**

Run: `git remote -v`

**Scenario 1: Downloaded as ZIP (no Git)**
```
❌ Not a Git repository

Looks like you downloaded Dex as a ZIP file instead of cloning it.

**To update:**
1. Download latest version: https://github.com/davekilleen/dex/archive/refs/heads/main.zip
2. Unzip to a new folder
3. Copy these folders from your current Dex to the new one:
   • System/user-profile.yaml
   • System/pillars.yaml
   • 00-Inbox/
   • 01-Quarter_Goals/
   • 02-Week_Priorities/
   • 03-Tasks/
   • 04-Projects/
   • 05-Areas/
   • 06-Resources/ (copy the entire folder, including root-level files)
   • Then replace 06-Resources/Dex_System/ with the copy from the downloaded Dex so shipped documentation stays current
   • 07-Archives/
   • System/Session_Learnings/
   • .env (if it exists)
4. Verify those copies exist in the new folder
5. Delete old Dex folder
6. Rename new folder to 'dex'
7. Open in Cursor

[Show detailed guide] — Open step-by-step instructions
[Cancel] — I'll do this later
```

If detailed guide selected, open `06-Resources/Dex_System/Updating_Dex.md` (Manual Update section).

---

**Scenario 2: Cloned but no upstream remote**

If `git remote -v` shows only "origin" pointing to github.com/davekilleen/dex:

```
✓ Git repository detected

Setting up automatic updates...
```

Run:
```bash
git remote rename origin upstream
```

Continue to Step 2.

---

**Scenario 3: Already configured**

If upstream exists, continue to Step 2.

---

### Step 2: Check for Updates

Call update checker:
```
check_for_updates(force=True)
```

**If no updates available:**
```
✅ You're already on the latest version (v1.2.0)

No update needed!
```
Exit.

**If updates available, show summary:**
```
🎁 Dex v1.3.0 is available

You're on: v1.2.0
Latest: v1.3.0

What's new:
- Career coach improvements
- Task deduplication fix  
- Meeting intelligence enhancement

[View full release notes]
[Update now]
[Cancel]
```

---

### Step 3: Pre-Update Safety Check

**A. Check for uncommitted changes**

Run: `git status --porcelain`

**If there are changes:**
```
💾 Saving your work...

Dex found unsaved changes in your vault.
Let me save them before updating.
```

Run the shipped explicit-candidate, credential-preflight, temporary-index staging helper:
```bash
if ! python3 -m core.utils.safe_autosave; then
  echo "Couldn't prepare your unsaved changes — update stopped before creating a backup tag or changing releases; fix the Git error above, then retry"
  exit 1
fi

echo "Safe autosave completed"
```

Show:
```
✓ Your work is saved
```

**B. Create backup reference (safety net)**

Run:
```bash
if ! git tag backup-before-v1.3.0; then
  echo "Update stopped before changing releases: backup-before-v1.3.0 already exists or could not be created; review or remove that tag, then retry"
  exit 1
fi
```

This creates a snapshot at the just-verified autosave commit. If the fixed tag is stale or cannot be created, the update stops rather than later resetting to an older attempt.

---

### Step 4: Download Updates

```
⬇️ Downloading updates from GitHub...
```

Run:
```bash
git fetch upstream
```

**If network error:**
```
❌ Couldn't connect to GitHub

Please check your internet connection and try again.

[Retry]
[Cancel]
```

**Success:**
```
✓ Updates downloaded
```

---

### Step 5: Check for Breaking Changes

Parse the update response from Step 2.

**If `breaking_changes: true`:**

```
⚠️ Important: This update includes major changes

Dex v2.0.0 includes breaking changes that require extra steps:

[Show what's changing]

This is safe to proceed, but:
• Some folders may be renamed
• Configuration format may change  
• Migration will run automatically

[Continue with update]
[Cancel — I'll read the details first]
```

If cancelled:
- Show link to release notes
- Exit gracefully
- User can run `/dex-update` again when ready

---

### Step 6: Apply Updates

```
🔄 Applying updates...
```

**A. Capture the user-owned MCP trust registry before the merge**

This is unconditional. `.gitignore` protects only untracked files, so preserve the
pre-merge state with the shipped guard copied into system temp before upstream can
change the working tree:

```bash
DEX_TRUST_GUARD_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/dex-update-trust.XXXXXX") || exit 1
cp -- .claude/skills/dex-update/scripts/protect_trust_registry.py \
  "$DEX_TRUST_GUARD_ROOT/protect_trust_registry.py" || exit 1
python3 "$DEX_TRUST_GUARD_ROOT/protect_trust_registry.py" capture \
  --repo "$PWD" --state "$DEX_TRUST_GUARD_ROOT/state" || exit 1
```

**B. Merge updates**

Run:
```bash
git merge upstream/release --no-edit
```

**C. Reject any tracked registry supplied by upstream**

Run this immediately after the merge command whether the merge was clean or conflicted:

```bash
python3 "$DEX_TRUST_GUARD_ROOT/protect_trust_registry.py" restore \
  --repo "$PWD" --state "$DEX_TRUST_GUARD_ROOT/state" || {
    echo "Update stopped: Dex could not protect your MCP trust registry"
    exit 1
  }
```

If upstream introduced or modified a tracked `System/trusted-mcps.yaml`, the guard
removes it from the Git index and warns. It restores the user's exact pre-merge file,
or removes the path entirely if the user never had one. Upstream may **never** supply
this registry or grant consent, even during a clean merge.

If the merge was clean and the guard staged removal of an upstream registry, record
that rejection before continuing:

```bash
if [ ! -f "$(git rev-parse --git-path MERGE_HEAD)" ] && \
   ! git diff --cached --quiet -- System/trusted-mcps.yaml; then
  git commit -m "Protect user-owned MCP trust registry" || exit 1
fi
```

During a conflicted merge, leave the guard's staged removal in place and include it in
the normal merge-resolution commit below. Never `git add` the restored, ignored user
registry.

**D. Handle merge outcome**

**Case 1: Clean merge (no conflicts)**
```
✓ Updates applied successfully
```

Continue to Step 7.

---

**Case 2: Merge conflicts**

Check which files have conflicts:
```bash
git status | grep "both modified"
```

**Automatic conflict resolution (protected blocks + guided choices):**

**Protected user blocks (preserved verbatim):**
- `CLAUDE.md` contains a user block:
  - `USER_EXTENSIONS_START` ... `USER_EXTENSIONS_END`

**Custom MCP servers (preserved by name):**
- Any MCP server name starting with `custom-` is preserved
- Example: `custom-gmail`, `custom-hubspot`

**Custom skills (preserved by name):**
- Any skill folder ending with `-custom` is preserved
- Example: `meeting-prep-custom`, `daily-plan-custom`

**When conflicts occur:**

1. **If file is user data** (00-07, System/user-profile.yaml, System/pillars.yaml, System/trusted-mcps.yaml):
   - Keep user version
   - Run: `git checkout --ours <file>`

2. **If file contains protected user block** (CLAUDE.md):
   - Take upstream version
   - Re-insert preserved user block(s) verbatim
   - Validate markers still present

3. **If file is .mcp.json**:
   - Preserve any MCP entries named `custom-*`
   - Continue with Dex core updates for all other MCPs

4. **If skill folder ends with `-custom`**:
   - Preserve entirely, never modify
   - These are user's personal skills

5. **If file is core Dex** (skills, core MCP, scripts) **and user edited it**:
   - Use AskUserQuestion to resolve, instead of a merge editor

**AskUserQuestion flow (generic, parameterized):**
```
Title: Dex update conflict: {{item_name}}

Your change:
{{user_change_summary}}
Enables: {{user_use_case_summary}}

Dex update:
{{dex_change_summary}}
Enables: {{dex_use_case_summary}}

Options:
1) Keep my version (preserve my changes)
2) Use Dex version (take upstream changes)
3) Keep both (rename one)
4) Let me tell you what to do (I'll write instructions)
```

**If AskUserQuestion is not available (non-Claude Code):**
- Use a simple CLI prompt with the same 4 options.
- Add one-line tradeoffs to each option (what you keep vs lose).
- If user types an invalid choice, re-prompt once and default to "Keep my version" so an input mistake cannot discard user work.

**If user chooses "Keep both":**
- MCP: `name` → `name-custom`
- Skill folder: `name/` → `name-custom/`

**After resolving all conflicts:**
```bash
git add <file>
git commit --no-edit
```

**Show to user:**
```
✓ Updates applied successfully

Handled conflicts:
• Preserved your protected blocks
• Updated core Dex features
• Resolved overlapping changes with your choice

[See what changed]
```

---

**Case 3: Merge failed (rare)**

```
❌ Update couldn't complete automatically

This is rare, but sometimes updates need manual review.

**What happened:**
[Error message]

**Options:**
[Restore to before update] — Uses the backup we created
[Get help] — Opens GitHub issue template
```

If restore:
```bash
# Run this protected-reset block with bash or zsh, from the vault root.
[ -f package.json ] && [ -d .claude ] || { echo "run from the vault root"; exit 1; }

git merge --abort
DEX_UPDATE_RESET_TARGET="backup-before-v1.3.0"
DEX_USER_DATA_PATHS=(
  "00-Inbox/" "01-Quarter_Goals/" "02-Week_Priorities/" "03-Tasks/"
  "04-Projects/" "05-Areas/" "06-Resources/" "07-Archives/"
  "System/user-profile.yaml" "System/pillars.yaml" "System/trusted-mcps.yaml" "System/Session_Learnings/"
)
DEX_USER_DATA_SOURCE=$(git rev-parse HEAD)
DEX_DATA_STASH_BEFORE=$(git rev-parse -q --verify refs/stash 2>/dev/null || true)
DEX_USER_DATA_STASH_PATHS=(
  ":(top,glob)00-Inbox/**" ":(top,glob)01-Quarter_Goals/**"
  ":(top,glob)02-Week_Priorities/**" ":(top,glob)03-Tasks/**"
  ":(top,glob)04-Projects/**" ":(top,glob)05-Areas/**"
  ":(top,glob)06-Resources/**" ":(top,glob)07-Archives/**"
  ":(top)System/user-profile.yaml" ":(top)System/pillars.yaml"
  ":(top)System/trusted-mcps.yaml"
  ":(top,glob)System/Session_Learnings/**"
)
git stash push --all \
  -m "dex-user-data-before-update-recovery-$(date +%Y%m%d-%H%M%S)" \
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
    echo "Update recovery stopped: changed user data remains outside the snapshot, so no reset ran"
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

if ! git reset --hard "$DEX_UPDATE_RESET_TARGET"; then
  echo "Update recovery stopped: the reset failed. User data remains at $DEX_USER_DATA_SOURCE and in $DEX_DATA_STASH_REF"
  exit 1
fi
if ! git restore --source="$DEX_USER_DATA_SOURCE" --staged --worktree -- "${DEX_USER_DATA_PATHS[@]}"; then
  if dex_export_user_data_rescue; then
    echo "Update recovery stopped: the committed snapshot was exported to $DEX_RESCUE_DIR"
  else
    echo "Do not continue: use commit $DEX_USER_DATA_SOURCE and $DEX_DATA_STASH_REF to recover user data"
  fi
  exit 2
fi
if [ -n "$DEX_DATA_STASH_REF" ] && ! git stash pop "$DEX_DATA_STASH_REF"; then
  if dex_export_user_data_rescue; then
    echo "Update recovery stopped for review: both user-data versions are preserved in $DEX_RESCUE_DIR"
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

Some files in 00-07 are tracked. The recovery therefore restores their pre-reset snapshot explicitly; it does not assume ignore rules make them safe.

---

### Step 7: Post-Update Steps

**A. Check for migration needs**

If breaking_changes was true, check for migration script:

```bash
ls core/migrations/v*-to-v*.sh 2>/dev/null | grep -v -- '-example'   # templates ending in -example.sh are not migrations
```

If found:
```
🔧 Running migration...

This update requires a one-time migration to update your data structure.
This is safe and automatic.
```

Run:
```bash
./core/migrations/<script-found-by-the-check-above>.sh --auto
```

Show migration output.

**B. Update dependencies**

```
📦 Updating dependencies...
```

Run:
```bash
npm install
```

Update Python dependencies using the venv. Create the venv first if upgrading from an older Dex that used system pip:
```bash
if [ ! -d ".venv" ]; then python3 -m venv .venv; fi
.venv/bin/pip install -r core/mcp/requirements.txt
```

**C. Sync MCP Configuration (Automatic)**

Check if new MCP servers were added in the update by comparing `.mcp.json.example` entries against the user's live `.mcp.json` (or `System/.mcp.json`).

For each entry in `.mcp.json.example` that is NOT in the user's `.mcp.json`:
1. Read the entry from `.mcp.json.example`
2. Replace `{{VAULT_PATH}}` with the actual vault path
3. **Skip** entries whose env values still contain `{{...}}` placeholder patterns after substitution
4. **Skip** entries whose key starts with `_` (comment keys)
5. Add to the user's `.mcp.json`
6. Log: "✓ Added new MCP server: [name]"

**Never remove or modify existing user MCP entries.** Only add missing ones.

**Example:** If `.mcp.json.example` has `dex-analytics` but user's config doesn't:
```json
"dex-analytics": {
  "type": "stdio",
  "command": "<vault_path>/.venv/bin/python",
  "args": ["<vault_path>/core/mcp/analytics_server.py"],
  "env": { "VAULT_PATH": "<vault_path>" }
}
```

**Note:** Always use the venv Python path (`<vault_path>/.venv/bin/python`) for new Python MCP entries, never `"python"` or `"python3"`.

Add to summary if new MCPs added: "✓ Added new MCP servers: dex-analytics"

**D. Sync Usage Log Features (Automatic)**

Merge new feature entries from the template `System/usage_log.md` into the user's existing `System/usage_log.md`.

**Merge logic:**
1. Read the upstream template `System/usage_log.md` (from the just-updated dex-core files)
2. Read the user's existing `System/usage_log.md`
3. For each `- [ ]` or `- [x]` line in the template:
   - Extract the feature description (text after the checkbox)
   - Search the user's file for a line containing the same feature description
   - **If found:** Keep the user's version (preserves their `[x]` state)
   - **If NOT found:** This is a new feature — add it to the same section in the user's file
4. Preserve ALL user state: checked boxes, consent decisions, journey metadata, dates
5. Update the feature count in `Feature adoption score: X/Y` (Y = new total)

**Section matching:** Match new entries to the correct section by the `## Section Name` headers (e.g., "## Core Workflows", "## Advanced"). If a new section exists in the template but not in the user's file, add the entire section.

**Never:**
- Uncheck a user's checked box
- Change consent or metadata values
- Remove entries the user has

Log: "✓ Added N new features to usage_log.md" (or "✓ Usage log up to date" if nothing added)

**E. Enable new background automations (Automatic)**

Check for automation scripts that need installation. These run silently without prompting.

**Meeting Sync (when Granola is connected):**

Check if Granola is installed:
```bash
[ -d "/Applications/Granola.app" ] && echo "Granola app detected — run /granola-setup to connect it (needs a Granola Business API key)"
```

Check for `GRANOLA_API_KEY` in the environment, then in the vault-root `.env`, matching the meeting sync worker. App presence does not gate API-backed sync.

If no key is present, do not install the automation. If the app is present, add this to the summary: "Granola app detected — run `/granola-setup` to connect it (needs a Granola Business API key)." If the app is absent, include the https://granola.ai install pointer before the `/granola-setup` guidance.

If the API key is configured and meeting automation is not yet installed:
```bash
# Check if already installed
launchctl list | grep com.dex.meeting-intel
```

If not installed:
```bash
cd .scripts/meeting-intel && ./install-automation.sh 2>/dev/null
```

Add to summary if installed: "✓ Enabled automatic meeting sync (runs every 30 min)"

**Nightly smoke (reinstall if already installed):**

```bash
if launchctl list | grep -q com.dex.smoke-nightly; then
  .scripts/install-smoke-automation.sh 2>/dev/null
fi
```

Add to summary if reinstalled: "✓ Updated nightly self-check automation"

**Future automations:** This pattern extends to other background services. Check for the prerequisite (e.g., app installed, API key present), then run the installer silently.

---

### Step 8: Verification

```
✓ Update complete! Now testing...
```

Run Dex's quick doctor with safe healing, then its isolated end-to-end journeys. Use the same venv interpreter for both:

```bash
.venv/bin/python core/utils/doctor.py --heal
.venv/bin/python core/utils/smoke.py --json
```

The smoke command exits `1` when a journey is `BROKEN`; keep and inspect its JSON output instead of discarding it. Exit `2` means the smoke harness itself failed and must be reported as `UNKNOWN`.

Add the corresponding `summary` counts from both JSON reports and always render all four buckets:

```
Verification
✓ OK: N
○ OFF: N
✗ BROKEN: N
? UNKNOWN: N
```

`OFF` is informational, not a failure. If there are no `BROKEN` or `UNKNOWN` results:

```
✅ Update verified successfully!
```

If a customization is `BROKEN`, name the exact file from the finding and keep the update in place:

```
⚠️ Update applied, but one of your customizations needs attention

Fix your customization: [exact path]
[Exact doctor or smoke detail]

Dex will not roll back for a customization problem.
```

Customization failures include `-custom` skills, `custom-*` MCP entries, the `USER_EXTENSIONS` block, and user-owned YAML/integration files. **Never recommend `/dex-rollback` or `/dex-update` for these findings.**

If an unmodified Dex-owned file or journey is `BROKEN`, the update has not proved itself. Name the failing check and offer the backup path created in Step 3:

```
❌ Update verification failed in Dex-owned code

[Exact check and detail]

Your data is safe, but you may want to:
[Restore to previous version] — Run /dex-rollback using backup-before-v1.3.0
[Report this issue]
```

Do not roll back automatically. If there are only `UNKNOWN` results, say the update was applied but could not be fully verified, list each unknown detail, and do not declare verification successful.

---

### Step 9: Summary

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Dex Updated: v1.2.0 → v1.3.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

What's new:
• Career coach improvements
• Task deduplication fix
• Meeting intelligence enhancement

Your data:
✓ Note files present after update
✓ Task files present after update
✓ Protected customization markers and entries present

[View full changelog]
[Start using new features]
```

**If new automations were enabled:**
```
🤖 New automations enabled:
✓ Automatic meeting sync (runs every 30 min)
```

**If there were conflicts:**
```
🔍 Changes applied:
• Updated 12 core files
• Kept 5 of your customized files
• Kept your version of every user-data conflict

[See detailed change list]
```

---

### Step 9b: Check New Integrations (After Success)

After successful update, check if new integration features are available:

```python
from core.integrations import get_post_update_integration_message, should_show_integration_prompt

if should_show_integration_prompt():
    msg = get_post_update_integration_message()
    if msg:
        print(msg)
```

**If integrations are available but not configured:**
```
---

## 🔌 New: Productivity Integrations

This update includes integrations for your favorite tools:

- **Notion** — Search your workspace, pull docs into meeting prep
- **Slack** — Search conversations, get context about people
- **Google** — Gmail search, email context in person pages

**Set up now?** These are optional but unlock powerful features like:
- "What did Sarah say about the Q1 budget?" → Searches Slack
- Meeting prep pulls relevant docs from Notion
- Person pages show email/Slack history

Run `/integrate-mcp` to connect any of these tools.
```

**If user has integrations that could be upgraded:**
```
---

## 🔄 Integration Upgrade Available

You have some integrations that could be upgraded to Dex recommended packages:

### Notion
- **Current:** custom-notion-mcp
- **Recommended:** @notionhq/notion-mcp-server
- **Benefits:** Official from Notion, Best maintained, Full API coverage

**Options:**
1. **Keep existing** — Your current setup works fine
2. **Upgrade** — Run `/integrate-mcp` to review and switch the connection
```

---

### Step 10: Track Usage (Silent)

Update `System/usage_log.md` to mark Dex update as used.

**Analytics (Silent):**

Call `track_event` with event_name `dex_update_completed` and properties:
- `from_version`
- `to_version`

This only fires if the user has opted into analytics. No action needed if it returns "analytics_disabled".

**Clear update notification:**

Call `dismiss_update()` from the Update Checker MCP to remove the `System/.update-available` file. This stops the daily update reminder from appearing in future sessions.

---

## Error Recovery

### If Update Fails at Any Point

User always has escape hatch:

```
🔙 Restoring to before update...
```

Run:
```bash
# Requires bash or zsh because the protected paths below are arrays.
[ -f package.json ] && [ -d .claude ] || { echo "run from the vault root"; exit 1; }

git merge --abort 2>/dev/null || true
DEX_UPDATE_RESET_TARGET="backup-before-v1.3.0"
DEX_USER_DATA_PATHS=(
  "00-Inbox/" "01-Quarter_Goals/" "02-Week_Priorities/" "03-Tasks/"
  "04-Projects/" "05-Areas/" "06-Resources/" "07-Archives/"
  "System/user-profile.yaml" "System/pillars.yaml" "System/trusted-mcps.yaml" "System/Session_Learnings/"
)
DEX_USER_DATA_SOURCE=$(git rev-parse HEAD)
DEX_DATA_STASH_BEFORE=$(git rev-parse -q --verify refs/stash 2>/dev/null || true)
DEX_USER_DATA_STASH_PATHS=(
  ":(top,glob)00-Inbox/**" ":(top,glob)01-Quarter_Goals/**"
  ":(top,glob)02-Week_Priorities/**" ":(top,glob)03-Tasks/**"
  ":(top,glob)04-Projects/**" ":(top,glob)05-Areas/**"
  ":(top,glob)06-Resources/**" ":(top,glob)07-Archives/**"
  ":(top)System/user-profile.yaml" ":(top)System/pillars.yaml"
  ":(top)System/trusted-mcps.yaml"
  ":(top,glob)System/Session_Learnings/**"
)
git stash push --all \
  -m "dex-user-data-before-update-error-recovery-$(date +%Y%m%d-%H%M%S)" \
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
    echo "Update recovery stopped: changed user data remains outside the snapshot, so no reset ran"
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

if ! git reset --hard "$DEX_UPDATE_RESET_TARGET"; then
  echo "Update recovery stopped: the reset failed. User data remains at $DEX_USER_DATA_SOURCE and in $DEX_DATA_STASH_REF"
  exit 1
fi
if ! git restore --source="$DEX_USER_DATA_SOURCE" --staged --worktree -- "${DEX_USER_DATA_PATHS[@]}"; then
  if dex_export_user_data_rescue; then
    echo "Update recovery stopped: the committed snapshot was exported to $DEX_RESCUE_DIR"
  else
    echo "Do not continue: use commit $DEX_USER_DATA_SOURCE and $DEX_DATA_STASH_REF to recover user data"
  fi
  exit 2
fi
if [ -n "$DEX_DATA_STASH_REF" ] && ! git stash pop "$DEX_DATA_STASH_REF"; then
  if dex_export_user_data_rescue; then
    echo "Update recovery stopped for review: both user-data versions are preserved in $DEX_RESCUE_DIR"
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
git status --short
```

Do not run `git clean` during recovery: untracked files may be the user's unsaved work. Any stray files created by the failed update are left in place and listed by `git status` for review.

```
✓ Restored to v1.2.0

Tracked Dex files are back to their pre-update state. User data was restored from the protected snapshot, and untracked files were left in place. If the restore needed manual review, the command stopped and printed the timestamped rescue folder instead of showing this success message.

[Try update again]
[Report issue]
[Cancel]
```

---

## Migration Support (for Breaking Changes)

### Auto-Migration Flag

If migration script supports `--auto` flag, run non-interactively:

```bash
./core/migrations/<script-found-by-the-check-above>.sh --auto
```

**Migration script must:**
- Accept `--auto` flag
- Skip confirmation prompts
- Return exit code 0 on success
- Log to `System/.migration-log`

### Manual Migration Required

If script doesn't support `--auto`:

```
⚠️ Manual step required

This update needs you to run a migration script.

Don't worry - it's one command and takes 30 seconds.

**In Cursor's terminal (bottom panel), run:**

./core/migrations/<script-found-by-the-check-above>.sh

**Then come back here when it's done.**

[I've run the migration — continue]
[Show me what the migration does]
[Cancel update]
```

---

## Alternative: ZIP Download Path

For users who can't/won't use Git, provide manual instructions:

```
📥 Manual Update Method

If automatic updates don't work, you can update manually:

1. **Download latest Dex:**
   https://github.com/davekilleen/dex/archive/refs/heads/main.zip

2. **Copy your data and custom blocks:**
   From OLD Dex folder, copy these to NEW Dex folder:
   
   ✓ System/user-profile.yaml
   ✓ System/pillars.yaml
   ✓ 00-Inbox/ (entire folder)
   ✓ 01-Quarter_Goals/ (entire folder)
   ✓ 02-Week_Priorities/ (entire folder)
   ✓ 03-Tasks/ (entire folder)
   ✓ 04-Projects/ (entire folder)
   ✓ 05-Areas/ (entire folder)
   ✓ 06-Resources/ (copy the entire folder, including root-level files)
   ✓ Then replace 06-Resources/Dex_System/ with the copy from the downloaded Dex so shipped documentation stays current
   ✓ 07-Archives/ (entire folder)
   ✓ System/Session_Learnings/
   ✓ .env (if it exists)
   ✓ Your `USER_EXTENSIONS` block from `CLAUDE.md`
   ✓ Any custom MCP entries named `custom-*` from `.mcp.json`
   ✓ Any custom skills ending with `-custom`

3. **DON'T copy:**
   ✗ .claude/skills/ (use new version)
   ✗ core/mcp/ (use new version)
   ✗ README.md (use new version)

4. **Open new folder in Cursor**

5. **Run /setup to verify**

[Download now]
[Copy step-by-step instructions to clipboard]
```

---

## Settings

User can configure update behavior in `System/user-profile.yaml`:

```yaml
updates:
  auto_check: true              # Check during /daily-plan
  check_interval_days: 7        # How often to check
  auto_update: false            # Never auto-update without asking
  backup_before_update: true    # Always create backup tag
```

---

## Related Commands

- `/dex-whats-new` - Check what's new without updating
- `/dex-rollback` - Undo last update (if something went wrong)
- `/dex-update-settings` - Configure update preferences

---

## Non-Technical User Experience

**User sees in daily plan:**
```
🎁 Dex v1.3.0 is available. Run /dex-whats-new for details.
```

**User runs:**
```
/dex-update
```

**User sees:**
```
✓ Git detected
✓ Updates downloaded
✓ No conflicts
✓ Dependencies updated
✅ Update complete! v1.2.0 → v1.3.0
```

**Total clicks:** 1 (just ran the command)
**Total time:** 2 minutes
**Technical knowledge required:** Zero

---

## Philosophy

**Automatic where possible:**
- Git commands run silently
- Conflicts resolved automatically
- Dependencies updated automatically
- Migrations run automatically (when safe)

**Interactive where necessary:**
- Breaking changes: confirm understanding
- Manual migration: clear instructions
- Errors: always offer restoration

**Safe always:**
- Backup created before any changes
- Some files in 00-07 are tracked, so hard-reset recovery snapshots and restores all eight data folders explicitly
- Restore conflicts stop the recovery and keep both versions in a timestamped rescue folder
- One-command rollback if issues
- Clear status at every step

**No jargon:**
- Don't say "merge conflict" - say "overlapping changes"
- Don't say "upstream" - say "main Dex repository"
- Don't say "git fetch" - say "downloading updates"
- Don't say "rebase" - just don't use rebase
