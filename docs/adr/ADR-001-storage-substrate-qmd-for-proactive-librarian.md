# ADR-001: Storage substrate for Proactive Librarian — reuse QMD

- **Status**: accepted
- **Date**: 2026-05-16
- **Implemented**: 2026-05-18 (commit 9d2e28c on `feat/proactive-librarian-hardening`)
- **Deciders**: David Orban
- **Tags**: librarian, retrieval, qmd

## Context

The Proactive Librarian needs a way to index and search 1,377 PDFs (~11 GB) sitting in `06-Resources/Research/`. Three substrates were considered:

1. **QMD** — the local search engine already indexing 1,416 docs across 10 collections in the Dex vault (lex BM25 + vec semantic + hyde hypothetical-doc search). Provided by `mcp__qmd-mcp__*`.
2. **Standalone vector store** — a new component (e.g., chromadb, lance, lancedb, or pgvector) dedicated to research PDFs.
3. **Metadata-only index** — extract title/topics/date into a JSON/SQLite catalog; rely on filename + frontmatter search; no full-text vectors.

Scale: ~1,400 PDFs, average ~30–50 pages each → roughly 50k–70k page-level chunks. QMD's current corpus is comparable (1,416 docs). Standalone vector stores typically shine past 100k–1M chunks; below that the operational overhead outweighs the benefit.

The Librarian's core query pattern is "find PDFs relevant to what I'm drafting" — semantic similarity, not structured lookup. Metadata-only fails this immediately.

## Decision

Use **QMD** as the storage and retrieval substrate. Add a new `research` collection pointed at `06-Resources/Research/.derived/` (the per-page-extracted markdown cache). No new infrastructure.

The Librarian skill queries QMD via the existing `mcp__qmd-mcp__query` tool with `collection=research`, running parallel `lex` (BM25) + `vec` (semantic) sub-queries and merging results.

## Consequences

### Positive
- Zero new infrastructure to operate, monitor, or back up.
- Existing daily reindex cron picks up the new collection automatically.
- Same query syntax as every other Dex retrieval use case — no second mental model.
- Free hybrid lex+vec retrieval; QMD already does both.
- Reversible: if QMD scale or ranking proves insufficient we can layer a vector DB later behind the same skill surface.

### Negative
- No custom re-ranking or specialised retrieval pipeline (e.g., HyDE-then-rerank). QMD does support `type='hyde'` but no cross-encoder rerank step.
- One global QMD instance — heavy ingest of 50k+ research chunks could affect query latency for other collections during the reindex window.
- No first-class page-level retrieval semantics; page numbers travel as markdown markers and must be parsed back out from snippets (see ADR-002).

### Neutral
- Couples the Librarian to QMD's API surface. Future migration to a vector DB would mean rewriting the query path but keeping the skill UX intact.

## Links

- Plan: [`plans/dex-improvement-proactive-librarian.md`](../../plans/dex-improvement-proactive-librarian.md)
- Backlog: idea-003 Proactive Librarian
- Related ADRs: [ADR-002](ADR-002-page-level-chunk-granularity.md) (granularity), [ADR-004](ADR-004-pdf-canonical-derived-markdown-cache.md) (source of truth), [ADR-005](ADR-005-dex-skill-plus-qmd-collection-no-new-mcp.md) (stack placement)
