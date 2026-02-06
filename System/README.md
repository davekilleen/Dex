# System

Configuration and system files for Dex.

## Key Files

- **pillars.yaml** — Your strategic pillars (main focus areas)
- **user-profile.yaml** — User preferences and settings (created during onboarding)
- **user-profile-template.yaml** — Template for user profile structure
- **Dex_Backlog.md** — AI-ranked improvement backlog (ideas from you + AI discoveries)
- **usage_log.md** — Feature adoption tracking (used by `/dex-level-up`)
- **.mcp.json.example** — Example MCP server configuration
- **.last-learning-check** — Timestamp for learning review prompts
- **claude-code-state.json** — Tracks Anthropic changelog checks

## Subfolders

- **Templates/** — Note templates for consistent formatting
- **Session_Learnings/** — Daily learning capture from `/review` sessions
- **Demo/** — Demo mode configuration and sample data

## What to Edit

**You should modify:**
- `pillars.yaml` — Update your strategic focus areas as they evolve
- `user-profile.yaml` — Adjust preferences and settings
- `Dex_Backlog.md` — Mark ideas as implemented, add notes

**Don't modify:**
- Demo/ — Managed by `/dex-demo` command
- usage_log.md — Auto-updated by system
- .last-learning-check — Auto-updated by learning prompt system
- claude-code-state.json — Auto-updated by changelog monitoring

## Key Concepts

### Pillars

Your strategic pillars define your main focus areas. Everything ladders up to pillars:
- Quarterly goals advance pillars
- Weekly priorities support quarterly goals
- Daily work supports weekly priorities
- Tasks are tagged with pillar associations

To update pillars, just ask Dex: "Update my pillars" or edit `pillars.yaml` directly.

### User Profile

Stores preferences like:
- Communication style (formal, casual)
- Directness level
- Career stage
- Working style
- Journaling preferences
- Role-specific settings

These preferences shape how Dex communicates and what features are enabled.

## Onboarding

The `user-profile.yaml` file is created during initial onboarding via the Onboarding MCP server. This stateful onboarding system validates required fields (especially email domain for person routing) and creates the vault structure automatically.

After onboarding, run `/getting-started` for an interactive tour of available features.

## Usage

Most of the time you won't interact with System/ directly — Dex manages it. But when you want to adjust strategic direction or preferences, the key files are here.
