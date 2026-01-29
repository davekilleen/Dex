---
name: roadmap
description: Review roadmap, surface blockers, check alignment with priorities
role_groups: [product, operations]
jtbd: |
  You're constantly asked "what's on the roadmap?" and need to check alignment. 
  This scans your projects, surfaces blockers and stale initiatives, and checks 
  if your current work aligns with your strategic pillars.
time_investment: "10-15 minutes per review"
---

## Purpose

Review your product roadmap holistically - surface blockers, identify stale initiatives, and ensure alignment with strategic priorities. This gives you a quick health check of all roadmap work.

## Usage

- `/roadmap` - Full roadmap review
- `/roadmap [pillar-name]` - Filter by specific pillar

---

## Step 1: Gather Roadmap Context

Read roadmap-related projects and context:

1. **Scan 04-Projects/** for project files
2. **Read System/pillars.yaml** for strategic pillars
3. **Read 01-Quarter_Goals/Quarter_Goals.md** (if quarterly planning enabled)
4. **Search for roadmap mentions** in recent meeting notes (last 30 days)

---

## Step 2: Analyze Projects

For each project in 04-Projects/, extract:

**Status indicators:**
- Last modified date (flag if > 14 days without update)
- Completion status (in progress, blocked, completed)
- Pillar tags (ensure they exist and are valid)

**Blockers:**
- Search for keywords: "blocked", "waiting", "dependency", "need"
- Extract stakeholder dependencies
- Identify missing decisions

**Alignment:**
- Check if project tags match pillars in System/pillars.yaml
- Verify project supports a quarterly goal (if applicable)
- Note projects without clear pillar alignment

---

## Step 3: Check Recent Feedback

Search recent meeting notes (00-Inbox/Meetings/ from last 30 days) for:

- Customer feedback on roadmap items
- Stakeholder concerns about priorities
- Competitive mentions that might affect roadmap
- Requests for roadmap changes or updates

---

## Step 4: Generate Roadmap Summary

Present findings in this format:

```markdown
# 📋 Roadmap Review

**Date:** [Today's date]
**Projects reviewed:** [Count]

---

## 🎯 Active Initiatives

[For each in-progress project:]

### [Project Name]
**Pillar:** [Pillar tag]
**Status:** [Status indicator]
**Last updated:** [Days ago]
**Next milestone:** [If available]

[Brief status summary from project file]

---

## 🚨 Attention Needed

[Projects that need attention - stale, blocked, or misaligned]

### [Project Name]
**Issue:** [Stale / Blocked / No pillar alignment]
**Details:** [Specific problem]
**Suggested action:** [What to do next]

---

## 💡 Recent Stakeholder Feedback

[Key feedback from recent meetings that affects roadmap]

- **[Person/Customer]** - [Feedback summary]
- **[Person/Customer]** - [Feedback summary]

---

## ✅ Alignment Check

**Pillars with active work:**
- [Pillar 1]: [X projects]
- [Pillar 2]: [X projects]

**Pillars without active work:**
- [Pillar]: [Note if this is intentional or a gap]

---

## 📊 Summary

**Health score:** [Good / Needs Attention / Blocked]
- [X] projects on track
- [X] projects need attention
- [X] projects blocked

**Recommended actions:**
1. [Top priority action]
2. [Second priority action]
3. [Third priority action]
```

---

## Step 5: Offer Follow-Ups

After presenting the summary, ask:

> "Want me to:
> 1. Dive deeper into any specific project?
> 2. Create a roadmap update doc for stakeholders?
> 3. Update a stale project with current status?"

---

## Filter Behavior

When user specifies a pillar (e.g., `/roadmap customer-experience`):

1. Filter projects to only those tagged with that pillar
2. Check for gaps in that pillar's roadmap
3. Suggest opportunities based on recent customer feedback related to that pillar

---

## Integration with Other Skills

- **After running this:** Suggest `/customer-intel` if feedback patterns emerge
- **If blockers found:** Suggest `/meeting-prep` for key stakeholder discussions
- **If misalignment detected:** Suggest reviewing System/pillars.yaml

---

## Example Output

```markdown
# 📋 Roadmap Review

**Date:** 2026-01-28
**Projects reviewed:** 8

---

## 🎯 Active Initiatives

### Payments Redesign
**Pillar:** Revenue Growth
**Status:** In Progress
**Last updated:** 3 days ago
**Next milestone:** Design review on Friday

On track. Engineering started implementation. Sarah (design) needs 
feedback by Wed for final mockups.

### Real-time Notifications
**Pillar:** Product Quality
**Status:** In Progress
**Last updated:** 2 days ago
**Next milestone:** Beta launch Feb 5

Engineering complete. QA testing in progress. Beta group identified 
(10 customers).

---

## 🚨 Attention Needed

### Dashboard Analytics v2
**Issue:** Stale (21 days since update)
**Details:** No recent activity. Last note: "waiting on data team"
**Suggested action:** Check in with data team lead on timeline

### Mobile App Refresh
**Issue:** Blocked
**Details:** Waiting on design system components from design team
**Suggested action:** Schedule checkpoint with design team this week

### Customer Portal Improvements
**Issue:** No pillar alignment
**Details:** No pillar tag found in project file
**Suggested action:** Tag with appropriate pillar or clarify strategic fit

---

## 💡 Recent Stakeholder Feedback

- **Acme Corp (Sarah)** - Frustrated with reporting time, wants dashboards
- **Engineering (Mike)** - API refactor taking longer than expected, may impact Q1
- **Sales team** - 3 prospects asked about mobile app during demos this month

---

## ✅ Alignment Check

**Pillars with active work:**
- Revenue Growth: 3 projects
- Product Quality: 2 projects
- Customer Experience: 2 projects

**Pillars without active work:**
- Team Development: No active projects (intentional - focus is external)

---

## 📊 Summary

**Health score:** Needs Attention
- 5 projects on track
- 2 projects need attention
- 1 project blocked

**Recommended actions:**
1. Unblock Dashboard Analytics v2 - check data team status
2. Resolve Mobile App Refresh blocker - design checkpoint
3. Add pillar tag to Customer Portal Improvements
```
