#!/usr/bin/env python3
"""
ingest.py — PDF → per-page markdown extraction pipeline for the Proactive Librarian.

Phase 1 of the Proactive Librarian (idea-003 / Q2-2026-goal-4 recipe library).

This script walks the entire 06-Resources/Research/ tree, extracts text page-by-page
using pypdf, writes a reproducible .derived/ cache, and records rich frontmatter
so that QMD (ADR-001) can later index the collection with page-level citation
support (ADR-002).

Design goals (documented for Claude + code-reviewer):
- Idempotent on file content (sha1). Re-running the script is cheap after the
  first full pass.
- Atomic writes: never leave a half-written .md file.
- Loud, actionable failures on taxonomy violations (via _categories.py).
- Excellent progress / resume UX for a 30-60 minute first run.
- Zero side-effects on the canonical PDFs themselves (ADR-004).
- Follows the exact skill shape and venv pattern of expense-report/.

Usage (after venv is ready — see SKILL.md):
    source /tmp/librarian-venv/bin/activate
    python .../librarian/scripts/ingest.py --help
    python .../librarian/scripts/ingest.py --dry-run --limit 10
    python .../librarian/scripts/ingest.py --incremental   # default
    python .../librarian/scripts/ingest.py --full          # force re-extract everything

The .derived/ directory is created as a sibling of the PDF tree:
    06-Resources/Research/.derived/Artificial Intelligence/General/Report.md

Each output file contains:
    ---
    source_pdf: "..."
    subject: "..."
    geography: "..."
    page_count: N
    sha1: "..."
    ingested_at: "..."
    derived_version: 1
    ---

    ## Page 1

    [text]

    ## Page 2

    [text]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import frontmatter
    from pypdf import PdfReader
    from tqdm import tqdm
except ImportError as e:
    print(
        "Missing dependency. Please run the pre-flight from SKILL.md:\n"
        "  python3 -m venv /tmp/librarian-venv\n"
        "  source /tmp/librarian-venv/bin/activate\n"
        "  pip install pypdf python-frontmatter tqdm\n"
        f"\nOriginal error: {e}"
    )
    sys.exit(1)

# Local module (same directory)
from _categories import (
    derive_subject_geography,
    validate_subject_or_raise,
)

# =============================================================================
# CONSTANTS
# =============================================================================

RESEARCH_ROOT = Path("/Users/davidorban/Dev/Dex/06-Resources/Research")
DERIVED_ROOT = RESEARCH_ROOT / ".derived"
DERIVED_VERSION = 1

# We write a small sidecar next to each derived file so that even if the .md
# is opened in Obsidian the original sha1 is still machine-readable without
# parsing frontmatter every time. (Optional future optimisation.)
SHA1_SIDECAR_SUFFIX = ".sha1"


def compute_sha1(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Streaming SHA-1 of a (potentially large) PDF. Never loads whole file."""
    h = hashlib.sha1()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def get_derived_path(pdf_path: Path) -> Path:
    """Map 06-Resources/Research/Foo/Bar.pdf → .derived/Foo/Bar.md"""
    rel = pdf_path.relative_to(RESEARCH_ROOT)
    return DERIVED_ROOT / rel.with_suffix(".md")


def extract_page_text(page) -> str:
    """Robust page text extraction with graceful degradation."""
    try:
        text = page.extract_text() or ""
    except Exception as exc:
        # Some PDFs have weird page objects; we still want to continue.
        text = f"[pypdf extraction failed: {exc}]"
    return text.strip()


def build_frontmatter(
    source_pdf: Path,
    subject: str,
    geography: Optional[str],
    page_count: int,
    file_size: int,
    sha1: str,
) -> dict:
    """Return the exact frontmatter schema agreed in ADR-004 + Phase 1 design."""
    return {
        "source_pdf": str(source_pdf.relative_to(RESEARCH_ROOT)),
        "subject": subject,
        "geography": geography or "General",
        "page_count": page_count,
        "file_size_bytes": file_size,
        "sha1": sha1,
        "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "derived_version": DERIVED_VERSION,
    }


def write_derived_markdown(
    pdf_path: Path,
    subject: str,
    geography: Optional[str],
    sha1: str,
    force: bool = False,
) -> tuple[bool, str]:
    """
    Core workhorse. Returns (did_write, reason).

    The function is deliberately side-effect free except for the atomic write.
    """
    derived_path = get_derived_path(pdf_path)
    derived_path.parent.mkdir(parents=True, exist_ok=True)

    # Idempotency check (the heart of "cheap re-runs")
    if not force and derived_path.exists():
        try:
            existing = frontmatter.load(derived_path)
            if existing.get("sha1") == sha1:
                return False, "sha1-match (idempotent skip)"
        except Exception:
            # Corrupt or unreadable frontmatter → treat as "needs rebuild"
            pass

    # Perform the actual extraction
    try:
        reader = PdfReader(str(pdf_path))
        page_count = len(reader.pages)
    except Exception as exc:
        return False, f"pypdf open failed: {exc}"

    file_size = pdf_path.stat().st_size

    # Build the frontmatter + page content
    post = frontmatter.Post("", **build_frontmatter(
        pdf_path, subject, geography, page_count, file_size, sha1
    ))
    content = frontmatter.dumps(post)

    # Append the page-level sections (ADR-002 contract)
    content += "\n\n"

    for i, page in enumerate(reader.pages, start=1):
        text = extract_page_text(page)
        content += f"## Page {i}\n\n{text}\n\n"

    # Atomic write (critical for long-running job)
    tmp_path = derived_path.with_suffix(".md.tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(derived_path)  # atomic on POSIX + most Windows
    except Exception as exc:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        return False, f"atomic write failed: {exc}"

    return True, f"extracted {page_count} pages"


def should_process(pdf_path: Path, args) -> bool:
    """Apply --limit, category filter, etc."""
    if args.limit and args.limit > 0:
        # Simple counter is handled by the caller
        pass
    if args.category:
        subject, _ = derive_subject_geography(pdf_path)
        if subject != args.category:
            return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Proactive Librarian PDF ingest (Phase 1 foundation)"
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Ignore existing sha1 cache and re-extract every PDF"
    )
    parser.add_argument(
        "--incremental", action="store_true", default=True,
        help="Default mode: only process PDFs whose sha1 changed or are new (default)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Walk, validate taxonomy, compute sha1s, but do NOT write any .md files"
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Process at most N PDFs (excellent for testing on Uncategorised)"
    )
    parser.add_argument(
        "--category", type=str, default=None,
        help="Only process PDFs under this exact top-level subject (e.g. 'Cryptocurrency')"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print every file decision (very noisy on full run)"
    )

    args = parser.parse_args()

    if not RESEARCH_ROOT.exists():
        print(f"FATAL: Research root does not exist: {RESEARCH_ROOT}")
        sys.exit(2)

    DERIVED_ROOT.mkdir(exist_ok=True)

    # Collect all PDFs first (so we can give a total count to tqdm)
    print("Scanning for PDFs under 06-Resources/Research/ ...")
    all_pdfs = sorted(RESEARCH_ROOT.rglob("*.pdf"))
    print(f"Found {len(all_pdfs)} PDF files.")

    # Filter according to CLI
    to_process = [p for p in all_pdfs if should_process(p, args)]

    if args.limit and args.limit > 0:
        to_process = to_process[: args.limit]
        print(f"Limited to first {len(to_process)} PDFs for this run.")

    if not to_process:
        print("Nothing to do after filters.")
        return

    print(f"Mode: {'FULL (force re-extract)' if args.full else 'INCREMENTAL (sha1 cache)'}")
    if args.dry_run:
        print("*** DRY RUN — no files will be written ***")

    start = time.time()
    stats = {"processed": 0, "skipped": 0, "errors": 0, "pages": 0}

    iterator = tqdm(to_process, desc="Ingesting PDFs", unit="pdf")

    for pdf_path in iterator:
        subject, geography = derive_subject_geography(pdf_path)

        try:
            validate_subject_or_raise(subject)
        except ValueError as ve:
            stats["errors"] += 1
            tqdm.write(f"ERROR: {ve}")
            continue

        sha1 = compute_sha1(pdf_path)

        if args.dry_run:
            stats["processed"] += 1
            if args.verbose:
                tqdm.write(f"DRY: would process {pdf_path.relative_to(RESEARCH_ROOT)} "
                           f"(subject={subject}, geo={geography}, sha1={sha1[:8]})")
            continue

        did_write, reason = write_derived_markdown(
            pdf_path, subject, geography, sha1, force=args.full
        )

        if did_write:
            stats["processed"] += 1
            # We don't know exact page count here without re-opening, but the
            # write function already did the work. For progress we just count files.
        else:
            if "sha1-match" in reason:
                stats["skipped"] += 1
            else:
                stats["errors"] += 1
                tqdm.write(f"ERROR on {pdf_path.name}: {reason}")

    elapsed = time.time() - start

    print("\n" + "=" * 60)
    print("INGEST COMPLETE")
    print(f"  PDFs processed (new or updated): {stats['processed']}")
    print(f"  PDFs skipped (sha1 match):        {stats['skipped']}")
    print(f"  Errors / taxonomy violations:     {stats['errors']}")
    print(f"  Wall time:                        {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print(f"  Derived cache location:           {DERIVED_ROOT}")
    print("=" * 60)

    if stats["errors"] > 0:
        print("\nThere were errors. Review the output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
