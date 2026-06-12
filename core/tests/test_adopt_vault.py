"""Adopt-existing-vault entrypoint: scripts/adopt-vault.sh and onboarding pre-fill.

The subprocess tests drive the real script against temp fixture vaults shaped
like what Dex Desktop reliably creates (System/routines plus content folders),
serving a fake "release archive" from a local path so no network is involved.
The server-level tests cover the onboarding pre-fill half of the existing-vault
path (R17), reusing the U4 fixture-vault patterns.

Performance budget: docs/testing-governance.md requires a "large-vault
performance budget" merge gate but defines no concrete number. The only
concrete precedent in this repo is core/tests/test_large_vault_performance.py,
which requires a 1,500-file vault scan to finish within 5.0 seconds. Adoption
is a one-time setup action that includes archive verification, expansion, and
several hundred file copies, so this suite pins a budget of 30 seconds for
adopting a vault with about 3,000 content files from a local archive with the
install step skipped. That number is proposed here, not taken from governance,
and is flagged for explicit sign-off.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import time
from pathlib import Path

import pytest

import core.mcp.onboarding_server as onboarding

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "adopt-vault.sh"
TAG = "v9.9.9-test"
ARCHIVE_TOP_DIR = "Dex-9.9.9-test"

# A minimal but complete fake release. Mirrors the real tag-archive shape
# (dev-only paths like pyproject.toml are export-ignored from archives, while
# scripts/ may or may not be carried; it is present here to cover the copy
# path). Includes trap content (numbered folders, System defaults) that the
# overlay must never plant in a vault.
RELEASE_FILES = {
    "install.sh": "#!/bin/bash\necho fake install ran\n",
    "requirements.txt": "pyyaml\n",
    "README.md": "# Dex release readme\n",
    "CLAUDE.md": (
        "# Dex - Your Personal Knowledge System\n\n"
        "## User Profile\n\n<!-- Updated during onboarding -->\n"
        "**Name:** Not yet configured\n\n---\n"
    ),
    "env.example": "EXAMPLE=1\n",
    "core/paths.py": "# release paths module\n",
    "core/mcp/onboarding_server.py": "# release onboarding server\n",
    "core/mcp/requirements.txt": "mcp\n",
    ".claude/flows/onboarding.md": "# onboarding flow\n",
    ".agents/skills/getting-started/SKILL.md": "# getting started\n",
    "scripts/adopt-vault.sh": "# release copy of the adopt entrypoint\n",
    "docs/continue-from-dex-desktop.md": "# guide\n",
    "System/user-profile-template.yaml": "name: ''\nrole: ''\nemail_domain: ''\n",
    "System/.mcp.json.example": "{\"mcpServers\": {}}\n",
    # Trap content below: must never appear in the adopted vault.
    "00-Inbox/sample-idea.md": "# Sample idea shipped with dex-core\n",
    "04-Projects/Sample_Project.md": "# Sample project shipped with dex-core\n",
    "06-Resources/Dex_System/Folder_Structure.md": "# Template doc\n",
    "System/user-profile.yaml": "name: Dex Default\n",
    "System/pillars.yaml": "pillars: []\n",
}

NUMBERED_DIRS = [
    "00-Inbox",
    "01-Quarter_Goals",
    "02-Week_Priorities",
    "03-Tasks",
    "04-Projects",
    "05-Areas",
    "06-Resources",
    "07-Archives",
]

WORK_PERSON_PAGE = (
    "---\nownership: work\n---\n\n# Pat Partner\n\n"
    "**Email:** pat.partner@desktop.example\n\n"
    "Works with me on the Big Launch project.\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_archive(base: Path, files: dict[str, str] | None = None, name: str = "release.tar.gz") -> tuple[Path, str]:
    """Build a fake release tarball shaped like a GitHub tag archive."""
    files = files if files is not None else RELEASE_FILES
    tree = base / "archive-tree" / ARCHIVE_TOP_DIR
    if tree.parent.exists():
        shutil.rmtree(tree.parent)
    for rel, content in files.items():
        target = tree / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    (tree / "install.sh").chmod(0o755)
    archive = base / name
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(tree, arcname=ARCHIVE_TOP_DIR)
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    return archive, checksum


def make_desktop_vault(base: Path, light: bool = False) -> Path:
    """Build a vault shaped like what Dex Desktop reliably creates."""
    vault = base / "My Vault"
    routines = vault / "System" / "routines"
    routines.mkdir(parents=True)
    (routines / "morning-briefing.md").write_text("# Morning briefing routine\n", encoding="utf-8")
    (vault / "System" / "user-profile.yaml").write_text(
        "name: Desktop Dana\nrole: Designer\nemail_domain: desktop.example\n",
        encoding="utf-8",
    )
    areas = vault / "05-Areas"
    if light:
        areas.mkdir(parents=True)
        (areas / "Notes.md").write_text("# A single area note\n", encoding="utf-8")
        return vault
    (vault / "00-Inbox" / "Meetings").mkdir(parents=True)
    (vault / "00-Inbox" / "Meetings" / "2026-06-01 - Kickoff.md").write_text(
        "# Kickoff\n\nNotes from the kickoff meeting.\n", encoding="utf-8"
    )
    (vault / "03-Tasks").mkdir(parents=True)
    (vault / "03-Tasks" / "Tasks.md").write_text("# Tasks\n\n- [ ] Ship the launch\n", encoding="utf-8")
    (vault / "04-Projects").mkdir(parents=True)
    (vault / "04-Projects" / "Big_Launch.md").write_text("# Big Launch\n", encoding="utf-8")
    people = areas / "People" / "Internal"
    people.mkdir(parents=True)
    (people / "Pat_Partner.md").write_text(WORK_PERSON_PAGE, encoding="utf-8")
    (vault / "06-Resources").mkdir(parents=True)
    (vault / "06-Resources" / "Reading_List.md").write_text("# Reading list\n", encoding="utf-8")
    return vault


def run_adopt(
    vault: Path,
    archive_url: str,
    checksum: str,
    home: Path,
    *extra: str,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env.pop("DEX_ADOPT_LOG_DIR", None)
    env.pop("DEX_ADOPT_ARCHIVE_URL", None)
    env.pop("DEX_ADOPT_REPO", None)
    cmd = [
        "bash",
        str(SCRIPT),
        "--vault",
        str(vault),
        "--tag",
        TAG,
        "--checksum",
        checksum,
        "--archive-url",
        archive_url,
        "--no-install",
        *extra,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)


def snapshot(root: Path) -> dict[str, str]:
    """Map every file under root (dotfiles included) to a content hash."""
    out: dict[str, str] = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in filenames:
            path = Path(dirpath) / fname
            rel = str(path.relative_to(root))
            if path.is_symlink():
                out[rel] = "symlink:" + os.readlink(path)
            else:
                out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def numbered_dir_counts(vault: Path) -> dict[str, int]:
    counts = {}
    for d in NUMBERED_DIRS:
        target = vault / d
        if target.is_dir():
            counts[d] = sum(1 for _ in target.rglob("*") if _.is_file())
        else:
            counts[d] = -1  # absent
    return counts


def log_path_from_output(stdout: str) -> Path:
    for line in stdout.splitlines():
        if line.startswith("Adoption log: "):
            return Path(line.removeprefix("Adoption log: "))
    raise AssertionError(f"No adoption log path in output:\n{stdout}")


def read_log_actions(log_file: Path) -> list[dict]:
    records = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Full and light desktop vaults adopt cleanly
# ---------------------------------------------------------------------------


def test_full_vault_adopts_with_content_untouched(tmp_path: Path):
    """Covers AE2 and AE4: content byte-identical, work person page present."""
    vault = make_desktop_vault(tmp_path)
    archive, checksum = make_archive(tmp_path)
    before = snapshot(vault)
    counts_before = numbered_dir_counts(vault)

    result = run_adopt(vault, str(archive), checksum, tmp_path / "home")

    assert result.returncode == 0, result.stdout + result.stderr
    after = snapshot(vault)
    for rel, digest in before.items():
        assert after.get(rel) == digest, f"pre-existing file changed: {rel}"

    # Work-labeled person page still present and readable
    page = vault / "05-Areas" / "People" / "Internal" / "Pat_Partner.md"
    assert page.read_text(encoding="utf-8") == WORK_PERSON_PAGE
    assert "ownership: work" in page.read_text(encoding="utf-8")

    # Runtime scaffolding landed
    for rel in (
        "core/paths.py",
        "core/mcp/onboarding_server.py",
        "install.sh",
        "requirements.txt",
        ".claude/flows/onboarding.md",
        ".agents/skills/getting-started/SKILL.md",
        "scripts/adopt-vault.sh",
        "docs/continue-from-dex-desktop.md",
        "System/user-profile-template.yaml",
        "System/.mcp.json.example",
    ):
        assert (vault / rel).exists(), f"missing scaffolding: {rel}"

    # Completion marker carries the adopted flag and the pinned tag
    marker = json.loads((vault / "System" / ".onboarding-complete").read_text(encoding="utf-8"))
    assert marker["adopted"] is True
    assert marker["adopt_release_tag"] == TAG

    # Nothing planted inside the numbered content folders
    assert numbered_dir_counts(vault) == counts_before
    assert not (vault / "00-Inbox" / "sample-idea.md").exists()
    assert not (vault / "04-Projects" / "Sample_Project.md").exists()
    assert not (vault / "06-Resources" / "Dex_System").exists()

    # The release's own System defaults are never planted over user config
    profile = (vault / "System" / "user-profile.yaml").read_text(encoding="utf-8")
    assert "Desktop Dana" in profile
    assert "Dex Default" not in profile
    assert not (vault / "System" / "pillars.yaml").exists()


def test_light_usage_vault_accepted(tmp_path: Path):
    """System/routines plus a single content folder is enough for preflight."""
    vault = make_desktop_vault(tmp_path, light=True)
    archive, checksum = make_archive(tmp_path)
    note_before = (vault / "05-Areas" / "Notes.md").read_bytes()

    result = run_adopt(vault, str(archive), checksum, tmp_path / "home")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (vault / "05-Areas" / "Notes.md").read_bytes() == note_before
    marker = json.loads((vault / "System" / ".onboarding-complete").read_text(encoding="utf-8"))
    assert marker["adopted"] is True
    assert (vault / "core" / "paths.py").exists()


# ---------------------------------------------------------------------------
# Preflight refusals leave the target untouched
# ---------------------------------------------------------------------------


def test_unrecognizable_directory_refused_with_no_changes(tmp_path: Path):
    target = tmp_path / "random-folder"
    (target / "notes").mkdir(parents=True)
    (target / "a.txt").write_text("hello\n", encoding="utf-8")
    (target / "notes" / "b.md").write_text("# b\n", encoding="utf-8")
    archive, checksum = make_archive(tmp_path)
    before = snapshot(target)

    result = run_adopt(target, str(archive), checksum, tmp_path / "home")

    assert result.returncode == 2
    assert "does not look like a Dex vault" in result.stdout
    assert snapshot(target) == before
    assert not (target / "System").exists()


def test_dex_core_checkout_refused(tmp_path: Path):
    target = tmp_path / "dex-core-clone"
    (target / "core" / "mcp").mkdir(parents=True)
    (target / "core" / "paths.py").write_text("# paths\n", encoding="utf-8")
    (target / "core" / "mcp" / "onboarding_server.py").write_text("# server\n", encoding="utf-8")
    (target / "install.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    archive, checksum = make_archive(tmp_path)
    before = snapshot(target)

    result = run_adopt(target, str(archive), checksum, tmp_path / "home")

    assert result.returncode == 2
    assert "already contains the open-source Dex code" in result.stdout
    assert snapshot(target) == before


# ---------------------------------------------------------------------------
# Git safety: .git byte-identical, non-git equally safe
# ---------------------------------------------------------------------------


def test_git_vault_keeps_dot_git_byte_identical(tmp_path: Path):
    vault = make_desktop_vault(tmp_path)
    git_env = dict(os.environ)
    git_env["GIT_CONFIG_GLOBAL"] = str(tmp_path / "no-gitconfig")
    git_env["GIT_CONFIG_SYSTEM"] = str(tmp_path / "no-gitconfig-system")

    def git(*args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(vault), "-c", "user.email=t@example.com", "-c", "user.name=T", *args],
            capture_output=True,
            text=True,
            check=True,
            env=git_env,
        )
        return proc.stdout

    git("init", "--quiet")
    git("remote", "add", "origin", "https://example.com/private-vault.git")
    git("add", "-A")
    git("commit", "--quiet", "-m", "vault before adoption")
    head_before = git("rev-parse", "HEAD").strip()
    remotes_before = git("remote", "-v")
    dot_git_before = snapshot(vault / ".git")

    archive, checksum = make_archive(tmp_path)
    result = run_adopt(vault, str(archive), checksum, tmp_path / "home")

    assert result.returncode == 0, result.stdout + result.stderr
    assert snapshot(vault / ".git") == dot_git_before
    assert git("rev-parse", "HEAD").strip() == head_before
    assert git("remote", "-v") == remotes_before
    # No tracked file modified or deleted; only untracked additions appear
    status = git("status", "--porcelain")
    for line in status.splitlines():
        assert line.startswith("??"), f"tracked file changed: {line}"


# ---------------------------------------------------------------------------
# Fetch and verification failures: clean exit, vault untouched
# ---------------------------------------------------------------------------


def test_tampered_archive_rejected_before_expansion(tmp_path: Path):
    vault = make_desktop_vault(tmp_path)
    archive, _good = make_archive(tmp_path)
    wrong_checksum = hashlib.sha256(b"tampered").hexdigest()
    before = snapshot(vault)

    result = run_adopt(vault, str(archive), wrong_checksum, tmp_path / "home")

    assert result.returncode == 4
    assert "checksum" in result.stdout.lower()
    assert snapshot(vault) == before
    assert not (vault / "core").exists()


def test_fetch_failure_leaves_vault_byte_identical(tmp_path: Path):
    vault = make_desktop_vault(tmp_path)
    checksum = hashlib.sha256(b"irrelevant").hexdigest()
    before = snapshot(vault)

    result = run_adopt(
        vault, "file:///nonexistent/dex-release.tar.gz", checksum, tmp_path / "home"
    )

    assert result.returncode == 3
    assert "download did not complete" in result.stdout
    assert snapshot(vault) == before


# ---------------------------------------------------------------------------
# Idempotency: no-op verify after success, repair after interruption
# ---------------------------------------------------------------------------


def test_rerun_after_success_is_verify_and_report_noop(tmp_path: Path):
    vault = make_desktop_vault(tmp_path)
    archive, checksum = make_archive(tmp_path)
    home = tmp_path / "home"
    first = run_adopt(vault, str(archive), checksum, home)
    assert first.returncode == 0, first.stdout + first.stderr
    after_first = snapshot(vault)

    # A bogus archive URL proves the verify path downloads nothing.
    second = run_adopt(vault, "file:///nonexistent/never-fetched.tar.gz", checksum, home)

    assert second.returncode == 0, second.stdout + second.stderr
    assert "already adopted" in second.stdout
    assert snapshot(vault) == after_first
    log_file = log_path_from_output(second.stdout)
    actions = read_log_actions(log_file)
    assert any(r["action"] == "verify" and "already-adopted-complete" in r["detail"] for r in actions)


def test_rerun_after_interrupted_overlay_repairs_to_complete(tmp_path: Path):
    vault = make_desktop_vault(tmp_path)
    # Simulate an interrupted earlier overlay: some scaffolding landed
    # (including the files that look like a dex-core checkout), no marker.
    (vault / "core" / "mcp").mkdir(parents=True)
    (vault / "core" / "paths.py").write_text("# partial sentinel\n", encoding="utf-8")
    (vault / "core" / "mcp" / "onboarding_server.py").write_text("# partial sentinel\n", encoding="utf-8")
    (vault / "install.sh").write_text("# partial sentinel\n", encoding="utf-8")
    archive, checksum = make_archive(tmp_path)

    result = run_adopt(vault, str(archive), checksum, tmp_path / "home")

    assert result.returncode == 0, result.stdout + result.stderr
    # Partial files were never overwritten
    assert (vault / "core" / "paths.py").read_text(encoding="utf-8") == "# partial sentinel\n"
    assert (vault / "install.sh").read_text(encoding="utf-8") == "# partial sentinel\n"
    # Missing pieces were completed and the marker now exists
    assert (vault / "requirements.txt").exists()
    assert (vault / "docs" / "continue-from-dex-desktop.md").exists()
    marker = json.loads((vault / "System" / ".onboarding-complete").read_text(encoding="utf-8"))
    assert marker["adopted"] is True


def test_partial_scaffolding_collisions_skipped_and_reported(tmp_path: Path):
    vault = make_desktop_vault(tmp_path)
    (vault / "README.md").write_text("# My own readme\n", encoding="utf-8")
    (vault / "docs").mkdir()
    (vault / "docs" / "my-notes.md").write_text("# Mine\n", encoding="utf-8")
    archive, checksum = make_archive(tmp_path)

    result = run_adopt(vault, str(archive), checksum, tmp_path / "home")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (vault / "README.md").read_text(encoding="utf-8") == "# My own readme\n"
    assert (vault / "docs" / "my-notes.md").read_text(encoding="utf-8") == "# Mine\n"
    assert "kept yours: README.md" in result.stdout
    actions = read_log_actions(log_path_from_output(result.stdout))
    skips = [r for r in actions if r["action"] == "skip-collision"]
    assert any(r["path"] == "README.md" for r in skips)
    # The release's docs file still landed next to the user's own file
    assert (vault / "docs" / "continue-from-dex-desktop.md").exists()


# ---------------------------------------------------------------------------
# Manifest boundaries and the adoption log
# ---------------------------------------------------------------------------


def test_no_files_land_inside_numbered_content_folders(tmp_path: Path):
    vault = make_desktop_vault(tmp_path)
    archive, checksum = make_archive(tmp_path)
    counts_before = numbered_dir_counts(vault)

    result = run_adopt(vault, str(archive), checksum, tmp_path / "home")

    assert result.returncode == 0, result.stdout + result.stderr
    assert numbered_dir_counts(vault) == counts_before


def test_adoption_log_lives_outside_vault_and_is_machine_readable(tmp_path: Path):
    vault = make_desktop_vault(tmp_path)
    archive, checksum = make_archive(tmp_path)
    home = tmp_path / "home"

    result = run_adopt(vault, str(archive), checksum, home)

    assert result.returncode == 0, result.stdout + result.stderr
    log_file = log_path_from_output(result.stdout)
    assert log_file.exists()
    # Outside the vault tree, under the home dot-directory by default
    assert vault not in log_file.parents
    assert (home / ".dex" / "adopt") in log_file.parents
    actions = read_log_actions(log_file)
    kinds = {r["action"] for r in actions}
    assert {"run-start", "checksum", "copy", "marker", "final-verify", "run-complete"} <= kinds
    copied = [r for r in actions if r["action"] == "copy"]
    assert any(r["path"] == "core/paths.py" for r in copied)


# ---------------------------------------------------------------------------
# Onboarding pre-fill (server-level): the existing-vault path of R17
# ---------------------------------------------------------------------------


def _patch_paths(monkeypatch: pytest.MonkeyPatch, vault: Path) -> None:
    system = vault / "System"
    monkeypatch.setattr(onboarding, "BASE_DIR", vault)
    monkeypatch.setattr(onboarding, "USER_PROFILE_FILE", system / "user-profile.yaml")
    monkeypatch.setattr(onboarding, "PILLARS_FILE", system / "pillars.yaml")
    monkeypatch.setattr(onboarding, "USER_PROFILE_TEMPLATE", system / "user-profile-template.yaml")
    monkeypatch.setattr(onboarding, "CLAUDE_MD", vault / "CLAUDE.md")
    monkeypatch.setattr(onboarding, "MCP_CONFIG_EXAMPLE", system / ".mcp.json.example")
    monkeypatch.setattr(onboarding, "MCP_CONFIG_TARGET", system / ".mcp.json")
    monkeypatch.setattr(onboarding, "MARKER_FILE", system / ".onboarding-complete")
    monkeypatch.setattr(onboarding, "SESSION_FILE", system / ".onboarding-session.json")


def _call_tool(tool: str, arguments: dict | None = None) -> dict:
    result = asyncio.run(onboarding.handle_call_tool(tool, arguments or {}))
    if isinstance(result, list):
        text = "".join(getattr(item, "text", "") for item in result)
    else:
        text = getattr(result, "text", str(result))
    return json.loads(text)


@pytest.fixture
def adopted_marker_vault(fixture_vault: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fixture vault dressed as freshly adopted: marker written, no session."""
    vault = tmp_path / "adopted-vault"
    shutil.copytree(fixture_vault, vault)
    system = vault / "System"
    (system / ".onboarding-complete").write_text(
        json.dumps({"adopted": True, "adopt_release_tag": TAG}), encoding="utf-8"
    )
    session_file = system / ".onboarding-session.json"
    if session_file.exists():
        session_file.unlink()
    (system / ".mcp.json.example").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    _patch_paths(monkeypatch, vault)
    return vault


def test_prefill_from_existing_profile_no_reinterview(adopted_marker_vault: Path):
    """Adoption pre-fills from System/user-profile.yaml; no re-interview."""
    (adopted_marker_vault / "System" / "pillars.yaml").write_text(
        "pillars:\n"
        "  - id: deal-support\n"
        "    name: Deal Support\n"
        "  - id: thought-leadership\n"
        "    name: Thought Leadership\n",
        encoding="utf-8",
    )
    profile_before = (adopted_marker_vault / "System" / "user-profile.yaml").read_bytes()

    response = _call_tool("start_onboarding_session")

    assert response["success"] is True
    session = response["data"]
    assert session["prefilled"] is True
    assert sorted(session["completed_steps"]) == [1, 2, 3, 4, 5, 6]
    assert session["data"]["name"] == "Test User"
    assert session["data"]["email_domain"] == "example.com"
    assert session["data"]["pillars"] == ["Deal Support", "Thought Leadership"]
    assert "pre-filled" in response["message"]
    assert "Do not" in response["message"]

    status = _call_tool("get_onboarding_status")
    assert status["data"]["ready_to_finalize"] is True

    finalize = _call_tool("finalize_onboarding")
    assert finalize["success"] is True
    # Existing config preserved byte for byte; adopted flag survives
    assert (adopted_marker_vault / "System" / "user-profile.yaml").read_bytes() == profile_before
    marker = json.loads(
        (adopted_marker_vault / "System" / ".onboarding-complete").read_text(encoding="utf-8")
    )
    assert marker["adopted"] is True


def test_prefill_partial_profile_asks_only_missing_steps(adopted_marker_vault: Path):
    """Empty pillars leave step 5 open; everything present is not re-asked."""
    # Fixture pillars.yaml is an empty list, so step 5 cannot pre-fill
    response = _call_tool("start_onboarding_session")

    assert response["success"] is True
    session = response["data"]
    assert session["prefilled"] is True
    assert 5 not in session["completed_steps"]
    assert sorted(session["completed_steps"]) == [1, 2, 3, 4, 6]
    assert session["current_step"] == 5
    assert "missing steps" in response["message"] or "Ask" in response["message"]


def test_absent_profile_falls_back_to_interview_with_adopted_flag(
    adopted_marker_vault: Path, monkeypatch: pytest.MonkeyPatch
):
    """No user-profile.yaml: standard interview, adopted stays true, Phase 2 gated."""
    (adopted_marker_vault / "System" / "user-profile.yaml").unlink()
    (adopted_marker_vault / "System" / "pillars.yaml").unlink()

    response = _call_tool("start_onboarding_session")

    assert response["success"] is True
    session = response["data"]
    assert "prefilled" not in session
    assert session["completed_steps"] == []
    assert "standard" in response["message"]

    # Complete the interview through the normal validated steps
    for step, payload in (
        (1, {"name": "Interview Name"}),
        (2, {"role_number": 1}),
        (3, {"company": "Interview Co", "company_size": "startup"}),
        (4, {"email_domain": "interview.example"}),
        (5, {"pillars": ["Pillar One", "Pillar Two"]}),
        (6, {"communication": {"formality": "professional_casual"}}),
    ):
        step_response = _call_tool(
            "validate_and_save_step", {"step_number": step, "step_data": payload}
        )
        assert step_response["success"] is True, step_response

    finalize = _call_tool("finalize_onboarding")
    assert finalize["success"] is True

    marker = json.loads(
        (adopted_marker_vault / "System" / ".onboarding-complete").read_text(encoding="utf-8")
    )
    assert marker["adopted"] is True

    # Phase 2 writes remain gated on the adopted vault (U4's gate, wired not duplicated)
    week_file = adopted_marker_vault / "02-Week_Priorities" / "Week_Priorities.md"
    week_before = week_file.read_bytes()
    assert onboarding.write_weekly_plan("# Generated Plan\n") is False
    assert week_file.read_bytes() == week_before


def test_fresh_vault_session_has_no_prefill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Golden-journey guard: without the adopted marker nothing pre-fills."""
    vault = tmp_path / "fresh-vault"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "user-profile.yaml").write_text("name: Someone\n", encoding="utf-8")
    _patch_paths(monkeypatch, vault)

    response = _call_tool("start_onboarding_session")

    assert response["success"] is True
    assert "prefilled" not in response["data"]
    assert response["message"] == "New onboarding session created"


# ---------------------------------------------------------------------------
# Real distribution archive: the shape GitHub serves for a tag
# ---------------------------------------------------------------------------


def test_real_repo_archive_adopts_cleanly(tmp_path: Path):
    """A git archive of this repo (what a GitHub tag serves, honoring
    .gitattributes export-ignore) passes the completeness check and adopts a
    desktop vault without planting template or sample content."""
    archive = tmp_path / "real-release.tar.gz"
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "archive",
            "--format=tar.gz",
            "--prefix=Dex-real-test/",
            "-o",
            str(archive),
            "HEAD",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.skip(f"git archive unavailable here: {proc.stderr}")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()

    vault = make_desktop_vault(tmp_path)
    counts_before = numbered_dir_counts(vault)
    profile_before = (vault / "System" / "user-profile.yaml").read_bytes()

    result = run_adopt(vault, str(archive), checksum, tmp_path / "home")

    assert result.returncode == 0, result.stdout + result.stderr
    # Runtime scaffolding from the real archive landed
    assert (vault / "core" / "paths.py").exists()
    assert (vault / "core" / "mcp" / "onboarding_server.py").exists()
    assert (vault / "install.sh").exists()
    assert (vault / ".claude" / "flows" / "onboarding.md").exists()
    # The real archive carries template and sample content that must stay out
    assert numbered_dir_counts(vault) == counts_before
    assert not (vault / "06-Resources" / "Dex_System").exists()
    assert not (vault / "System" / "Demo").exists()
    assert not (vault / "System" / "pillars.yaml").exists()
    assert (vault / "System" / "user-profile.yaml").read_bytes() == profile_before
    # The two runtime templates are the only System additions besides the marker
    assert (vault / "System" / "user-profile-template.yaml").exists()
    assert (vault / "System" / ".mcp.json.example").exists()
    system_entries = sorted(p.name for p in (vault / "System").iterdir())
    assert system_entries == [
        ".mcp.json.example",
        ".onboarding-complete",
        "routines",
        "user-profile-template.yaml",
        "user-profile.yaml",
    ]


# ---------------------------------------------------------------------------
# Performance budget on a large generated vault
# ---------------------------------------------------------------------------


def test_large_vault_adoption_within_budget(tmp_path: Path):
    """Adoption of a ~3,000-file vault completes within 30 seconds.

    Budget source: docs/testing-governance.md names a large-vault performance
    gate without a number; the closest precedent is the 1,500-file / 5.0s scan
    budget in test_large_vault_performance.py. Adoption is a one-time setup
    action including archive expansion and several hundred copies, so 30
    seconds for ~3,000 vault files (local archive, install step skipped) is
    proposed here and flagged for sign-off.
    """
    vault = make_desktop_vault(tmp_path)
    per_dir = 500
    for d in ("00-Inbox", "03-Tasks", "04-Projects", "05-Areas", "06-Resources", "07-Archives"):
        target = vault / d / "Bulk"
        target.mkdir(parents=True, exist_ok=True)
        for i in range(per_dir):
            (target / f"note-{i:04d}.md").write_text(f"# Note {i}\n", encoding="utf-8")

    # A fuller archive so the copy loop does representative work
    files = dict(RELEASE_FILES)
    for i in range(700):
        files[f".claude/skills/generated-{i:03d}/SKILL.md"] = f"# Skill {i}\n"
    archive, checksum = make_archive(tmp_path, files)

    counts_before = numbered_dir_counts(vault)
    started = time.monotonic()
    result = run_adopt(vault, str(archive), checksum, tmp_path / "home")
    elapsed = time.monotonic() - started

    assert result.returncode == 0, result.stdout + result.stderr
    assert elapsed <= 30.0, f"adoption took {elapsed:.1f}s, budget is 30s"
    assert numbered_dir_counts(vault) == counts_before
    marker = json.loads((vault / "System" / ".onboarding-complete").read_text(encoding="utf-8"))
    assert marker["adopted"] is True
