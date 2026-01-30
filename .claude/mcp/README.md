# MCP Configurations

**Purpose:** Model Context Protocol (MCP) server configurations that connect external tools and data sources to Dex.

---

## What Is MCP?

**MCP (Model Context Protocol)** is how Claude connects to your external tools and data. It's like giving Claude the ability to check your calendar, read your meeting transcripts, or create tasks — reliably and consistently.

### Why It Matters

Without MCP, Claude would have to guess how to interact with your systems. With MCP, Claude uses proper connections that work the same way every time.

**Think of it like this:**

**Without MCP:**
- You: "Create a task to follow up with John"
- Claude: "I'll write it to 03-Tasks/Tasks.md... maybe this format? Should I check for duplicates? Where should it go?"
- Result: Inconsistent, might miss important details

**With MCP (using the Work server):**
- You: "Create a task to follow up with John"  
- Claude: Uses the proper `create_task` tool
- Result: Task created with unique ID, synced everywhere, proper format, duplicate detection

**What you get:**
- ✅ Same format every time
- ✅ No duplicates
- ✅ Automatic syncing (task appears in meeting notes, 03-Tasks/Tasks.md, person pages)
- ✅ Reliable behavior

**Learn more:** [Anthropic's MCP Documentation](https://docs.anthropic.com/en/docs/build-with-claude/mcp)

---

## What Goes Here

JSON configuration files that define:
- MCP server connections
- Tool availability and permissions
- Environment variables and settings
- Integration-specific options

## When to Use

Create an MCP config when:
- **External integration** - Connecting to calendar, tasks, CRM, analytics, etc.
- **Specialized tools** - Adding capabilities beyond file operations
- **Live data** - Accessing real-time information from external systems
- **Bidirectional sync** - Reading and writing to external services

## Structure

Each `.json` file in this folder connects one external system (Calendar, Granola meetings, etc.). You don't need to understand the technical details - the `/create-mcp` skill will create these files for you when you want to add a new integration.

## Examples

- **calendar.json** - Apple Calendar integration (events, scheduling)
- **career.json** - Career development (evidence aggregation, ladder parsing, competency analysis)
- **granola.json** - Meeting transcription and processing
- **onboarding.json** - Stateful onboarding with validation (session management, dependency checks, vault creation)
- **resume.json** - Resume builder (stateful resume building, achievement validation, LinkedIn generation)
- **update-checker.json** - GitHub update detection for `/dex-update` (changelog checking, version comparison)
- **work.json** - Task management (create, update, complete tasks)

## Setup Process

Use `/create-mcp` skill to:
1. Generate MCP server code
2. Create configuration file
3. Test integration
4. Document usage

## Related

- **Reference** (`.claude/reference/mcp-servers.md`) - Technical MCP documentation
- **Core MCP** (`core/mcp/`) - MCP server implementations
- **Skills** (`.claude/skills/create-mcp/`) - MCP creation wizard
- **Integrations** (`06-Resources/Dex_System/Integrations/`) - Integration guides
