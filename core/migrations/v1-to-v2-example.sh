#!/bin/bash
# Dex Migration: v1.x → v2.0.0 (EXAMPLE)
# Description: Renames 03-Tasks/ to 03-Backlog/ and updates all references
# This is an EXAMPLE - not a real migration. Shows the pattern for future use.
# Date: 2026-01-29

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "================================================"
echo "Dex Migration: v1.x → v2.0.0 (EXAMPLE)"
echo "Description: Renames 03-Tasks/ to 03-Backlog/"
echo "================================================"
echo ""
echo "${YELLOW}NOTE: This is an EXAMPLE migration script.${NC}"
echo "Real migrations will follow this pattern when needed."
echo ""

# Check if already migrated
if [ -f ".migration-v2-complete" ]; then
    echo "${GREEN}✓${NC} Migration already completed"
    echo "  Remove .migration-v2-complete to run again"
    exit 0
fi

# Dry run - check what needs migration
echo "🔍 Checking what needs migration..."
echo ""

NEEDS_MIGRATION=false

# Check if 03-Tasks/ exists
if [ -d "03-Tasks" ]; then
    echo "${YELLOW}→${NC} Found 03-Tasks/ folder (will rename to 03-Backlog/)"
    NEEDS_MIGRATION=true
else
    echo "${GREEN}✓${NC} 03-Tasks/ folder not found (already migrated or doesn't exist)"
fi

# Check for references in markdown files
MD_FILE_COUNT=$(find . -type f -name "*.md" -exec grep -l "03-Tasks" {} \; 2>/dev/null | wc -l | tr -d ' ')
if [ "$MD_FILE_COUNT" -gt 0 ]; then
    echo "${YELLOW}→${NC} Found references to '03-Tasks' in $MD_FILE_COUNT markdown files"
    NEEDS_MIGRATION=true
else
    echo "${GREEN}✓${NC} No references to '03-Tasks' in markdown files"
fi

# Check YAML files
YAML_FILE_COUNT=$(find . -type f -name "*.yaml" -exec grep -l "03-Tasks" {} \; 2>/dev/null | wc -l | tr -d ' ')
if [ "$YAML_FILE_COUNT" -gt 0 ]; then
    echo "${YELLOW}→${NC} Found references to '03-Tasks' in $YAML_FILE_COUNT YAML files"
    NEEDS_MIGRATION=true
else
    echo "${GREEN}✓${NC} No references to '03-Tasks' in YAML files"
fi

echo ""

if [ "$NEEDS_MIGRATION" = false ]; then
    echo "${GREEN}✅ No migration needed - vault is already up to date${NC}"
    touch .migration-v2-complete
    echo "2.0.0" > .migration-version
    exit 0
fi

# Confirm before proceeding
echo "${YELLOW}⚠️  Migration will make the following changes:${NC}"
echo "  1. Rename: 03-Tasks/ → 03-Backlog/"
echo "  2. Update references in all markdown files"
echo "  3. Update references in all YAML files"
echo ""
echo "${RED}IMPORTANT: Make sure you have a backup before proceeding!${NC}"
echo ""

read -p "Proceed with migration? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Migration cancelled"
    exit 1
fi

# Start migration log
LOG_FILE="System/.migration-log"
mkdir -p System
echo "$(date '+%Y-%m-%d %H:%M:%S') | v1-to-v2 | Started" >> "$LOG_FILE"

echo ""
echo "🔄 Migrating..."
echo ""

# Step 1: Rename folder
if [ -d "03-Tasks" ]; then
    echo "  Renaming 03-Tasks/ → 03-Backlog/..."
    mv 03-Tasks 03-Backlog
    echo "$(date '+%Y-%m-%d %H:%M:%S') | v1-to-v2 | Renamed 03-Tasks/ → 03-Backlog/" >> "$LOG_FILE"
    echo "  ${GREEN}✓${NC} Folder renamed"
else
    echo "  ${YELLOW}⊘${NC} 03-Tasks/ not found (skipped)"
fi

# Step 2: Update markdown file references
echo "  Updating markdown file references..."
MD_UPDATED=0
find . -type f -name "*.md" -not -path "./.git/*" | while read -r file; do
    if grep -q "03-Tasks" "$file"; then
        sed -i '' 's/03-Tasks/03-Backlog/g' "$file"
        MD_UPDATED=$((MD_UPDATED + 1))
    fi
done
# Note: Counter won't work in subshell, so we recount
MD_UPDATED=$(find . -type f -name "*.md" -not -path "./.git/*" -exec grep -l "03-Backlog" {} \; 2>/dev/null | wc -l | tr -d ' ')
echo "$(date '+%Y-%m-%d %H:%M:%S') | v1-to-v2 | Updated $MD_UPDATED markdown files" >> "$LOG_FILE"
echo "  ${GREEN}✓${NC} Updated $MD_UPDATED markdown files"

# Step 3: Update YAML file references
echo "  Updating YAML file references..."
YAML_UPDATED=0
find . -type f -name "*.yaml" -not -path "./.git/*" | while read -r file; do
    if grep -q "03-Tasks" "$file"; then
        sed -i '' 's/03-Tasks/03-Backlog/g' "$file"
        YAML_UPDATED=$((YAML_UPDATED + 1))
    fi
done
# Recount after update
YAML_UPDATED=$(find . -type f -name "*.yaml" -not -path "./.git/*" -exec grep -l "03-Backlog" {} \; 2>/dev/null | wc -l | tr -d ' ')
echo "$(date '+%Y-%m-%d %H:%M:%S') | v1-to-v2 | Updated $YAML_UPDATED YAML files" >> "$LOG_FILE"
echo "  ${GREEN}✓${NC} Updated $YAML_UPDATED YAML files"

# Step 4: Update skill files
echo "  Updating skill references..."
find .claude/skills -type f -name "*.md" | while read -r file; do
    if grep -q "03-Tasks" "$file"; then
        sed -i '' 's/03-Tasks/03-Backlog/g' "$file"
    fi
done
echo "$(date '+%Y-%m-%d %H:%M:%S') | v1-to-v2 | Updated skill files" >> "$LOG_FILE"
echo "  ${GREEN}✓${NC} Updated skill files"

# Mark as complete
touch .migration-v2-complete
echo "2.0.0" > .migration-version
echo "$(date '+%Y-%m-%d %H:%M:%S') | v1-to-v2 | Complete" >> "$LOG_FILE"

echo ""
echo "================================================"
echo "${GREEN}✅ Migration complete!${NC}"
echo "================================================"
echo ""
echo "Summary:"
echo "  • Renamed folder: 03-Tasks/ → 03-Backlog/"
echo "  • Updated $MD_UPDATED markdown files"
echo "  • Updated $YAML_UPDATED YAML files"
echo "  • Updated skill files"
echo ""
echo "Next steps:"
echo "  1. Review changes: ${YELLOW}git status && git diff${NC}"
echo "  2. Test key workflows:"
echo "     • Open 03-Backlog/Tasks.md"
echo "     • Run /daily-plan"
echo "     • Check person pages"
echo "  3. If all looks good: ${YELLOW}git add . && git commit -m \"Migrated to v2.0.0\"${NC}"
echo "  4. Update Dex: ${YELLOW}git fetch upstream && git merge upstream/main${NC}"
echo ""
echo "Migration log: $LOG_FILE"
echo ""
echo "${YELLOW}If something went wrong:${NC}"
echo "  Restore from backup: ${RED}rm -rf ~/Documents/dex && cp -r ~/Documents/dex-backup-YYYYMMDD ~/Documents/dex${NC}"
echo ""
