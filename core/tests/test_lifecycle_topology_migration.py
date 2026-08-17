"""Journey coverage for the guided brain/vault topology upgrade."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from core.lifecycle import service

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATOR_RELATIVE = Path("core/migrations/v1-to-v2-brain-vault-split.cjs")
REPORT_RELATIVE = Path("System/migration-report-v2.md")


def _write_fake_migrator(vault: Path, source: str) -> None:
    migrator = vault / MIGRATOR_RELATIVE
    migrator.parent.mkdir(parents=True)
    migrator.write_text(source, encoding="utf-8")


def _combined_vault(tmp_path: Path, migrator_source: str) -> Path:
    vault = tmp_path / "vault"
    (vault / ".git").mkdir(parents=True)
    _write_fake_migrator(vault, migrator_source)
    return vault


def _successful_migrator_source() -> str:
    return r"""
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const root = process.cwd();
const mode = process.argv[2];
const report = path.join(root, 'System', 'migration-report-v2.md');
fs.mkdirSync(path.dirname(report), { recursive: true });
fs.appendFileSync(path.join(root, 'calls.log'), `${mode}\n`);

if (mode === '--dry-run') {
  fs.writeFileSync(
    report,
    '# Your Dex brain and vault split\n\n'
      + 'This was a preview. Only this report was written; the split has not started.\n',
  );
  process.exit(0);
}

if (mode === '--auto') {
  fs.mkdirSync(path.join(root, 'System', '.dex'), { recursive: true });
  fs.writeFileSync(
    path.join(root, 'System', '.dex', 'migration-v2-state.json'),
    JSON.stringify({ schemaVersion: 1, status: 'needs-resume', nextPhase: 3 }),
  );
  process.exit(75);
}

if (mode === '--resume') {
  fs.mkdirSync(path.join(root, '.dex', 'brain.git'), { recursive: true });
  fs.writeFileSync(
    path.join(root, '.git', 'dex-vault-v2'),
    JSON.stringify({ role: 'vault' }),
  );
  fs.writeFileSync(
    path.join(root, '.dex', 'brain.git', 'dex-brain-v2'),
    JSON.stringify({ role: 'brain' }),
  );
  fs.writeFileSync(
    path.join(root, 'System', '.dex', 'topology.json'),
    JSON.stringify({
      topology: 'brain-vault-split',
      vaultGitDir: '.git',
      brainGitDir: '.dex/brain.git',
      environment: { DEX_VAULT: root },
    }),
  );
  fs.writeFileSync(
    path.join(root, 'System', '.dex', 'migration-v2-state.json'),
    JSON.stringify({ schemaVersion: 1, status: 'complete', nextPhase: 10 }),
  );
  fs.writeFileSync(
    report,
    '# Your Dex brain and vault split\n\nThe split is complete.\n',
  );
  process.exit(0);
}

process.exit(2);
"""


def test_combined_topology_previews_approval_converts_and_receipts(
    tmp_path: Path,
) -> None:
    vault = _combined_vault(tmp_path, _successful_migrator_source())

    previewed = service.build_and_preview_topology_migration(vault)

    assert previewed["api_version"] == "1.5.0"
    assert previewed["topology"] == "combined"
    assert previewed["preview"]["operation"] == "brain-vault-topology-migration"
    assert [
        group["id"] for group in previewed["preview"]["groups"]
    ] == [
        "new-and-safe-to-adopt",
        "needs-your-review",
        "held-back-by-you",
        "could-not-be-proved",
        "already-yours",
    ]
    review_items = previewed["preview"]["groups"][1]["items"]
    assert len(review_items) == 1
    assert review_items[0]["report_path"] == REPORT_RELATIVE.as_posix()
    assert "This was a preview" in review_items[0]["report_markdown"]

    executed = service.execute_approved_topology_migration(
        vault,
        previewed["preview"],
        previewed["approval_token"],
    )

    assert (vault / "System/.dex/topology.json").is_file()
    assert executed["api_version"] == "1.5.0"
    assert executed["receipt"]["operation"] == "brain-vault-topology-migration"
    assert executed["receipt"]["topology_before"] == "combined"
    assert executed["receipt"]["topology_after"] == "post-split"
    assert executed["receipt"]["preview_sha256"] == previewed["approval_token"]
    assert executed["receipt"]["attempts"] == [
        {"mode": "auto", "exit_code": 75},
        {"mode": "resume", "exit_code": 0},
    ]
    receipt_path = vault / executed["receipt_path"]
    assert receipt_path.is_file()
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == executed["receipt"]
    assert (vault / "calls.log").read_text(encoding="utf-8").splitlines() == [
        "--dry-run",
        "--dry-run",
        "--dry-run",
        "--auto",
        "--resume",
    ]


def test_topology_migration_refuses_without_exact_preview_approval(
    tmp_path: Path,
) -> None:
    vault = _combined_vault(tmp_path, _successful_migrator_source())
    previewed = service.build_and_preview_topology_migration(vault)

    with pytest.raises(
        service.TopologyMigrationError,
        match="approval token does not match the exact canonical preview",
    ):
        service.execute_approved_topology_migration(
            vault,
            previewed["preview"],
            "",
        )

    assert not (vault / "System/.dex/topology.json").exists()
    assert "--auto" not in (vault / "calls.log").read_text(encoding="utf-8")


def test_topology_migration_refuses_when_dry_run_fails(tmp_path: Path) -> None:
    vault = _combined_vault(
        tmp_path,
        r"""
'use strict';
if (process.argv[2] === '--dry-run') {
  console.error('P0 could not prove the release history');
  process.exit(42);
}
process.exit(2);
""",
    )

    with pytest.raises(
        service.TopologyMigrationError,
        match="dry-run failed.*P0 could not prove the release history",
    ):
        service.build_and_preview_topology_migration(vault)

    assert not (vault / "System/.dex/topology.json").exists()


def test_topology_preview_refuses_non_combined_topology(tmp_path: Path) -> None:
    vault = _combined_vault(tmp_path, _successful_migrator_source())
    (vault / ".git/dex-vault-v2").write_text('{"role":"vault"}\n', encoding="utf-8")
    (vault / ".dex/brain.git").mkdir(parents=True)
    (vault / ".dex/brain.git/dex-brain-v2").write_text(
        '{"role":"brain"}\n',
        encoding="utf-8",
    )
    (vault / "System/.dex").mkdir(parents=True)
    (vault / "System/.dex/topology.json").write_text(
        json.dumps(
            {
                "topology": "brain-vault-split",
                "vaultGitDir": ".git",
                "brainGitDir": ".dex/brain.git",
                "environment": {"DEX_VAULT": str(vault.resolve())},
            }
        ),
        encoding="utf-8",
    )

    response = service.build_and_preview_topology_migration(vault)

    assert response["topology"] == "post-split"
    assert response["approval_token"] is None
    assert response["preview"]["groups"][4]["items"][0]["status"] == "complete"


def test_dex_update_skill_routes_the_guided_migration_through_service() -> None:
    instructions = (
        REPO_ROOT / ".claude/skills/dex-update/SKILL.md"
    ).read_text(encoding="utf-8")

    assert "version 1.5.0" in instructions
    assert "build_and_preview_topology_migration" in instructions
    assert "execute_approved_topology_migration" in instructions
    assert "dry-run" in instructions
    assert "five groups" in instructions
    assert "explicit yes" in instructions
    assert "approval token" in instructions
    assert "exit code 75" in instructions
    assert "receipt" in instructions


def test_real_migrator_completes_the_service_guided_journey() -> None:
    fixture = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/make-aged-vault-fixture.sh")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=180,
    )
    marker = "Fixture ready: "
    vault = Path(
        next(
            line.removeprefix(marker)
            for line in fixture.stdout.splitlines()
            if line.startswith(marker)
        )
    )
    task_path = vault / "03-Tasks/Tasks.md"
    task_bytes = task_path.read_bytes()
    try:
        previewed = service.build_and_preview_topology_migration(vault)
        executed = service.execute_approved_topology_migration(
            vault,
            previewed["preview"],
            previewed["approval_token"],
        )

        assert task_path.read_bytes() == task_bytes
        assert service.build_and_preview_topology_migration(vault)["topology"] == "post-split"
        assert executed["receipt"]["topology_after"] == "post-split"
        assert (vault / ".dex/pre-split-archive.git").is_dir()
        assert (vault / executed["receipt_path"]).is_file()
    finally:
        shutil.rmtree(vault)
