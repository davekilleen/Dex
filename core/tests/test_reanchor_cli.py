"""The interactive release re-anchoring flow: consent gates that are real.

Red-when-removed coverage for the adversarial-review conditions owned by the
consent lane (docs/superpowers/specs/2026-09-05-anchor-seam-adversarial-review.md):

- **C8** — every consent is a genuine TTY read: the flow refuses when stdin
  is not a TTY (no flag, no environment variable, no argument bypass — a
  ``--yes`` flag must NOT exist); generation is unreachable without the first
  confirmation and the write is unreachable without the second; the TTY check
  runs at the moment of EACH act; no MCP tool reaches the flow (extended in
  test_release_anchor_generation); neither the operation nor any consent is
  ever read from tool arguments, plan files, or anchor content.
- **C12** — the CLI accepts no version or tag argument; the release to prove
  is derived from the installed catalog's manifest-bound claim.
- **Ruling 6** — the flow is the anchor's only creator: neither the update
  transaction (core/update/apply_update.py) nor the lifecycle service's
  update path references anchor generation.
"""

from __future__ import annotations

import io
import os
import pty
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from core.lifecycle.customizations import load_release_baseline
from core.lifecycle.release_anchor import (
    RELEASE_ANCHOR_PATH,
    RELEASE_ANCHOR_RECEIPT_PATH,
)
from core.tests.test_release_anchor_generation import (
    _release_repo,
    _vault_with_brain,
)
from core.update import reanchor_cli

REPO_ROOT = Path(__file__).resolve().parents[2]

UNPROVED = "release-identity-unproved"


class _FakeTty(io.StringIO):
    """Monkeypatched stdin whose isatty answers are scripted per call."""

    def __init__(self, text: str, isatty_answers: tuple[bool, ...] = (True,) * 8):
        super().__init__(text)
        self._answers = list(isatty_answers)

    def isatty(self) -> bool:  # noqa: D102 - stdlib signature
        return self._answers.pop(0) if self._answers else False


@pytest.fixture
def anchored_vault(tmp_path: Path) -> Path:
    fixture = _release_repo(tmp_path)
    return _vault_with_brain(tmp_path, fixture)


def _run_flow(
    vault: Path,
    monkeypatch,
    capsys,
    *,
    stdin: io.StringIO,
    arguments: list[str] | None = None,
) -> tuple[int, str]:
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(sys, "stdin", stdin)
    return_code = reanchor_cli.run(arguments if arguments is not None else [])
    return return_code, capsys.readouterr().out


def _unproved_count(vault: Path) -> int:
    from core.customization_migration.service import assess

    return sum(
        1 for exclusion in assess(vault).exclusions if exclusion.reason == UNPROVED
    )


def _nothing_written(vault: Path) -> None:
    assert not (vault / RELEASE_ANCHOR_PATH).exists()
    assert not (vault / RELEASE_ANCHOR_RECEIPT_PATH).exists()


# ---------------------------------------------------------------------------
# C8 — the flow refuses when stdin is not a TTY; nothing bypasses it.
# ---------------------------------------------------------------------------


def test_flow_refuses_without_a_tty_even_with_yes_piped_in(
    anchored_vault: Path,
) -> None:
    # Both yeses are sitting on a PIPED stdin. Deleting the isatty gate would
    # let the flow read them and write the anchor — turning this test red.
    env = os.environ.copy()
    env.update({"PYTHONPATH": str(REPO_ROOT), "VAULT_PATH": str(anchored_vault)})
    result = subprocess.run(
        [sys.executable, "-m", "core.update.reanchor_cli"],
        input="yes\nyes\n",
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "needs you at the keyboard" in result.stdout
    assert "Nothing was changed" in result.stdout
    _nothing_written(anchored_vault)


def test_tty_is_rechecked_at_the_moment_of_each_consent(
    anchored_vault: Path, monkeypatch, capsys
) -> None:
    # A TTY for gate 1 that stops being one before gate 3: the write must be
    # unreachable. Deleting the per-act isatty check turns this red.
    stdin = _FakeTty("yes\nyes\n", isatty_answers=(True, False))

    return_code, output = _run_flow(anchored_vault, monkeypatch, capsys, stdin=stdin)

    assert return_code == 2
    assert "needs you at the keyboard" in output
    _nothing_written(anchored_vault)


def test_flow_has_no_yes_flag_and_accepts_no_arguments() -> None:
    # C8 (no bypass flag) + C12 (no version or tag argument): the parser
    # defines nothing beyond --help. Adding ANY argument turns this red.
    parser = reanchor_cli._parser()
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    assert option_strings == {"-h", "--help"}
    assert all(action.dest == "help" for action in parser._actions)

    with pytest.raises(SystemExit):
        reanchor_cli.run(["--yes"])
    with pytest.raises(SystemExit):
        reanchor_cli.run(["--version-to-prove", "1.64.0"])
    with pytest.raises(SystemExit):
        reanchor_cli.run(["dist/release/v1.64.0-0000000"])


def test_flow_reads_no_consent_from_environment_or_arguments() -> None:
    # The only environment variable the module may consult is VAULT_PATH
    # (which locates the vault, never consents to anything), and the
    # transaction operation value never appears here — it is the write seam's
    # hardcoded literal (pinned in test_release_anchor_generation).
    source = Path(reanchor_cli.__file__).read_text(encoding="utf-8")
    assert source.count("os.environ") == 1
    assert 'os.environ.get("VAULT_PATH")' in source
    # The parser defines no arguments at all: no flag, no positional, nothing
    # that could carry a consent, a version, a tag, or an operation.
    assert "add_argument" not in source
    assert "operation=" not in source


# ---------------------------------------------------------------------------
# C8 — generation and the write are unreachable without their confirmations.
# ---------------------------------------------------------------------------


def test_declining_gate_one_never_generates_and_writes_nothing(
    anchored_vault: Path, monkeypatch, capsys
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        reanchor_cli,
        "generate_release_anchor",
        lambda root: calls.append("generate"),
    )
    monkeypatch.setattr(
        reanchor_cli,
        "write_release_anchor",
        lambda *a, **k: calls.append("write"),
    )

    return_code, output = _run_flow(
        anchored_vault, monkeypatch, capsys, stdin=_FakeTty("no\n")
    )

    assert return_code == 2
    assert "nothing was changed" in output.casefold()
    assert calls == []
    _nothing_written(anchored_vault)


def test_declining_the_write_gate_previews_but_writes_nothing(
    anchored_vault: Path, monkeypatch, capsys
) -> None:
    return_code, output = _run_flow(
        anchored_vault, monkeypatch, capsys, stdin=_FakeTty("yes\nno\n")
    )

    assert return_code == 2
    # The preview ran (real generation) ...
    assert "nothing is saved yet" in output
    assert "Proof fingerprint" in output
    # ... but declining gate 3 leaves the vault untouched.
    assert "nothing was changed" in output.casefold()
    _nothing_written(anchored_vault)


def test_eof_at_a_consent_prompt_declines(
    anchored_vault: Path, monkeypatch, capsys
) -> None:
    return_code, _output = _run_flow(
        anchored_vault, monkeypatch, capsys, stdin=_FakeTty("")
    )

    assert return_code == 2
    _nothing_written(anchored_vault)


# ---------------------------------------------------------------------------
# The happy path: unproved before, two real yeses, anchor written, the deep
# assessment returns to completeness OK.
# ---------------------------------------------------------------------------


def test_happy_path_reanchors_and_unblocks_the_assessment(
    anchored_vault: Path, monkeypatch, capsys
) -> None:
    from core.customization_migration.service import assess

    before = assess(anchored_vault)
    assert before.completeness == "UNKNOWN"
    assert _unproved_count(anchored_vault) == 3

    return_code, output = _run_flow(
        anchored_vault, monkeypatch, capsys, stdin=_FakeTty("yes\nyes\n")
    )

    assert return_code == 0, output
    assert "can't currently be proved" in output
    assert "nothing is saved yet" in output
    assert "Proof saved and double-checked." in output
    assert (anchored_vault / RELEASE_ANCHOR_PATH).is_file()
    assert (anchored_vault / RELEASE_ANCHOR_RECEIPT_PATH).is_file()

    baseline = load_release_baseline(anchored_vault)
    assert baseline.anchor_state == "verified"
    assert baseline.errors == ()
    assert _unproved_count(anchored_vault) == 0

    # The anchor stands alone: with the generation-time evidence gone (the
    # brain store and the fixture's bare .git scaffolding, whose directory
    # names alone produce dependency-tree exclusions), the deep assessment
    # returns to completeness OK on the anchor's proof.
    shutil.rmtree(anchored_vault / ".dex")
    shutil.rmtree(anchored_vault / ".git")
    (anchored_vault / "System/.dex/topology.json").unlink()
    after = assess(anchored_vault)
    assert after.completeness == "OK"
    assert after.verdict == "OK"
    assert not any(e.reason == UNPROVED for e in after.exclusions)


def test_happy_path_output_names_the_previewed_digest(
    anchored_vault: Path, monkeypatch, capsys
) -> None:
    from core.update.anchor_generation import generate_release_anchor

    expected_digest = generate_release_anchor(anchored_vault).document_sha256

    _return_code, output = _run_flow(
        anchored_vault, monkeypatch, capsys, stdin=_FakeTty("yes\nyes\n")
    )

    assert expected_digest in output


# ---------------------------------------------------------------------------
# The honest stop: local sources cannot prove the release — no fetch, no
# write, a plain statement (the slice-3 fetch seam stays empty in this lane).
# ---------------------------------------------------------------------------


def test_local_sources_failing_stops_honestly_without_writing(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    fixture = _release_repo(tmp_path)
    # The installed catalog claims 1.63.0; only an official 1.64.0 tag exists
    # locally, so no local source verifies (and nothing may substitute the
    # derived claim — C12).
    vault = _vault_with_brain(tmp_path, fixture, claimed_version="1.63.0")

    return_code, output = _run_flow(
        vault, monkeypatch, capsys, stdin=_FakeTty("yes\nyes\n")
    )

    assert return_code == 2
    assert "couldn't find a copy of your installed version" in output
    assert "nothing was saved" in output.casefold()
    assert "can't do yet" in output
    _nothing_written(vault)


def test_flow_spawns_no_network_subprocess_in_the_local_lane(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    # This lane is LOCAL-only: even when local sources fail, no fetch runs.
    # The slice-3 fallback must add its own consent gate 2 before any fetch.
    fixture = _release_repo(tmp_path)
    vault = _vault_with_brain(tmp_path, fixture, claimed_version="1.63.0")
    fetched: list[list[str]] = []
    real_run = subprocess.run

    def _watch(command, *args, **kwargs):
        if isinstance(command, (list, tuple)) and any(
            isinstance(part, str) and part == "fetch" for part in command
        ):
            fetched.append(list(command))
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _watch)

    return_code, _output = _run_flow(
        vault, monkeypatch, capsys, stdin=_FakeTty("yes\nyes\n")
    )

    assert return_code == 2
    assert fetched == []


# ---------------------------------------------------------------------------
# Nothing to repair: an already-proved vault exits without asking anything.
# ---------------------------------------------------------------------------


def test_already_anchored_vault_reports_nothing_to_repair(
    anchored_vault: Path, monkeypatch, capsys
) -> None:
    _run_flow(anchored_vault, monkeypatch, capsys, stdin=_FakeTty("yes\nyes\n"))

    # Second run: everything is proved; no consent prompt is reached (the
    # scripted stdin would answer it, so a reached prompt would regenerate).
    first_bytes = (anchored_vault / RELEASE_ANCHOR_PATH).read_bytes()
    return_code, output = _run_flow(
        anchored_vault, monkeypatch, capsys, stdin=_FakeTty("yes\nyes\n")
    )

    assert return_code == 0
    assert "nothing here for this repair to fix" in output.casefold()
    assert (anchored_vault / RELEASE_ANCHOR_PATH).read_bytes() == first_bytes


# ---------------------------------------------------------------------------
# A real pseudo-terminal drives the full journey end to end.
# ---------------------------------------------------------------------------


def test_pty_journey_both_yeses_write_the_anchor(anchored_vault: Path) -> None:
    env = os.environ.copy()
    env.update({"PYTHONPATH": str(REPO_ROOT), "VAULT_PATH": str(anchored_vault)})
    controller, follower = pty.openpty()
    try:
        child = subprocess.Popen(
            [sys.executable, "-m", "core.update.reanchor_cli"],
            cwd=REPO_ROOT,
            env=env,
            stdin=follower,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        os.close(follower)
        os.write(controller, b"yes\nyes\n")
        stdout, stderr = child.communicate(timeout=120)
    finally:
        os.close(controller)

    assert child.returncode == 0, stdout + stderr
    assert "Proof saved and double-checked." in stdout
    assert (anchored_vault / RELEASE_ANCHOR_PATH).is_file()
    assert (anchored_vault / RELEASE_ANCHOR_RECEIPT_PATH).is_file()


def test_pty_journey_declined_write_leaves_nothing(anchored_vault: Path) -> None:
    env = os.environ.copy()
    env.update({"PYTHONPATH": str(REPO_ROOT), "VAULT_PATH": str(anchored_vault)})
    controller, follower = pty.openpty()
    try:
        child = subprocess.Popen(
            [sys.executable, "-m", "core.update.reanchor_cli"],
            cwd=REPO_ROOT,
            env=env,
            stdin=follower,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        os.close(follower)
        os.write(controller, b"yes\nno\n")
        stdout, stderr = child.communicate(timeout=120)
    finally:
        os.close(controller)

    assert child.returncode == 2, stdout + stderr
    _nothing_written(anchored_vault)


# ---------------------------------------------------------------------------
# Ruling 6 — on demand only: the flow is the anchor's only creator; nothing
# hooks generation into the update transaction or the lifecycle update path.
# ---------------------------------------------------------------------------


def test_unproved_guidance_points_at_the_reanchor_flow() -> None:
    # The design's guidance correction (ruling 5, second half): once the flow
    # exists, the release-identity-unproved guidance names the real remedy
    # instead of the interim "a guided repair is coming" wording — and still
    # never routes the user through the unprotected update.
    from core.customization_migration.model import EXCLUSION_GUIDANCE

    guidance = EXCLUSION_GUIDANCE["release-identity-unproved"]

    assert "guided repair" in guidance
    assert "/dex-doctor" in guidance
    assert "update until that's done" in guidance
    assert "coming" not in guidance


def test_update_and_lifecycle_paths_never_reference_anchor_generation() -> None:
    forbidden = (
        "anchor_generation",
        "generate_release_anchor",
        "write_release_anchor",
        "reanchor",
    )
    for relative in (
        "core/update/apply_update.py",
        "core/update/journey_protocol.py",
        "core/lifecycle/service.py",
        "core/lifecycle/engine.py",
    ):
        source = (REPO_ROOT / relative).read_text(encoding="utf-8")
        hits = [name for name in forbidden if name in source]
        assert not hits, f"{relative} references {hits}"
