"""A moved or copied vault is relocated, not invalid — and refusals say why.

Two contracts live here.

The first is that a brain/vault split whose structure is entirely intact but
whose recorded vault path names somewhere else is *relocated*. The recorded path
is an absolute path held in local runtime state, so copying, moving, or renaming
a vault makes it stale as a matter of course. Nothing reads that value as a path
— every consumer derives its paths from the vault root it was handed — so a
stale one cannot redirect a read or a write, and treating it as damage locked
any relocated vault out of updating at all.

The second is that every refusal names the condition that failed. The previous
message ("the current layout is invalid-split; Dex will not guess how to convert
it") cost a beta user an hour of reading engine.py to discover which of nine
checks had tripped.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from core.lifecycle import engine, service

MIGRATOR_RELATIVE = Path("core/migrations/v1-to-v2-brain-vault-split.cjs")


def _split_vault(root: Path) -> Path:
    """A structurally sound brain/vault split that records its own location."""
    (root / ".git").mkdir(parents=True)
    (root / ".git/dex-vault-v2").write_text('{"role":"vault"}\n', encoding="utf-8")
    (root / ".dex/brain.git").mkdir(parents=True)
    (root / ".dex/brain.git/dex-brain-v2").write_text(
        '{"role":"brain"}\n',
        encoding="utf-8",
    )
    (root / "System/.dex").mkdir(parents=True)
    (root / "System/.dex/topology.json").write_text(
        json.dumps(
            {
                "topology": "brain-vault-split",
                "vaultGitDir": ".git",
                "brainGitDir": ".dex/brain.git",
                "installedRelease": "a" * 40,
                "environment": {"DEX_VAULT": str(root.resolve())},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def _recorded(vault: Path) -> str:
    topology = json.loads(
        (vault / "System/.dex/topology.json").read_text(encoding="utf-8")
    )
    return topology["environment"]["DEX_VAULT"]


def _edit_topology(root: Path, **fields: object) -> None:
    path = root / "System/.dex/topology.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value.update(fields)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def test_split_vault_that_never_moved_is_post_split_and_not_relocated(
    tmp_path: Path,
) -> None:
    vault = _split_vault(tmp_path / "Dex")

    assert engine.split_layout_failures(vault) == ()
    assert engine.relocated_split(vault) is False
    assert engine.topology_state(vault) == "post-split"
    assert service.build_and_preview_topology_migration(vault)["topology"] == "post-split"


def test_copied_split_vault_is_accepted_as_post_split(tmp_path: Path) -> None:
    """A duplicate of a sound vault is relocated, not invalid.

    Every structural condition passes identically in the copy; only the recorded
    absolute path still names the original.
    """
    original = _split_vault(tmp_path / "Dex")
    duplicate = tmp_path / "Documents" / "Dex"
    duplicate.parent.mkdir(parents=True)
    shutil.copytree(original, duplicate, symlinks=True)

    assert Path(_recorded(duplicate)) == original
    assert engine.split_layout_failures(duplicate) == ()
    assert engine.relocated_split(duplicate) is True
    assert engine.topology_state(duplicate) == "post-split"
    assert service.build_and_preview_topology_migration(duplicate)["topology"] == "post-split"


def test_moved_split_vault_is_accepted_as_post_split(tmp_path: Path) -> None:
    """Moving ~/Dex to ~/Documents/Dex must not lock the vault out of updating."""
    original = _split_vault(tmp_path / "Dex")
    moved = tmp_path / "Documents" / "Dex"
    moved.parent.mkdir(parents=True)
    shutil.move(str(original), str(moved))

    assert engine.relocated_split(moved) is True
    assert engine.topology_state(moved) == "post-split"
    assert service.build_and_preview_topology_migration(moved)["topology"] == "post-split"


def test_classifying_a_relocated_vault_changes_nothing_on_disk(
    tmp_path: Path,
) -> None:
    """topology_state documents itself as read-only; tolerating must not write."""
    original = _split_vault(tmp_path / "Dex")
    duplicate = tmp_path / "Documents" / "Dex"
    duplicate.parent.mkdir(parents=True)
    shutil.copytree(original, duplicate, symlinks=True)
    marker = duplicate / "System/.dex/topology.json"
    before = marker.read_bytes()

    assert engine.topology_state(duplicate) == "post-split"
    assert engine.relocated_split(duplicate) is True
    assert engine.topology_refusal_detail(duplicate, "post-split")
    assert service.build_and_preview_topology_migration(duplicate)["topology"] == "post-split"

    assert marker.read_bytes() == before


def test_a_relocated_vault_that_resolves_to_the_same_place_is_not_relocated(
    tmp_path: Path,
) -> None:
    """A recorded path that merely spells the vault differently is not stale."""
    vault = _split_vault(tmp_path / "Dex")
    _edit_topology(
        vault,
        environment={"DEX_VAULT": str(vault / "." / "..") + f"/{vault.name}"},
    )

    assert engine.relocated_split(vault) is False
    assert engine.topology_state(vault) == "post-split"


_STRUCTURAL_BREAKS: tuple[tuple[str, object, str], ...] = (
    (
        "wrong-vault-git-dir",
        lambda root: _edit_topology(root, vaultGitDir=".vault.git"),
        "records vaultGitDir '.vault.git' instead of '.git'",
    ),
    (
        "wrong-brain-git-dir",
        lambda root: _edit_topology(root, brainGitDir=".dex/other.git"),
        "records brainGitDir '.dex/other.git' instead of '.dex/brain.git'",
    ),
    (
        "no-recorded-vault-path",
        lambda root: _edit_topology(root, environment={}),
        "records no environment.DEX_VAULT path",
    ),
    (
        "non-string-recorded-vault-path",
        lambda root: _edit_topology(root, environment={"DEX_VAULT": 7}),
        "records no environment.DEX_VAULT path",
    ),
    (
        "empty-recorded-vault-path",
        lambda root: _edit_topology(root, environment={"DEX_VAULT": ""}),
        "records no environment.DEX_VAULT path",
    ),
    (
        "symlinked-vault-git",
        lambda root: (
            shutil.rmtree(root / ".git"),
            (root / "elsewhere.git").mkdir(),
            (root / ".git").symlink_to(root / "elsewhere.git"),
        ),
        ".git is a symbolic link, which Dex refuses to follow",
    ),
    (
        "symlinked-brain-git",
        lambda root: (
            shutil.rmtree(root / ".dex/brain.git"),
            (root / ".dex/elsewhere.git").mkdir(),
            (root / ".dex/brain.git").symlink_to(root / ".dex/elsewhere.git"),
        ),
        ".dex/brain.git is a symbolic link, which Dex refuses to follow",
    ),
    (
        "missing-vault-git",
        lambda root: shutil.rmtree(root / ".git"),
        ".git is missing or is not a directory",
    ),
    (
        "missing-brain-git",
        lambda root: shutil.rmtree(root / ".dex/brain.git"),
        ".dex/brain.git is missing or is not a directory",
    ),
    (
        "missing-vault-marker",
        lambda root: (root / ".git/dex-vault-v2").unlink(),
        ".git/dex-vault-v2 is missing or unreadable",
    ),
    (
        "wrong-vault-marker-role",
        lambda root: (root / ".git/dex-vault-v2").write_text(
            '{"role":"brain"}\n', encoding="utf-8"
        ),
        ".git/dex-vault-v2 records role 'brain' instead of 'vault'",
    ),
    (
        "missing-brain-marker",
        lambda root: (root / ".dex/brain.git/dex-brain-v2").unlink(),
        ".dex/brain.git/dex-brain-v2 is missing or unreadable",
    ),
    (
        "wrong-brain-marker-role",
        lambda root: (root / ".dex/brain.git/dex-brain-v2").write_text(
            '{"role":"vault"}\n', encoding="utf-8"
        ),
        ".dex/brain.git/dex-brain-v2 records role 'vault' instead of 'brain'",
    ),
)


@pytest.mark.parametrize(
    ("label", "break_layout", "expected_clause"),
    _STRUCTURAL_BREAKS,
    ids=[entry[0] for entry in _STRUCTURAL_BREAKS],
)
def test_each_structural_break_is_still_refused_and_names_itself(
    tmp_path: Path,
    label: str,
    break_layout: object,
    expected_clause: str,
) -> None:
    """Tolerating relocation tolerates nothing else, and each cause explains itself."""
    vault = _split_vault(tmp_path / label)
    break_layout(vault)

    assert engine.topology_state(vault) == "invalid-split"
    assert engine.relocated_split(vault) is False
    assert any(
        expected_clause in failure for failure in engine.split_layout_failures(vault)
    )

    with pytest.raises(service.TopologyMigrationError) as refusal:
        service.build_and_preview_topology_migration(vault)
    assert expected_clause in str(refusal.value)
    assert "Dex will not guess how to convert it" in str(refusal.value)


@pytest.mark.parametrize(
    ("label", "break_layout", "expected_clause"),
    _STRUCTURAL_BREAKS,
    ids=[entry[0] for entry in _STRUCTURAL_BREAKS],
)
def test_a_structural_break_in_a_relocated_vault_is_still_refused(
    tmp_path: Path,
    label: str,
    break_layout: object,
    expected_clause: str,
) -> None:
    """Relocation is tolerable only when every other condition passes."""
    original = _split_vault(tmp_path / "Dex")
    duplicate = tmp_path / "Documents" / label
    duplicate.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(original, duplicate, symlinks=True)
    break_layout(duplicate)

    assert engine.topology_state(duplicate) == "invalid-split"
    assert engine.relocated_split(duplicate) is False
    with pytest.raises(service.TopologyMigrationError) as refusal:
        service.build_and_preview_topology_migration(duplicate)
    assert expected_clause in str(refusal.value)


def test_a_marker_that_records_no_split_at_all_is_refused(tmp_path: Path) -> None:
    vault = _split_vault(tmp_path / "Dex")
    _edit_topology(vault, topology="something-else")

    # A marker that does not claim the split is not an invalid split; it falls
    # through to the ordinary combined/zip classification, which still refuses.
    assert engine.topology_state(vault) != "post-split"
    assert engine.relocated_split(vault) is False
    assert engine.split_layout_failures(vault) == (
        "System/.dex/topology.json does not record a brain/vault split",
    )


def test_every_unconvertible_layout_says_which_condition_stopped_it(
    tmp_path: Path,
) -> None:
    """Nobody should have to read Dex's source to learn why they were refused."""
    downloaded = tmp_path / "downloaded"
    (downloaded / "System").mkdir(parents=True)

    too_old = tmp_path / "too-old"
    (too_old / ".git").mkdir(parents=True)

    stalled = tmp_path / "stalled"
    (stalled / ".git").mkdir(parents=True)
    (stalled / "System/.dex").mkdir(parents=True)
    (stalled / "System/.dex/migration-v2-state.json").write_text(
        '{"status":"staging"}\n',
        encoding="utf-8",
    )

    leftovers = tmp_path / "leftovers"
    (leftovers / ".git").mkdir(parents=True)
    (leftovers / ".dex/vault-staging.git").mkdir(parents=True)

    expectations = (
        (downloaded, "zip-or-manual", "has no .git directory"),
        (too_old, "invalid-combined", MIGRATOR_RELATIVE.as_posix()),
        (stalled, "migration-in-progress", "stopped at 'staging'"),
        (leftovers, "migration-in-progress", ".dex/vault-staging.git behind"),
    )
    for vault, expected_state, expected_clause in expectations:
        assert engine.topology_state(vault) == expected_state
        with pytest.raises(service.TopologyMigrationError) as refusal:
            service.build_and_preview_topology_migration(vault)
        assert expected_state in str(refusal.value)
        assert expected_clause in str(refusal.value)
