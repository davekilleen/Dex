#!/usr/bin/env python3
"""
query.py — Retrieval engine for the Proactive Librarian.

Phase 2 of the Proactive Librarian.

Given a natural language query, it runs a hybrid (lex + vec) search against
the dedicated `research` QMD collection (the per-page .derived/ markdown cache),
parses `## Page N` markers from the returned snippets, and emits clean, copy-pasteable citations in the form:

  **File_Name.pdf**:p.12  (score 0.87)
  > relevant passage excerpt...

Usage (from venv):
    python query.py "agentic workflow patterns in financial services" --limit 5

The script is designed to be called by the `/librarian` skill (or directly).
It shells out to the `qmd` binary (which supports structured lex/vec queries
and --collection filtering) and returns structured JSON for the skill layer.

This matches ADR-001 (QMD as substrate) and ADR-005 (no new MCP).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

QMD_BINARY = "/Users/davidorban/.bun/bin/qmd"  # or shutil.which("qmd")

PAGE_RE = re.compile(r"## Page (\d+)", re.IGNORECASE)
PAGE_TITLE_RE = re.compile(r"Page (\d+)", re.IGNORECASE)
FILENAME_RE = re.compile(r"([^/\\]+\.pdf)", re.IGNORECASE)
QMD_URI_RE = re.compile(r"qmd://research/(.+)")


def run_qmd_hybrid_query(query: str, collection: str = "research", limit: int = 5) -> List[Dict[str, Any]]:
    """
    Execute a hybrid lex + vec query against the research collection.

    Uses the structured query document syntax supported by `qmd query`:
        lex: <query>
        vec: <query>

    Returns parsed JSON results (or raises on failure).
    """
    if not Path(QMD_BINARY).exists():
        # Fallback to PATH
        qmd = "qmd"
    else:
        qmd = QMD_BINARY

    # Structured hybrid query (lex for keywords + vec for semantics)
    # This is the exact pattern recommended in ADR-001 and the plan.
    structured = f'lex: {query}\nvec: {query}'

    cmd = [
        qmd,
        "query",
        structured,
        "--collection", collection,
        "--json",
        "-n", str(limit),
        "--min-score", "0.0",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        data = json.loads(result.stdout)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("results", [])
        return []
    except subprocess.CalledProcessError as e:
        print(f"qmd query failed (rc={e.returncode}): {e.stderr}", file=sys.stderr)
        return []
    except json.JSONDecodeError:
        print("Failed to parse qmd JSON output", file=sys.stderr)
        return []
    except Exception as e:
        print(f"Unexpected error calling qmd: {e}", file=sys.stderr)
        return []


def extract_page_and_file(result: Dict[str, Any]) -> tuple[Optional[int], str]:
    """
    Extract page number and clean filename from a qmd result.

    Priority for page:
    1. "title" field (often "Page 12")
    2. ## Page N in the snippet
    """
    title = result.get("title", "")
    snippet = result.get("snippet", "")
    file_field = result.get("file", "")

    # Try title first (most reliable in current qmd output)
    page_match = PAGE_TITLE_RE.search(title)
    if not page_match:
        page_match = PAGE_RE.search(snippet)
    page = int(page_match.group(1)) if page_match else None

    # Extract clean filename from the qmd URI or path
    filename = None
    uri_match = QMD_URI_RE.search(file_field)
    if uri_match:
        filename = Path(uri_match.group(1)).name
    else:
        file_match = FILENAME_RE.search(file_field)
        filename = file_match.group(1) if file_match else Path(file_field).name

    return page, filename or "Unknown.pdf"


def format_citation(result: Dict[str, Any]) -> str:
    """
    Turn a single qmd result into a clean, copy-pasteable citation.
    """
    snippet = result.get("snippet", "").strip()
    score = result.get("score", 0.0)

    page, filename = extract_page_and_file(result)

    if page:
        header = f"**{filename}**:p.{page}  (score {score:.2f})"
    else:
        header = f"**{filename}**  (score {score:.2f})"

    # Clean up the snippet
    clean_snippet = PAGE_RE.sub("", snippet).strip()
    clean_snippet = re.sub(r"^@@.*@@\s*", "", clean_snippet)  # remove diff markers
    clean_snippet = re.sub(r"\n+", " ", clean_snippet).strip()

    if len(clean_snippet) > 320:
        clean_snippet = clean_snippet[:317] + "..."

    return f"{header}\n> {clean_snippet}\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Proactive Librarian — research PDF retrieval (Phase 2)")
    parser.add_argument("query", type=str, help="Natural language query, e.g. 'stablecoin regulation in the UAE'")
    parser.add_argument("--limit", "-n", type=int, default=5, help="Max results (default 5)")
    parser.add_argument("--collection", default="research", help="QMD collection to search")
    parser.add_argument("--json", action="store_true", help="Output raw JSON instead of formatted citations")

    args = parser.parse_args()

    results = run_qmd_hybrid_query(args.query, collection=args.collection, limit=args.limit)

    if not results:
        print("No results found (or qmd unavailable).")
        sys.exit(0)

    if args.json:
        print(json.dumps({"query": args.query, "results": results}, indent=2))
        return

    print(f"\nTop {len(results)} results for: \"{args.query}\"\n" + "=" * 60 + "\n")

    for i, r in enumerate(results, 1):
        citation = format_citation(r)
        print(f"{i}. {citation}")
        print("-" * 40)

    print("\nTip: Paste the bold [[File.pdf]]:p.N lines into your draft. The links will resolve in Obsidian/Preview.")


if __name__ == "__main__":
    main()
