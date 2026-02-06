# Pi Integration Beta

Welcome to the Pi Integration beta! Pi is a minimal, self-extending coding agent created by Mario Zechner that's generating serious excitement in the AI community.

## What is Pi?

Pi is different from other coding agents:

- **Minimal core** — Under 1,000 tokens of system prompt (vs thousands in other tools)
- **Self-extending** — Instead of waiting for features, you describe what you want and Pi builds it
- **Transparent** — You can see exactly what Pi is doing, no "black box" magic
- **Powers OpenClaw** — The viral AI assistant with 145k+ GitHub stars is built on Pi

Tobi Lutke (Shopify CEO) called it the *"Dawn of the age of malleable software."*

## Quick Start

### 1. Verify Installation

Pi was installed during beta activation. Verify it's working:

```bash
pi --version
```

You should see version 0.45+ or later.

### 2. Start Pi

In a terminal:

```bash
pi
```

Pi will start and be ready to build tools for you.

### 3. Build Your First Extension

Ask Pi to create something:

```
Build me a tool that lists all my overdue tasks from the Dex task system
```

Pi will:
1. Understand what you need
2. Write the code
3. Save it to `.pi/extensions/`
4. The tool is now available

## How Pi Connects to Dex

Pi has **native MCP (Model Context Protocol) support** — it can directly access your Dex MCP servers without any bridge code.

This means tools Pi builds can:
- Access your task list
- Read your calendar
- Look up people pages
- Query meeting notes

The MCP servers are configured automatically in your Pi settings.

## What to Build with Pi

Pi excels at **analytical and cross-cutting tools**:

- Pattern detection across meetings
- Relationship health tracking
- Custom alerts and notifications
- Ad-hoc dashboards
- Role-specific workflows

For **deterministic operations** (task CRUD, calendar writes), continue using Dex directly — reliability matters more than flexibility there.

## Pi vs Claude Code

| | Claude Code (Dex) | Pi |
|---|---|---|
| **Add features** | Edit skill files | Describe what you want |
| **Iteration** | Find file → edit → test | "Also do X" → done |
| **Best for** | Structured workflows | Custom tools |
| **Reliability** | High (deterministic) | Good (probabilistic) |

**Use together**: Claude Code for reliable operations, Pi for building new analytical tools.

## Configuration

### MCP Servers

Pi connects directly to these Dex MCP servers:

- **work-mcp** — For task/goal/priority operations
- **calendar-mcp** — For calendar access
- **career-mcp** — For career development tracking
- **commitment-mcp** — For commitment detection
- And all other Dex MCP servers

These are configured automatically during beta activation.

### AGENTS.md

Pi's context about your Dex vault is in `.pi/AGENTS.md`. Edit this to give Pi more context about your specific setup.

## Troubleshooting

### Pi command not found

Reinstall Pi:

```bash
npm install -g @mariozechner/pi-coding-agent
```

### Pi can't access Dex data

Check that MCP servers are running:

```bash
pi --mcp-status
```

If servers aren't connecting, verify your `.pi/config.json` has the Dex MCP servers configured.

### Extension not working

Pi extensions are TypeScript. Check for errors:

```bash
cat .pi/extensions/your-extension.ts
```

Ask Pi to fix any issues: "The extension has an error, can you fix it?"

## Feedback

Your feedback shapes this integration. Message Dave directly on WhatsApp with:

- What you tried to build
- What happened
- What you expected
- How it felt (even "confusing" is useful)

## Version History

### 0.1.0 (Current)
- Initial beta release
- MCP bridge to Dex task and calendar systems
- Auto-installation during activation

---

*Thanks for being a Pi beta tester! Built on Mario Zechner's Pi coding agent.*
