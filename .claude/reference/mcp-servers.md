# MCP Servers Reference

Dex includes several MCP servers in `core/mcp/`:

## Task MCP (`task_server.py`)

- Task deduplication and similarity detection
- Priority management (P0/P1/P2/P3 with configurable limits)
- Strategic pillar alignment
- Ambiguity detection for vague tasks
- Related task syncing to person/company pages

The server loads configuration from `System/pillars.yaml`.

## Calendar MCP (`calendar_server.py`)

- Apple Calendar integration via AppleScript
- Works with any calendar synced to Calendar.app (including Google accounts)
- Tools: `calendar_list_calendars`, `calendar_get_today`, `calendar_get_events_with_attendees`
- Used by `/daily-plan` for meeting context

## Granola MCP (`granola_server.py`)

- Reads meeting notes from Granola's local cache
- No API required - works directly with local data
- Tools: `granola_get_recent_meetings`, `granola_search_meetings`, `granola_get_meeting_details`
- Used by `/daily-plan` for meeting transcript context

## Pendo MCP (remote)

Pendo's hosted MCP server - brings product analytics into AI workflows.

- OAuth authentication via browser (no API key needed)
- Regional endpoints: US, US1, EU, Japan, Australia

**Available tools:**
- **Account/Visitor Query** - Retrieve account and visitor metadata with filters
- **Activity Query** - SQL-like queries on event summaries
- **Lookup Countable** - Get IDs for Pages, Features, Track Events
- **Segment List** - View visitor and account segments
- **List Applications** - Return tracked apps

**Use cases:**
- Pull account usage data before customer calls
- Check feature adoption during roadmap discussions
- Investigate churn signals or adoption patterns
- Enrich meeting prep with real product data

**Setup:** Add to `.mcp.json` with your regional URL:
```json
{
  "pendo": {
    "url": "https://app.eu.pendo.io/mcp/v0/shttp"
  }
}
```
Then authenticate via Cursor Settings > Tools & MCP > Connect.

**Regions:** 
- `app.pendo.io` (US)
- `us1.app.pendo.io` (US1)
- `app.eu.pendo.io` (EU)
- `app.jpn.pendo.io` (Japan)
- `app.au.pendo.io` (Australia)

**Note:** Requires Pendo MCP Server enabled in subscription settings (Settings > Subscription settings > AI features).

---

## Integration Status

Track configured integrations in `System/integration_status.yaml`. The `/daily-plan` command checks this on first run and guides you through setup.

### Supported Integrations

| Integration | MCP Server | Status |
|-------------|------------|--------|
| Apple Calendar | `calendar_server.py` | Built-in |
| Granola | `granola_server.py` | Built-in |
| Tasks | `task_server.py` | Built-in (always enabled) |
| Pendo | Remote (hosted) | OAuth auth required |

### Setting Up Integrations

Run `/daily-plan --setup` to configure integrations interactively, or add MCP servers manually to Claude Desktop config at `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "dex-calendar": {
      "command": "python",
      "args": ["/path/to/dex/core/mcp/calendar_server.py"],
      "env": { "VAULT_PATH": "/path/to/dex" }
    },
    "dex-granola": {
      "command": "python",
      "args": ["/path/to/dex/core/mcp/granola_server.py"],
      "env": { "VAULT_PATH": "/path/to/dex" }
    }
  }
}
```

### Creating Custom Integrations

Run `/create-mcp` to create a new MCP server integration through a guided wizard. No coding required — describe what you want to connect, and the wizard will:
1. Design the integration with you
2. Generate the MCP server code
3. Update CLAUDE.md and System Guide
4. Provide setup instructions
