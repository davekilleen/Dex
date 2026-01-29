#!/bin/bash
# Fix duplicate frontmatter in skills

set -e

SKILLS_DIR="/Users/dave/Dex/Dex/.claude/skills"

fix_skill() {
  local skill_name=$1
  local skill_file="$SKILLS_DIR/$skill_name/SKILL.md"
  
  if [ ! -f "$skill_file" ]; then
    echo "⚠️  Skill not found: $skill_name"
    return
  fi
  
  # Read the file content
  local content=$(cat "$skill_file")
  
  # Check if there are multiple frontmatter blocks (look for 3 or more --- lines)
  local frontmatter_count=$(echo "$content" | grep -c "^---$" || true)
  
  if [ "$frontmatter_count" -ge 4 ]; then
    echo "✓ Fixing duplicate frontmatter in: $skill_name"
    
    # Extract first frontmatter block (lines 1-5: ---, name, description, disable-model, ---)
    local first_frontmatter=$(head -n 5 "$skill_file")
    
    # Extract content after second frontmatter block (skip to line after 4th ---)
    # Count lines to find where 4th --- is
    local fourth_dash_line=$(awk '/^---$/{n++; if(n==4){print NR; exit}}' "$skill_file")
    
    if [ -n "$fourth_dash_line" ]; then
      # Create temp file with correct structure
      echo "$first_frontmatter" > "${skill_file}.tmp"
      tail -n +$((fourth_dash_line + 2)) "$skill_file" >> "${skill_file}.tmp"
      mv "${skill_file}.tmp" "$skill_file"
      echo "  ✓ Fixed"
    fi
  fi
}

# Fix skills that had existing frontmatter
fix_skill "setup"
fix_skill "process-meetings"

echo ""
echo "✅ Frontmatter fixes complete"
