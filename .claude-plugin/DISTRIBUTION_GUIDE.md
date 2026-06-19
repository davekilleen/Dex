# Dex Plugin Distribution Guide

This guide explains how to distribute Dex as a Claude Code plugin.

## Current Status

✅ **Plugin manifest created** - `.claude-plugin/plugin.json`
✅ **Plugin [[README]] created** - `.claude-plugin/PLUGIN_README.md`
✅ **Core components organized** - Skills, MCP servers, hooks all in `.claude/`
✅ **Python MCP servers functional** - `core/mcp/` directory with all servers
✅ **Documentation complete** - Comprehensive guides in `06-Resources/Dex_System/`

## Distribution Options

### Option 1: GitHub Direct Installation (Easiest - Recommended First)

**How it works:**
Users install directly from your GitHub repository:

```bash
claude plugin install https://github.com/davekilleen/dex
```

**What you need to do:**

1. **Create a GitHub repository**
   ```bash
   cd ~/dex-core
   git remote add origin https://github.com/davekilleen/dex.git
   git push -u origin main
   ```

2. **Test the installation**
   ```bash
   # In a test directory
   claude plugin install https://github.com/davekilleen/dex
   ```

3. **Document the installation** - Users need:
   - Python 3.10+
   - `pip install anthropic-mcp pyyaml python-dateutil`
   - Run `/setup` after installation

**Pros:**
- Simple to set up
- You control updates
- Users get latest version directly
- No marketplace approval needed

**Cons:**
- Users need to know the GitHub URL
- No centralized discovery
- Manual URL sharing

### Option 2: Submit to Official Claude Code Marketplace

**How it works:**
Anthropic maintains an official marketplace at `claude-plugins-official`. You submit a PR to add Dex.

**What you need to do:**

1. **Prepare your plugin**
   - Ensure all files are ready (done ✅)
   - Create comprehensive tests
   - Validate plugin manifest: `claude plugin validate dex-core/`

2. **Fork and clone the official marketplace**
   ```bash
   git clone https://github.com/anthropics/claude-plugins-public.git
   cd claude-plugins-public
   ```

3. **Add your plugin**
   ```bash
   # Copy your plugin to the marketplace
   cp -r /path/to/dex-core ./plugins/dex

   # Or add as external plugin (just metadata)
   # Edit marketplace.json to add your entry
   ```

4. **Submit PR** to `https://github.com/anthropics/claude-plugins-public`

5. **Wait for review** - Anthropic team reviews and approves

**Pros:**
- Official distribution
- Discoverable by all Claude Code users
- Trusted source
- Automatic updates

**Cons:**
- Requires approval from Anthropic
- May have submission guidelines
- Slower update cycle

### Option 3: Create Your Own Marketplace (Best for Distribution)

**How it works:**
You create a marketplace that users can add to Claude Code, similar to `every-marketplace`.

**What you need to do:**

1. **Create a marketplace repository**
   ```bash
   mkdir dex-marketplace
   cd dex-marketplace
   mkdir -p .claude-plugin plugins/dex
   ```

2. **Create marketplace manifest** - `.claude-plugin/marketplace.json`:
   ```json
   {
     "name": "dex-marketplace",
     "description": "Personal knowledge management and AI Chief of Staff tools",
     "owner": {
       "name": "Dave Killeen",
       "email": "dave@davekilleen.com"
     },
     "plugins": [
       {
         "name": "dex",
         "description": "Your AI Chief of Staff. Personal operating system with strategic work management, meeting intelligence, relationship tracking, and daily planning.",
         "source": "./plugins/dex",
         "category": "productivity",
         "version": "1.0.0",
         "author": {
           "name": "Dave Killeen",
           "email": "dave@davekilleen.com"
         },
         "homepage": "https://github.com/davekilleen/dex"
       }
     ]
   }
   ```

3. **Copy Dex into the marketplace**
   ```bash
   cp -r ~/dex-core ./plugins/dex
   ```

4. **Publish to GitHub**
   ```bash
   git init
   git add .
   git commit -m "Initial marketplace setup"
   git remote add origin https://github.com/davekilleen/dex-marketplace.git
   git push -u origin main
   ```

5. **Users install your marketplace**
   ```bash
   # Add the marketplace
   claude plugin marketplace add https://github.com/davekilleen/dex-marketplace

   # Install Dex from your marketplace
   claude plugin install dex@dex-marketplace
   ```

**Pros:**
- You control everything
- Can add other plugins later
- Fast updates (no approval needed)
- Professional distribution
- Build a brand around your tools

**Cons:**
- Requires maintaining a marketplace
- Users need to add marketplace first
- Extra setup step for users

### Option 4: Hybrid Approach (Recommended Strategy)

**Best of all worlds:**

1. **Start with GitHub direct** (Option 1)
   - Quick to test
   - Early adopters can install immediately
   - Get feedback fast

2. **Create your own marketplace** (Option 3)
   - Professional distribution
   - Easy for users: one command to add marketplace
   - You control updates
   - Can add complementary plugins later (Dex Premium features, integrations, etc.)

3. **Submit to official marketplace** (Option 2) - Later
   - Once proven stable
   - Wider discovery
   - Trusted distribution

## Testing Your Plugin

Before distributing, test thoroughly:

### 1. Validate the Plugin Manifest

```bash
cd ~/dex-core
claude plugin validate .
```

This checks:
- `plugin.json` is valid JSON
- Required fields are present
- MCP server configurations are correct
- Skills follow conventions

### 2. Test Local Installation

```bash
# Link locally for testing
claude plugin add ~/dex-core --scope user

# Check it's installed
claude plugin list

# Try a skill
cd /tmp
mkdir test-vault
cd test-vault
# Run: /setup or /daily-plan
```

### 3. Test Clean Installation

```bash
# Remove local installation
claude plugin remove dex

# Install from GitHub (after you've pushed)
claude plugin install https://github.com/davekilleen/dex

# Run onboarding
# Navigate to test directory
# Run: /setup
```

### 4. Test MCP Servers

After installation, verify MCP servers start:

```bash
# Check MCP server logs
# Look in ~/.claude/logs/mcp-servers/
tail -f ~/.claude/logs/mcp-servers/work.log
```

## Publishing Checklist

Before publishing, ensure:

- [ ] `plugin.json` has correct GitHub repository URL
- [ ] LICENSE file is present (PolyForm Noncommercial 1.0.0 - ✅)
- [ ] CHANGELOG.md is up to date (✅)
- [ ] [[README]].md explains installation clearly
- [ ] Python requirements documented
- [ ] `.gitignore` excludes personal data (vault contents, `.env`, etc.)
- [ ] All skills have proper YAML frontmatter
- [ ] MCP servers are documented in `.claude/mcp/[[README]].md` (✅)
- [ ] Test installation on a clean machine/directory
- [ ] Verify onboarding works from scratch
- [ ] Document any prerequisites (Python, Granola, etc.)

## .gitignore for Plugin Distribution

**CRITICAL**: Don't include personal vault data!

Create/update `.gitignore` in `dex-core/`:

```gitignore
# Personal vault data (DO NOT INCLUDE IN PLUGIN)
00-Inbox/
01-Quarter_Goals/
02-Week_Priorities/
03-Tasks/
04-Projects/
05-Areas/
07-Archives/
System/Session_Learnings/
System/Session_Memory/
System/.onboarding/state.json
System/user-profile.yaml
System/pillars.yaml

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
env/

# Environment
.env
.secrets

# IDE
.vscode/
.cursor/
.idea/

# OS
.DS_Store
Thumbs.db

# MCP logs
*.log

# Keep template/example files
!System/user-profile.example.yaml
!System/pillars.example.yaml
```

## Example Installation Flow for Users

Document this clearly in your main [[README]]:

```bash
# 1. Install the plugin
claude plugin install https://github.com/davekilleen/dex

# 2. Install Python dependencies
pip install anthropic-mcp pyyaml python-dateutil

# 3. Create or navigate to your vault directory
mkdir ~/my-dex-vault
cd ~/my-dex-vault

# 4. Run onboarding
# In Claude Code, type: /setup
# Follow the prompts (name, role, pillars, etc.)

# 5. Start using Dex!
# Type: /daily-plan
```

## Marketing Your Plugin

Once distributed, promote it:

1. **Vibe PM Podcast Episode** - You already have Episode 8, create a follow-up about the plugin
2. **LinkedIn Post** - "Dex is now available as a Claude Code plugin"
3. **GitHub [[README]]** - Clear "Install" button at the top
4. **Demo Video** - Show installation and first 5 minutes
5. **X/Twitter Thread** - Installation walkthrough
6. **Blog Post Update** - Add "How to Install" section to existing post
7. **Community Sharing** - Claude Code Slack, Discord, Reddit communities

## Monetization Options (Future)

If you want to offer premium features later:

1. **Free Core + Premium Marketplace**
   - Base Dex is free (current features)
   - Premium marketplace with advanced features:
     - Advanced integrations (Salesforce, HubSpot, etc.)
     - Team collaboration features
     - White-label configurations
     - Priority support

2. **Freemium MCP Servers**
   - Free: Basic work management, calendar, tasks
   - Premium: Advanced analytics, AI insights, custom workflows

3. **Consulting/Setup Services**
   - Free: Self-service installation
   - Paid: 1-on-1 onboarding, custom setup, team rollout

## Next Steps

1. **Immediate** (This week):
   - [ ] Update `.gitignore` to exclude personal vault data
   - [ ] Create example configuration files (with placeholders)
   - [ ] Test local plugin installation
   - [ ] Validate with `claude plugin validate`

2. **Short-term** (Next 2 weeks):
   - [ ] Create GitHub repository for Dex
   - [ ] Push dex-core to main branch
   - [ ] Test GitHub-based installation
   - [ ] Update main [[README]] with plugin installation instructions
   - [ ] Record quick installation demo

3. **Medium-term** (Next month):
   - [ ] Create dex-marketplace repository
   - [ ] Add more plugins to marketplace (future: Dex Premium, Dex Analytics, etc.)
   - [ ] Submit to claude-plugins-official (if desired)
   - [ ] Create comprehensive installation guide video
   - [ ] Promote on LinkedIn, X, podcast

## Getting Help

If you have questions about plugin development:
- Official docs: Check Claude Code documentation
- Community: Claude Code Slack/Discord
- Example plugins: Study `compound-engineering` structure
- Anthropic support: For marketplace submission questions

---

**Ready to distribute?** Start with Option 1 (GitHub direct), then expand to Option 3 (your marketplace) for professional distribution.
