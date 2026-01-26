# Create MCP Server

## What This Command Does

**In plain English:** A guided wizard that helps you create and integrate an MCP server into Dex. No coding knowledge required - you describe what you want, we build it together.

**When to use it:**
- You want to connect Dex to an external service (calendar, email, CRM, API)
- You have data somewhere that would be useful in Dex
- You want to automate interactions with a tool you use regularly

**How to run it:**
```
/create-mcp                    # Starts the wizard from the beginning
/create-mcp "calendar"         # Jumps ahead with a service hint
```

---

## Why MCP Matters: Probabilistic AI vs Deterministic Tools

### The Problem with AI Alone

AI models like Claude are fundamentally **probabilistic** - they generate responses by predicting the most likely next token based on patterns in their training data. This is powerful for reasoning and language, but dangerous for facts:

| Question | Without MCP | With MCP |
|----------|-------------|----------|
| "What's on my calendar today?" | *"I don't have access to your calendar, but typically..."* | **Queries actual calendar, returns real events** |
| "What's our feature adoption rate?" | *"Based on typical SaaS metrics, around 30-40%..."* | **Queries Pendo: "Feature X has 67% adoption"** |
| "Did Sarah email about the roadmap?" | *"I can't access your email..."* | **Searches Gmail, finds 3 matching threads** |

Without MCP, AI can only:
- Guess based on general knowledge
- Hallucinate plausible-sounding but wrong answers
- Admit it doesn't have access

### What MCP Actually Does

MCP (Model Context Protocol) provides **guardrails and structure** for AI interactions with external systems:

```
┌─────────────────────────────────────────────────────────────┐
│                    YOUR QUESTION                            │
│         "What features are customers using most?"           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    AI REASONING                             │
│  "I need feature usage data. I have a Pendo MCP tool       │
│   called `get_feature_usage`. Let me call it..."           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    MCP TOOL CALL                            │
│  Tool: get_feature_usage                                    │
│  Input: { "days": 30, "limit": 10 }                        │
│  ─────────────────────────────────────────────────────────  │
│  │ GUARDRAILS:                                          │  │
│  │ ✓ Defined input schema - can't send bad data         │  │
│  │ ✓ Authenticated connection - uses real credentials   │  │
│  │ ✓ Structured output - returns consistent format      │  │
│  │ ✓ Deterministic - same query = same results          │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    REAL DATA RESPONSE                       │
│  { "features": [                                            │
│    { "name": "Dashboard", "usage": 89% },                   │
│    { "name": "Reports", "usage": 67% },                     │
│    { "name": "Guides", "usage": 45% }                       │
│  ]}                                                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    AI SYNTHESIS                             │
│  "Your top 3 features by usage are Dashboard (89%),        │
│   Reports (67%), and Guides (45%). Dashboard dominates -   │
│   consider investing more there."                          │
└─────────────────────────────────────────────────────────────┘
```

### The Key Insight

MCP doesn't make AI smarter - it gives AI **reliable ways to get real data**. The AI still does reasoning, synthesis, and explanation. But the facts come from deterministic tool calls, not probabilistic generation.

| Aspect | Probabilistic (AI alone) | Deterministic (MCP) |
|--------|--------------------------|---------------------|
| Data source | Training patterns | Live API calls |
| Accuracy | Plausible but unreliable | Exact (from source) |
| Freshness | Stale (training cutoff) | Real-time |
| Consistency | May vary per query | Same query = same data |
| Guardrails | None | Schema validation, auth, error handling |

---

## Entry Point

### If no arguments provided:

```
🔌 **MCP Server Creation Wizard**

MCP (Model Context Protocol) lets Dex connect to external tools and services. Instead of guessing or saying "I don't have access", AI can query real data and give you accurate answers.

**The difference MCP makes:**
- ❌ Without: "I'd estimate your feature adoption is around 30-40%..."
- ✅ With: "Pendo shows Feature X has 67% adoption, up 12% this month"

**Examples of what you can build:**
- 📅 Calendar → "What meetings do I have tomorrow? Who's attending?"
- 📧 Email → "Find emails from Sarah about the Q1 roadmap"
- 💬 Slack → "What did #product-team discuss today?"
- 📊 Analytics → "Show me feature adoption for our enterprise tier"
- 🔗 Any API → If it has an API, we can probably connect it

**Benefits:**
- Real data, not AI guessing
- Guardrails prevent hallucination
- Live queries, not stale training data
- Structured tools with validation

**This wizard will:**
1. Help you describe what you want to connect
2. Design the integration together
3. Generate the MCP server code
4. Integrate it into Dex
5. Update all documentation so future sessions know how to use it

Ready to get started? **What would you like to connect Dex to?**

(Just describe it in plain English — e.g., "my Google Calendar", "Notion database", "company CRM")
```

### If service hint provided:

Skip education and jump to Phase 1 with the hint as starting context.

---

## Phase 1: Understand the Connection

### Goal: Get clarity on what service and what data

Ask these questions (adapt based on what's already known):

**Question 1: Service identification**
```
What service or tool do you want to connect?

Examples:
- A specific app (Google Calendar, Notion, Salesforce)
- A type of data (my emails, my tasks, my documents)
- An API you have access to

Your answer:
```

**Question 2: Authentication**
```
How do you currently access this service?

1. I log in with username/password
2. I have an API key
3. It uses OAuth (Google, Microsoft login)
4. It's a local file or database
5. Something else

This helps me understand what authentication we'll need.
```

**Question 3: Data of interest**
```
What specific information do you want Dex to access?

Be specific about:
- What types of data (events, messages, records)
- What you'd want to read vs. write
- Any specific fields that matter most

Example: "I want to see my calendar events - title, time, attendees. Just reading, no need to create events."
```

**Question 4: Use cases**
```
How would you actually use this in practice?

Give me 2-3 example questions or commands you'd want to ask:
- "Show me today's meetings"
- "Find emails from [person] about [topic]"
- "What's the status of [account]?"

This shapes what tools we'll build.
```

### After Phase 1, summarize:

```
**Understood. Here's what we're building:**

📦 **Service:** [service name]
🔐 **Auth method:** [auth type]
📊 **Data access:** [read/write + what data]
🎯 **Primary use cases:**
1. [use case 1]
2. [use case 2]
3. [use case 3]

Does this capture what you want? (yes / let me clarify)
```

---

## Phase 2: Design the Tools

### Goal: Define the specific MCP tools to build

Based on use cases, propose tool designs:

```
**Proposed MCP Tools**

Based on your use cases, here's what I suggest building:

| Tool Name | What It Does | Example Usage |
|-----------|--------------|---------------|
| `[tool_1]` | [description] | "[natural language example]" |
| `[tool_2]` | [description] | "[natural language example]" |
| `[tool_3]` | [description] | "[natural language example]" |

**Input parameters for each:**

### `[tool_1]`
- `param_1` (required): [description]
- `param_2` (optional): [description]

### `[tool_2]`
...

**Questions:**
1. Do these tools cover your use cases?
2. Should any tool do more or less?
3. Are there additional scenarios I missed?
```

### Iterate until user confirms design

Keep refining based on feedback. Ask focused questions:
- "Should [tool] also support [capability]?"
- "What happens if [edge case]?"
- "Do you need to filter by [field]?"

### Confirm before implementation:

```
**Final Tool Design**

We're building an MCP server called `[server-name]` with:

| Tool | Purpose | Inputs |
|------|---------|--------|
| [tool] | [purpose] | [inputs summary] |

**Authentication:** [method + what user needs to provide]
**Configuration:** [any env vars or config needed]

Ready to build? (yes / let me adjust)
```

---

## Phase 3: Implementation

### Goal: Generate the MCP server code

**Step 3.1: Create the server file**

Generate Python code following the pattern in `core/mcp/task_server.py`:

```python
#!/usr/bin/env python3
"""
MCP Server for [Service Name]
[Brief description of what this server does]

Tools:
- [tool_1]: [description]
- [tool_2]: [description]
"""

import os
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
import mcp.server.stdio
import mcp.types as types

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration from environment
[RELEVANT_CONFIG_VARS]

# ============================================================================
# SERVICE CLIENT
# ============================================================================

class [ServiceName]Client:
    """Client for interacting with [Service]"""
    
    def __init__(self):
        [initialization code]
    
    [methods for each operation]

# ============================================================================
# MCP SERVER
# ============================================================================

app = Server("[server-name]-mcp")
client = [ServiceName]Client()

@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List all available tools"""
    return [
        types.Tool(
            name="[tool_name]",
            description="[tool description]",
            inputSchema={
                "type": "object",
                "properties": {
                    [property definitions]
                },
                "required": [required fields]
            }
        ),
        # ... more tools
    ]

@app.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool calls"""
    
    if name == "[tool_name]":
        [implementation]
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]
    
    # ... more tool handlers
    
    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]

async def _main():
    """Async main entry point"""
    logger.info("Starting [Service] MCP Server")
    
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="[server-name]-mcp",
                server_version="1.0.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

def main():
    """Sync entry point"""
    import asyncio
    asyncio.run(_main())

if __name__ == "__main__":
    main()
```

Save to: `core/mcp/[service_name]_server.py`

**Step 3.2: Update requirements**

Add any new dependencies to `core/mcp/requirements.txt`

**Step 3.3: Create launcher script (if needed)**

Create `core/mcp/run_[service_name].sh`:

```bash
#!/bin/bash
# Launch [Service] MCP server
cd "$(dirname "$0")"
source venv/bin/activate 2>/dev/null || true
python [service_name]_server.py
```

Make executable: `chmod +x run_[service_name].sh`

### Tell user what was created:

```
**Server Created!** ✅

Files generated:
- `core/mcp/[service_name]_server.py` — The MCP server
- `core/mcp/requirements.txt` — Updated with dependencies

**Before we integrate, you'll need to:**

[Auth-specific instructions based on Phase 1]

Examples:
- For API key: "Add [SERVICE]_API_KEY to your environment or .env file"
- For OAuth: "Run the OAuth setup script: `python core/mcp/setup_[service]_auth.py`"
- For local: "No additional setup needed"

Let me know when you're ready to integrate.
```

---

## Phase 4: Integration

### Goal: Connect the MCP server to Dex

**Step 4.1: Update CLAUDE.md**

Add to the Integration Options section or create new MCP section:

```markdown
### [Service Name] Integration

**Server:** `core/mcp/[service_name]_server.py`
**Purpose:** [what it does]

**Available Tools:**

| Tool | What It Does | Example |
|------|--------------|---------|
| `[tool]` | [description] | "[natural example]" |

**Configuration Required:**
- `[ENV_VAR]`: [description]

**Usage examples:**
- "[natural language request]" → uses `[tool]` tool
- "[another request]" → uses `[another_tool]` tool
```

**Step 4.2: Add MCP Instructions (if not present)**

Check if CLAUDE.md has mcp_instructions section. If not, add:

```markdown
<mcp_instructions>
### [service-name]-mcp

[Description of the server and when to use it]

**Tools:**
- `[tool_name]`: [when to use and what it returns]

</mcp_instructions>
```

**Step 4.3: Update System Guide**

Add to `Resources/Dex_System/Dex_System_Guide.md` under Integration Options:

```markdown
| **[Service]** | [Brief description of capabilities] |
```

And add a new section if significant:

```markdown
### [Service] MCP Server

Server: `core/mcp/[service_name]_server.py`

#### Available Tools

| Tool | Purpose |
|------|---------|
| `[tool]` | [description] |

#### Usage

[How to use in natural language, what to expect]

#### Configuration

| Variable | Description |
|----------|-------------|
| `[ENV_VAR]` | [what it's for] |
```

---

## Phase 5: Verification

### Goal: Ensure everything is properly connected

**Run verification checklist:**

```
**Integration Complete!** 🎉

Let me verify everything is in place:

✅ Server created: `core/mcp/[service_name]_server.py`
✅ Dependencies updated: `core/mcp/requirements.txt`
✅ CLAUDE.md updated with integration docs
✅ System Guide updated

**To start using it:**

1. Install dependencies (if new ones added):
   ```
   cd core/mcp && pip install -r requirements.txt
   ```

2. Add your credentials:
   ```
   export [ENV_VAR]="your-value-here"
   ```
   Or add to your shell config / .env file.

3. Configure Claude Desktop to use the server:
   Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:
   ```json
   {
     "mcpServers": {
       "[server-name]": {
         "command": "python",
         "args": ["[full-path]/core/mcp/[service_name]_server.py"],
         "env": {
           "VAULT_PATH": "[full-path-to-dex]"
         }
       }
     }
   }
   ```

4. Test it! Try asking:
   - "[example natural language query]"

**Want me to help you test the integration?**
```

---

## Example Walkthrough

```
User: /create-mcp

Claude: [Shows education intro]

User: I want to connect my Todoist

Claude: Great choice! Let me understand what you need...

[Phase 1 questions]

User: I want to see my tasks, add new ones, and mark them complete.
      Example: "What's on my Todoist today?" or "Add 'buy groceries' to Todoist"

Claude: **Understood. Here's what we're building:**

📦 **Service:** Todoist
🔐 **Auth method:** API key (Todoist provides this)
📊 **Data access:** Read tasks, create tasks, update task status
🎯 **Primary use cases:**
1. "What's on my Todoist today/this week?"
2. "Add [task] to Todoist"
3. "Mark [task] as done in Todoist"

Does this capture what you want?

User: Yes, but also let me filter by project

Claude: Got it! Adding project filtering...

[Phase 2 - Tool design]

**Proposed MCP Tools**

| Tool Name | What It Does |
|-----------|--------------|
| `list_tasks` | Get tasks with filters (today, date range, project) |
| `create_task` | Add a new task to Todoist |
| `complete_task` | Mark a task as done |
| `list_projects` | See available projects |

[Continues through phases...]
```

---

## Real-World Example: Pendo MCP Server

This example shows a product analytics integration - the kind of connection where MCP's guardrails really matter.

### The Problem Without MCP

```
You: "What's the feature adoption rate for our Dashboard feature?"

AI (without MCP): "Based on typical SaaS benchmarks, dashboard features 
usually see 60-80% adoption among active users. For enterprise products 
like Pendo, I'd estimate around 70%..."
```

That's a **hallucinated guess** - plausible-sounding but potentially wrong. If you make decisions based on this, you're flying blind.

### The Solution With Pendo MCP

```
You: "What's the feature adoption rate for our Dashboard feature?"

AI (with MCP): *calls get_feature_adoption(feature="Dashboard", days=30)*

"Dashboard has 67% adoption over the last 30 days, up from 54% last month.
Enterprise tier is at 82%, while SMB is at 51%. The gap suggests enterprise 
users find more value in the dashboard - worth investigating what they're 
doing differently."
```

Real numbers. From real data. With insight.

### Pendo MCP Tools Design

| Tool | What It Does | Example Query |
|------|--------------|---------------|
| `get_feature_usage` | Feature adoption and usage patterns | "Which features are most used?" |
| `get_visitor_activity` | Individual visitor behavior | "Show me what Acme Corp has been doing" |
| `search_feedback` | Poll responses and NPS data | "What feedback do we have about onboarding?" |
| `get_guide_performance` | Guide views, completions, dismissals | "How is our new tooltip performing?" |
| `get_account_health` | Account-level engagement metrics | "Which accounts are at risk of churning?" |

### Pendo MCP Use Cases

**For Product Managers:**
```
"What features are enterprise customers using that SMB customers aren't?"
→ Queries feature usage segmented by tier
→ Returns ranked list with adoption deltas
→ AI synthesizes: "Enterprise heavily uses Advanced Analytics (78% vs 12%) 
   and Custom Dashboards (65% vs 8%). These are your expansion levers."
```

**For Customer Success:**
```
"Is Acme Corp engaged? They're up for renewal next month."
→ Queries visitor activity for account
→ Returns login frequency, feature usage, guide completion
→ AI synthesizes: "Acme's engagement dropped 40% last month. Only 2 of 15 
   users logged in this week. Their admin hasn't completed the new setup 
   guide. Flag this for immediate outreach."
```

**For Sales:**
```
"What do customers say about our reporting feature?"
→ Searches NPS responses and poll data mentioning "report"
→ Returns verbatim quotes with sentiment
→ AI synthesizes: "Mixed sentiment. Power users love the flexibility (8.2 NPS), 
   but 34% of feedback mentions 'too complex for basic needs'. Consider 
   highlighting the quick reports in demos."
```

### Why This Works

The Pendo MCP doesn't make AI smarter about product analytics. It gives AI:

1. **Real data** - Not benchmarks or guesses, actual numbers from your Pendo instance
2. **Guardrails** - Structured inputs (feature name, date range, segment) prevent garbage-in queries
3. **Consistency** - Same question always queries the same underlying data
4. **Freshness** - Live API calls, not stale training data
5. **Context** - AI can cross-reference multiple tools (feature usage + feedback + account health)

The AI's job becomes synthesis and insight, not data retrieval. That's what it's good at.

---

## Behaviors

### Always Do
- Start with education for new users
- Confirm understanding before building
- Generate complete, working code
- Update ALL documentation (CLAUDE.md, System Guide)
- Provide clear setup instructions
- Offer to help test

### Never Do
- Skip the design phase
- Generate partial/placeholder code
- Forget to update documentation
- Assume authentication works without explaining setup
- Create tools without clear use cases

### If stuck on technical details
- Search for the service's API documentation
- Check if an existing Python library handles auth
- Offer simpler alternatives if complexity is high

---

## Integration Checklist

After completion, verify:

- [ ] Server file created in `core/mcp/`
- [ ] Requirements.txt updated
- [ ] CLAUDE.md has integration documentation
- [ ] System Guide updated with new capabilities
- [ ] Setup instructions are clear and complete
- [ ] Example queries provided for testing
- [ ] User knows how to configure Claude to use the server
