"""
QMD Semantic Search Utility — Shared Query Interface

Provides vault-wide search that uses QMD (semantic: BM25 + vectors + LLM reranking)
when available, falling back to grep when QMD is not installed.

Every skill and MCP server that searches vault content should use this utility.
One place for availability checks, fallback logic, error handling, and result normalization.

Usage:
    from core.utils.qmd_query import vault_search, is_qmd_available

    # Semantic if QMD available, grep fallback if not
    results = vault_search("customer retention strategies")
    # Returns: [{"path": "...", "score": 0.85, "snippet": "...", "source": "qmd"}]

    # Check availability (cached, <1ms after first call)
    if is_qmd_available():
        print("Semantic search active")

    # Explicit grep fallback pattern for domain-specific searches
    results = vault_search(
        "customer retention",
        fallback_grep="retention|churn|cancel|NPS",
    )
"""

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# QMD Binary Discovery (shared with qmd_indexer.py)
# ---------------------------------------------------------------------------

_qmd_path: Optional[str | bool] = None


def _find_qmd() -> Optional[str]:
    """Find the qmd binary, checking common install locations. Result is cached."""
    global _qmd_path
    if _qmd_path is not None:
        return _qmd_path if _qmd_path else None

    path = shutil.which("qmd")
    if path:
        _qmd_path = path
        return path

    home = Path.home()
    candidates = [
        home / ".bun" / "bin" / "qmd",
        home / ".local" / "bin" / "qmd",
        Path("/usr/local/bin/qmd"),
        Path("/opt/homebrew/bin/qmd"),
    ]
    for candidate in candidates:
        if candidate.exists():
            _qmd_path = str(candidate)
            return _qmd_path

    _qmd_path = False
    return None


# ---------------------------------------------------------------------------
# Availability Check
# ---------------------------------------------------------------------------

_qmd_available: Optional[bool] = None


def is_qmd_available() -> bool:
    """
    Check if QMD is installed and has indexed collections.
    Result is cached for the lifetime of the process.
    """
    global _qmd_available
    if _qmd_available is not None:
        return _qmd_available

    qmd = _find_qmd()
    if not qmd:
        _qmd_available = False
        return False

    try:
        result = subprocess.run(
            [qmd, "status"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        _qmd_available = result.returncode == 0
    except (subprocess.TimeoutExpired, Exception):
        _qmd_available = False

    return _qmd_available


def reset_cache():
    """Reset cached availability state. Useful after install/uninstall."""
    global _qmd_path, _qmd_available
    _qmd_path = None
    _qmd_available = None


# ---------------------------------------------------------------------------
# QMD Search (Semantic)
# ---------------------------------------------------------------------------


def _qmd_search(
    query: str,
    limit: int = 10,
    search_type: str = "query",
) -> list[dict]:
    """
    Run a QMD search via CLI and parse results.

    search_type:
        "query"   — hybrid (BM25 + vectors + LLM reranking) [default, best quality]
        "search"  — keyword only (BM25)
        "vsearch" — vector only (embedding similarity)
    """
    qmd = _find_qmd()
    if not qmd:
        return []

    try:
        cmd = [qmd, search_type, query, "--limit", str(limit)]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.debug(f"qmd {search_type} failed: {result.stderr.strip()}")
            return []

        return _parse_qmd_output(result.stdout)

    except subprocess.TimeoutExpired:
        logger.warning(f"QMD {search_type} timed out for query: {query[:50]}")
        return []
    except Exception as e:
        logger.debug(f"QMD {search_type} error: {e}")
        return []


def _parse_qmd_output(output: str) -> list[dict]:
    """
    Parse QMD CLI output into normalized result dicts.
    Handles both JSON output and text output formats.
    """
    if not output.strip():
        return []

    results = []

    # Try JSON parse first
    try:
        data = json.loads(output)
        if isinstance(data, list):
            for item in data:
                results.append({
                    "path": item.get("path", item.get("file", item.get("source", ""))),
                    "score": float(item.get("score", item.get("relevance", 0.5))),
                    "snippet": item.get("snippet", item.get("content", item.get("text", "")))[:500],
                    "source": "qmd",
                })
            return results
        elif isinstance(data, dict) and "results" in data:
            return _parse_qmd_output(json.dumps(data["results"]))
    except (json.JSONDecodeError, ValueError):
        pass

    # Parse text output — QMD typically outputs blocks per result
    current_result: dict = {}
    for line in output.strip().split("\n"):
        line = line.strip()
        if not line:
            if current_result.get("path"):
                results.append(current_result)
                current_result = {}
            continue

        # Match patterns like "path/to/file.md" or "path/to/file.md (score: 0.85)"
        score_match = re.search(r"\((?:score|relevance)[:\s]*([\d.]+)\)", line)
        path_match = re.search(r"((?:[\w./-]+)?[\w-]+\.md)", line)

        if path_match and not current_result.get("path"):
            current_result = {
                "path": path_match.group(1),
                "score": float(score_match.group(1)) if score_match else 0.5,
                "snippet": "",
                "source": "qmd",
            }
        elif current_result.get("path"):
            snippet = current_result.get("snippet", "")
            current_result["snippet"] = (snippet + " " + line).strip()[:500]

    if current_result.get("path"):
        results.append(current_result)

    return results


# ---------------------------------------------------------------------------
# Grep Fallback
# ---------------------------------------------------------------------------


def _resolve_vault_path() -> str:
    """Resolve the vault path from environment or common locations."""
    vault_path = os.environ.get("VAULT_PATH", "")
    if vault_path and os.path.isdir(vault_path):
        return vault_path

    cwd = Path.cwd()

    # Walk up to find a Dex vault root (has System/pillars.yaml)
    for parent in [cwd] + list(cwd.parents):
        if (parent / "System" / "pillars.yaml").exists():
            return str(parent)

    # Check common locations
    home = Path.home()
    for name in ["Dex", "Dex", "dex-vault"]:
        candidate = home / name
        if candidate.exists() and (candidate / "System").exists():
            return str(candidate)

    return str(cwd)


def _grep_fallback(
    query: str,
    vault_path: str,
    glob_pattern: str = "**/*.md",
    grep_pattern: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """Fall back to ripgrep/grep when QMD is not available."""
    results = []

    # Build grep pattern from query words if not provided
    if not grep_pattern:
        words = [w for w in query.lower().split() if len(w) > 2]
        if not words:
            return []
        grep_pattern = "|".join(re.escape(w) for w in words)

    if not grep_pattern:
        return []

    try:
        rg = shutil.which("rg")

        if rg:
            cmd = [
                rg, "-i", "-l",
                "--glob", glob_pattern,
                "-m", "1",
                grep_pattern,
                vault_path,
            ]
        else:
            cmd = [
                "grep", "-r", "-i", "-l",
                "--include=*.md",
                "-E", grep_pattern,
                vault_path,
            ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10,
        )

        files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]

        for i, filepath in enumerate(files[:limit]):
            snippet = _extract_snippet(filepath, grep_pattern)
            results.append({
                "path": filepath,
                "score": max(0.1, 1.0 - (i * 0.08)),
                "snippet": snippet,
                "source": "grep",
            })

    except (subprocess.TimeoutExpired, Exception) as e:
        logger.debug(f"Grep fallback error: {e}")

    return results


def _extract_snippet(filepath: str, pattern: str, max_chars: int = 200) -> str:
    """Extract a relevant snippet from a file around the first pattern match."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            start = max(0, match.start() - 60)
            end = min(len(content), match.end() + max_chars)
            snippet = content[start:end].strip()
            if start > 0:
                snippet = "..." + snippet
            if end < len(content):
                snippet = snippet + "..."
            return snippet

        return content[:max_chars].strip() + ("..." if len(content) > max_chars else "")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def vault_search(
    query: str,
    limit: int = 10,
    min_score: float = 0.0,
    search_type: str = "query",
    fallback_glob: str = "**/*.md",
    fallback_grep: Optional[str] = None,
) -> list[dict]:
    """
    Search vault content. Semantic (QMD) when available, grep fallback when not.

    Args:
        query:          Natural language search query
        limit:          Maximum results to return
        min_score:      Minimum relevance score (0.0 to 1.0). Only applied to QMD results.
        search_type:    QMD mode — "query" (hybrid), "search" (keyword), "vsearch" (vector)
        fallback_glob:  Glob pattern for grep fallback file matching
        fallback_grep:  Explicit regex for grep fallback. Auto-generated from query if None.

    Returns:
        List of dicts: [{"path": str, "score": float, "snippet": str, "source": "qmd"|"grep"}]
        Sorted by score descending. Empty list if nothing found.
    """
    # Try QMD first (semantic: BM25 + vectors + LLM reranking)
    if is_qmd_available():
        results = _qmd_search(query, limit=limit, search_type=search_type)
        if results:
            if min_score > 0:
                results = [r for r in results if r.get("score", 0) >= min_score]
            results.sort(key=lambda r: r.get("score", 0), reverse=True)
            return results[:limit]
        # QMD returned nothing — fall through to grep
        logger.debug(f"QMD returned no results for '{query[:50]}', falling back to grep")

    # Grep fallback
    vault_path = _resolve_vault_path()
    return _grep_fallback(
        query=query,
        vault_path=vault_path,
        glob_pattern=fallback_glob,
        grep_pattern=fallback_grep,
        limit=limit,
    )


def vault_search_multi(
    queries: list[str],
    limit_per_query: int = 5,
    deduplicate: bool = True,
    **kwargs,
) -> list[dict]:
    """
    Run multiple search queries and merge results. Useful for meeting prep
    (search topic + each attendee) or triage (match against multiple goals).

    Args:
        queries:          List of search queries
        limit_per_query:  Max results per individual query
        deduplicate:      Remove duplicate paths, keeping highest score
        **kwargs:         Passed through to vault_search()

    Returns:
        Merged, deduplicated, score-sorted list of results.
    """
    all_results: list[dict] = []
    seen_paths: dict[str, float] = {}

    for query in queries:
        results = vault_search(query, limit=limit_per_query, **kwargs)
        for r in results:
            path = r.get("path", "")
            score = r.get("score", 0)

            if deduplicate and path in seen_paths:
                if score <= seen_paths[path]:
                    continue
                # Remove old lower-score entry
                all_results = [x for x in all_results if x.get("path") != path]

            seen_paths[path] = score
            all_results.append(r)

    all_results.sort(key=lambda r: r.get("score", 0), reverse=True)
    return all_results
