# Dex Migration Scripts

This folder contains migration scripts for major version updates that require structural changes to user data.

---

## When Migrations Are Needed

**Minor/Patch updates (v1.2.0 → v1.3.0):** No migration needed - just merge
**Major updates (v1.x → v2.0.0):** Migration required for breaking changes

**Breaking changes include:**
- Folder renames (e.g., `03-Tasks/` → `03-Backlog/`)
- File format changes (e.g., YAML schema updates)
- Configuration structure changes
- Metadata format updates

---

## How Migrations Work

### For Users

**Step 1: Check release notes**
```
/dex-whats-new
```

If you see ⚠️ **BREAKING CHANGES**, read the release notes carefully.

**Step 2: Back up your vault**
```bash
cp -r ~/Documents/dex ~/Documents/dex-backup-$(date +%Y%m%d)
```

**Step 3: Run the migration script**
```bash
./core/migrations/v1-to-v2.sh
```

The script will:
- Check if migration is needed
- Transform your data safely
- Report what changed
- Create `.migration-log` file

**Step 4: Review changes**
```bash
git status
git diff
```

**Step 5: Update Dex**
```bash
git fetch upstream
git merge upstream/main
```

**Step 6: Test**

Run key workflows to verify everything works:
- `/daily-plan`
- Open person pages
- Check tasks

If anything breaks, restore from backup and report the issue.

---

## For Maintainers

### Creating a Migration Script

**Template:**

```bash
#!/bin/bash
# Migration: v1.x → v2.0.0
# Description: [What this migration does]
# Date: YYYY-MM-DD

set -e  # Exit on error

echo "================================================"
echo "Dex Migration: v1.x → v2.0.0"
echo "Description: [Brief description]"
echo "================================================"
echo ""

# Check if migration already ran
if [ -f ".migration-v2-complete" ]; then
    echo "✓ Migration already completed"
    echo "  Remove .migration-v2-complete to run again"
    exit 0
fi

# Dry run first
echo "🔍 Checking what needs migration..."
echo ""

# [Detection logic - what needs changing?]

echo ""
read -p "Proceed with migration? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Migration cancelled"
    exit 1
fi

# Actual migration
echo ""
echo "🔄 Migrating..."

# [Migration logic]

# Mark as complete
touch .migration-v2-complete
echo "2.0.0" > .migration-version

echo ""
echo "================================================"
echo "✅ Migration complete!"
echo "================================================"
echo ""
echo "Next steps:"
echo "1. Review changes: git status && git diff"
echo "2. Update Dex: git fetch upstream && git merge upstream/main"
echo "3. Test workflows: /daily-plan, person pages, tasks"
echo ""
```

### Migration Best Practices

1. **Idempotent**: Safe to run multiple times
2. **Reversible**: Can undo if needed (or at least document how)
3. **Verbose**: Tell user what's happening
4. **Safe**: Verify before destructive operations
5. **Tested**: Run on multiple test vaults before release

### Testing Migrations

Before releasing:

1. Create test vaults representing different user states:
   - Fresh install
   - Heavily customized
   - Multiple projects and people
   - Custom folder names

2. Run migration on each test vault

3. Verify:
   - All data preserved
   - No corruption
   - Skills still work
   - MCP servers functional

---

## Migration Log

Migrations are logged to `System/.migration-log`:

```
2026-03-15 14:23:11 | v1-to-v2 | Started
2026-03-15 14:23:15 | v1-to-v2 | Renamed 03-Tasks/ → 03-Backlog/
2026-03-15 14:23:18 | v1-to-v2 | Updated 47 markdown file references
2026-03-15 14:23:19 | v1-to-v2 | Complete
```

This helps debug if something goes wrong.

---

## Example: Folder Rename Migration

See `v1-to-v2-example.sh` for a complete example of a folder rename migration.

---

## Emergency Rollback

If migration fails:

```bash
# Restore from backup
rm -rf ~/Documents/dex
cp -r ~/Documents/dex-backup-YYYYMMDD ~/Documents/dex

# Report issue
# Open GitHub issue with .migration-log contents
```

---

## Questions?

- **GitHub Issues:** Report migration problems
- **Discussions:** Ask about migration strategy
- **CHANGELOG.md:** See migration requirements for each major version
