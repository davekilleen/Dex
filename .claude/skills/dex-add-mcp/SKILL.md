---
name: dex-add-mcp
description: "Add a known MCP server to config using Dex-safe user scope. Use when the user has server details in hand and says 'add this MCP', 'register this server'. Not for discovering/installing from a marketplace; use `integrate-mcp`. Not for building one; use `create-mcp`."
---

## Purpose

Add a new MCP server the safe way: **user scope by default** so your custom MCP survives Dex updates.

## When to Use

- You want to add an MCP server without touching `.mcp.json`
- You want it to work across all projects (user scope)
- You are not sure which scope to pick

## Default Behavior (Recommended)

Use **user scope** unless you explicitly want to share with a team.

### User scope (recommended)

```
claude mcp add --scope user <server-name> -- <command> <args>
```

**Why:** Survives Dex updates and applies across all projects.

### Project scope (team-shared)

```
claude mcp add --scope project <server-name> -- <command> <args>
```

**Why:** Stored in `.mcp.json` and shared with everyone on this repo.

## Examples

### Add a local stdio MCP (user scope)

```
claude mcp add --scope user gmail --transport stdio -- node .scripts/mcp/gmail-mcp.js
```

### Add a remote HTTP MCP (user scope)

```
claude mcp add --scope user notion --transport http https://mcp.notion.com/mcp
```

### Add a project-shared MCP (explicit)

```
claude mcp add --scope project github --transport http https://api.githubcopilot.com/mcp/
```

## Guardrails

- If you are not sure, **use user scope**.
- Only use project scope if **everyone** should get the server.
- Do not add personal MCPs to `.mcp.json`.

---

## Track Usage (Silent)

Update `System/usage_log.md` to mark MCP addition as used.

**Analytics (Silent):**

Call `track_event` with event_name `mcp_added` and properties:
- (no properties — do NOT include server names)

This only fires if the user has opted into analytics. No action needed if it returns "analytics_disabled".
