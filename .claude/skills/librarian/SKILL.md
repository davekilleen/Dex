---
name: librarian
description: Proactive research librarian. Ingests the 1,377 PDFs in 06-Resources/Research/ into a QMD-indexable per-page markdown cache and (in v2) will answer citation queries with page numbers.
model_hint: standard
---

**Phase 1 status (Foundation — complete):** The PDF → `.derived/` per-page markdown ingest pipeline is fully implemented and tested.

## Current Commands (Phase 1)

```bash
# 1. Create/repair the dedicated venv (one time)
python3 -m venv /tmp/librarian-venv
source /tmp/librarian-venv/bin/activate
pip install pypdf python-frontmatter tqdm cryptography

# 2. Run the ingest (idempotent, safe to re-run)
source /tmp/librarian-venv/bin/activate
python /Users/davidorban/Dev/Dex/.claude/skills/librarian/scripts/ingest.py --help
python .../ingest.py --dry-run --limit 10          # safe testing
python .../ingest.py --verbose                     # real run (first time = 30-60 min)
```

See the full implementation log and design rationale:
`docs/proactive-librarian/Phase-1-Foundation-Execution-Log.md`

## What the Ingest Produces

- `06-Resources/Research/.derived/<Subject>/<Geography>/<Document>.md`
- Each file has YAML frontmatter (source_pdf, subject, geography, page_count, sha1, ingested_at, derived_version)
- Page-level sections using the exact contract `## Page N` (required for later citation parsing)

## Phase 2 (Core retrieval — complete)

The retrieval engine is now functional.

### Usage

```bash
# Direct usage (recommended while we finalize the slash command)
source /tmp/librarian-venv/bin/activate
python .claude/skills/librarian/scripts/query.py "stablecoin regulation in the UAE" --limit 5

# Or with JSON output for scripting
python .claude/skills/librarian/scripts/query.py "agentic AI in financial services" --json
```

The command returns clean citations with page numbers that you can paste directly into documents.

**Note:** Full `/librarian "query"` slash command support will be added in the next iteration (it will simply call the above script).

## References

- Master plan: `plans/dex-improvement-proactive-librarian.md`
- 5 ADRs: `docs/adr/ADR-00{1-5}*.md`
- Execution log (mandatory reading for reviewers): `docs/proactive-librarian/Phase-1-Foundation-Execution-Log.md`

**This skill follows the exact expense-report shape** (dedicated venv, pre-flight in docs, heavy scripts, memory links).
