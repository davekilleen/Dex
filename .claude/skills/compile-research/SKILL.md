---
name: compile-research
description: Compile raw research documents into a structured, cross-linked wiki
context: fork
---

# /compile-research

Reads raw documents from `00-Inbox/Research/`, compiles them into categorized wiki articles in `06-Resources/Wiki/`, and maintains a master index. You rarely touch the wiki directly — it's the LLM's domain.

## Usage

```
/compile-research          # Process all new files in 00-Inbox/Research/
/compile-research --all    # Reprocess everything (including already-processed)
/compile-research --health # Run health check on existing wiki (find gaps, suggest new articles)
/compile-research --ask    # Q&A mode: ask a question against the wiki
```

## Arguments

$MODE: Optional flag (--all, --health, --ask)

---

## Process

### Step 0: Check for files

Scan `00-Inbox/Research/` for `.md` files (excluding `processed/` subfolder).

If no files found and not `--health` or `--ask`:
> "No new files in `00-Inbox/Research/`. Drop markdown files there to get started.
>
> Tip: Use the Obsidian Web Clipper to save articles directly to this folder."

List files found and confirm:
> "Found X files to process:
> - filename.md
> - ...
> Compile these into the wiki?"

---

### Step 1: Read existing wiki state

Read `06-Resources/Wiki/_index.md` to understand:
- What articles already exist
- What topics are already covered
- Last compiled date

Read all existing article files in `06-Resources/Wiki/` to avoid duplicating concepts.

---

### Step 2: Process each raw file

For each file in `00-Inbox/Research/`:

**Extract:**
- Title / topic
- Key concepts and entities mentioned
- Main claims or insights
- Any people, companies, or projects mentioned
- Source URL (if present in frontmatter or content)

**Determine placement:**
- Does a related wiki article already exist? → enrich it
- Is this a new concept? → create a new article
- Does it span multiple concepts? → split into multiple articles

---

### Step 3: Write or update wiki articles

**Article format:**

```markdown
---
title: [Article Title]
topic: [broad category]
sources: [list of source filenames]
last_updated: YYYY-MM-DD
---

# [Article Title]

[2-3 sentence overview of the concept]

## Key Points

- [Point 1]
- [Point 2]
- [Point 3]

## Details

[Deeper explanation, drawing from all sources on this topic]

## Connections

- Related to: [[Article A]], [[Article B]]
- Mentioned in context of: [[Article C]]

## Source Notes

| Source | Key Contribution |
|--------|-----------------|
| [[filename]] | [what this source added] |

---
*Compiled by Dex from [N] source(s). Last updated: YYYY-MM-DD*
```

**Rules:**
- Use `[[WikiLinks]]` for all cross-references between articles
- Use `[[WikiLinks]]` for people and companies (auto-link to person/company pages)
- Keep articles focused — one concept per file
- Article filenames: `Topic_Name.md` (title case, underscores)
- Organise into subdirectories by broad topic: `06-Resources/Wiki/[Topic]/Article.md`
- Never delete existing content — only add and refine

---

### Step 4: Update the master index

Rewrite `06-Resources/Wiki/_index.md`:

```markdown
# Research Wiki

LLM-compiled knowledge base. Do not edit manually — maintained by `/compile-research`.

## Articles

<!-- Auto-maintained by /compile-research. Each entry: [[Article]] — one-line summary -->

### [Category 1]
- [[Article_Name]] — One-line summary
- [[Article_Name]] — One-line summary

### [Category 2]
- [[Article_Name]] — One-line summary

## Stats

- Articles: [N]
- Sources ingested: [N]
- Last compiled: YYYY-MM-DD
```

---

### Step 5: Move processed files

Move each processed file from `00-Inbox/Research/` to `00-Inbox/Research/processed/YYYY-MM-DD_filename.md`

This keeps the inbox clean while preserving raw sources.

---

### Step 6: Run auto-link script

After writing all wiki files, run the auto-link script on the wiki directory:

```bash
node .scripts/auto-link-people.cjs 06-Resources/Wiki/
```

---

### Step 7: Summary

Output:

```
✅ Research compiled

📥 Sources processed: [N]
📄 Articles created: [N]
🔄 Articles updated: [N]
🔗 Cross-links added: [N]

New articles:
- [[Article_A]] (Category)
- [[Article_B]] (Category)

Updated articles:
- [[Article_C]] — added [N] new points from [source]

View your wiki in Obsidian: 06-Resources/Wiki/_index.md
```

Then ask: "Anything you want me to dig deeper on, or shall I suggest some follow-up questions?"

---

## Health Check Mode (--health)

When run with `--health`:

1. Read all articles in `06-Resources/Wiki/`
2. Check for:
   - **Gaps**: Concepts mentioned in articles but not yet their own article
   - **Inconsistencies**: Contradictory claims across articles
   - **Orphans**: Articles with no connections to other articles
   - **Stale sources**: Articles with only 1 source (could benefit from more research)
   - **Missing context**: Articles that reference people/companies without links

3. Output:

```
🔍 Wiki Health Check

📊 Coverage: [N] articles across [N] categories

⚠️  Gaps (concepts not yet covered):
- "[Concept]" — mentioned in [[Article A]], [[Article B]]
- ...

🔗 Orphaned articles (no connections):
- [[Article_X]] — consider linking to [[Article_Y]]

💡 Suggested new articles:
- "[Topic]" — would connect [N] existing articles
- ...

❓ Suggested research questions:
1. [Question based on gaps]
2. [Question based on connections]

Want me to create stub articles for any of these?
```

---

## Q&A Mode (--ask)

When run with `--ask`:

1. Ask: "What do you want to know?"
2. Read `06-Resources/Wiki/_index.md` to understand available coverage
3. Read relevant articles based on the question
4. Synthesise an answer with citations: "According to [[Article_A]] and [[Article_B]]..."
5. Ask: "Want me to save this answer as a new wiki article?"

If yes, save to `06-Resources/Wiki/Queries/YYYY-MM-DD_[topic].md` and update the index.

---

## Notes

- The wiki is the LLM's domain — don't manually edit articles (they'll be overwritten)
- Raw sources in `00-Inbox/Research/processed/` are preserved forever
- Run `/compile-research --health` weekly to keep the wiki sharp
- Drop files from Obsidian Web Clipper, MGit syncs, or manual saves — all work
