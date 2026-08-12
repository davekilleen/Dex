import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "detect-flaky-tests.sh"


def _copy_detector_fixture(tmp_path: Path) -> Path:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    detector = scripts_dir / "detect-flaky-tests.sh"
    shutil.copy2(SCRIPT, detector)
    detector.chmod(0o755)

    for test_dir in ("core/tests", "core/mcp/tests", "core/migrations/tests"):
        (tmp_path / test_dir).mkdir(parents=True)

    return detector


def _run_detector(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path / 'bin'}:{env['PATH']}"
    return subprocess.run(
        ["/bin/bash", "scripts/detect-flaky-tests.sh", ".logs/flaky"],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def test_flaky_detector_fails_when_pytest_collects_no_tests(tmp_path: Path) -> None:
    _copy_detector_fixture(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pytest = bin_dir / "pytest"
    pytest.write_text("#!/bin/sh\nprintf 'collected 0 items\\n\\nno tests ran in 0.01s\\n'\nexit 5\n")
    pytest.chmod(0o755)

    result = _run_detector(tmp_path)

    assert result.returncode != 0
    assert "collected no tests" in result.stdout


def test_flaky_detector_allows_repeatable_test_failures(tmp_path: Path) -> None:
    _copy_detector_fixture(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pytest = bin_dir / "pytest"
    pytest.write_text(
        "#!/bin/sh\n"
        "printf 'FAILED core/tests/test_example.py::test_repeatable\\n'\n"
        "printf '1 failed, 2 passed in 0.01s\\n'\n"
        "exit 1\n"
    )
    pytest.chmod(0o755)

    result = _run_detector(tmp_path)

    assert result.returncode == 0
    assert "No flaky test signature detected" in result.stdout
