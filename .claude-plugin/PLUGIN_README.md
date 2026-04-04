# Dex Plugin

**Your AI Chief of Staff as a Claude Code Plugin**

This document explains how Dex works as a Claude Code plugin and how to install it.

## What This Plugin Provides

Dex is more than a traditional plugin - it's a complete personal operating system that includes:

### Skills (60+)
- Daily planning and review workflows
- Meeting intelligence and prep
- Task and project management
- Career development tracking
- Quarterly and weekly planning
- System improvement tools
- Content creation assistants

### MCP Servers (9)
- **work** - Task, priority, and goal management
- **calendar** - Calendar integration (macOS Calendar.app)
- **tasks** - Task tracking and completion
- **career** - Career development and evidence capture
- **resume** - Resume building and optimization
- **onboarding** - First-time setup wizard
- **beta** - Beta feature management
- **dex-analytics** - Anonymous usage analytics
- **dex-improvements** - System improvement backlog

### Session Hooks
- Automatic context injection (people, companies)
- Daily intelligence updates (meetings, newsletters, YouTube)
- Session startup automation
- Git safety checks

### Vault Structure
Dex uses the PARA method (Projects, Areas, Resources, Archives):
- `00-Inbox/` - Capture zone
- `01-Quarter_Goals/` - Quarterly planning
- `02-Week_Priorities/` - Weekly focus
- `03-Tasks/` - Task backlog
- `04-Projects/` - Active projects
- `05-Areas/` - Ongoing areas (People, Companies, Career)
- `06-Resources/` - Reference material
- `07-Archives/` - Historical data
- `System/` - Configuration and learnings

## Installation Methods

### Method 1: Direct Plugin Installation (Recommended for Claude Code users)

```bash
# Install from GitHub
claude plugin install https://github.com/davekilleen/dex
```

After installation:
1. Navigate to a directory where you want your vault
2. Run the onboarding: `/setup` (or the skill the plugin provides)
3. Answer the setup questions (name, role, pillars, etc.)
4. The vault structure will be created automatically

### Method 2: Clone and Link (For development or customization)

```bash
# Clone the repository
git clone https://github.com/davekilleen/dex.git
cd dex/dex-core

# Install Python dependencies
pip install -r requirements.txt

# Link as a local plugin
claude plugin add . --scope user
```

### Method 3: Marketplace Installation (Coming Soon)

Once Dex is added to a marketplace:
```bash
claude plugin install dex@marketplace-name
```

## Post-Installation Setup

### 1. Python Requirements

Dex MCP servers require Python 3.10+:

```bash
# Check Python version
python3 --version

# Install dependencies
pip install anthropic-mcp pyyaml python-dateutil
```

### 2. Vault Initialization

The plugin needs to know where your vault is located. This is configured during onboarding via the MCP server, which will:
- Create the folder structure
- Generate configuration files
- Set up your user profile
- Configure MCP server paths

### 3. Optional Integrations

For full functionality, you can integrate:
- **Granola** - Meeting recording and transcription
- **Gmail API** - Newsletter intelligence
- **ScreenPipe** - Ambient commitment detection (beta)
- **Calendar.app** (macOS) - Calendar integration

## Plugin Architecture

### How MCP Servers Work

The plugin's MCP servers use the `VAULT_PATH` environment variable to find your vault:

```json
{
  "mcpServers": {
    "work": {
      "command": "python",
      "args": ["-m", "core.mcp.work_server"],
      "env": {
        "VAULT_PATH": "/path/to/your/vault"
      }
    }
  }
}
```

During onboarding, Dex automatically configures this path.

### How Skills Work

Skills are invoked with `/skill-name`:
- `/daily-plan` - Morning planning ritual
- `/daily-review` - End-of-day review
- `/week-plan` - Weekly priority setting
- `/meeting-prep` - Prepare for upcoming meetings
- `/project-health` - Check project status
- `/dex-level-up` - Discover unused features

Full list: Run `/dex-level-up` or check `.claude/skills/[[README]].md`

### How Hooks Work

Session hooks run automatically:
- **Startup** - Load context, check for updates
- **People/Company Context** - Inject context when files reference people
- **Daily Intelligence** - Process YouTube/newsletter/meeting intel

## Differences from Traditional Plugins

Most Claude Code plugins provide agents, commands, or skills that augment your workflow.

**Dex is different:**
- It creates a complete vault structure (folders, files, configuration)
- It manages persistent state (tasks, people, projects, goals)
- It has a learning system that improves over time
- It requires onboarding to tailor the system to your role

Think of Dex as **"installing an operating system"** rather than **"adding a feature"**.

## Customization

After installation, you can customize Dex by:

1. **Adding custom skills** - Use `/create-skill` to build your own workflows
2. **Editing CLAUDE.md** - Add personal instructions in the USER_EXTENSIONS block
3. **Configuring pillars** - Edit `System/pillars.yaml` to match your priorities
4. **Adjusting settings** - Modify `System/user-profile.yaml` for preferences

## Updating

The plugin includes a self-update system:

```bash
# Check for updates
/dex-whats-new

# Update Dex
/dex-update

# Rollback if needed
/dex-rollback
```

## Troubleshooting

### MCP Servers Not Loading

If MCP servers don't start:
1. Check Python version: `python3 --version` (need 3.10+)
2. Install dependencies: `pip install anthropic-mcp pyyaml python-dateutil`
3. Verify vault path in `.claude/settings.json`

### Skills Not Appearing

If skills aren't available:
1. Check plugin is enabled: `claude plugin list`
2. Enable if disabled: `claude plugin enable dex`
3. Restart Claude Code

### Onboarding Won't Complete

If onboarding gets stuck:
1. Check `System/.onboarding/state.json` for errors
2. Delete the state file to restart: `rm System/.onboarding/state.json`
3. Run `/setup` again

## Support

- **Documentation**: See `06-Resources/Dex_System/Dex_System_Guide.md` in your vault
- **Issues**: Report on [GitHub Issues](https://github.com/davekilleen/dex/issues)
- **Discussions**: Join [GitHub Discussions](https://github.com/davekilleen/dex/discussions)

## License

PolyForm Noncommercial 1.0.0 - see `LICENSE` and `../COMMERCIAL_LICENSE.md` for details.
