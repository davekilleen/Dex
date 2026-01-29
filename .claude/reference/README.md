# Reference

**Purpose:** Technical documentation for developers and advanced users working on Dex internals.

**⚠️ For Technical Users** - This folder contains architecture docs, implementation details, and integration guides. If you're just using Dex, you don't need to read these files.

---

## What Is Reference Documentation?

**Reference docs** are technical guides that explain *how* and *why* Dex works under the hood. These are for:
- Claude when implementing new features
- Developers extending Dex
- Advanced users debugging issues
- Contributors understanding the architecture

**Most users don't need these files** - the system works without understanding internals.

### Reference vs User Documentation

| Type | Audience | Content | Example |
|------|----------|---------|---------|
| **Reference** | Developers, Claude, advanced users | Technical details, architecture, implementation | "MCP server protocol", "Hook execution order" |
| **User docs** | End users | How to use features | "Run /daily-plan to start your day" |
| **Skills** | End users | Commands and workflows | `/meeting-prep` instructions |

### When Claude Uses Reference Docs

Claude reads reference docs when:
- Implementing new features that integrate with existing systems
- Debugging issues (understanding how something should work)
- Extending functionality (knowing what patterns to follow)
- Setting up integrations (MCP servers, external APIs)

**Example scenario:**
- User: "Add Slack integration to Dex"
- Claude reads: `mcp-servers.md` to understand MCP patterns
- Claude reads: `System/user-profile.yaml` to understand configuration
- Claude implements: New Slack MCP server following established patterns

---

## What Goes Here

Technical reference docs that:
- Explain implementation details
- Document system architecture
- Describe integration patterns
- Define technical specifications

## When to Use

Create reference docs for:
- **Implementation details** - How features work under the hood
- **Integration guides** - Setting up external connections
- **API documentation** - Tool interfaces and parameters
- **Architecture decisions** - Why things work the way they do

## Audience

Reference docs are for:
- Claude when implementing features
- Developers extending Dex
- Advanced users customizing their setup
- Contributors debugging issues

## Structure

Reference docs should:
- Be technically precise
- Include code examples
- Link to related files
- Explain trade-offs and decisions

## Examples

- **mcp-servers.md** - MCP setup, troubleshooting, and integration patterns
- **meeting-intel.md** - Meeting processing pipeline details
- **demo-mode.md** - Demo mode implementation and usage

## Related

- **MCP** (`.claude/mcp/`) - MCP server configurations
- **Core** (`core/`) - Implementation code
