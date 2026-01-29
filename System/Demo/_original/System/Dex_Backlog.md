# Dex System Improvement Backlog

Ideas for improving the Dex personal knowledge system, ranked by AI based on impact, alignment, token efficiency, learning capabilities, and proactivity.

**Last AI ranking:** 2026-01-24
**Next review:** Weekly during planning

---

## High Priority (Score: 85+)

### 1. Auto-link related tasks ⭐ 92/100
**Status:** Not started  
**Captured:** 2026-01-18

**The idea:**
When I create a task about a person or project, automatically suggest linking it to that person's page or project file. E.g., "Schedule interview with Sarah" → prompt to add to Sarah_Chen.md

**Why now:**
- **Impact (35%):** 32/35 - Reduces manual linking, surfaces tasks in context
- **Alignment (20%):** 19/20 - Matches my workflow (lots of person/project tasks)
- **Token Efficiency (20%):** 18/20 - Less searching for related tasks later
- **Memory (15%):** 14/15 - Better task-context connections over time
- **Proactivity (10%):** 9/10 - Dex suggests connections I might miss

**Implementation approach:**
- Parse task content for names, project keywords
- Check People/ and Projects/ folders for matches
- Prompt: "This task mentions Sarah Chen. Add to her person page?"
- Update both locations (Tasks.md + person page)

**Effort:** Medium - Entity detection + file updates

---

### 2. Meeting-to-project linker ⭐ 88/100
**Status:** Not started  
**Captured:** 2026-01-19

**The idea:**
After capturing meeting notes, Dex scans content and suggests which projects this meeting relates to. Auto-adds meeting link to project file's meeting history.

**Why now:**
- **Impact (35%):** 31/35 - Meetings often drive project progress, need connection
- **Alignment (20%):** 18/20 - I have lots of project meetings
- **Token Efficiency (20%):** 17/20 - Saves searching meeting notes later
- **Memory (15%):** 13/15 - Project context accumulates automatically
- **Proactivity (10%):** 9/10 - Dex makes connections I'd forget

**Implementation approach:**
- After meeting capture, scan for project keywords
- Match against active projects in 04-Projects/
- Prompt: "This meeting mentions Mobile App Launch. Link to project?"
- Add to project's "Meeting Notes" section

**Effort:** Medium - Content analysis + project matching

---

### 3. Weekly pattern detection ⭐ 87/100
**Status:** Not started  
**Captured:** 2026-01-22

**The idea:**
During weekly review, Dex analyzes the week's meetings, tasks, and journal entries to detect patterns. E.g., "You had 3 meetings with Sales this week (unusual). Energy dips every afternoon at 3pm. Mobile launch mentioned in 8 different contexts."

**Why now:**
- **Impact (35%):** 30/35 - Self-awareness drives improvement
- **Alignment (20%):** 18/20 - I love weekly reviews and pattern recognition
- **Token Efficiency (20%):** 17/20 - Better insights from existing data
- **Memory (15%):** 13/15 - Patterns compound over time
- **Proactivity (10%):** 9/10 - Surfaces insights I'd miss

**Implementation approach:**
- During /week-review, scan last 7 days
- Count: meeting types, people interactions, energy mentions, recurring topics
- Prompt: "Patterns this week: X meetings with Y, energy low at Z, mobile launch in 8 contexts"
- Suggest learnings to capture

**Effort:** Medium-High - Pattern detection across multiple files

---

## Medium Priority (Score: 60-84)

### 4. Task dependency suggestions 📊 78/100
**Status:** Not started  
**Captured:** 2026-01-23

**The idea:**
When creating tasks, Dex analyzes existing tasks and suggests dependencies. E.g., "Schedule user interviews" might depend on "Finalize interview script" being completed.

**Why now:**
- **Impact (35%):** 27/35 - Better task sequencing, fewer blockers
- **Alignment (20%):** 16/20 - I often work on tasks in wrong order
- **Token Efficiency (20%):** 16/20 - Reduced thrashing on blocked work
- **Memory (15%):** 11/15 - Learns dependency patterns
- **Proactivity (10%):** 8/10 - Suggests connections proactively

**Implementation approach:**
- When creating task, check for potential blockers in backlog
- Use keywords + project context to suggest dependencies
- Prompt: "This task might depend on [other task]. Mark as blocked-by?"
- Use Work MCP to create dependency link

**Effort:** High - Dependency analysis is complex

---

### 5. Quarterly goals dashboard 📊 75/100
**Status:** Not started  
**Captured:** 2026-01-15

**The idea:**
Create a `/quarter-dashboard` command that shows progress on quarterly goals: tasks completed toward each goal, evidence captured, time remaining, on-track status.

**Why now:**
- **Impact (35%):** 26/35 - Better goal visibility and tracking
- **Alignment (20%):** 15/20 - I use quarterly planning
- **Token Efficiency (20%):** 15/20 - Quick goal check-ins
- **Memory (15%):** 12/15 - Tracks progress over time
- **Proactivity (10%):** 7/10 - Shows goal status automatically

**Implementation approach:**
- Read Quarter_Goals.md for current goals
- Count tasks tagged with quarter goals
- Check Career evidence with goal tags
- Generate dashboard: Goal → Progress → Status → Evidence count
- Flag goals falling behind

**Effort:** Medium - Aggregation across multiple sources

---

### 6. Smart meeting prep template 📊 73/100
**Status:** Not started  
**Captured:** 2026-01-20

**The idea:**
Instead of generic meeting prep, Dex customizes the template based on meeting type. 1:1s show different context than customer calls. Sales calls surface deal info, design reviews show project context.

**Why now:**
- **Impact (35%):** 25/35 - More relevant context for each meeting type
- **Alignment (20%):** 15/20 - I do lots of meeting prep
- **Token Efficiency (20%):** 14/20 - Right context without manual search
- **Memory (15%):** 11/15 - Learns what context matters per type
- **Proactivity (10%):** 8/10 - Auto-customizes based on meeting

**Implementation approach:**
- Detect meeting type from title/attendees (1:1, customer, design review, etc.)
- Load type-specific template
- Populate with relevant context (person pages for 1:1s, project for design reviews)
- Generate customized prep doc

**Effort:** Medium-High - Meeting type detection + template system

---

### 7. Email-to-task capture 📊 71/100
**Status:** Not started  
**Captured:** 2026-01-21

**The idea:**
Forward emails to a special address, Dex extracts action items and creates tasks automatically. E.g., forward customer request → Dex creates task with context.

**Why now:**
- **Impact (35%):** 25/35 - Faster capture from email (big time sink)
- **Alignment (20%):** 14/20 - Some capture from email, not huge
- **Token Efficiency (20%):** 14/20 - Saves copy-paste time
- **Memory (15%):** 10/15 - Task context preserved from email
- **Proactivity (10%):** 8/10 - Auto-extraction of action items

**Implementation approach:**
- Set up email forwarding address
- Parse email for action items
- Use Work MCP to create tasks
- Link to person if sender is in People/
- Prompt for confirmation

**Effort:** High - Email parsing + infrastructure setup

---

### 8. Career evidence auto-tagging 📊 69/100
**Status:** Not started  
**Captured:** 2026-01-21

**The idea:**
When completing tasks or capturing achievements, Dex suggests career competency tags based on content. E.g., "Presented to exec team" → suggests "# Career: Executive Communication"

**Why now:**
- **Impact (35%):** 24/35 - Easier evidence tracking for promotion
- **Alignment (20%):** 14/20 - I'm focusing on L5 progression
- **Token Efficiency (20%):** 13/20 - Saves manual tagging
- **Memory (15%):** 10/15 - Builds career evidence library
- **Proactivity (10%):** 8/10 - Suggests tags I'd miss

**Implementation approach:**
- When task completed or achievement captured, analyze content
- Match keywords to career competencies (Strategic Thinking, Executive Communication, etc.)
- Prompt: "This demonstrates Executive Communication. Tag for career evidence?"
- Add tag to task/achievement

**Effort:** Medium - Content analysis + competency matching

---

## Low Priority (Score: <60)

### 9. Voice note capture 🔵 58/100
**Status:** Not started  
**Captured:** 2026-01-16

**The idea:**
Record quick voice memos that Dex transcribes and routes to appropriate location (person page, project, idea).

**Why now:**
- **Impact (35%):** 20/35 - Faster capture while walking, but not huge workflow change
- **Alignment (20%):** 12/20 - I mostly type, not voice
- **Token Efficiency (20%):** 12/20 - Saves typing time
- **Memory (15%):** 8/15 - Transcription loses some nuance
- **Proactivity (10%):** 6/10 - Routing is proactive

**Effort:** High - Voice transcription infrastructure

---

### 10. Browser extension for capture 🔵 55/100
**Status:** Not started  
**Captured:** 2026-01-17

**The idea:**
Browser extension to capture web pages, snippets, or notes directly to Dex inbox while browsing.

**Why now:**
- **Impact (35%):** 19/35 - Saves context switching
- **Alignment (20%):** 11/20 - Limited web research in my workflow
- **Token Efficiency (20%):** 11/20 - Marginal time savings
- **Memory (15%):** 8/15 - Captures sources better
- **Proactivity (10%):** 6/10 - Extension suggests capture

**Effort:** High - Browser extension development

---

## Ideas for Future Consideration

### Rejected/Deferred

#### Calendar-task sync
**Status:** Rejected  
**Reason:** Cursor/Claude can't access calendar APIs directly. Would require external integration that's not feasible within Cursor constraints.

---

## Scoring Methodology

Each idea scored on 5 dimensions:

| Dimension | Weight | What It Measures |
|-----------|--------|------------------|
| Impact | 35% | Daily workflow improvement, time saved, friction reduced |
| Alignment | 20% | Fits your actual usage patterns and workflow |
| Token Efficiency | 20% | Reduces context/token usage in sessions |
| Memory & Learning | 15% | Enhances persistence, self-learning, compound knowledge |
| Proactivity | 10% | Enables proactive concierge behavior |

**Priority Bands:**
- **High (85+):** Implement soon - high value, strong fit
- **Medium (60-84):** Implement when time permits - good value
- **Low (<60):** Consider if becomes higher priority

---

*AI ranking date: 2026-01-24*
*Next review: Weekly during planning*
