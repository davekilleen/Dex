# Dex System Improvement Backlog

*Last ranked: 2026-01-28 (Initial setup)*

Welcome to your Dex system improvement backlog! This file tracks ideas for making Dex better.

## How It Works

1. **Capture ideas** anytime using the `capture_idea` MCP tool
2. **Review regularly** with `/dex-backlog` to see AI-ranked priorities
3. **Workshop ideas** by running `/dex-improve [idea title]`
4. **Mark implemented** when you build an idea

Ideas are automatically ranked on 5 dimensions:
- **Impact** (35%) - How much would this improve your daily workflow?
- **Alignment** (20%) - Does it fit how you actually use the system?
- **Token Efficiency** (20%) - Does it reduce how much Cursor needs to read? (Faster responses, lower costs)
- **Memory & Learning** (15%) - Does the system get smarter over time from this?
- **Proactivity** (10%) - Does this help Cursor anticipate your needs?

**What "Cursor Feasibility" Means:**
Ideas must work with what Cursor can actually do - reading/writing files, running commands, and using MCP tools. Ideas that require tracking your edits in real-time or hooking into Cursor's internals won't work, so they get scored 0.

*Don't worry about how hard something is to build - with AI coding, that's the easy part. Focus on ideas that would genuinely help your workflow!*

---

## Quick Start

**Your backlog comes pre-populated with a couple of ideas to show you how this works.** These aren't just examples - they're real, valid improvements that could genuinely help your workflow.

Want to try one? Just say:
- "Hey Claude, can you implement idea 001 please?"
- "I like idea 002, let's build it"
- "Run `/dex-improve` for idea 001"

The ideas below demonstrate the level of detail you'll see when you capture your own. Notice how each explains the problem, the solution, how it works in Cursor, and the real-world benefit.

---

## Priority Queue

<!-- Auto-ranked by /dex-backlog command -->

### 🔥 High Priority (Score: 85+)

- **[idea-001]** Save meeting summaries so I don't re-read entire notes every time

  **The Problem:** 
  Right now, when you're preparing for a follow-up meeting, Cursor has to re-read your entire meeting notes from scratch. If you had 3 meetings with Sarah last quarter, that's reading thousands of words just to remember "What did we decide last time?"
  
  **The Solution:**
  Create a separate folder (`06-Resources/Meeting_Cache/`) that stores short, structured summaries of each meeting:
  - Who attended
  - Key decisions made
  - Action items assigned
  - Important topics discussed
  
  **How It Works in Cursor:**
  ✅ Totally doable! When you run `/process-meetings` or create a meeting note, Cursor:
  1. Reads the new meeting note (one file)
  2. Extracts the key information above
  3. Saves a short summary file in the cache folder
  4. Next time you need meeting context, reads the small summary instead of the full notes
  
  **The Benefit:**
  Instead of reading 2,000 words of meeting notes, Cursor reads 200 words of summaries. That's 90% less to process, which means faster responses and you stay under usage limits.
  
  **Real Example:**
  - Before: "Prepare for my 1:1 with Sarah" → Reads 3 full meeting notes (3,000 words)
  - After: "Prepare for my 1:1 with Sarah" → Reads cached summaries (300 words), only reads full notes if you ask for specific details
  
  - **Score:** 92 (Impact: 95, Alignment: 85, Token: 95, Memory: 90, Proactive: 85)
  - **Category:** knowledge
  - **Captured:** 2026-01-28

### ⚡ Medium Priority (Score: 60-84)

- **[idea-002]** Quick-reference directory of people so Cursor doesn't read every person page

  **The Problem:**
  You have person pages for everyone you work with (managers, colleagues, customers). When you ask "Who's my contact at Acme Corp?" Cursor currently has to open and read every person page file to find the answer. If you have 30 person pages, that's a lot of unnecessary reading.
  
  **The Solution:**
  Create one lightweight "directory" file (`System/People_Index.json`) that lists basic info about everyone:
  ```
  Sarah Johnson → Internal, Engineering Manager, last met 2026-01-25
  Mike Chen → External, Acme Corp, Product Lead, last met 2026-01-20
  ```
  
  **How It Works in Cursor:**
  ✅ Totally doable! Here's how:
  1. When you create or update a person page, Cursor quickly scans it
  2. Extracts just the basics: name, company, role, last interaction
  3. Adds or updates that one entry in the directory file
  4. When you ask "Who do I know at Acme Corp?", Cursor checks the directory first (one small file)
  5. Only opens full person pages when you need detailed context
  
  **The Benefit:**
  Simple lookups become instant. Instead of reading 30 full person pages (15,000 words), Cursor reads one directory file (500 words). That's 97% less to process for common questions.
  
  **Real Example:**
  - Before: "Who did I meet with last week?" → Opens and reads all 30 person pages
  - After: "Who did I meet with last week?" → Reads directory, finds 3 names, only opens those 3 person pages if you need details
  
  - **Score:** 78 (Impact: 75, Alignment: 80, Token: 90, Memory: 70, Proactive: 65)
  - **Category:** system
  - **Captured:** 2026-01-28

### 💡 Low Priority (Score: <60)

*Example ideas provided above to show the level of detail and clarity expected.*

**When you capture your own ideas, explain:**
- What problem you're trying to solve (be specific!)
- What you imagine the solution looking like
- Why it would help your workflow
- Any specific examples or use cases you have in mind

*The AI will handle the technical details and feasibility assessment - you focus on describing the problem clearly!*

---

## Archive (Implemented)

*Implemented ideas will appear here with completion dates.*

---

*Run `/dex-backlog` to re-rank ideas based on current system state.* 