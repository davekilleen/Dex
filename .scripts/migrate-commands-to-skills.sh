#!/bin/bash
# Migrate commands to skills format

set -e

SKILLS_DIR="/Users/dave/Dex/Dex/.claude/skills"
COMMANDS_DIR="/Users/dave/Dex/Dex/.claude/commands"

# Create skills directory structure
mkdir -p "$SKILLS_DIR"

# Function to create a skill from a command
create_skill() {
  local cmd_file=$1
  local skill_name=$2
  local description=$3
  local disable_model=${4:-false}
  
  local skill_dir="$SKILLS_DIR/$skill_name"
  mkdir -p "$skill_dir"
  
  # Read the original command content
  local content=$(cat "$COMMANDS_DIR/$cmd_file")
  
  # Create SKILL.md with proper frontmatter
  cat > "$skill_dir/SKILL.md" <<EOF
---
name: $skill_name
description: $description
disable-model-invocation: $disable_model
---

$content
EOF
  
  echo "✓ Created skill: $skill_name"
}

# Daily workflow
create_skill "daily-plan.md" "daily-plan" "Generate context-aware daily plan with calendar, tasks, and priorities" "false"
create_skill "daily-review.md" "review" "End of day review with learning capture" "false"
create_skill "journal.md" "journal" "Toggle journaling or start a journal entry (morning/evening/weekly)" "false"
create_skill "meeting-prep.md" "meeting-prep" "Prepare for meetings by gathering attendee context and related topics" "false"
create_skill "process-meetings.md" "process-meetings" "Process Granola meetings to extract insights and update person pages" "false"
create_skill "triage.md" "triage" "Organize inbox files and extract tasks with entity awareness" "false"

# Weekly/Quarterly planning
create_skill "week-plan.md" "week-plan" "Set weekly priorities and plan the week ahead" "false"
create_skill "week-review.md" "week-review" "Review week's progress, meetings, and learnings" "false"
create_skill "quarter-plan.md" "quarter-plan" "Set 3-5 strategic goals for the quarter" "false"
create_skill "quarter-review.md" "quarter-review" "Review quarter completion and capture learnings" "false"

# Career development
create_skill "career-setup.md" "career-setup" "Initialize career development system with job description and ladder" "true"
create_skill "career-coach.md" "career-coach" "Personal career coach for reflections and assessments" "false"
create_skill "resume-builder.md" "resume-builder" "Build resume and LinkedIn profile through guided interview" "false"

# Project management
create_skill "project-health.md" "project-health" "Scan active projects for status, blockers, and next steps" "false"
create_skill "product-brief.md" "product-brief" "Extract product ideas through questions and generate PRD" "false"

# Dex system improvements
create_skill "dex-level-up.md" "dex-level-up" "Discover unused Dex features based on usage patterns" "false"
create_skill "dex-backlog.md" "dex-backlog" "AI-powered ranking of Dex improvement ideas" "false"
create_skill "dex-improve.md" "dex-improve" "Workshop improvement ideas into implementation plans" "false"

# System/Utility
create_skill "demo.md" "demo" "Toggle demo mode on/off, reset demo content, or check status" "true"
create_skill "setup.md" "setup" "Set up personal knowledge system through guided conversation" "true"
create_skill "reset.md" "reset" "Re-run onboarding to restructure Dex system" "true"
create_skill "prompt-improver.md" "prompt-improver" "Improve prompts using Anthropic best practices" "false"
create_skill "save-insight.md" "save-insight" "Capture learnings from completed work for future reference" "false"
create_skill "create-mcp.md" "create-mcp" "Wizard to create and integrate MCP servers into Dex" "false"
create_skill "whats-new-claude.md" "whats-new-claude" "Check for Claude Code updates and get improvement suggestions" "false"

echo ""
echo "✅ Migration complete! Created 25 skills in $SKILLS_DIR"
echo ""
echo "Next steps:"
echo "1. Review the generated skills"
echo "2. Delete create-video.md"
echo "3. Keep .claude/commands/ temporarily for verification"
