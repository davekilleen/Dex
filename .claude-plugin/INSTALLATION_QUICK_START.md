# Dex Quick Start Installation

**Get up and running with Dex in 5 minutes.**

## Prerequisites

- **Claude Code** installed and configured
- **Python 3.10+** installed (`python3 --version`)
- **Git** installed (for GitHub-based installation)

## Installation

### Option 1: GitHub Direct (Recommended)

```bash
# Install the plugin
claude plugin install https://github.com/davekilleen/dex

# Install Python dependencies
pip install anthropic-mcp pyyaml python-dateutil
```

### Option 2: Local Development

```bash
# Clone the repository
git clone https://github.com/davekilleen/dex.git
cd dex/dex-core

# Install Python dependencies
pip install anthropic-mcp pyyaml python-dateutil

# Link as local plugin
claude plugin add . --scope user
```

## First Run

1. **Open Claude Code**
   ```bash
   cd ~/Documents  # or wherever you want your vault
   mkdir my-dex-vault
   cd my-dex-vault
   claude
   ```

2. **Run Onboarding**

   In Claude Code, type:
   ```
   /setup
   ```

   Or if that skill isn't available yet, ask Claude:
   ```
   I'd like to set up Dex. Can you start the onboarding process?
   ```

3. **Answer Setup Questions**

   The onboarding wizard will ask about:
   - Your name and role
   - Company size and domain
   - Your strategic pillars (what you focus on)
   - Working style preferences
   - Optional integrations

4. **Vault Creation**

   Dex will automatically create your vault structure:
   ```
   my-dex-vault/
   ├── 00-Inbox/           # Capture zone
   ├── 01-Quarter_Goals/   # Quarterly planning
   ├── 02-Week_Priorities/ # Weekly focus
   ├── 03-Tasks/           # Task backlog
   ├── 04-Projects/        # Active projects
   ├── 05-Areas/           # People, Companies, Career
   ├── 06-Resources/       # Reference material
   ├── 07-Archives/        # Historical data
   └── System/             # Configuration
   ```

## Your First Day

### Morning Planning

Type in Claude Code:
```
/daily-plan
```

This will:
- Pull in your calendar for today
- Review your task list
- Show your weekly priorities
- Help you plan your day

### During the Day

Capture meeting notes naturally:
```
I just had a meeting with Sarah Chen about the Q2 roadmap.
Key decisions:
- Moving forward with the new feature set
- Launch target is June 15
- Need design mockups by next week
```

Dex will automatically:
- Create a meeting note
- Extract action items
- Create/update Sarah's person page
- Link to relevant projects

### End of Day

Type:
```
/daily-review
```

This will:
- Review what you accomplished
- Check for uncommitted tasks
- Capture learnings
- Set up tomorrow

## Essential Skills to Learn

### Daily Workflow
- `/daily-plan` - Morning planning ritual (10 min)
- `/daily-review` - End-of-day review (5 min)

### Weekly Workflow
- `/week-plan` - Sunday evening planning (20 min)
- `/week-review` - Friday wrap-up (15 min)

### Meeting Intelligence
- `/meeting-prep` - Prepare before meetings (automatic context)
- `/granola-daily` - Process recorded meetings (if using Granola app)

### Task Management
- Just say: "Add task: [description]" - Dex infers the pillar
- "Mark X as done" - Complete tasks naturally
- `/promote-to-week` - Pull tasks from projects into weekly focus

### Discovery
- `/dex-level-up` - See what features you haven't used yet
- `/dex-whats-new` - Check for system updates
- `/xray` - Understand how Dex works under the hood

## Troubleshooting

### Plugin Not Found

```bash
# Check installed plugins
claude plugin list

# Enable if disabled
claude plugin enable dex
```

### MCP Servers Not Starting

```bash
# Check Python version (need 3.10+)
python3 --version

# Install dependencies again
pip install anthropic-mcp pyyaml python-dateutil

# Check MCP server logs
tail -f ~/.claude/logs/mcp-servers/work.log
```

### Skills Not Appearing

1. Restart Claude Code
2. Check `.claude/settings.json` in your vault
3. Verify plugin is enabled: `claude plugin list`

### Onboarding Won't Complete

If you get stuck during onboarding:

1. Check the state file:
   ```bash
   cat System/.onboarding/state.json
   ```

2. If needed, restart onboarding:
   ```bash
   rm System/.onboarding/state.json
   ```
   Then type `/setup` again.

## Next Steps

### Week 1: Build the Habit

- Run `/daily-plan` every morning
- Capture meetings and tasks as they happen
- Run `/daily-review` every evening

### Week 2: Add Intelligence

- Set up Granola for meeting recording
- Configure Gmail API for newsletter intelligence
- Enable calendar integration (macOS Calendar.app)

### Week 3: Go Deeper

- Set up quarterly goals with `/quarter-plan`
- Explore career tracking with `/career-setup`
- Create custom skills with `/create-skill`

### Week 4: Master the System

- Learn `/xray` to understand the AI context system
- Customize your workflow with personal skills
- Share the workflows that work best with your team

## Getting Help

- **Documentation**: Check `06-Resources/Dex_System/Dex_System_Guide.md` in your vault
- **Feature Discovery**: Type `/dex-level-up` to see unused features
- **System Updates**: Type `/dex-whats-new` for latest improvements
- **Issues**: Report on [GitHub Issues](https://github.com/davekilleen/dex/issues)

## What Makes Dex Different

Most people use AI as a chat interface. You ask questions, get answers, start fresh every time.

**Dex is different:**
- Persistent memory across sessions
- Context that compounds over time
- Proactive intelligence (not just reactive)
- Learns your patterns and preferences
- Automates cognitive overhead

**Two weeks of daily use and you'll wonder how you worked before.**

---

Ready to start? Type `/setup` in Claude Code!
