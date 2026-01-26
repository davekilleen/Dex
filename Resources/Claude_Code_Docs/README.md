# Claude Code Documentation Cache

This folder contains cached Claude Code documentation for offline reference and version tracking.

## Files

| File | Purpose |
|------|---------|
| `changelog-log.md` | Running log of Claude Code releases by date |
| `changelog-latest.md` | Full current changelog from GitHub |
| `capabilities-overview.md` | Core capabilities documentation |
| `hooks-reference.md` | Hooks documentation |
| `skills-reference.md` | Skills documentation |
| `sub-agents-reference.md` | Sub-agents documentation |

## Scripts

Located in `.scripts/claude-code-intel/`:

- `fetch-changelog.cjs` - Fetches changelog from GitHub (no API key needed)
- `refresh-docs.cjs` - Scrapes full docs (requires FIRECRAWL_API_KEY)

## Usage

```bash
# Check for new Claude Code versions (lightweight, no API key)
node .scripts/claude-code-intel/fetch-changelog.cjs

# Refresh full documentation (requires Firecrawl API key)
node .scripts/claude-code-intel/refresh-docs.cjs
node .scripts/claude-code-intel/refresh-docs.cjs --force  # Ignore 24h freshness check
```

## When to Use

- Run `/whats-new` command to check for updates and get improvement suggestions
- Run `fetch-changelog.cjs` manually if you want just the raw changelog data
- Run `refresh-docs.cjs` when you need detailed documentation offline
