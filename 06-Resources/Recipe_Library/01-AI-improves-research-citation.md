# Recipe: AI Improves Research Citation — Proactive Librarian

**Date:** 2026-05-16  
**Author:** David Orban  
**Pillar:** Change & Knowledge Management (R2) + Al Liwan Labs (R3)  
**Goal Alignment:** Q2-2026 Goal 4 — "AI improves [X]" recipe library (Recipe #1)

---

## The Problem (Before)

When writing memos, briefs, decks, or strategy documents, I frequently needed to cite research PDFs from my library of 1,377 documents (~11 GB) in `06-Resources/Research/`.

**Previous workflow:**
- Manually search folder names and file names (very slow)
- Open PDFs one by one and use Ctrl+F
- Often couldn't remember which report contained the specific data point
- No reliable way to get **page-level citations** quickly
- Result: Either weak citations or hours wasted digging through reports

This was a classic high-friction, low-leverage task that happened repeatedly.

---

## The Solution (After)

I built the **Proactive Librarian** — a Dex skill that lets me run:

```bash
/librarian "stablecoin regulation in emerging markets"
```

And get back the top relevant passages with **precise page citations** I can paste directly into my document.

**New workflow:**
1. Type a natural language query in any context
2. Get ranked results with `File.pdf:p.XX` citations
3. Paste the citation + excerpt into my deliverable
4. Click the link in Obsidian/Preview to jump straight to the page

Time to get good citations: **under 30 seconds** instead of 20–60+ minutes.

---

## Tools & Stack Used

| Layer | Tool | Purpose |
|-------|------|---------|
| **Ingestion** | `pypdf` + custom Python pipeline | Per-page text extraction with `## Page N` markers |
| **Storage** | QMD (local hybrid search) | BM25 + vector search over 27k+ chunks |
| **Interface** | Dex skill (`/librarian`) | Simple slash command surface |
| **Architecture** | No new MCP server | Reused existing QMD + Dex skill pattern |

**Key design decisions** (documented in ADRs):
- PDF is canonical; derived markdown is a reproducible cache
- Page-level granularity (not paragraph or file-level)
- Explicit invocation only (v1)
- QMD as the retrieval substrate (no new vector database)

---

## How to Replicate This Pattern

This recipe is now reusable for any large document collection.

### 1. Ingest Pipeline Pattern
- Walk source files (PDFs, DOCX, etc.)
- Extract with structure preservation (page numbers, sections)
- Write derived markdown with consistent markers (`## Page N`)
- Store rich frontmatter (source, category, sha1, etc.)
- Make it idempotent on content hash

### 2. Retrieval Layer Pattern
- Add a dedicated QMD collection pointed at the derived folder
- Use hybrid queries (`lex:` + `vec:`) for best results
- Parse structural markers from results to surface citations

### 3. Interface Pattern
- Expose via a simple Dex skill (`/librarian "query"`)
- Return clean, copy-pasteable output with citations
- Follow the existing expense-report / triage skill shape

---

## Results & Measurement

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Time to find relevant passages | 20–90 min | < 30 sec | **40–180x faster** |
| Quality of citations | Often vague or missing | Precise (`File.pdf:p.12`) | Dramatically better |
| Friction to cite research | High (avoided when possible) | Low (now default behavior) | Behavioral shift |
| Derived cache size | N/A | 132 MB | Highly efficient |

**Qualitative wins:**
- I now cite research *more often* because it's easy
- Citations are more credible (specific pages instead of "in a McKinsey report")
- The system surfaces reports I had forgotten existed

---

## Reusable Template

This pattern ("AI improves research citation") can be applied to:

- Legal document libraries
- Academic paper collections
- Internal company research repositories
- Policy and regulatory document sets

**Core reusable components:**
- Per-page (or per-section) markdown extraction with structural markers
- Dedicated QMD collection + hybrid search
- Simple skill interface returning citable excerpts

---

## Lessons Learned

1. **Page-level granularity was the right call** — file-level search would have been much less useful.
2. **Real data is messy** — encrypted PDFs, poor text extraction, and weird folder naming were bigger issues than the AI components.
3. **The recipe template is powerful** — forcing myself to document this as a reusable pattern made the work more valuable than a one-off tool.
4. **QMD was the correct substrate** — adding a new vector database would have added unnecessary complexity for this scale.

---

## References

- Master Plan: `plans/dex-improvement-proactive-librarian.md`
- ADRs: `docs/adr/ADR-001` through `ADR-005`
- Implementation Log: `docs/proactive-librarian/Phase-1-Foundation-Execution-Log.md`
- Scripts: `.claude/skills/librarian/scripts/`

**This is Recipe #1 in the Q2-2026 "AI improves [X]" series.**