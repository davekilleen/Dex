import json
import os
import shutil
import subprocess
from pathlib import Path


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _fixture(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "-q")
    scripts = root / "scripts"
    scripts.mkdir()
    source = Path(__file__).resolve().parents[2] / "scripts"
    shutil.copy2(source / "security-gate.sh", scripts / "security-gate.sh")
    shutil.copy2(source / "security-scan.py", scripts / "security-scan.py")
    shutil.copy2(source / "security-allowlist.txt", scripts / "security-allowlist.txt")
    core_utils = root / "core/utils"
    core_utils.mkdir(parents=True)
    (root / "core/__init__.py").write_text("")
    (core_utils / "__init__.py").write_text("")
    shutil.copy2(Path(__file__).resolve().parents[2] / "core/utils/local_git.py", core_utils / "local_git.py")
    config = root / "System/integrations/config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("todoist:\n  enabled: false\n")
    return root


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "scripts/security-gate.sh"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "SECURITY_STRICT_AUDIT": "0"},
    )


def test_security_gate_redacts_values_and_scans_space_and_newline_names(tmp_path):
    root = _fixture(tmp_path)
    secret = "ghp_" + "A" * 24
    names = ("space name.txt", "line\nname.txt")
    for name in names:
        (root / name).write_text(secret + "\n")
    _git(root, "add", ".")

    result = _run(root)

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert secret not in combined
    assert "github-token" in combined
    diagnostics = [json.loads(line.strip()) for line in result.stdout.splitlines() if line.strip().startswith("{")]
    assert {item["file"] for item in diagnostics} >= set(names)
    assert all(set(item) == {"file", "line", "category"} for item in diagnostics)


def test_production_scanner_redaction_mutation_would_disclose_matched_value(tmp_path):
    root = _fixture(tmp_path)
    secret = "ghp_" + "B" * 24
    (root / "space name.txt").write_text(secret + "\n")
    _git(root, "add", ".")

    scanner = root / "scripts/security-scan.py"
    source = scanner.read_text()
    source = source.replace(
        'print(json.dumps({"file": path, "line": line, "category": category}, ensure_ascii=True))',
        'print(data.decode("utf-8", errors="replace"))',
    )
    assert source != scanner.read_text()
    scanner.write_text(source)

    mutated = subprocess.run(
        ["python3", "scripts/security-scan.py"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert mutated.returncode == 1
    assert secret in mutated.stdout


def test_security_gate_refuses_tracked_file_parent_symlink_without_reading_target(tmp_path):
    root = _fixture(tmp_path)
    tracked = root / "tracked/value.txt"
    tracked.parent.mkdir()
    tracked.write_text("safe\n")
    _git(root, "add", ".")
    shutil.rmtree(tracked.parent)
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = "ghp_" + "C" * 24
    (outside / "value.txt").write_text(secret + "\n")
    tracked.parent.symlink_to(outside, target_is_directory=True)

    result = _run(root)

    assert result.returncode != 0
    assert "failed closed" in (result.stdout + result.stderr).lower()
    assert secret not in result.stdout + result.stderr
