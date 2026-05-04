---
name: dex-backlog
description: AI-powered ranking of Dex system improvement ideas
---

# dex-backlog

AI-powered ranking of Dex system improvement ideas

## What This Command Does

**In plain English:** AI-powered ranking of your Dex system improvement backlog based on current system state. Shows you what to build next.

**When to use it:**
- Weekly check-in on system improvements
- After capturing several new ideas
- When deciding what to work on next
- During quarterly planning for system improvements

**How to run it:**
```
$dex-backlog              # Full review with re-ranking
```

---

## Process Overview

1. **Load context** - Read system state, usage patterns, learnings
2. **Score ideas** - Calculate 5-dimension scores for each idea
3. **Re-rank backlog** - Sort by weighted total score
4. **Update file** - Write new rankings to `System/Dex_Backlog.md`
5. **Present top ideas** - Show top 5 with "Why now?" justification
6. **Offer next steps** - Workshop, implement, or defer

---

## Step 1: Load System Context

Read these files to understand current system state:

### Required Files
```
System/Dex_Backlog.md              # All ideas to score
System/usage_log.md                # Feature adoption patterns
System/user-profile.yaml           # Role, preferences
AGENTS.md                          # Current capabilities
```

### Optional Files (if they exist)
```
System/Session_Learnings/           # Recent pain points (last 30 days)
.agents/skills/                    # Available Dex workflows
core/mcp/                          # MCP integrations
06-Resources/Learnings/               # Captured patterns
```

### Extract Context

Build a context dictionary with:
- **Usage patterns**: Which features are used vs. unused
- **Role profile**: PM, Sales, Leadership, Engineer, etc.
- **Pain points**: Recent friction from session learnings
- **System capabilities**: What's currently available
- **Backlog state**: All ideas and their current scores

---

## Step 2: Score Each Idea

For every active idea in the backlog, calculate 5 dimension scores.

### ⚠️ CURSOR FEASIBILITY CHECK (Do This First!)

Before scoring ANY idea, validate it's actually implementable in Codex:

**What Codex/Terminal CAN do:**
- ✅ Read and write files
- ✅ Execute shell commands
- ✅ Build MCP tools for structured operations
- ✅ Parse and transform file contents
- ✅ Create caches and indexes (file-based)
- ✅ Run commands on schedules or triggers

**What Codex/Terminal CANNOT do:**
- ❌ Track user edits in real-time
- ❌ Hook into Codex internals
- ❌ Monitor user actions passively
- ❌ Access edit history without explicit file reads
- ❌ Real-time background processes watching for changes

**If idea requires something from the CANNOT list → Set all scores to 0 and flag as "Not feasible in Codex"**

---

After feasibility check passes, score on 5 dimensions:

### Dimension 1: Impact (35% weight)

**Question:** How much would this improve daily workflow?

**Scoring logic:**
```
Base score: 50

+20 if matches_recent_pain_points():
  - Search System/Session_Learnings/ for mentions of this issue
  - Keywords from idea title/description appear in learnings
  - Problem stated explicitly in recent notes

+15 if affects_daily_workflow():
  - Touches commands used >3x per week (from usage_log)
  - Modifies core files (03-Tasks/Tasks.md, daily plans, person pages)
  - Impacts repetitive actions

+15 if has_compound_value():
  - Enables other ideas in backlog
  - Reduces technical debt
  - Creates reusable patterns
  - Unblocks multiple workflows

Max: 100
```

**Examples:**
- "Auto-suggest person pages": 95 (daily workflow + enables relationship tracking)
- "Export to blog": 40 (nice-to-have, doesn't affect core workflow)

---

### Dimension 2: Alignment (20% weight)

**Question:** Does this fit actual usage patterns?

**Scoring logic:**
```
Base score: 50

+30 based on usage_overlap():
  - Extract features idea depends on
  - Check if those features are used (usage_log)
  - Calculate overlap: (used_features / total_features) * 30

+20 if fits_role_profile():
  - PM roles: prioritize project/product features
  - Sales roles: prioritize relationship/account features
  - Leadership: prioritize synthesis$review features
  - Match category to role focus areas

Max: 100
```

**Examples:**
- Idea needs "person pages" → Check if user has created person pages
- If usage_log shows person pages = used → Higher alignment
- If role = PM and idea = product features → +20 role fit

---

### Dimension 3: Token Efficiency (20% weight)

**Question:** Does this reduce context/token usage?

**CRITICAL - Codex Feasibility Check:**
Before scoring, verify the idea is implementable in Codex/Terminal:
- ✅ Can use: File read/write, MCP tools, command execution, file-based caching
- ❌ Cannot use: Real-time edit tracking, Codex internal hooks, monitoring user actions
- If not feasible in Codex → Score = 0 on all dimensions

**Scoring logic:**
```
Base score: 50

+25 if reduces_token_usage():
  - Caches/stores frequently accessed data (in files/MCP)
  - Compresses or summarizes verbose content (file-based)
  - Eliminates redundant reads
  - Enables more efficient retrieval patterns

+15 if improves_context_efficiency():
  - Reduces number of files that need reading
  - Creates structured summaries (YAML/JSON files)
  - Better indexing/search to avoid broad scans
  - Moves data from markdown to structured format

+10 if enables_incremental_updates():
  - Supports partial updates instead of full rewrites
  - Tracks changes in separate files
  - Lazy loading or on-demand computation

Max: 100
```

**Examples:**
- "Cache meeting summaries in YAML": 90 (file-based, avoids re-reading)
- "Track user edits for learning": 0 (NOT FEASIBLE - can't track edits)
- "Add new field to template": 50 (neutral token impact)

---

### Dimension 4: Memory & Learning (15% weight)

**Question:** Does this enhance system memory, persistence, or self-learning?

**Scoring logic:**
```
Base score: 50

+20 if improves_memory_persistence():
  - Stores learnings for future reference
  - Creates retrievable knowledge base
  - Captures patterns that compound over time
  - Builds historical context

+20 if enables_self_learning():
  - System learns from user behavior
  - Adapts recommendations based on patterns
  - Builds preference models
  - Improves predictions over time

+10 if creates_feedback_loops():
  - Tracks outcomes of suggestions
  - Measures effectiveness of recommendations
  - Refines based on what works

Max: 100
```

**Examples:**
- "Learning pattern synthesizer": 95 (captures + compounds knowledge)
- "Preference learning from edits": 85 (system adapts over time)
- "Static template update": 50 (no learning component)

---

### Dimension 5: Proactivity (10% weight)

**Question:** Does this enable proactive concierge behavior?

**Scoring logic:**
```
Base score: 50

+25 if enables_anticipation():
  - Surfaces relevant info before asked
  - Predicts needs based on patterns
  - Proactive suggestions not just reactive
  - Context-aware prompts

+15 if automates_routine_decisions():
  - Handles repetitive choices automatically
  - Learns user preferences and applies them
  - Reduces decision fatigue

+10 if improves_timing():
  - Right information at right time
  - Context-aware interruptions
  - Anticipates upcoming needs

Max: 100
```

**Examples:**
- "Auto-prep meetings based on calendar": 90 (proactive + anticipatory)
- "Suggest weekly priorities from patterns": 80 (learns and anticipates)
- "Add manual review step": 50 (reactive, not proactive)

---

## Step 3: Calculate Weighted Score

```
total_score = (
  (impact * 0.35) +
  (alignment * 0.20) +
  (token_efficiency * 0.20) +
  (memory_learning * 0.15) +
  (proactivity * 0.10)
)

Round to integer: total_score = round(total_score)
```

**Priority Bands:**
- **High Priority (85+):** Should tackle soon, high ROI
- **Medium Priority (60-84):** Good ideas, right time matters
- **Low Priority (<60):** Maybe later or needs refinement

**Why These Dimensions:**
- **Effort excluded:** With AI coding, implementation is cheap - focus on value, not cost
- **Token efficiency prioritized:** Context efficiency is critical for performance
- **Memory & learning emphasized:** System should get smarter over time
- **Proactivity valued:** Concierge behavior > reactive tool

---

## Step 4: Update Backlog File

Rewrite `System/Dex_Backlog.md` with:

1. **Update timestamp** at top
2. **Re-sort ideas** by total score (high to low)
3. **Update each idea** with new scores:
   ```markdown
   - **[idea-XXX]** Title
     - **Score:** 92 (Impact: 95, Alignment: 90, Effort: 85, Synergy: 95, Fresh: 70)
     - **Category:** category
     - **Captured:** YYYY-MM-DD
     - **Why ranked here:** [1-2 sentence reasoning based on scores]
     - **Description:** [original description]
   ```
4. **Place in correct section** (High/Medium/Low priority)
5. **Preserve Archive section** (don't re-rank implemented ideas)

---

## Step 5: Present Results

Show the user the top 5 ideas with context:

```markdown
# 📊 Backlog Review Complete

*Analyzed {{total_ideas}} ideas against current system state*

## 🔥 Top 5 Recommendations

### 1. [idea-XXX] {{title}} (Score: {{score}})

**Why now:** {{reasoning based on scores - be specific}}

**Quick assessment:**
- Impact: {{impact_justification}}
- Fits your patterns: {{alignment_justification}}
- Effort: {{effort_estimate}}

**Next step:** Run `$dex-improve "{{title}}"` to workshop this idea

---

### 2. [idea-YYY] {{title}} (Score: {{score}})

[Same format]

---

[... continue for top 5 ...]

---

## 📈 Backlog Health

- **Total ideas:** {{total}}
- **High priority (85+):** {{high_count}}
- **Medium priority (60-84):** {{medium_count}}
- **Low priority (<60):** {{low_count}}

{{#if high_count > 5}}
⚠️ **Note:** You have {{high_count}} high-priority ideas. Consider tackling 1-2 this week to reduce backlog.
{{/if}}

{{#if low_count > 10}}
💡 **Tip:** {{low_count}} low-priority ideas might be worth archiving or refining.
{{/if}}

---

## What would you like to do?

1. **Workshop an idea** → `$dex-improve "[title]"`
2. **Capture a new idea** → Use `capture_idea` MCP tool
3. **Mark one implemented** → Use `mark_implemented` MCP tool
4. **View full backlog** → Check `System/Dex_Backlog.md`
```

---

## Step 6: Handle Special Cases

### If Backlog is Empty
```markdown
# 📊 Backlog Review

Your backlog is empty! 

Start capturing improvement ideas:
- Use the `capture_idea` MCP tool anytime you think "I wish Dex did X"
- Run `$dex-improve` to explore capability gaps
- Run `$dex-level-up` to discover unused features

The backlog system will help you track and prioritize ideas systematically.
```

### If No High Priority Ideas
```markdown
🎉 **Good news:** No urgent improvements needed!

Your system is working well. The backlog has ideas for later, but nothing critical right now.

Consider:
- Running `$dex-level-up` to discover unused features
- Capturing ideas as they come up
- Reviewing backlog quarterly
```

### If Many Stale Ideas (>6 months old)
```markdown
⚠️ **Backlog maintenance needed**

You have {{stale_count}} ideas older than 6 months. These might be:
- No longer relevant → Archive them
- Still valuable but not urgent → Keep them
- Worth revisiting with new context → Re-evaluate descriptions

Review stale ideas:
{{list stale ideas}}

Want to bulk archive these? I can help clean up the backlog.
```

---

## Integration with Other Commands

### Hand-off to $dex-improve

When user says "Let's work on #1" or "Workshop idea-XXX":

1. Read the idea details from backlog
2. Pass to `$dex-improve` with context:
   ```
   $dex-improve "{{idea_title}}"
   
   Context from backlog:
   - Current score: {{score}}
   - Why it's prioritized: {{reasoning}}
   - Original description: {{description}}
   ```
3. `$dex-improve` takes over for workshopping

---

## Scoring Implementation Tips

### Codex Feasibility Check (Run FIRST)

```python
def check_cursor_feasibility(idea: dict) -> dict:
    """
    Returns: {
        'feasible': bool,
        'reason': str,
        'capabilities_required': list
    }
    """
    description_lower = idea['description'].lower()
    
    # Red flags - things Codex CAN'T do
    cannot_do = {
        'track edits': 'Cannot monitor file edits in real-time',
        'watch user': 'Cannot observe user actions passively',
        'hook into': 'Cannot hook into Codex internals',
        'monitor changes': 'Cannot monitor without explicit file reads',
        'background process': 'No persistent background processes'
    }
    
    for phrase, reason in cannot_do.items():
        if phrase in description_lower:
            return {
                'feasible': False,
                'reason': reason,
                'suggestion': 'Reframe as file-based or command-triggered'
            }
    
    # Green flags - things Codex CAN do
    can_do = ['file', 'read', 'write', 'mcp', 'command', 'cache', 'index', 'parse']
    has_feasible_approach = any(word in description_lower for word in can_do)
    
    if has_feasible_approach:
        return {'feasible': True, 'reason': 'Uses Codex-compatible operations'}
    else:
        return {
            'feasible': False,
            'reason': 'No clear implementation path in Codex',
            'suggestion': 'Add file-based or MCP approach'
        }
```

### For Impact Calculation

```python
def calculate_impact(idea, context):
    # First check feasibility
    feasibility = check_cursor_feasibility(idea)
    if not feasibility['feasible']:
        return 0  # Not feasible = 0 impact
    
    score = 50
    
    # Check session learnings for pain point mentions
    learnings = context['session_learnings']
    idea_keywords = extract_keywords(idea['title'] + idea['description'])
    
    for learning in learnings:
        learning_keywords = extract_keywords(learning['content'])
        if overlap(idea_keywords, learning_keywords) > 0.3:
            score += 20
            break
    
    # Check if affects daily workflow
    if touches_daily_commands(idea, context['usage_log']):
        score += 15
    
    # Check compound value
    if enables_other_ideas(idea, context['backlog']):
        score += 15
    
    return min(score, 100)
```

### For Alignment Calculation

```python
def calculate_alignment(idea, context):
    score = 50
    
    # Extract related features
    features = extract_related_features(idea)
    used_features = get_used_features(context['usage_log'])
    
    overlap_ratio = len(features & used_features) / len(features)
    score += int(overlap_ratio * 30)
    
    # Role fit
    role = context['user_profile']['role']
    category = idea['category']
    
    role_fit_map = {
        'PM': ['projects', 'workflows', 'knowledge'],
        'Sales': ['relationships', 'tasks'],
        'Leadership': ['knowledge', 'workflows']
    }
    
    if category in role_fit_map.get(role, []):
        score += 20
    
    return min(score, 100)
```

### For Token Efficiency Calculation

```python
def calculate_token_efficiency(idea, context):
    score = 50
    
    # Check if reduces token usage
    if reduces_reads(idea):  # Caching, summaries
        score += 25
    
    # Context efficiency improvements
    if improves_retrieval(idea):  # Better indexing, structured data
        score += 15
    
    # Incremental updates
    if supports_incremental(idea):  # Partial updates, lazy loading
        score += 10
    
    return min(score, 100)
```

### For Memory & Learning Calculation

```python
def calculate_memory_learning(idea, context):
    score = 50
    
    # Memory persistence
    if stores_learnings(idea):  # Knowledge base, historical context
        score += 20
    
    # Self-learning capability
    if enables_adaptation(idea):  # Learns from behavior, improves over time
        score += 20
    
    # Feedback loops
    if tracks_outcomes(idea):  # Measures effectiveness, refines
        score += 10
    
    return min(score, 100)
```

### For Proactivity Calculation

```python
def calculate_proactivity(idea, context):
    score = 50
    
    # Anticipation capability
    if enables_anticipation(idea):  # Surfaces info before asked
        score += 25
    
    # Automation of routine decisions
    if automates_decisions(idea):  # Handles repetitive choices
        score += 15
    
    # Timing improvements
    if improves_timing(idea):  # Right info at right time
        score += 10
    
    return min(score, 100)
```

---

## Best Practices

1. **Run weekly** during `$week-plan` or standalone
2. **Don't obsess over scores** - they're guidance, not gospel
3. **Trust your instinct** - high score + gut feel = go
4. **Keep backlog lean** - max 20 active ideas
5. **Archive implemented** - celebrate progress
6. **Refine low scorers** - add detail to boost alignment/impact

---

## Philosophy

The backlog isn't a todo list - it's a **decision support system**.

Scores help you:
- Surface high-value work
- Avoid shiny object syndrome
- Align improvements with actual usage
- Make intentional choices

But you're still the decision maker. If a low-scoring idea excites you, workshop it. The system serves you, not the other way around.

---

## Track Usage (Silent)

Update `System/usage_log.md` to mark backlog review as used.

**Analytics (Silent):**

Call `track_event` with event_name `backlog_reviewed` and properties:
- `ideas_count`

This only fires if the user has opted into analytics. No action needed if it returns "analytics_disabled".
