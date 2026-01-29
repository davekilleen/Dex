# System

Configuration and system files for Dex.

## Key Files

- **pillars.yaml** — Your strategic pillars (main focus areas)
- **user-profile.yaml** — User preferences and settings
- **Dex_Backlog.md** — AI-ranked improvement backlog for Dex itself
- **usage_log.md** — Feature adoption tracking (used by `/dex-level-up`)

## Subfolders

- **Templates/** — Note templates for consistent formatting
- **Agents/** — Internal agent configurations (don't modify directly)
- **Demo/** — Demo mode configuration and sample data
- **Skills/** — Internal skill definitions (don't modify directly)

## What to Edit

**You should modify:**
- `pillars.yaml` — Update your strategic focus areas as they evolve
- `user-profile.yaml` — Adjust preferences and settings
- `Dex_Backlog.md` — Mark ideas as implemented, add notes

**Don't modify:**
- Agents/ — Managed by system commands
- Demo/ — Managed by `/dex-demo` command
- Skills/ — Managed by skill system
- usage_log.md — Auto-updated by system

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

## Usage

Most of the time you won't interact with System/ directly — Dex manages it. But when you want to adjust strategic direction or preferences, the key files are here.
