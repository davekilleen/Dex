---
name: Person Lookup
description: Protocol for finding information about people you know
triggers: [meeting with, last met, who is, person, contact]
---

# Person Lookup Skill

When the user mentions a person's name (e.g., "When did I last meet with Jane Smith?"), follow this lookup protocol.

---

## Lookup Priority Order

### Step 1: Check People Folder FIRST
Search `People/` for their markdown file using glob: `People/**/[Name].md`

Person pages contain:
- Context (company, role, how you met)
- Key topics (recurring themes)
- Recent mentions
- Action items involving them
- Meeting history links

### Step 2: Read the Person Page
The person page is the aggregation point for relationship context. It contains:
- Meeting links
- Recent mentions
- Action items

### Step 3: Only Then Do Broader Searches
If the person page doesn't exist or lacks the info, fall back to:
- Vault-wide search for mentions
- Search in `Inbox/Meetings/` for meeting notes

---

## Example - Correct Approach

```
User: "When is the last meeting I had with Jane Smith?"

1. Search People/ for Jane_Smith.md
2. Read person page for meeting history section
3. Only if needed, do vault-wide search
```

---

## Example - Wrong Approach

```
User: "When is the last meeting I had with Jane Smith?"

❌ Immediately search vault-wide without checking People folder
❌ Skip the People folder aggregation point
```

---

## Adding New People

If a person doesn't exist but should, offer to create their page.

Use the Person_Template from `System/Templates/Person_Template.md` with:
- Name
- Company
- Role
- How you know them
- Folder (Internal or External)

---

## Auto-Update Behavior

When users share significant context about people in conversation:
1. Detect person mentions (role changes, project involvement, etc.)
2. Check for existing page
3. Create or update proactively
4. Cross-reference related person pages

**What counts as significant context:**
- Role or company changes
- Reporting relationships
- Project involvement
- Management style or philosophy
- Key decisions or preferences
- Meeting outcomes or action items

---

## Meeting Integration

When processing meetings:

### Participant Page Updates
For each meeting participant:
1. Check if person page exists in `People/`
2. If exists, add meeting to their Recent Mentions section
3. If they have action items from the meeting, link them
4. Update "Last Interaction" in frontmatter

### Creating New Person Pages
If participant has no page and meets threshold (2+ meetings or explicit request):
1. Create page in appropriate folder (`Internal/` or `External/`)
2. Extract context from meeting notes (company, role if mentioned)
3. Link initial meeting as first Recent Mention
