# Dex Folder Structure (PARA Method)

Dex uses the PARA method for organization: **Projects**, **Areas**, **Resources**, and **Archives**.

## What is PARA?

PARA organizes information by **actionability**:

- **Projects** = time-bound work with clear outcomes (has an end date)
- **Areas** = ongoing responsibilities (never "finish")
- **Resources** = reference material you consult
- **Archives** = inactive items for historical reference

## Root Files (Active State)

```
00-A-Quarter_Goals/Quarter_Goals.md       # Current quarter's 3-5 strategic goals
00-C-Tasks/Tasks.md               # Task backlog with pillar tags and goal links
00-B-Week_Priorities/Week_Priorities.md     # Current week's Top 3 priorities
```

These files represent your **current state**—what you're working toward right now.

---

## 01-Projects/

**Time-bound initiatives with clear goals and deliverables.**

### What makes something a project?
- Clear outcome (specific deliverable or result)
- End date (defined completion point)
- Active work (you're currently working on it)

### Examples
- Product launches
- Feature development
- Migrations or technical upgrades
- Campaign execution

### When complete
Move to `04-Archives/01-Projects/` with completion date and learnings.

**Key distinction:**  
Project = has an end ("Ship payments redesign")  
Area = ongoing ("Customer success management")

---

## 02-Areas/

**Ongoing responsibilities that require maintenance but never "finish."**

### Default Areas

Everyone gets:
- **People/** — Relationships with colleagues, customers, partners
  - `Internal/` — Teammates, managers, cross-functional partners
  - `External/` — Customers, prospects, partners

### Role-Specific Areas

Created during onboarding based on your role:

| Role | Areas Created |
|------|--------------|
| Sales / Account Exec | `Accounts/` — Companies and deals |
| Manager | `Team/` — Direct reports and team development |
| Content Creator | `Content/` — Thought leadership and published work |
| Customer Success | `Customers/` — Customer health tracking |

### Career Area

Created via `/career-setup` command:
- `Career/` — Career development tracking
  - `Current_Role.md`
  - `Career_Ladder.md`
  - `Evidence/` — Achievements, feedback, skills

**Key distinction:**  
Area = ongoing ("Manage customer relationships")  
Project = has an end ("Onboard Acme Corp")

---

## 03-Resources/

**Reference material you consult but aren't actively working on.**

```
03-Resources/
├── Dex_System/      # Documentation about how Dex works
├── Learnings/       # Compound knowledge (frameworks, lessons learned)
└── Templates/       # Note templates for consistency
```

### What belongs here?
- Things you reference repeatedly
- Knowledge that compounds over time
- Context for future decisions
- Lasting value beyond current work

### Examples
- Frameworks and mental models
- Best practices and lessons learned
- Process documentation
- Research and competitive analysis

**Key distinction:**  
Resources = you actively reference this  
Archives = historical record, rarely consulted

---

## 04-Archives/

**Historical records and completed work.**

```
04-Archives/
├── 01-Projects/        # Completed or cancelled projects
├── Plans/           # Daily and weekly plans (auto-archived)
└── Reviews/         # Daily, weekly, and quarterly reviews (auto-archived)
```

### Auto-Archiving

Plans and reviews automatically move here:
- Daily plans → after `/daily-plan` runs
- Daily reviews → after `/daily-review` runs
- Weekly plans → after `/week-plan` runs
- Quarterly reviews → after `/quarter-review` runs

### Manual Archiving

Projects move here when complete:
- Add completion date and outcome
- Document key learnings
- Keep original filename for searchability

### Retention

Keep archives indefinitely—they're your historical record and learning source for quarterly reviews and career reflections.

---

## Inbox/

**Capture zone for quick notes before you organize them.**

```
Inbox/
├── Meetings/        # Meeting notes
└── Ideas/           # Quick captures and random thoughts
```

### Philosophy

Inbox is for **capture, not organization**. Don't worry about structure—just get it down.

### Workflow

1. **Capture** — Drop everything here first
2. **Triage** — Run `/triage` to process and organize
3. **Move** — Files route to 01-Projects/, 02-Areas/, or 03-Resources/

### Inbox Zero

Aim to triage weekly. If something sits 30+ days:
- Not important → delete
- Reference → move to 03-Resources/
- Dormant project → archive

---

## System/

**Configuration and system files.**

```
System/
├── Session_Learnings/   # System improvements discovered during sessions
├── Templates/           # Note templates
├── pillars.yaml         # Strategic pillars
├── user-profile.yaml    # User preferences
└── Dex_Backlog.md       # System improvement backlog (AI-ranked)
```

Most users won't edit this directly—Dex manages it. But when you want to adjust strategic direction or preferences, the key files are here.

---

## Planning Hierarchy

Everything connects from pillars → quarters → weeks → days:

1. **Strategic Pillars** (`System/pillars.yaml`)  
   Your ongoing focus areas

2. **Quarter Goals** (`00-A-Quarter_Goals/Quarter_Goals.md`)  
   Time-bound outcomes (3 months) advancing pillars

3. **Week Priorities** (`00-B-Week_Priorities/Week_Priorities.md`)  
   Top 3 this week advancing quarterly goals

4. **Daily Plan** (`04-Archives/Plans/`)  
   Today's work supporting weekly priorities (auto-archived)

5. **Tasks** (`00-C-Tasks/Tasks.md`)  
   Backlog tagged with `#pillar [Q1-2] [Week-1]`

---

## Quick Reference

| Folder | Purpose | Lifespan |
|--------|---------|----------|
| **01-Projects/** | What you're building | Until project ships |
| **02-Areas/** | Ongoing responsibilities | Indefinite |
| **03-Resources/** | Reference material | Indefinite |
| **04-Archives/** | Historical record | Indefinite |
| **Inbox/** | Quick captures | Days (until triaged) |
| **System/** | Configuration | Indefinite |

---

## First Time Setup

New to Dex? Just ask to start onboarding. The structure will be customized for your role and working style.

For detailed explanations of each folder, check the README.md file in that folder.
