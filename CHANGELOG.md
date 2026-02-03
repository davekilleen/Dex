# Changelog

All notable changes to Dex will be documented in this file.

**For users:** Each entry explains what was frustrating before, what's different now, and why you'll care.

---

## [Unreleased]

### Your Customizations Are Now Protected

**Before:** Every time you updated Dex, you risked losing personal tweaks. If you'd added custom instructions to CLAUDE.md or connected your own integrations, updates could overwrite them. You had to manually back things up and restore them after each update.

**Now:** Dex recognizes and preserves your customizations automatically:
- Personal instructions in CLAUDE.md (between the `USER_EXTENSIONS` markers) stay untouched
- Custom integrations named `user-*` or `custom-*` are protected
- When your changes overlap with an update, you get a simple menu instead of a confusing merge screen

**Result:** Customize freely, update confidently. Your personal setup survives every update.

---

### Prompt Improvement Works Everywhere

**Before:** The `/prompt-improver` skill required an Anthropic API key configured separately. In restricted environments or when the API was unavailable, it just failed.

**Now:** It automatically uses whatever AI is available — no special configuration needed.

**Result:** Prompt improvement just works, regardless of your setup.

---

### Background Meeting Sync (Granola Users)

**Before:** To get your Granola meetings into Dex, you had to manually run `/process-meetings`. Each time, you'd wait for the MCP server to start, watch it process, then continue your work. Easy to forget, tedious when you remembered.

**Now:** A background job syncs your meetings from Granola every 30 minutes automatically. One-time setup, then it just runs.

**To enable:** Run `.scripts/meeting-intel/install-automation.sh`

**Result:** Your meeting notes are always current. When you run `/daily-plan` or look up a person, their recent meetings are already there — no manual step needed.

---

### Easier First-Time Setup

**Before:** New users hit cryptic error messages during setup. "Python version mismatch" or "pip install failed" with no guidance on what to do next. Many got stuck and needed help.

**Now:**
- Clear error messages explain exactly what's wrong and how to fix it
- Python 3.10+ requirement is checked upfront with installation instructions
- MCP server configuration is streamlined with fewer manual steps

**Result:** New users get up and running faster with less frustration.

---

### New Skill: `/dex-add-mcp`

**Before:** Adding a new integration (Gmail, Notion, etc.) meant editing config files manually and hoping you got the format right. And if you named it wrong, the next Dex update might overwrite it.

**Now:** `/dex-add-mcp` handles the technical setup correctly and names your integration with a `user-` prefix so it's automatically protected during updates.

**Result:** Connect new tools without touching config files, and know they'll survive future updates.

---

## [1.0.0] - 2026-01-25

### Initial Release

Dex is your AI-powered personal knowledge system. It helps you organize your professional life — meetings, projects, people, ideas, and tasks — with an AI assistant that learns how you work.

**Core features:**
- **Daily planning** (`/daily-plan`) — Start each day with clear priorities
- **Meeting capture** — Extract action items, update person pages automatically
- **Task management** — Track what matters with smart prioritization
- **Person pages** — Remember context about everyone you work with
- **Project tracking** — Keep initiatives moving forward
- **Weekly and quarterly reviews** — Reflect and improve systematically

**Requires:** Cursor IDE with Claude, Python 3.10+, Node.js
