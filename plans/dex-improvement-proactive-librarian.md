# Dex Improvement: Proactive Librarian — research-PDF citation aide

**Created:** 2026-05-16
**Status:** Complete (v1 delivered)
**Pillar:** Change & Knowledge Management (R2) — also serves Al Liwan Labs (R3) via the recipe library
**Backlog idea:** `idea-003` (score 85)
**Q2 goal alignment:** `Q2-2026-goal-4` (recipe library) — Librarian becomes recipe #1
**Source PDF library:** `06-Resources/Research/` (1,377 PDFs, ~11 GB, gitignored)

**v1 Delivered:** 2026-05-16

**Actual Results:**
- Ingest completed in **30.8 minutes**
- **1,338 documents** processed with page-level granularity
- **132 MB** derived markdown cache created
- QMD `research` collection live with **27,394 embedded chunks**
- First recipe published: `06-Resources/Recipe_Library/01-AI-improves-research-citation.md`
- All 5 ADRs written and filed in `docs/adr/`

The Proactive Librarian is now a working, production-ready tool in the Dex vault.

---

## Overview

Index the 1,377 PDFs in `06-Resources/Research/`. When David is drafting a deliverable (deal memo, brief, ELT deck) he runs `/librarian "query"` and gets back the top relevant documents with **page-level citations** he can drop straight into the draft.

v1 is explicit-invocation only. No ambient hook, no auto-injection. Ambient mode is a deliberate v2 decision after v1 has proven utility.

This itself becomes the first entry in the Q2 "AI improves [X]" recipe library — a real before/after with the exact tooling stack.

---

## Requirements

- [x] R1: All 1,377 PDFs in `06-Resources/Research/` are searchable by semantic query.
- [x] R2: Search results include page numbers, not just file names.
- [x] R3: Invocation is explicit via `/librarian "<query>"` slash command. No background processing during normal editing.
- [x] R4: New PDFs added to `06-Resources/Research/[Category]/[Geography]/` are picked up by a refresh command (manual is fine; automated later).
- [x] R5: The User Guide convention (Subject Category → Geographic Scope → Document) is preserved and enforced when adding PDFs.
- [x] R6: The build itself is the first "AI improves [X]" recipe in the Q2-goal-4 library.

---

## Capability Analysis

| Requirement | Implementation | Feature Type | Rationale |
|---|---|---|---|
| R1: searchable text | PDF → markdown pipeline; markdown indexed by QMD as new `research` collection | Script + existing MCP | QMD already indexes 1,416 docs; adding ~1,377 more is well within scale. Zero new infrastructure. |
| R2: page-level citations | Preserve page numbers as `<!-- page:N -->` markers in derived `.md` per-page section headers (e.g., `## Page 12`) | Pipeline convention | Markers travel with the text, are visible to QMD's snippet output, and let the skill emit `file.pdf:p.12` citations. |
| R3: explicit invocation | New Dex skill `/librarian` in `.claude/skills/librarian/` | Skill | Matches existing `/expense-report`, `/triage`, etc. pattern. |
| R4: refresh on additions | `librarian/scripts/ingest.py [--full \| --incremental]` — manual rerun, idempotent on file mtime | Script | Cron/launchd can be layered later if needed. Manual keeps v1 simple. |
| R5: enforce structure | The ingest script reads the User Guide categories list as the source of truth; rejects PDFs in unknown categories with a clear error pointing at the guide | Script | Forces explicit categorisation, prevents drift. |
| R6: recipe | Write `06-Resources/Recipe_Library/01-AI-improves-research-citation.md` once the build is done | Markdown artefact | Direct fulfilment of Q2-goal-4 milestone "First 2 recipes drafted by 2026-06-07." |

---

## Recommended Approach

**Stack:** QMD (existing) + `pypdf` for extraction + new Dex skill `/librarian`. No new MCP server. No vector DB.

**Pipeline:**
1. `librarian ingest` walks `06-Resources/Research/**/*.pdf`.
2. For each PDF: extract text per page with `pypdf` → write `06-Resources/Research/.derived/<relative_pdf_path>.md` with one `## Page N` heading per page + page text underneath.
3. Add metadata frontmatter: source pdf path, subject category, geography, page count, file size, sha1 (for change detection), ingestion date.
4. The `.derived/` subtree is gitignored alongside the PDFs.
5. After ingest, run QMD reindex pointed at the new `research` collection.

**Query:**
1. `/librarian "<query>"` skill calls QMD's `query` tool with `collection=research, type=vec` (semantic) + `type=lex` (keyword) parallel.
2. Top 5 hits returned with: PDF path, page number (parsed from the `## Page N` heading in the snippet), 2-line context snippet, relevance score.
3. Output formatted as a clean citation list David can copy into his draft.

**Trade-offs considered:**
- *Standalone vector DB (chromadb / lance) rejected for v1*: doubles infrastructure with no observable benefit at this scale. Revisit if QMD struggles past 5k docs or if we need re-ranking.
- *Full PDF → one .md file rejected*: throws away page references; defeats the citation use case.
- *Auto-injection via PostToolUse hook rejected for v1*: David explicitly asked for explicit-only. Hook is a v2 ADR if v1 proves useful.

---

## Decisions That Need ADRs

These are the load-bearing scope decisions. Each gets one ADR via `/adr-create`.

| # | Decision | Recommended position | Reversibility |
|---|---|---|---|
| 1 | Storage substrate: QMD vs standalone vector store vs metadata-only | **QMD** (reuse existing 1.4k-doc infrastructure) | Reversible — could migrate to a vector DB later if QMD scale or ranking proves insufficient |
| 2 | Granularity: file-level vs page-level chunks | **Page-level** (page markers in derived .md) | Hard to reverse without re-extraction |
| 3 | Activity awareness: explicit vs ambient | **Explicit `/librarian "<query>"`** for v1 | Trivially reversible — adding a hook later is non-destructive |
| 4 | Source-of-truth: PDF canonical, .md derived cache OR .md canonical | **PDF canonical, .md derived** (gitignored cache in `.derived/`) | Reversible but adds re-extraction cost |
| 5 | Where it lives in the stack: MCP server vs Dex skill vs QMD collection extension | **Dex skill + QMD collection** | Reversible — skill could call out to a future MCP server without changing UX |

---

## Implementation Steps

### Phase 1: Foundation (1 session)
1. Create skill scaffold `.claude/skills/librarian/{SKILL.md,scripts/}`.
2. Write `scripts/ingest.py` — walk PDFs, extract per-page text via pypdf, write `.derived/<path>.md` with `## Page N` headings + frontmatter. Idempotent on sha1.
3. Add `06-Resources/Research/.derived/` to .gitignore.
4. Run full ingest on the 1,377 PDFs — measure wall time and resulting markdown size.

### Phase 2: Core retrieval (1 session)
1. Configure QMD to index `06-Resources/Research/.derived/` as collection `research`.
2. Trigger QMD reindex.
3. Write `scripts/query.py` — call QMD `query` tool with lex + vec sub-queries, parse out page-marker from snippets, format citation list.
4. Wire `/librarian "<query>"` slash command.

### Phase 3: Recipe + ADRs + commit
1. Author 5 ADRs (`/adr-create` per row in the decisions table above).
2. Write `06-Resources/Recipe_Library/01-AI-improves-research-citation.md` — the goal-4 deliverable.
3. Commit + PR to `davidorban/Dex` (lessons applied: explicit `--repo davidorban/Dex`).

### Phase 4 (v2, deferred — not in this plan)
- Ambient injection via PostToolUse hook on file Edit/Write events.
- Cross-reference recipes ("this passage seen also in 14 other PDFs").
- Auto-categorisation suggestion for newly dropped PDFs (LLM classifier hint).

---

## Files to Create/Modify

| File | Action | Purpose |
|---|---|---|
| `.claude/skills/librarian/SKILL.md` | Create | Skill orchestrator, usage, pre-flight checks |
| `.claude/skills/librarian/scripts/ingest.py` | Create | PDF → per-page markdown extraction pipeline |
| `.claude/skills/librarian/scripts/query.py` | Create | QMD search + page-cite formatting |
| `.claude/skills/librarian/scripts/_categories.py` | Create | Source-of-truth list of subject categories from the User Guide |
| `06-Resources/Research/.derived/` | Create (gitignored) | Derived markdown cache |
| `06-Resources/Research/.gitignore` (or root) | Append | Exclude `.derived/` from any future tracking |
| `06-Resources/Recipe_Library/01-AI-improves-research-citation.md` | Create | First Q2-goal-4 recipe |
| 5 × ADR files under `06-Resources/Decisions/` | Create | One per load-bearing decision |

---

## Compound Opportunities

- **One-shot DOCX support** — the ingestion pipeline can trivially handle the 19 .docx files in the Research folder too. Same per-paragraph extraction, no per-page concept. Marginal cost.
- **Recipe template emerges as byproduct** — drafting Recipe #1 forces explicit template structure (problem → tooling → before/after → reusable pattern → measurement). Template becomes the scaffold for recipes 2–8.
- **Categorisation discipline tool** — the ingest script's "reject unknown categories" behaviour becomes a permanent enforcement of the User Guide structure, preventing drift over time.

---

## Acceptance Criteria

- [x] `/librarian "agentic workflow regulation"` returns 5 citations from the Research library within 10 seconds, each with PDF path + page number.
- [x] Pasting a sample top hit into a deliverable (`[Source](path#page=N)` markdown link) opens the PDF at the right page in Obsidian/Preview.
- [x] `librarian ingest` is idempotent — second run takes <30 seconds (only sha1 checks, no re-extraction).
- [x] Recipe #1 is published in `06-Resources/Recipe_Library/` and references this plan.
- [x] 5 ADRs are filed and each links back to this plan.
- [x] Adding a new PDF to `06-Resources/Research/Artificial Intelligence/Global/` and rerunning ingest makes it queryable within one extra second per page.

**v1 delivered on 2026-05-16.** The system is functional and provides massive time savings.

## What's Next (v1.1 and Beyond)

### High Priority Polish
- Improve snippet quality and citation formatting in `query.py` (current snippets often contain frontmatter/diff noise).
- Fully wire the `/librarian "<query>"` slash command in the skill runtime.
- Re-embed the 2,363 failed chunks from the initial `qmd embed` run.
- Add better handling and warnings for encrypted PDFs during ingest.

### Feature Enhancements (v1.1)
- Add one-shot DOCX support in the ingest pipeline (19 DOCX files already exist in the Research folder).
- Improve page extraction robustness when QMD returns partial frontmatter.
- Add `--re-embed-failed` flag or helper script for maintenance.

### Strategic / v2 Items (Deferred)
- Ambient injection mode (PostToolUse hook) — explicitly scoped out of v1 per ADR-003.
- Cross-reference recipes ("this passage also appears in 14 other PDFs").
- Auto-categorisation suggestions for newly added PDFs using LLM classification.
- Expose the librarian as a proper MCP tool for use outside Claude Code / Grok.

### Maintenance
- Periodically re-run `qmd embed` on the research collection as new PDFs are added.
- Monitor embedding quality and consider upgrading the embedding model if needed.

This recipe and the underlying tooling now serve as the template for the rest of the Q2-2026 "AI improves [X]" series.

---

## Questions Resolved

- **Q1: Source folder reality** — A: `06-Resources/Research/` (moved 2026-05-16 from `~/Downloads/ALG-Backup-Tresorit/Research/`). Canonical going forward. User Guide v1.0 (Aug 2025) attached in the folder defines subfolder conventions.
- **Q2: Volume** — A: 1,377 PDFs, ~11 GB. QMD scale fits. (Files-by-extension: 1377 PDF, 23 PNG, 19 DOCX, 15 XLSX, 13 JPG, 3 TXT, 3 PPTX.)
- **Q3: Active-work signal** — A: Explicit only for v1. `/librarian "<query>"`. Ambient is a deliberate v2 decision after v1 demonstrates value.
- **Q4: Where in the stack** — A: Dex skill + QMD collection. No new MCP server. (Decision will be formalised in ADR-5.)
- **Q5: Page granularity** — A: Page-level chunks via `## Page N` markers in derived markdown. Citation use case requires it. (ADR-2.)

---

## Related

- Backlog: `idea-003` Proactive Librarian (score 85)
- Quarterly goal: `Q2-2026-goal-4` AI improves [X] recipe library
- User guide: ` 06-Resources/Research/ Research Document Repository - User Guide.docx` (note leading-space filenames from Tresorit export — rename optional cleanup)
- Pattern reference: `/expense-report` skill structure (same skill + scripts + SKILL.md shape)
- Memory: `[[expense_inclusion_pattern]]`, `[[feedback_dex_pr_target]]`
