"""Performance budgets for large-vault scans."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_large_vault_benchmark_budget():
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "benchmark_large_vault.py"

    proc = subprocess.run(
        [sys.executable, str(script), "--files", "1500", "--budget-seconds", "5.0"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"Performance budget failed:\n{proc.stdout}\n{proc.stderr}"
