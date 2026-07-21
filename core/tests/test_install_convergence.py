"""Outcome-level tests for install.sh Brain/Vault topology convergence."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATOR = "core/migrations/v1-to-v2-brain-vault-split.cjs"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _install_fixture(tmp_path: Path, scenario: str) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "dex-install"
    root.mkdir()
    shutil.copy2(REPO_ROOT / "install.sh", root / "install.sh")

    (root / "System").mkdir()
    (root / "System" / ".mcp.json.example").write_text(
        '{"mcpServers":{"work":{"args":["{{VAULT_PATH}}/core/mcp/work_server.py"]}}}\n',
        encoding="utf-8",
    )
    (root / "core" / "migrations").mkdir(parents=True)
    (root / MIGRATOR).write_text("// exercised through the node shim\n", encoding="utf-8")
    (root / "core" / "mcp").mkdir()
    (root / "core" / "mcp" / "requirements.txt").write_text("", encoding="utf-8")

    if scenario == "post-split":
        (root / ".dex" / "brain.git").mkdir(parents=True)
        (root / "System" / ".dex").mkdir()
        (root / "System" / ".dex" / "topology.json").write_text("{}\n", encoding="utf-8")

    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    _write_executable(
        shim_dir / "git",
        """#!/bin/sh
if [ "$1" = "--version" ]; then echo "git version 2.50.0"; fi
exit 0
""",
    )
    _write_executable(
        shim_dir / "node",
        """#!/bin/sh
if [ "$1" = "-v" ]; then echo "v22.0.0"; exit 0; fi
printf '%s\n' "$*" >> "$DEX_TEST_NODE_LOG"
case "$DEX_TEST_SCENARIO:$2" in
  resume:--auto)
    if [ ! -f "$DEX_TEST_RESUME_SENTINEL" ]; then
      : > "$DEX_TEST_RESUME_SENTINEL"
      exit 75
    fi
    ;;
  resume:--resume)
    mkdir -p .dex/brain.git System/.dex
    printf '{}\n' > System/.dex/topology.json
    ;;
  split:--auto)
    mkdir -p .dex/brain.git System/.dex
    printf '{}\n' > System/.dex/topology.json
    ;;
  failure:--auto)
    exit 42
    ;;
esac
exit 0
""",
    )
    _write_executable(
        shim_dir / "python3",
        """#!/bin/sh
if [ "$1" = "--version" ]; then echo "Python 3.12.0"; exit 0; fi
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  mkdir -p "$3/bin"
  printf '#!/bin/sh\nexit 0\n' > "$3/bin/pip"
  printf '#!/bin/sh\nexit 0\n' > "$3/bin/python"
  chmod +x "$3/bin/pip" "$3/bin/python"
fi
exit 0
""",
    )
    for command in ("npm", "npx"):
        _write_executable(shim_dir / command, "#!/bin/sh\nexit 0\n")
    _write_executable(shim_dir / "xcode-select", "#!/bin/sh\nexit 0\n")

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{shim_dir}:/usr/bin:/bin",
            "DEX_TEST_NODE_LOG": str(tmp_path / "node.log"),
            "DEX_TEST_RESUME_SENTINEL": str(tmp_path / "resume.once"),
            "DEX_TEST_SCENARIO": scenario,
        }
    )
    return root, environment


def _run_install(tmp_path: Path, scenario: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    root, environment = _install_fixture(tmp_path, scenario)
    result = subprocess.run(
        ["/bin/bash", "install.sh"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    log_path = Path(environment["DEX_TEST_NODE_LOG"])
    calls = log_path.read_text(encoding="utf-8").splitlines() if log_path.exists() else []
    return result, calls


def test_fresh_git_install_routes_bounded_migration_through_auto_then_resume(tmp_path: Path) -> None:
    result, calls = _run_install(tmp_path, "resume")

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == [f"{MIGRATOR} --auto", f"{MIGRATOR} --resume"]
    assert "Separating the Dex brain from your vault" in result.stdout
    assert "separate Git histories" in result.stdout
    assert "Dex installation complete" in result.stdout


def test_already_split_install_is_safe_and_keeps_normal_setup_working(tmp_path: Path) -> None:
    result, calls = _run_install(tmp_path, "post-split")

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == [f"{MIGRATOR} --auto"]
    assert "separate Git histories" in result.stdout
    assert "Dex installation complete" in result.stdout


def test_zip_combined_layout_finishes_install_without_claiming_a_split(tmp_path: Path) -> None:
    result, calls = _run_install(tmp_path, "zip")

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == [f"{MIGRATOR} --auto"]
    assert "no Git clone history" in result.stdout
    assert "Your files are unchanged" in result.stdout
    assert "Dex installation complete" in result.stdout


def test_migration_failure_stops_install_with_plain_english_recovery(tmp_path: Path) -> None:
    result, calls = _run_install(tmp_path, "failure")

    assert result.returncode == 42
    assert calls == [f"{MIGRATOR} --auto"]
    assert "could not finish the brain/vault split" in result.stdout
    assert "migration-report-v2.md" in result.stdout
    assert "Dex installation complete" not in result.stdout
