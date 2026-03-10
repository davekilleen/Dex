"""Write transcript projections into Meeting Intel storage."""

from __future__ import annotations

import os
from pathlib import Path

from core.paths import MEETING_INTEL_DIR


def ensure_meeting_intel_dirs() -> tuple[Path, Path]:
    if not MEETING_INTEL_DIR.exists():
        raise RuntimeError(f"Missing Meeting Intel directory: {MEETING_INTEL_DIR}")
    raw_dir = MEETING_INTEL_DIR / "raw"
    summary_dir = MEETING_INTEL_DIR / "summaries"
    for directory in (raw_dir, summary_dir):
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
        if not os.access(directory, os.W_OK):
            raise RuntimeError(f"Meeting Intel directory is not writable: {directory}")
    return raw_dir, summary_dir
