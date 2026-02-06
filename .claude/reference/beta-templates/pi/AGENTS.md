# Dex - Personal Knowledge System (Pi Agent Configuration)

You are working in a **Dex vault** - a personal knowledge system for organizing professional life. This file provides the essential context for Pi agents operating in this workspace.

---

## User Profile

**Name:** Not configured
**Role:** Not configured
**Company:** Not configured
**Email Domain:** Not configured

*Configuration stored in: `System/user-profile.yaml`*

---

## Folder Structure (PARA Method)

This vault uses PARA: Projects (time-bound), Areas (ongoing), Resources (reference), Archives (historical).

### Key Paths

| Path | Purpose |
|------|---------|
| `00-Inbox/` | Capture zone for new content |
| `00-Inbox/Meetings/` | Meeting notes landing zone |
| `00-Inbox/Ideas/` | Quick thoughts and ideas |
| `03-Tasks/Tasks.md` | Task backlog (primary task file) |
| `04-Projects/` | Active projects |
| `05-Areas/People/` | Person pages (Internal/ and External/ subfolders) |
| `05-Areas/People/Internal/` | Colleagues (matching email domain) |
| `05-Areas/People/External/` | External contacts (customers, partners) |
| `05-Areas/Companies/` | Company/account pages |
| `05-Areas/Career/` | Career development (optional) |
| `06-Resources/` | Reference materials |
| `07-Archives/` | Completed/historical items |
| `System/` | Configuration files |
| `System/pillars.yaml` | Strategic focus areas |
| `System/user-profile.yaml` | User identity and preferences |

---

## Strategic Pillars

*Pillars are ongoing focus areas (not time-bound goals). Configuration in `System/pillars.yaml`.*

Currently: Not configured

---

## File Conventions

- **Date format:** YYYY-MM-DD
- **Meeting notes:** `YYYY-MM-DD - Meeting Topic.md`
- **Person pages:** `Firstname_Lastname.md`
- **Task IDs:** `^task-YYYYMMDD-XXX` (e.g., `^task-20260128-001`)

---

## Core Behaviors

### Person Lookup
Always check `05-Areas/People/` first when looking for context about someone. Person pages aggregate meeting history, relationships, and action items.

### Task Management
Tasks live in `03-Tasks/Tasks.md`. Each task has a unique ID format: `^task-YYYYMMDD-XXX`

### Meeting Processing
Meeting notes go to `00-Inbox/Meetings/`. Key extractions:
- Action items
- Decisions made
- People mentioned (update/create person pages)
- Related projects

### Writing Style
- Direct and concise
- Bullet points for lists
- Surface important information first

---

## Planning Hierarchy

Pillars (ongoing) -> Quarter Goals (optional) -> Week Priorities -> Daily Plans -> Tasks

- `01-Quarter_Goals/Quarter_Goals.md` - Quarterly objectives (optional)
- `02-Week_Priorities/Week_Priorities.md` - Weekly focus

---

## Reference Documentation

For detailed system information:
- `06-Resources/Dex_System/Dex_System_Guide.md` - Complete usage guide
- `06-Resources/Dex_System/Folder_Structure.md` - Folder details
- `CLAUDE.md` - Full Claude Code configuration

---

## Notes for Pi Agents

1. **Person pages are the knowledge hub** - They connect meetings, projects, and action items
2. **Check existing files first** - Before creating, search for related content
3. **Respect the PARA structure** - Route content to appropriate folders
4. **Use task IDs** - When referencing tasks, use the `^task-YYYYMMDD-XXX` format
5. **Internal vs External** - People are routed by email domain matching
