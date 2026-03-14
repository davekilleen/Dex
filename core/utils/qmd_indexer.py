"""
QMD Search Index Refresh Utility

Triggers incremental re-indexing of vault content after write operations.
Only processes changed files — typically completes in under a second.

Gracefully handles:
- QMD not installed (silently skips)
- QMD not configured (silently skips)
- Index errors (logs warning, doesn't break caller)

Usage:
    from core.utils.qmd_indexer import refresh_search_index
    refresh_search_index()  # Fire-and-forget, non-blocking
"""

import logging
import shutil
import subprocess
import threading

logger = logging.getLogger(__name__)

# Cache the QMD binary path (None = not checked, False = not found)
_qmd_path = None


def _find_qmd() -> str | None:
    """Find the qmd binary, checking common install locations."""
    global _qmd_path
    if _qmd_path is not None:
        return _qmd_path if _qmd_path else None

    # Check PATH first
    path = shutil.which("qmd")
    if path:
        _qmd_path = path
        return path

    # Check common bun/npm global install locations
    from pathlib import Path
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


def _run_reindex():
    """Run qmd update + embed in background. Called from a thread."""
    qmd = _find_qmd()
    if not qmd:
        return

    try:
        # Update FTS index (changed files only)
        result = subprocess.run(
            [qmd, "update"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.debug(f"qmd update returned {result.returncode}: {result.stderr.strip()}")
            return

        # Update vector embeddings (changed chunks only)
        result = subprocess.run(
            [qmd, "embed"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.debug(f"qmd embed returned {result.returncode}: {result.stderr.strip()}")

    except subprocess.TimeoutExpired:
        logger.warning("QMD re-index timed out")
    except Exception as e:
        logger.debug(f"QMD re-index error: {e}")


def refresh_search_index():
    """
    Trigger an incremental re-index of the QMD search index.

    Non-blocking: spawns a background thread so the caller returns immediately.
    Safe to call frequently — only processes changed files.
    Silently skips if QMD is not installed.
    """
    if _find_qmd() is None:
        return

    thread = threading.Thread(target=_run_reindex, daemon=True)
    thread.start()
