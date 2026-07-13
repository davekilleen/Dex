from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts" / "check-pii.sh"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _synthetic_repo(tmp_path: Path, *, include_profile: bool = False) -> Path:
    repo = tmp_path / "contributor-pr"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Dex Test")
    _git(repo, "config", "user.email", "noreply@example.com")

    system = repo / "System"
    system.mkdir()
    template = 'name: ""\nrole: ""\ncompany: ""\nemail_domain: ""\n'
    (system / "user-profile-template.yaml").write_text(template, encoding="utf-8")
    if include_profile:
        (system / "user-profile.yaml").write_text(template, encoding="utf-8")
    (repo / "README.md").write_text("# Contributor fixture\n", encoding="utf-8")
    _git(repo, "add", "README.md", "System/user-profile-template.yaml")
    if include_profile:
        _git(repo, "add", "System/user-profile.yaml")
    _git(repo, "commit", "-m", "fixture: base")
    _git(repo, "remote", "add", "origin", str(repo))
    _git(repo, "fetch", "origin", "main")
    _git(repo, "checkout", "-b", "contributor-change")
    return repo


def _commit(repo: Path, path: str, content: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", path)
    _git(repo, "commit", "-m", "fixture: contributor change")


def _run_gate(repo: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GITHUB_BASE_REF"] = "main"
    return subprocess.run(
        ["bash", str(GATE)],
        cwd=repo,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_pii_gate_blocks_real_email_added_outside_fixtures(tmp_path: Path):
    repo = _synthetic_repo(tmp_path)
    real_email = "dana" + "@real-company.io"
    _commit(repo, "docs/example.md", f"Contact Dana at {real_email}\n")

    result = _run_gate(repo)

    assert result.returncode == 1
    assert "docs/example.md:1" in result.stderr
    assert "this looks like personal data — see CONTRIBUTING.md" in result.stderr


def test_pii_gate_allows_email_added_inside_test_fixtures(tmp_path: Path):
    repo = _synthetic_repo(tmp_path)
    real_email = "dana" + "@real-company.io"
    _commit(
        repo,
        "core/tests/fixtures/messy/person.md",
        f"Contact Dana at {real_email}\n",
    )

    result = _run_gate(repo)

    assert result.returncode == 0, result.stderr


def test_pii_gate_blocks_real_user_profile(tmp_path: Path):
    repo = _synthetic_repo(tmp_path, include_profile=True)
    _commit(
        repo,
        "System/user-profile.yaml",
        'name: "Dana Realperson"\nrole: "Founder"\ncompany: "Real Co"\nemail_domain: "real-company.io"\n',
    )

    result = _run_gate(repo)

    assert result.returncode == 1
    assert "System/user-profile.yaml:1" in result.stderr


def test_pii_gate_allows_template_shaped_user_profile(tmp_path: Path):
    repo = _synthetic_repo(tmp_path)
    template = (repo / "System" / "user-profile-template.yaml").read_text(encoding="utf-8")
    _commit(repo, "System/user-profile.yaml", template)

    result = _run_gate(repo)

    assert result.returncode == 0, result.stderr


def test_pii_gate_blocks_enabled_integration_identity_even_in_fixtures(tmp_path: Path):
    repo = _synthetic_repo(tmp_path)
    _commit(
        repo,
        "core/tests/fixtures/vault/System/integrations/slack.yaml",
        "enabled: true\nworkspace: Real Company\n",
    )

    result = _run_gate(repo)

    assert result.returncode == 1
    assert "System/integrations/slack.yaml:2" in result.stderr


def test_pii_gate_blocks_personal_vault_content(tmp_path: Path):
    repo = _synthetic_repo(tmp_path)
    _commit(repo, "07-Archives/Meetings/customer-renewal.md", "Private meeting notes\n")

    result = _run_gate(repo)

    assert result.returncode == 1
    assert "07-Archives/Meetings/customer-renewal.md:1" in result.stderr


def test_pii_gate_blocks_configured_claude_user_profile(tmp_path: Path):
    repo = _synthetic_repo(tmp_path)
    _commit(
        repo,
        "CLAUDE.md",
        "# Dex\n\n## User Profile\n\n**Name:** Dana Realperson\n\n## Reference Documentation\n",
    )

    result = _run_gate(repo)

    assert result.returncode == 1
    assert "CLAUDE.md:5" in result.stderr


def test_pii_gate_blocks_real_usage_consent_identity(tmp_path: Path):
    repo = _synthetic_repo(tmp_path)
    _commit(repo, "System/usage_log.md", "**Consent identity:** Dana Realperson\n")

    result = _run_gate(repo)

    assert result.returncode == 1
    assert "System/usage_log.md:1" in result.stderr


def test_pii_gate_blocks_rename_only_move_into_personal_archive(tmp_path: Path):
    repo = _synthetic_repo(tmp_path)
    _commit(repo, "docs/public-note.md", "Content that was safe only in public docs.\n")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--ff-only", "contributor-change")
    _git(repo, "fetch", "origin", "main")
    _git(repo, "checkout", "-b", "rename-change")
    destination = repo / "07-Archives" / "Meetings" / "private-note.md"
    destination.parent.mkdir(parents=True)
    _git(repo, "mv", "docs/public-note.md", str(destination.relative_to(repo)))
    _git(repo, "commit", "-m", "fixture: rename into archive")

    result = _run_gate(repo)

    assert result.returncode == 1
    assert "07-Archives/Meetings/private-note.md:1" in result.stderr


def test_pii_gate_blocks_binary_personal_archive_content(tmp_path: Path):
    repo = _synthetic_repo(tmp_path)
    target = repo / "07-Archives" / "recording.bin"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\x00\x01\x02private fixture")
    _git(repo, "add", str(target.relative_to(repo)))
    _git(repo, "commit", "-m", "fixture: binary archive")

    result = _run_gate(repo)

    assert result.returncode == 1
    assert "07-Archives/recording.bin:1" in result.stderr


def test_pii_gate_blocks_flow_style_enabled_integration_identity(tmp_path: Path):
    repo = _synthetic_repo(tmp_path)
    _commit(
        repo,
        "System/integrations/slack.yaml",
        "{enabled: true, workspace: Real Company}\n",
    )

    result = _run_gate(repo)

    assert result.returncode == 1
    assert "System/integrations/slack.yaml:1" in result.stderr


def test_pii_gate_scans_added_lines_that_begin_with_two_plus_signs(tmp_path: Path):
    repo = _synthetic_repo(tmp_path)
    real_email = "dana" + "@real-company.io"
    _commit(repo, "docs/patch-notes.md", f"++ b/{real_email}\n")

    result = _run_gate(repo)

    assert result.returncode == 1
    assert "docs/patch-notes.md:1" in result.stderr


def test_pii_gate_uses_the_earliest_personal_root_in_nested_paths(tmp_path: Path):
    repo = _synthetic_repo(tmp_path)
    _commit(repo, "07-Archives/System/private.md", "Private archive content\n")

    result = _run_gate(repo)

    assert result.returncode == 1
    assert "07-Archives/System/private.md:1" in result.stderr


def test_pii_gate_blocks_identity_when_legacy_enabled_map_has_true_value(tmp_path: Path):
    repo = _synthetic_repo(tmp_path)
    _commit(
        repo,
        "System/integrations/config.yaml",
        "enabled:\n  slack: true\nidentity: Dana Realperson\n",
    )

    result = _run_gate(repo)

    assert result.returncode == 1
    assert "System/integrations/config.yaml:3" in result.stderr
