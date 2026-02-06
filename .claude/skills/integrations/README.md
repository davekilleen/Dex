# Productivity Integration Skills

Connect your favorite tools to Dex for richer context in meetings, person pages, and daily planning.

## Available Integrations

| Skill | Tool | Auth Complexity | Time |
|-------|------|-----------------|------|
| `/integrate-notion` | Notion | ⭐ Easy (token) | 2 min |
| `/integrate-slack` | Slack | ⭐⭐ Medium | 3 min |
| `/integrate-google` | Google Workspace | ⭐⭐⭐ Complex (OAuth) | 5 min |

## What You Get

### Notion Integration
- Search your Notion workspace from Dex
- Meeting prep pulls relevant Notion docs
- Link Notion pages to person and project pages
- "Find the Q1 planning doc" → instant results

### Slack Integration  
- "What did Sarah say about the Q1 budget?" → searches Slack
- Meeting prep includes recent Slack context with attendees
- Person pages show Slack interaction history
- Commitment detection finds promises made in threads

### Google Workspace Integration
- "What emails am I behind on with VP Sales?" → searches Gmail
- Calendar event context with attendee details
- Person pages show email communication history
- Contact info lookup

## Setup Order Recommendation

1. **Notion** — Simplest setup, immediate value
2. **Slack** — High value for meeting prep
3. **Google** — Most complex, save for last

## Configuration

Integration settings are stored in:
- `System/integrations/config.yaml` — Master config
- `System/integrations/{service}.yaml` — Service-specific settings

Credentials are stored securely in Claude Desktop config:
- `~/Library/Application Support/Claude/claude_desktop_config.json`

## Existing User Updates

When you run `/dex-update`, Dex automatically:
1. Detects if you have existing MCP configs for these tools
2. Compares them to Dex recommended packages
3. Offers to upgrade or keep your existing setup

## Related

- `.claude/flows/onboarding.md` — Integration setup during onboarding (Step 9)
- `core/integrations/` — Python modules for detection and setup
- `06-Resources/Dex_System/Dex_Technical_Guide.md` — Technical details
