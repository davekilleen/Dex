"""
_categories.py — Canonical Subject / Geography taxonomy for the Research library.

This module is the **single source of truth** (in code) for which top-level folders
under 06-Resources/Research/ are considered valid "Subject" categories.

It enforces the contract defined in:
  "Research Document Repository - User Guide.docx"
  (the authoritative human document living alongside the PDFs)

Phase 1 design decisions (documented for Claude review):
- We validate primarily on the first path component (Subject).
- Geography / Scope (second path component) is captured for frontmatter but is
  intentionally *permissive* in v1. The User Guide defines a tree, not a rigid
  closed set of geography values per subject. Strict geography whitelisting would
  cause constant maintenance pain every time a new "Regional (X)" or "Policy"
  subfolder appears.
- Unknown subjects cause a hard failure with a clear, actionable error message
  that tells the user exactly which file to consult and how to extend the list.
- The list below was mechanically extracted from the on-disk folder tree on
  2026-05-16 and cross-checked against the visible structure in the User Guide.
- Future improvement (Phase 3+): add a `librarian refresh-taxonomy` command that
  uses the anthropic-docx skill to re-parse the .docx narrative + folder map and
  proposes an updated _categories.py (or a JSON sidecar).

This file is deliberately **not** a data file that the ingest script "reads at
runtime from the docx". That would have required either (a) python-docx + complex
narrative parsing or (b) a one-time manual extraction that then drifts. The
current approach gives us the desired "fail loud on unknown category" behaviour
while keeping the implementation in one small, reviewable file.

Usage:
    from _categories import derive_subject_geography, validate_subject

    subject, geo = derive_subject_geography(Path("Cryptocurrency/Stablecoin/foo.pdf"))
    ok, err = validate_subject(subject)
    if not ok:
        raise ValueError(err)
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

# =============================================================================
# AUTHORITATIVE SUBJECT LIST (as of 2026-05-16)
# =============================================================================
# Extracted from:
#   06-Resources/Research/  (on-disk top-level directories)
#   + cross-reference with " Research Document Repository - User Guide.docx"
#
# These are the ONLY values allowed as the first path component under Research/.
# Any PDF found outside these will cause ingest to abort with a helpful message.
#
# When adding a new major research domain:
#   1. Create the folder following the User Guide convention
#   2. Add the exact string here (case-sensitive, with proper spacing)
#   3. Update this comment with the date and your initials
#   4. Re-run `librarian ingest --dry-run` to validate
# =============================================================================

ALLOWED_SUBJECTS: set[str] = {
    "Artificial Intelligence",
    "Business Strategy",
    "Cryptocurrency",
    "Economics",
    "Energy",
    "Family Office",
    "Financial Services",
    "General Business",
    "Government Policy",
    "Healthcare",
    "Insurance",
    "Real Estate",
    "Technology",
    "Venture Capital",
    # Special structural folders (allowed but treated differently in reporting)
    "Uncategorised [Sorting Needed]",
    "ZZ Archived Structure",
}

# Optional: per-subject geography hints (not a hard whitelist in v1)
# These are the most common second-level directories observed. They are used
# only for documentation and future stricter validation if desired.
COMMON_GEOGRAPHIES: dict[str, set[str]] = {
    "Artificial Intelligence": {
        "AI Pulse", "Ethics", "General", "Global", "Governance", "Healthcare",
        "Industry Analysis", "Infrastructure", "Policy and Governance",
        "Regional (Americas)", "Regional (Europe)", "Regional (India)",
        "Regional (Japan)", "Regional (UK)", "Smart Cities", "Society", "Strategy",
    },
    "Cryptocurrency": {
        "Digital Assets", "General", "Global", "Regulation", "Stablecoin",
        "store-value-of-digital-oil-btc-eth.pdf",  # edge case file directly under subject
    },
    # ... (other subjects have fewer or no second-level folders in the current snapshot)
}


def derive_subject_geography(pdf_path: Path) -> Tuple[str, Optional[str]]:
    """
    Given a path like:
        06-Resources/Research/Artificial Intelligence/Global/Some Report.pdf
    or
        06-Resources/Research/Cryptocurrency/Stablecoin/foo.pdf

    Returns (subject, geography_or_None).

    The geography is the second path component when it exists and is not the
    filename itself. For PDFs that sit directly under a subject (rare), geography
    is None and the caller should usually default it to "General".
    """
    parts = pdf_path.parts

    # Find the index of "Research" so we can be robust to absolute vs relative paths
    try:
        research_idx = parts.index("Research")
    except ValueError:
        # Fallback: assume the path is already relative to Research/
        research_idx = -1

    rel_parts = parts[research_idx + 1 :]

    if not rel_parts:
        return "Unknown", None

    # Strip whitespace — some legacy folders from the Tresorit export have
    # leading spaces (e.g. " Uncategorised [Sorting Needed]"). This is the
    # real-world data we must be robust against.
    subject = rel_parts[0].strip()

    # Geography is the next directory component, if it is not a file
    if len(rel_parts) >= 2 and not rel_parts[1].lower().endswith((".pdf", ".docx", ".xlsx")):
        geography = rel_parts[1].strip()
    else:
        geography = None

    return subject, geography


def validate_subject(subject: str) -> Tuple[bool, str]:
    """
    Returns (is_valid, error_message_if_invalid).

    The error message is written for a human operator and explicitly tells them
    where to look (the User Guide .docx) and what to do.
    """
    if subject in ALLOWED_SUBJECTS:
        return True, ""

    # Build a helpful error
    sorted_subjects = sorted(ALLOWED_SUBJECTS)
    hint = "\n".join(f"  - {s}" for s in sorted_subjects)

    err = (
        f"Unknown research Subject category: {subject!r}\n\n"
        "This PDF lives under a top-level folder that is not in the allowed taxonomy.\n"
        "The Research library follows a strict Subject/Geography/Document structure\n"
        "defined in the official User Guide:\n\n"
        "  06-Resources/Research/ Research Document Repository - User Guide.docx\n\n"
        "Allowed subjects (as of 2026-05-16):\n"
        f"{hint}\n\n"
        "How to fix:\n"
        "  1. Move the PDF into one of the folders listed above, OR\n"
        "  2. If this is a legitimate new domain, add the exact folder name to\n"
        "     ALLOWED_SUBJECTS in .claude/skills/librarian/scripts/_categories.py\n"
        "     and document the change in this file's header comment.\n"
        "  3. Re-run the ingest.\n"
    )
    return False, err


def validate_subject_or_raise(subject: str) -> None:
    """Convenience wrapper used by ingest.py."""
    ok, msg = validate_subject(subject)
    if not ok:
        raise ValueError(msg)


# =============================================================================
# Convenience for ad-hoc inspection (can be run as: python -m _categories)
# =============================================================================
if __name__ == "__main__":
    print("Allowed subjects:")
    for s in sorted(ALLOWED_SUBJECTS):
        print(f"  {s}")
    print("\nExample derivations:")
    examples = [
        Path("Artificial Intelligence/Global/ARK Invest Big Ideas 2026.pdf"),
        Path("Cryptocurrency/Stablecoin/build-ur-strategy-stablecoin-guide-bvnk.pdf"),
        Path("Uncategorised [Sorting Needed]/Some New Paper.pdf"),
        Path("ZZ Archived Structure/Really Old Report.pdf"),
    ]
    for ex in examples:
        subj, geo = derive_subject_geography(ex)
        print(f"  {ex} -> subject={subj!r}, geography={geo!r}")
