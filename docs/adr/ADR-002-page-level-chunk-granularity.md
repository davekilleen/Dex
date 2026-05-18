# ADR-002: Chunk granularity — page-level via markdown page markers

- **Status**: accepted
- **Date**: 2026-05-16
- **Implemented**: 2026-05-18 (commit 9d2e28c on `feat/proactive-librarian-hardening`)
- **Deciders**: David Orban
- **Tags**: librarian, retrieval, granularity

## Context

The Proactive Librarian's core value proposition is **citation with page references**. The query "find me passages on X that I can cite in this draft" is materially different from "find me PDFs about X". The first requires page-level granularity; the second is satisfied by file-level.

Three granularities considered:

1. **File-level** — one document per PDF in the index. Returns file matches, no page info.
2. **Page-level** — one document per page. Returns `(file, page)` matches usable for citation.
3. **Paragraph/semantic-chunk level** — splits within pages on semantic boundaries (~512-token chunks). Better retrieval precision but loses cleanly-cite-able physical-document references.

PDFs are physical artefacts. Citations in deliverables historically reference page numbers, not paragraph IDs. Paragraph-level chunking would force a re-derivation step ("which page is this on?") on every hit.

## Decision

Index **at page granularity** via markdown page markers in the derived `.md` files.

Convention: each derived markdown file contains `## Page N` headings, with the page's extracted text underneath. QMD indexes these as part of the document; result snippets include the `## Page N` heading or nearby text, which the Librarian skill parses to emit `path/to/file.pdf:p.N` citations.

Implementation detail: if a page contains so much text that it exceeds QMD's chunking window, QMD's own internal sub-chunking still operates within the page — the `## Page N` marker remains the structural unit.

## Consequences

### Positive
- Citations are physical and unambiguous (`Brief_Stablecoins.pdf:p.12`).
- Pasting `[Source](path#page=12)` into a markdown deliverable opens the PDF at the right page in Obsidian/Preview/most PDF viewers.
- Recall is preserved — semantic search still matches; granularity decision affects what's *returned*, not what's *searched*.

### Negative
- Index size scales with page count, not file count. ~50k–70k page-units for 1.4k PDFs is well within QMD's range but is roughly 50× the file-level alternative.
- Extraction pipeline must preserve page boundaries (uses `pypdf`'s per-page iteration — standard).
- For very short PDFs (1–3 pages) the page-level concept adds no value over file-level but costs nothing either.

### Neutral
- Page-marker convention (`## Page N`) becomes a load-bearing contract between the ingest pipeline and the query skill. Documented in the plan and in `ingest.py`.

## Links

- Plan: [`plans/dex-improvement-proactive-librarian.md`](../../plans/dex-improvement-proactive-librarian.md)
- Related ADRs: [ADR-001](ADR-001-storage-substrate-qmd-for-proactive-librarian.md) (storage), [ADR-004](ADR-004-pdf-canonical-derived-markdown-cache.md) (derived cache)
