---
name: getting-started
description: "Interactive post-onboarding tour that adapts to whatever data exists (calendar, Granola, or none). Use right after onboarding, or when the user says 'show me around', 'how do I start'. Also use proactively when the vault is < 7 days old. Not for the initial setup itself; use `setup`."
---

## Purpose

Transform the post-onboarding experience from "blank chat window" to guided value delivery. Adaptive based on what data sources are available (calendar, Granola, or neither).

## When to Run

- Automatically suggested at session start if vault < 7 days old
- User types `/getting-started`
- After onboarding completion (Step 11)
- User says they're not sure what to do next

## Entry Point

### Step 1: Verify Onboarding

Call `check_onboarding_complete()` from onboarding-mcp to verify vault status.

The first-week reveal already ran during onboarding. Do not repeat the first-week statistics or present them as a new discovery, even if an older completion marker suggests analysis was deferred. `/getting-started` is now the deeper tour.

### Step 2: Environment Check

Check what data sources are available:
- Calendar: Try calling calendar MCP (if fails, not available)
- Granola: Call `granola_check_available()` from granola-mcp

Based on results, route to appropriate flow.

---

## Flow A: Has Calendar + Granola

**The Deeper History Flow**

### Historical Data Discovery

```
👋 **Welcome back, [Name]!**

You have already seen this week's calendar snapshot, so I won't repeat it. Let's look at the deeper meeting history you can turn into useful context.

**Calendar:** ✅ Connected
**Granola:** ✅ Connected

I'll check how much Granola history is available before suggesting what to process.
```

Then execute:
1. Analyze Granola data extent using helper function (6 months by default)
2. If more data exists, ask if they want to see full extent
3. Present the historical summary

```
📊 **Your Granola history:**

**Granola data (last 6 months):**
• [N] meetings captured
• Going back [days_back] days (to [oldest_date])
• [M] unique people detected ([I] internal, [E] external)
• [K] external companies identified
```

**If `has_more_data` is True, ask:**

```
💡 **I see there are meetings beyond 6 months.**
   Want me to check how much more history you have?
   This will take a few more seconds.
   
   → Yes - show me the full extent
   → No - 6 months is plenty
```

**If user says "Yes", refetch with `extended=True` and update:**

```
📊 **Updated - Full data extent:**
• [N_total] meetings captured (found [N_new] older meetings)
• Going back [total_days] days (to [oldest_date])
• [M_total] unique people detected
• [K_total] external companies identified

---

Here's what I can create from your Granola history:

**📇 People & Company Pages** (Recommended: All history)
   ✅ Builds context for relationships
   ✅ Low overhead - just reference pages
   ✅ Helps you see interaction history

**📝 Meeting Notes** (Recommended: Last 30 days)
   ✅ Searchable record of discussions
   ⚠️  Medium overhead - lots of reading material
   ✅ Good for finding past decisions

**✅ Action Items / Todos** (Recommended: Last 7 days)
   ✅ Actionable recent tasks
   ⚠️  Can be overwhelming if too many
   ⚠️  Old todos often outdated or already done

**What would you like me to do?**

1️⃣ Smart default (Recommended)
   • People/companies: All [days_back] days
   • Meeting notes: Last 30 days (~[est_30d] meetings)
   • Todos: Last 7 days (~[est_7d] meetings)

2️⃣ Recent only (Conservative)
   • Everything: Last 7 days only

3️⃣ Full history (Comprehensive)
   • Everything: All [days_back] days

4️⃣ Custom (You choose)
   • Pick different time ranges for each type

5️⃣ Just going forward
   • Start fresh from today

6️⃣ Skip for now
```

### User Chooses Processing Strategy

Use AskUserQuestion tool. If AskUserQuestion is not available, prompt in CLI with the same numbered options and capture the selection:
```json
{
  "questions": [{
    "id": "granola_strategy",
    "prompt": "How would you like to process your Granola data?",
    "allow_multiple": false,
    "options": [
      {"id": "smart", "label": "1️⃣ Smart default - People/companies (all) + Notes (30d) + Todos (7d)"},
      {"id": "recent", "label": "2️⃣ Recent only - Everything from last 7 days"},
      {"id": "full", "label": "3️⃣ Full history - Everything from all available data"},
      {"id": "custom", "label": "4️⃣ Custom - I'll choose time ranges for each type"},
      {"id": "forward", "label": "5️⃣ Just going forward - Start fresh from today"},
      {"id": "skip", "label": "6️⃣ Skip for now"}
    ]
  }]
}
```

### Custom Mode Flow

If user selects "custom", ask for granular preferences:

```json
{
  "title": "Choose time ranges for historical data",
  "questions": [
    {
      "id": "people_range",
      "prompt": "People & Company Pages: How far back?",
      "allow_multiple": false,
      "options": [
        {"id": "7d", "label": "Last 7 days"},
        {"id": "30d", "label": "Last 30 days"},
        {"id": "90d", "label": "Last 90 days"},
        {"id": "all", "label": "All [days_back] days (recommended)"},
        {"id": "none", "label": "Skip - don't create"}
      ]
    },
    {
      "id": "notes_range",
      "prompt": "Meeting Notes: How far back?",
      "allow_multiple": false,
      "options": [
        {"id": "7d", "label": "Last 7 days"},
        {"id": "30d", "label": "Last 30 days (recommended)"},
        {"id": "90d", "label": "Last 90 days"},
        {"id": "all", "label": "All [days_back] days"},
        {"id": "none", "label": "Skip - don't create"}
      ]
    },
    {
      "id": "todos_range",
      "prompt": "Action Items / Todos: How far back?",
      "allow_multiple": false,
      "options": [
        {"id": "7d", "label": "Last 7 days (recommended)"},
        {"id": "30d", "label": "Last 30 days"},
        {"id": "90d", "label": "Last 90 days"},
        {"id": "all", "label": "All [days_back] days"},
        {"id": "none", "label": "Skip - don't create"}
      ]
    }
  ]
}
```

Map responses to days:
- "7d" → 7
- "30d" → 30
- "90d" → 90
- "all" → [days_back from extent analysis]
- "none" → 0 (skip)

### Process Based on Selection

**Map strategy to time ranges:**

```python
def map_strategy_to_ranges(strategy: str, extent: dict) -> dict:
    """Convert user strategy choice to specific time ranges"""
    
    if strategy == "smart":
        return {
            'people_days': extent['days_back'],  # All history
            'notes_days': min(30, extent['days_back']),  # Last 30 days or all if less
            'todos_days': min(7, extent['days_back'])   # Last 7 days or all if less
        }
    elif strategy == "recent":
        return {
            'people_days': 7,
            'notes_days': 7,
            'todos_days': 7
        }
    elif strategy == "full":
        return {
            'people_days': extent['days_back'],
            'notes_days': extent['days_back'],
            'todos_days': extent['days_back']
        }
    elif strategy == "forward":
        return {
            'people_days': 0,
            'notes_days': 0,
            'todos_days': 0
        }
    elif strategy == "skip":
        return None
    # For "custom", ranges come from separate AskUserQuestion responses (or CLI fallback)
```

**Show confirmation before processing:**

```
**Here's what I'll do:**

📇 People/Company Pages: Last [people_days] days
   → ~[est_people] people pages, ~[est_companies] company pages

📝 Meeting Notes: Last [notes_days] days
   → ~[est_notes] meeting notes

✅ Todos: Last [todos_days] days
   → Estimated [est_todos] action items

**This will take about 2-3 minutes. Ready?**
```

**Processing phases:**

1. **Fetch meetings by maximum range needed:**
   ```python
   max_days = max(people_days, notes_days, todos_days)
   all_meetings = granola_get_recent_meetings(days_back=max_days, limit=1000)
   ```

2. **Phase 1: People & Companies (if people_days > 0):**
   ```python
   # Filter meetings for people processing
   people_meetings = [m for m in all_meetings 
                      if days_ago(m['date']) <= people_days]
   
   # For each unique person:
   # - Extract from all meetings in range
   # - Create person page with meeting history
   # - Route to Internal/ or External/
   # - Create/update company pages for external domains
   
   # Use /process-meetings --people-only --days-back={people_days} logic
   ```

3. **Phase 2: Meeting Notes (if notes_days > 0):**
   ```python
   # Filter meetings for note creation
   notes_meetings = [m for m in all_meetings 
                     if days_ago(m['date']) <= notes_days]
   
   # For each meeting:
   # - Create detailed meeting note
   # - Extract key points and decisions
   # - Link to person/company pages
   # - BUT don't extract todos yet
   
   # Use /process-meetings --no-todos --days-back={notes_days} logic
   ```

4. **Phase 3: Todos (if todos_days > 0):**
   ```python
   # Filter meetings for todo extraction
   todo_meetings = [m for m in all_meetings 
                    if days_ago(m['date']) <= todos_days]
   
   # For meetings that have notes:
   # - Extract action items
   # - Create tasks in 03-Tasks/Tasks.md
   # - Add task IDs to meeting notes
   
   # For meetings in todo range but not notes range:
   # - Still extract todos but note they came from unprocessed meetings
   ```

5. **Show completion summary:**
   ```
   ## Processing Complete ✅
   
   **People & Companies:**
   • Created [X] person pages ([I] internal, [E] external)
   • Created [Y] company pages
   • Processed [P] days of history
   
   **Meeting Notes:**
   • Created [N] detailed meeting notes
   • From last [notes_days] days
   
   **Action Items:**
   • Extracted [T] todos
   • From last [todos_days] days
   • Added to 03-Tasks/Tasks.md
   
   **Your vault now has:**
   • Rich context from [people_days] days of meetings
   • Searchable notes from [notes_days] days
   • Actionable todos from [todos_days] days
   
   Want to explore what was created?
   ```

**If "skip" selected:**
- Show: "No problem! You can always run `/process-meetings` later when you're ready."
- Move to completion flow

**If "forward" selected:**
- Show: "Got it - starting fresh from today. I won't backfill historical data."
- Update a marker file to remember this choice
- Future meetings will be processed normally

---

## Flow B: Has Calendar OR Granola (Not Both)

**The "Let Me Help You Complete The Picture" Flow**

### If Only Calendar:

```
👋 **Welcome back, [Name]!**

You already saw this week's calendar snapshot during onboarding, so I won't repeat those numbers. I can now show you how to use that context for daily planning, meeting prep, and relationship notes.

**But I notice Granola isn't connected** - that's how I process meeting transcripts into action items and insights.

Want help with:
1. Connecting Granola — run `/granola-setup` to add your Granola API key (needs a Granola Business plan) for automatic meeting intelligence
2. Connecting another meeting tool
3. Or tell me what other tools you use - I'll build integrations

What sounds useful?
```

### If Only Granola:

**Same discovery flow as Flow A, but calendar-less:**

```
👋 **Welcome back, [Name]!**

I can see Granola is connected. Let me check what's available...

[Analyze Granola data extent - 6 months by default]

📊 **Granola data (last 6 months):**
• [N] meetings captured
• Going back [days_back] days (to [oldest_date])
• [M] unique people detected ([I] internal, [E] external)
• [K] external companies identified
```

**If `has_more_data` is True:**

```
💡 **I see there are meetings beyond 6 months.**
   Want me to check how much more history you have?
   
   → Yes - show me the full extent
   → No - 6 months is plenty
```

**Then continue:**

```
---

Here's what I can create from your Granola history:

**📇 People & Company Pages** (Recommended: All history)
   ✅ Builds context for relationships
   ✅ Low overhead - just reference pages

**📝 Meeting Notes** (Recommended: Last 30 days)
   ✅ Searchable record of discussions
   ⚠️  Medium overhead

**✅ Action Items / Todos** (Recommended: Last 7 days)
   ✅ Actionable recent tasks
   ⚠️  Can be overwhelming if too many

**What would you like me to do?**

1️⃣ Smart default - People/companies (all) + Notes (30d) + Todos (7d)
2️⃣ Recent only - Everything from last 7 days
3️⃣ Full history - Everything from all available data
4️⃣ Custom - I'll choose time ranges for each type
5️⃣ Just going forward - Start fresh from today
6️⃣ Skip for now

**I also notice your calendar isn't connected.** After processing, want to:
• Connect Google Calendar (even if work is restricted)
• Connect Apple Calendar
• Or skip - I can work with just Granola
```

Use the same AskUserQuestion and processing logic as Flow A (or CLI fallback).

---

## Flow C: Neither Calendar Nor Granola

**The "Let's Connect Your Tools" Flow**

```
👋 **Welcome back, [Name]!**

Your workspace is set up, but you don't have calendar or meeting tools connected yet.

**Let's get you integrated with the tools you actually use.**

What tools do you use most? Examples:
• Notion, Linear, Jira
• Slack, Discord
• GitHub, GitLab
• Your company's internal tools
• Newsletters, RSS feeds

**Give me names or URLs** (URLs are better - just the root domain like "notion.so" or "linear.app")

Once you tell me, I'll:
1. Check for API documentation
2. Analyze what's possible
3. Generate working MCP code
4. Get you integrated in ~2 minutes

What's your most important tool?
```

### Tool Integration Flow

When user provides tool name/URL:

**Step 1: Find API docs**
```python
if url_provided:
    # Fetch directly
    base_url = normalize_url(user_input)
    doc_content = web_fetch(base_url)
else:
    # Search for docs
    search_patterns = [
        f"{tool_name} API documentation",
        f"{tool_name} developer docs",
        f"{tool_name} API reference"
    ]
    # Try WebSearch or direct fetch of common patterns
    doc_url = find_api_docs(tool_name)
    doc_content = web_fetch(doc_url)
```

**Step 2: Analyze capabilities**
```
"Hold on - reading [Tool]'s API documentation..."

[Analyze doc_content for:]
- Authentication methods
- Available endpoints
- Common operations
- Rate limits

"Got it! I just read [Tool]'s API. Here's what we can build:

**Possible integrations:**
• [Capability 1] - [Dex use case]
• [Capability 2] - [Dex use case]
• [Capability 3] - [Dex use case]

Based on your role ([role]), I'd focus on [specific capabilities].

Ready to build this? Takes about 2 minutes."
```

**Step 3: Generate MCP**

Follow `/create-mcp` skill flow:
1. Design tools based on API analysis
2. Generate server code
3. Configure authentication
4. Test connection
5. Update documentation

**Step 4: The Magic Moment**
```
"Your [Tool] integration is live! ✅

Test it right now:
'[Natural language query about that tool]'

See? Real data, not AI guessing. That's what MCP does."
```

**Step 5: Offer More**
```
"Want to connect another tool? Or explore what else Dex can do?"

[If yes, repeat]
[If no, show quick reference guide]
```

---

## Additional Pathways (Available in Any Flow)

### Google Workspace Setup

If user wants to connect Gmail/Calendar:

```
"Let's connect your Google account.

This works even if your work account has restrictions - we can use your personal Google if needed.

**What we'll set up:**
• Calendar sync (see meetings in Dex)
• Gmail access (summarize newsletters, find emails)
• Optional: Create daily digest

I'll guide you through OAuth step-by-step.

Ready?"
```

Then:
1. Guide through OAuth flow for Google Calendar MCP
2. Add Gmail MCP if they want
3. Offer to set up newsletter digest

### Information Diet Setup

If user mentions newsletters, RSS, or content consumption:

```
"Want me to create a daily digest for you?

I can pull from:
• Newsletters (via Gmail)
• YouTube channels you follow
• RSS feeds from blogs
• Specific websites you check regularly

Each morning, you'd get:
• Summaries of new content
• Key points extracted
• Novel insights highlighted
• All in one place

What sources matter most to you?"
```

Then build appropriate scrapers/integrations.

### Smithery.ai Discovery

Anytime during tool discussion:

```
"By the way - there are 100+ pre-built MCP servers at **Smithery.ai**

Browse there for:
• GitHub, Linear, Jira
• Notion, Airtable, Sheets
• Slack, Discord, Email
• Databases, monitoring tools
• And way more...

Find something interesting? Just paste the URL here and I'll integrate it.

Or we can build custom if you don't find what you need."
```

---

## Setting Expectations

Throughout ANY flow, include:

```
"**Fair warning:** I can't promise everything will work perfectly.

Company restrictions, API limitations, weird auth flows - 
lots can go wrong in the real world.

**But here's what's cool:** Even when it doesn't work, you learn:
• How to use Claude to debug APIs
• How to build integrations yourself
• How MCP servers work
• How to read API documentation

It's educational even when it fails.

Still want to try?"
```

---

## Cursor UX Tip (If Running in Cursor)

After a few file edits, offer:

```
"**Quick Cursor tip:**

You're seeing 'Accept' prompts for each change I make. That's Cursor asking permission.

**Useful at first** - you see what's happening
**Annoying later** - slows things down

If you want to auto-accept:
1. Settings (Cmd+,)
2. Search "always allow tool use"
3. Enable it

Your choice - some prefer control, others prefer speed."
```

Only show if:
- Detected running in Cursor (check environment)
- After 3-4 accept prompts shown

---

## Integration Discovery (Contextual)

**Trigger:** Run this check if the vault is < 7 days old AND few or no integrations are connected.

### When to Check

After completing the main pathway flow (A, B, or C) but before showing the completion message:

1. Read `System/integrations/config.yaml` (if it exists)
2. Count how many integrations have `enabled: true` (exclude `slack` since it's a default)
3. If connected integrations <= 1 AND vault age < 7 days, run the concierge

### How to Run

Execute the integration concierge — it scans the vault for signals (mentions, links, email domains) of tools the user already works with and ranks them:

```bash
node .claude/hooks/integration-concierge.cjs
```

Parse the JSON output for the high_value and moderate_value tiers. Each entry includes `shortName`, `reason` (a ready-to-use plain-English signal — "installed on your Mac", "3 mentions in your notes", "already set up as a connector but not switched on yet"), `value`, `setupTime`, and `setup` (the setup skill to run). Prefer `reason` verbatim — it already names the strongest evidence (an installed app or configured connector outranks a passing mention).

### Presenting Recommendations

**Only surface high_value items** (keep it light — this isn't onboarding, it's a nudge).

For each high_value integration found:

```
By the way — **[shortName]** ([reason]).

Connecting it would give you: [value proposition]

Setup takes [setupTime]. Want to connect it now?
```

**If multiple high_value items:**

```
I also spotted signals for **[shortName2]** and **[shortName3]** in your notes.
Want to connect any of these? Or run `/integrate-mcp` anytime later.
```

**Rules:**
- Maximum 2 integration suggestions (don't overwhelm)
- Only mention high_value items (score >= 5) — skip moderate and available
- If the user says yes, run the setup skill (its `setup` field, e.g. `/trello-setup`) inline, then return to the getting-started completion
- If the user says no/skip/later, move on without pressure
- Don't show this section if the user already went through integration setup during onboarding Step 10 — check the `.onboarding-complete` marker for an `integrations_offered` flag and skip if present

---

## Completion & Next Steps

After any pathway completes:

```
"**You're set up!**

**Daily workflow:**
• Run `/daily-plan` each morning
• Use `/meeting-prep [person]` before meetings
• Tell me about meetings - I'll extract action items

**Discovery:**
• `/dex-level-up` - Find features you haven't tried
• `/integrate-mcp` - Add more tools anytime
• Smithery.ai - Browse MCP marketplace

**Come back anytime:**
• `/getting-started` - Run this tour again
• Just ask in natural language - I'll figure out what you need

What would you like to work on first?"
```

Update marker file:
```python
marker_data['phase2_completed'] = True
marker_data['phase2_completed_at'] = datetime.now().isoformat()
marker_data['pathways_completed'] = selected_pathways
```

---

## Usage Log Integration

Before showing suggestions, check `System/usage_log.md`:

```python
usage = read_usage_log()
tried_features = [f for f, checked in usage.items() if checked]

# Adaptive suggestions based on what they've used
if len(tried_features) < 3:
    # New user - basics
    suggest = ["daily-plan", "meeting-prep"]
elif "meeting-prep" not in tried_features and has_calendar:
    # Have meetings but haven't prepped
    suggest = ["meeting-prep"]
elif "process-meetings" not in tried_features and has_granola:
    # Have Granola but haven't processed
    suggest = ["process-meetings"]
else:
    # Power user - advanced features
    suggest = get_advanced_features(usage, role)
```

Don't show features they've already tried - focus on gaps.

---

## Escape Hatches

At EVERY major decision point:

- "This is a lot - want to pause and come back later?"
- "No pressure - you can always run `/getting-started` again"
- "Want to explore on your own first? That's cool"

After full tour:
- "Want to see everything you now own on one page? Run `/dex-dashboard`"
- "Remember - invoke `/dex-level-up` to discover more"
- "Or `/integrate-mcp` to add tools as you need them"
- "The system grows with you"

---

## Success Metric

The moment they think: **"How did it know to do that?"**

Different magic for different situations:
- **With data:** Analyzed calendar/Granola intelligently, offered smart actions
- **Without data:** Built working integration in 2 minutes from just a name
- **Either way:** They see value immediately and know where to go next

---

## Helper: Analyze Granola Data Extent

Before presenting choices, discover how much Granola data is available:

```python
def analyze_granola_extent(user_email_domain: str, extended: bool = False) -> dict:
    """
    Discover how much Granola data is available
    
    Args:
        user_email_domain: User's company email domain for internal/external classification
        extended: If True, fetch up to 2 years. If False, fetch 6 months (default)
    
    Returns:
        Dictionary with extent analysis or None if no data
    """
    from datetime import datetime
    
    # Default to 6 months for speed, optionally extend to 2 years
    days_to_fetch = 365 * 2 if extended else 180
    result = granola_get_recent_meetings(days_back=days_to_fetch, limit=1000)
    
    if not result.get('success') or not result.get('meetings'):
        return {
            'meetings_count': 0,
            'days_back': 0,
            'has_data': False
        }
    
    meetings = result['meetings']
    
    # Find oldest and newest dates
    dates = [m['date'] for m in meetings if m.get('date')]
    if not dates:
        return {'meetings_count': 0, 'days_back': 0, 'has_data': False}
    
    oldest = min(dates)
    newest = max(dates)
    
    # Calculate days back
    oldest_dt = datetime.fromisoformat(oldest)
    newest_dt = datetime.fromisoformat(newest)
    days_back = (newest_dt - oldest_dt).days + 1  # +1 to include both days
    
    # Extract unique people and companies
    people = set()
    internal_people = set()
    external_people = set()
    companies = set()
    
    # Normalize user domain for comparison
    user_domains = [d.strip().lower() for d in user_email_domain.split(',')]
    
    for meeting in meetings:
        for participant in meeting.get('participants', []):
            name = participant.get('name')
            email = participant.get('email')
            
            if name:
                people.add(name)
                
                if email:
                    domain = email.split('@')[1].lower() if '@' in email else None
                    
                    # Classify as internal or external
                    if domain and any(d in domain or domain in d for d in user_domains):
                        internal_people.add(name)
                    else:
                        external_people.add(name)
                        if domain:
                            companies.add(domain)
                else:
                    # No email provided - default to external
                    external_people.add(name)
    
    # Calculate meetings in different time ranges for estimation
    now = datetime.now()
    meetings_7d = sum(1 for m in meetings if m.get('date') and 
                      (now - datetime.fromisoformat(m['date'])).days <= 7)
    meetings_30d = sum(1 for m in meetings if m.get('date') and 
                       (now - datetime.fromisoformat(m['date'])).days <= 30)
    meetings_90d = sum(1 for m in meetings if m.get('date') and 
                       (now - datetime.fromisoformat(m['date'])).days <= 90)
    
    # Check if there might be more data beyond what we fetched
    has_more = False
    if not extended and len(meetings) >= 900:  # Close to limit, likely more data
        has_more = True
    
    # Check if oldest meeting is exactly at the boundary (suggests more data)
    if not extended and days_back >= 175:  # Close to 180 days
        has_more = True
    
    return {
        'has_data': True,
        'meetings_count': len(meetings),
        'days_back': days_back,
        'oldest_date': oldest,
        'newest_date': newest,
        'unique_people': len(people),
        'internal_people': len(internal_people),
        'external_people': len(external_people),
        'unique_companies': len(companies),
        'people_sample': list(people)[:10],
        'companies_list': list(companies),
        'meetings_7d': meetings_7d,
        'meetings_30d': meetings_30d,
        'meetings_90d': meetings_90d,
        'has_more_data': has_more,
        'fetched_range_days': days_to_fetch
    }
```

**Usage in Flow A:**
```python
# After detecting Granola is available
user_profile = read_user_profile()
email_domain = user_profile.get('email_domain', '')

# Fetch initial 6 months
extent = analyze_granola_extent(email_domain)

if not extent['has_data']:
    # Handle no data case
    pass
else:
    # Check if there's more data beyond 6 months
    if extent['has_more_data']:
        # Ask if they want to fetch more
        response = AskUserQuestion({
            "questions": [{
                "id": "fetch_more",
                "prompt": f"I found {extent['meetings_count']} meetings going back {extent['days_back']} days. There appears to be more data beyond that. Want me to check how much more?",
                "allow_multiple": false,
                "options": [
                    {"id": "yes", "label": "Yes - show me the full extent"},
                    {"id": "no", "label": "No - 6 months is enough"}
                ]
            }]
        })
        
        if response['fetch_more'] == 'yes':
            # Fetch extended range (2 years)
            extent = analyze_granola_extent(email_domain, extended=True)
    
    # Show discovery summary and choice framework
    pass
```

---

## Track Usage (Silent)

Update `System/usage_log.md` to mark getting started as used.

**Analytics (Silent):**

Call `track_event` with event_name `getting_started_completed` and properties:
- calendar_connected
- granola_connected
- artifacts_created

This only fires if the user has opted into analytics. No action needed if it returns "analytics_disabled".
