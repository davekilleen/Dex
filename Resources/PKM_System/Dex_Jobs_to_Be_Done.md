# Dex Jobs to Be Done

What problems does Dex solve? This document maps user needs to system components.

---

## The 6 Core Jobs

### 1. Start My Day with Clarity
**When:** Morning, before diving into work
**I want to:** See what matters today, prepare for meetings, know my priorities
**So I can:** Work intentionally instead of reactively

**Components:**
- `/daily-plan` command
- Calendar integration
- Task priority limits
- Meeting prep agent

---

### 2. Capture Everything Without Friction
**When:** During the day, in meetings, having ideas
**I want to:** Quickly capture without organizing
**So I can:** Trust nothing falls through the cracks

**Components:**
- `Inbox/` folder structure
- Meeting templates
- `/triage` command
- Voice notes support

---

### 3. Find What I Need Fast
**When:** Before meetings, writing, or decision-making
**I want to:** Recall past conversations, decisions, and context
**So I can:** Show up prepared and informed

**Components:**
- Person pages with meeting history
- WikiLinks for connections
- Search across vault
- `/meeting-prep` command

---

### 4. Track Projects Without Overhead
**When:** Managing multiple initiatives
**I want to:** See status, blockers, and next actions at a glance
**So I can:** Keep things moving without constant review

**Components:**
- `Active/Projects/` structure
- `/project-health` command
- Task linking to projects
- Cracks detector agent

---

### 5. Build Relationships Over Time
**When:** Working with many people
**I want to:** Remember context about each person
**So I can:** Maintain meaningful professional relationships

**Components:**
- `People/` folder (Internal/External)
- Automatic person page updates
- Meeting history tracking
- Related tasks linking

---

### 6. Learn From My Work
**When:** Completing tasks, making mistakes, discovering preferences
**I want to:** Capture lessons and patterns
**So I can:** Improve over time without repeating mistakes

**Components:**
- `Resources/Learnings/` folder
- Working_Preferences.md
- Mistake_Patterns.md
- `/codify` command (coming)

---

## Component to Job Index

| Component | Job 1 | Job 2 | Job 3 | Job 4 | Job 5 | Job 6 |
|-----------|:-----:|:-----:|:-----:|:-----:|:-----:|:-----:|
| `/daily-plan` | ● | | | | | |
| `/triage` | | ● | | | | |
| `/meeting-prep` | ● | | ● | | | |
| `/project-health` | | | | ● | | |
| `/process-meetings` | | ● | ● | | ● | |
| Task MCP | ● | | | ● | | |
| Person pages | | | ● | | ● | |
| Pillars system | ● | | | ● | | |
| Cracks detector | | ● | | ● | | |
| Learnings folder | | | | | | ● |

---

## Job Priority by Role

Different roles emphasize different jobs:

### Product Manager
1. Track Projects (Job 4)
2. Start Day with Clarity (Job 1)
3. Find What I Need (Job 3)

### Sales / Account Executive
1. Build Relationships (Job 5)
2. Find What I Need (Job 3)
3. Capture Everything (Job 2)

### Consultant
1. Build Relationships (Job 5)
2. Track Projects (Job 4)
3. Learn From Work (Job 6)

### Engineering Manager
1. Track Projects (Job 4)
2. Build Relationships (Job 5)
3. Start Day with Clarity (Job 1)

---

## Success Metrics

How to know Dex is working:

| Job | Success Indicator |
|-----|-------------------|
| Start Day | Morning planning < 10 minutes |
| Capture | Zero "forgot to write down" moments |
| Find | Context found in < 30 seconds |
| Projects | No project stalls for > 1 week unknowingly |
| Relationships | No "when did we last talk?" questions |
| Learning | Repeated mistakes decrease |

---

*This document helps prioritize what to build next. If a component doesn't serve a job, question its existence.*
