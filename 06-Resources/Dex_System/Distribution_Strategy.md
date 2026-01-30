# Dex Distribution Strategy

**Last Updated:** January 29, 2026

This document explains how Dex handles updates, customizations, and distribution to users.

---

## Core Philosophy

**Dex is yours, not ours.**

When users clone Dex, they get a complete copy that they customize heavily:
- Rename folders
- Modify skills
- Create custom MCP servers
- Fill with personal data (notes, tasks, projects)

Updates must **enhance without disrupting**. We ship improvements that users can safely merge while preserving their customizations.

---

## The Distribution Model

### Git Upstream Pattern

Dex uses the "framework model" - users maintain their own repo with the main Dex repo as an upstream source.

**User setup (one time):**

```bash
git clone https://github.com/davekilleen/dex.git my-dex
cd my-dex
git remote rename origin upstream    # Main repo becomes "upstream"
git remote add origin <their-repo>   # Optional: their backup
```

**User workflow:**

```bash
git fetch upstream                   # Download updates
git merge upstream/main              # Merge safely
```

**What happens:**
- New files automatically added
- Changed core files merge cleanly
- User customizations preserved (gitignored or separate folders)
- Conflicts marked clearly if both modified same file

---

## Protected Customizations

### What's Gitignored (Never Tracked)

These files/folders are in `.gitignore` so updates never touch them:

```
# User configuration
System/user-profile.yaml
System/pillars.yaml
System/.last-update-check

# Custom extensions
CLAUDE-custom.md                     # User prompt overrides
.claude/skills-custom/               # User custom skills
core/mcp-custom/                     # User custom MCP servers

# User data (PARA structure)
00-Inbox/
01-Quarter_Goals/
02-Week_Priorities/
03-Tasks/
04-Projects/
05-Areas/
07-Archives/

# Secrets
.env
.mcp.json
```

**Result:** User data and customizations are never tracked by Git, so updates can't conflict with them.

### What Updates Safely

These files are tracked and update cleanly:

```
# Core skills (users don't usually modify)
.claude/skills/

# Core MCP servers
core/mcp/*.py

# Documentation
README.md
CHANGELOG.md
06-Resources/Dex_System/*.md

# Core infrastructure
install.sh
package.json
.scripts/
```

**Strategy:** If users want to customize core files, they use override patterns (see below).

---

## Customization Patterns

### Pattern 1: Custom Folders

Keep custom work separate:

```
.claude/skills/           ← Our skills (updateable)
.claude/skills-custom/    ← User skills (protected)

core/mcp/                 ← Our servers (updateable)
core/mcp-custom/          ← User servers (protected)
```

### Pattern 2: Override Files

Instead of editing `CLAUDE.md`, users create:

```
CLAUDE-custom.md          ← Gitignored, user-specific
```

At end of `CLAUDE.md`:
```markdown
<!-- If CLAUDE-custom.md exists, load it for user overrides -->
```

This way updates to `CLAUDE.md` never conflict with user changes.

### Pattern 3: Namespace Separation

User creates `System/my-customizations.md` documenting their changes. Helps resolve conflicts later.

---

## Update Notification System

### Automatic Checks

**Trigger:** During `/daily-plan`, every 7 days

**Process:**
1. Update checker MCP calls GitHub API
2. Compares local `package.json` version with latest release
3. If newer version available, stores notification
4. Notification prepended to daily plan output

**User experience:**
```
🎁 Dex v1.3.0 is available. Run /dex-whats-new for details.

---

Here's your plan for today...
```

**Benefits:**
- Non-intrusive (doesn't block workflow)
- Automatic (users don't need to remember to check)
- Respectful (only every 7 days, can disable)

### Manual Checks

**Command:** `/dex-whats-new`

**Shows:**
- Current version vs latest version
- Full release notes
- Breaking change warnings
- Direct link to GitHub release
- Update instructions

**Force check:** Ignores 7-day interval when invoked manually

---

## Handling Breaking Changes

### Version Numbering

**Semantic Versioning:**
- **Patch (v1.2.3 → v1.2.4):** Bug fixes, no migration
- **Minor (v1.2.0 → v1.3.0):** New features, backwards compatible
- **Major (v1.x → v2.0.0):** Breaking changes, migration required

### Migration Scripts

When major updates require structural changes (folder renames, schema updates), we provide migration scripts:

**Location:** `core/migrations/v1-to-v2.sh`

**Migration script must:**
- Be idempotent (safe to run multiple times)
- Check if already migrated
- Show dry run before executing
- Require user confirmation
- Log all changes to `System/.migration-log`
- Provide rollback instructions

**Example:** Renaming `03-Tasks/` to `03-Backlog/`

```bash
./core/migrations/v1-to-v2.sh    # Transforms user data
git fetch upstream                # Then pull updates
git merge upstream/main
```

### CHANGELOG Format for Breaking Changes

```markdown
## [2.0.0] - 2026-03-15

### ⚠️ BREAKING CHANGES

**Folder Rename:** 03-Tasks/ → 03-Backlog/

**Migration required:**
1. Back up your vault
2. Run: ./core/migrations/v1-to-v2.sh
3. Review changes: git diff
4. Update Dex: git fetch upstream && git merge upstream/main

**Why this change:** [Explanation]
```

---

## Conflict Resolution

### When Conflicts Happen

Conflicts occur when both the user AND the main repo modified the same file.

**Example:**
```bash
$ git merge upstream/main
CONFLICT (content): Merge conflict in CLAUDE.md
```

### Resolution Strategy by File Type

| File Type | Recommended Action |
|-----------|-------------------|
| User data (00-07/) | **Always keep user version** |
| System config (user-profile.yaml) | **Always keep user version** |
| Core skills (.claude/skills/) | **Keep upstream** (unless user customized) |
| MCP servers (core/mcp/) | **Keep upstream** (unless user customized) |
| CLAUDE.md | **Tricky - review both** |
| Documentation | **Keep upstream** (usually) |

### Handling CLAUDE.md Conflicts

Since CLAUDE.md is central and users might customize it:

**Recommended:**
- Point users to override pattern (`CLAUDE-custom.md`)
- During conflict, examine both versions
- If user made significant changes, suggest moving them to `CLAUDE-custom.md`
- Then accept upstream version of `CLAUDE.md`

This prevents future conflicts while preserving user customizations.

---

## Update Process (User Perspective)

### Regular Updates (Minor/Patch)

**Step 1:** Get notified
- During `/daily-plan`: "🎁 Dex v1.3.0 is available"
- Or run: `/dex-whats-new`

**Step 2:** Save work
```bash
git status
git add .
git commit -m "My changes before update"
```

**Step 3:** Merge updates
```bash
git fetch upstream
git merge upstream/main
```

**Step 4:** Reinstall dependencies (if needed)
```bash
npm install
pip3 install -r core/mcp/requirements.txt
```

**Time:** 2-5 minutes

### Major Updates (Breaking Changes)

**Step 1:** Read release notes
- Check for ⚠️ BREAKING CHANGES warning
- Understand what's changing

**Step 2:** Back up
```bash
cp -r ~/Documents/dex ~/Documents/dex-backup-$(date +%Y%m%d)
```

**Step 3:** Run migration
```bash
./core/migrations/v1-to-v2.sh
```

**Step 4:** Review changes
```bash
git diff
```

**Step 5:** Merge updates
```bash
git fetch upstream
git merge upstream/main
```

**Step 6:** Test
- `/daily-plan`
- Open person pages
- Check tasks

**Time:** 10-15 minutes

---

## Technical Implementation

### Update Checker MCP

**File:** `core/mcp/update_checker.py`

**Tools:**
- `check_for_updates(force=bool)` - Main update check
- `get_changelog_from_github(version=str)` - Fetch CHANGELOG
- `get_update_status()` - Current version status

**API Calls:**
- GitHub API: `https://api.github.com/repos/davekilleen/dex/releases/latest`
- Rate limit friendly: 7-day interval, respects 304 Not Modified

**State:**
- Last check time: `System/.last-update-check`
- Current version: `package.json` → `version` field

### Integration with `/daily-plan`

**Step 1** in daily-plan skill:
```yaml
1. Call check_for_updates(force=False)
2. If update_available: store notification
3. Continue silently (don't wait for user)
4. At Step 7 (output): prepend notification if present
```

**Silent operation:** No "Checking for updates..." message, no blocking.

---

## Best Practices

### For Users

1. **Set up upstream remote** immediately after cloning
2. **Check updates monthly** (or when notified)
3. **Keep custom work in protected folders** (skills-custom/, mcp-custom/)
4. **Document customizations** in `System/my-customizations.md`
5. **Back up before major updates**

### For Maintainers

1. **Minimize breaking changes** - refactor without user impact
2. **Provide migration scripts** for unavoidable changes
3. **Clear CHANGELOG entries** - users read these
4. **Test on diverse vaults** before releasing major versions
5. **Preserve gitignore patterns** - user data stays protected

### For Contributors

1. **Don't modify gitignored files** in PRs
2. **Document any breaking changes** prominently
3. **Test merge workflows** - does your change merge cleanly?
4. **Respect customization patterns** - use override files

---

## Monitoring & Support

### User-Reported Issues

Track update-related problems:
- Merge conflicts that shouldn't happen
- Data loss during updates
- Migration script failures
- Breaking changes not caught

**Label:** `update-system` on GitHub issues

### Metrics to Watch

- How many users run `/dex-whats-new`
- Merge conflict rates (via GitHub Discussions)
- Migration script success rates
- Time between releases and user updates

---

## Future Enhancements

### Potential Improvements

1. **Diff preview before merge**
   - Show exactly what will change
   - "Accept all" vs "Review each file"

2. **Automated testing**
   - Run test vault through update workflow
   - Verify no data loss

3. **Rollback command**
   - `/dex-rollback` to undo last update
   - Automatic backup before major updates

4. **Update staging**
   - Try update in temporary branch
   - Commit only if tests pass

5. **Community plugins**
   - Registry of user-created skills/MCPs
   - One-command install: `/install-plugin [name]`

---

## Related Documentation

- **User Guide:** `06-Resources/Dex_System/Updating_Dex.md`
- **Migration README:** `core/migrations/README.md`
- **Technical Guide:** `06-Resources/Dex_System/Dex_Technical_Guide.md` (MCP section)
- **Skills Catalog:** `.claude/skills/README.md`

---

## Summary

**Distribution model:** Git upstream pattern (framework approach)

**User experience:** Automatic notifications, manual updates, safe merges

**Protection:** Gitignore + custom folders + override patterns

**Breaking changes:** Migration scripts + clear warnings

**Philosophy:** Your vault, your customizations, our improvements - all coexisting safely.
