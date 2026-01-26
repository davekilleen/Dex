# Triage

Process and organize your inbox - both files and tasks - with awareness of your existing structure.

## Usage

- `/triage` - Process everything (files + tasks)
- `/triage files` - Organize files in Inbox folder
- `/triage tasks` - Extract and route tasks from notes

## Arguments

$MODE: Optional. "files" | "tasks" | "all". Default: "all"

---

---

## Demo Mode Check

Before executing, check if demo mode is active:

1. Read `System/user-profile.yaml` and check `demo_mode`
2. **If `demo_mode: true`:**
   - Display: "Demo Mode Active — Using sample data"
   - Use `System/Demo/` paths instead of root paths
   - Write any output to `System/Demo/` subdirectories
3. **If `demo_mode: false`:** Use normal vault paths


## Step 0: Structure Discovery

Before processing inbox items, build an index of existing entities. This makes triage aware of your actual folder structure and lets it route items to specific destinations.

### 1. Scan Projects

List all files in `Active/Projects/`:
- Extract project name from filename (convert underscores to spaces)
- Read frontmatter if present for description, status, pillar
- Build index: `{ name, path, description, status, pillar }`

### 2. Scan People

List all files in `People/External/` and `People/Internal/`:
- Extract name from filename
- Read frontmatter/metadata table for role, company
- Build index: `{ name, path, company, role, type: internal|external }`

### 3. Scan Relationships/Companies

List all files in `Active/Relationships/` (including subdirectories like `Companies/`):
- Extract account/company name from filename
- Read domains field if present
- Build index: `{ name, path, domains, contacts }`

### 4. Read Pillars

Parse `System/pillars.yaml`:
- Extract pillar names, descriptions, and keywords
- These inform categorization when no entity match is found

### 5. Scan Custom Folders

List any additional folders under `Active/` that aren't Projects, Relationships, or Content:
- These may be role-specific folders created during setup
- Include them as potential routing destinations

---

## Mode: Files

Organize notes in the `Inbox/` folder by suggesting where they belong.

### Process

1. **Scan Inbox/**
   - List all files (exclude Week Priorities.md, README.md)
   - Read each file's content

2. **Match Against Discovered Entities**

   For each inbox file, check in this order:

   | Check | Match Criteria | Action |
   |-------|---------------|--------|
   | **Project match** | File mentions project name, or filename contains project reference | Route to specific project file |
   | **Person match** | File is about a specific person, contains their name prominently | Route to person page OR suggest linking |
   | **Company/Account match** | File mentions company name, or attendees from known domain | Route to company page OR relationship folder |
   | **Pillar keyword match** | Content matches pillar keywords | Tag with pillar, suggest relevant category |
   | **No entity match** | None of the above | Fall back to category routing |

3. **Category Fallback Rules**

   When no specific entity matches, use these rules:

   | Destination | Criteria |
   |-------------|----------|
   | `Active/Projects/` | Has deadline, specific outcome, time-bound |
   | `Active/Relationships/` | Account or stakeholder related |
   | `Active/Content/` | Thought leadership, articles, presentations |
   | `Resources/` | Reference material, knowledge, learnings |
   | `People/` | Person-specific information |
   | Archive | Old/completed, no longer active |
   | Delete | No value, redundant, or temporary |

4. **Present Suggestions with Entity Context**

   Show what was matched:

   ```
   File: [filename]
   Match: [entity type] → [specific entity name]
   Destination: [exact path]
   Confidence: [high/medium/low]
   Action: [suggested action]
   ```

5. **Execute with Confirmation**
   - Show full plan
   - Wait for user approval
   - Move files using `mv` (not copy)
   - For merges, append content to existing file

---

## Mode: Tasks

Extract uncompleted tasks from notes and route them appropriately.

### Process

1. **Scan Sources**
   - `Inbox/Meetings/*.md` - Meeting action items
   - `Inbox/*.md` - Captured tasks
   - Any file with unchecked tasks `- [ ]`

2. **Extract Tasks**
   - Find all `- [ ]` items
   - Note the source file for each
   - Extract any mentioned names, projects, companies

3. **Match Tasks to Entities**

   For each task:
   - Check if it mentions a known project → suggest adding to that project
   - Check if it mentions a known person → suggest linking to person page
   - Check if it mentions a known company → suggest linking to company

4. **Deduplication Check**

   For each task, check against:
   - `Inbox/Week Priorities.md`
   - `Tasks.md`

   Flag items with >60% similarity to existing tasks.

5. **Ambiguity Detection**

   Flag tasks that are:
   - Less than 3 words
   - Match vague patterns (e.g., "fix bug", "follow up", "research X")

   Generate clarification questions for ambiguous items.

6. **Present Results**

   **Ready to Route** (clear, non-duplicate items):
   - Show suggested destination with entity context
   - Show pillar if detectable
   - Show any linked entities

   **Potential Duplicates** (>60% similarity):
   - Show the existing task it matches
   - Ask: Skip / Merge / Keep Both

   **Needs Clarification** (ambiguous):
   - Show the issue
   - Ask clarifying questions
   - Wait for user input

7. **Route with Confirmation**
   - To Week Priorities: Add to `Inbox/Week Priorities.md`
   - To Project: Add to relevant project file
   - To Person: Add to person page's action items
   - Skip: Don't process
   - Defer: Leave for later

---

## Mode: All (Default)

Run both files and tasks modes in sequence:
1. First, run structure discovery (once)
2. Organize files
3. Extract and route tasks

---

## Example Output

```
📬 Triage Report

=== STRUCTURE DISCOVERED ===
• 4 projects found in Active/Projects/
• 12 people found in People/
• 3 companies found in Active/Relationships/Companies/
• 3 pillars configured

=== FILES (3 items) ===

1. "Q1 Mobile App Notes.md"
   Match: PROJECT → "Mobile App Launch"
   Destination: Active/Projects/Mobile_App_Launch.md
   Confidence: HIGH (exact name match)
   Action: Merge into existing project? / Keep separate?

2. "Call with Sarah.md"
   Match: PERSON → "Sarah Chen"
   Destination: People/External/Sarah_Chen.md
   Confidence: HIGH (name in filename)
   Action: Add to meeting history? / Keep as separate note?

3. "Random product ideas.md"
   Match: PILLAR → "Product Development" (keyword match)
   Destination: Active/Content/ (no specific entity)
   Confidence: MEDIUM
   Action: Move to Content?

4. "Old project notes.md"
   Match: None
   Destination: Archive (last modified 60 days ago, no open tasks)
   Action: Archive?

=== TASKS (5 items) ===

✅ READY TO ROUTE (3):
1. "Follow up with Sarah about Q1 budget"
   → Week Priorities
   Links: People/External/Sarah_Chen.md

2. "Prep slides for conference"
   → Week Priorities
   Pillar: Thought Leadership

3. "Review competitor analysis for Acme deal"
   → Active/Projects/Acme_Deal.md (project match)
   Links: Active/Relationships/Companies/Acme_Corp.md

⚠️ POTENTIAL DUPLICATE (1):
4. "Contact Tom about implementation"
   → 78% match with "Reach out to Tom" in Week Priorities
   [s]kip / [m]erge / [k]eep both?

❓ NEEDS CLARIFICATION (1):
5. "Fix the bug"
   - Too vague. Which bug? What system?

---
Proceed with ready items? [y/n]
```

---

## How Structure Discovery Evolves

Because discovery happens at runtime:
- **New projects** are automatically recognized in the next triage
- **New people pages** become available for matching
- **New companies** get detected
- **Custom folders** you add are included as destinations

No configuration needed - triage adapts as your structure grows.

---

## Notes

- Never auto-route without confirmation
- Duplicates require explicit decision
- Ambiguous items block until clarified
- Use `mv` not `cp` when moving files
- Entity matches show confidence level (high/medium/low)
- Multiple entity matches are shown for user to choose
