"""The interactive release re-anchoring flow (Doctor's guided repair).

This is the consent lane of the customization re-anchoring design
(docs/superpowers/specs/2026-09-04-customization-reanchoring-design.md), built
under the adversarial review's conditions
(docs/superpowers/specs/2026-09-05-anchor-seam-adversarial-review.md):

- **C8 — consent is a genuine interactive act.** Every confirmation in this
  flow is read from a real terminal at the moment of the act. When stdin is
  not a TTY the flow refuses to proceed — there is no ``--yes`` flag, no
  environment-variable bypass, and no argument that substitutes for a person
  saying yes. This deliberately does NOT repeat the confirm-token pattern of
  ``core.customization_migration.cli``, whose token a model can mint by
  running the preview (review finding F3, §2.5). No MCP tool reaches this
  module, and neither the ``operation`` value nor any consent is ever read
  from tool arguments, plan files, or anchor content.
- **C12 — the release to prove is derived, never supplied.** The command
  accepts no version or tag argument; ``generate_release_anchor`` derives the
  claim from the installed catalog's manifest-bound identity.
- **Ruling 6 — on demand only.** This flow is the only creator of the release
  anchor. Nothing hooks anchor generation into the update transaction or any
  automatic path.
- **Ruling 3 — the network-fetch consent (gate 2) lives inside this flow** as
  its own explicit yes/no when slice 3 ships. This lane uses LOCAL sources
  only; the clearly marked seam below is where the fetch fallback goes.

Run it from the vault folder::

    python3 -m core.update.reanchor_cli

The vault root comes from ``VAULT_PATH`` when set, otherwise the current
directory. That is the only environment variable this module reads.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from core.customization_migration import service as migration_service
from core.lifecycle.catalog import release_bytes_match
from core.lifecycle.customizations import load_release_baseline
from core.lifecycle.filesystem import FilesystemInspectionError, bounded_read
from core.lifecycle.release_anchor import (
    RELEASE_ANCHOR_PATH,
    brain_owned_rows,
)
from core.update.anchor_generation import (
    AnchorGenerationError,
    generate_release_anchor,
    write_release_anchor,
)

_UNPROVED_REASON = "release-identity-unproved"
# Per-file cap for the preview's on-disk comparison reads. Release-owned
# files are far smaller than this; anything over the cap is honestly counted
# as unreadable rather than silently classified.
_PREVIEW_READ_BYTES = 16 * 1024 * 1024

# ---------------------------------------------------------------------------
# FOUNDER COPY - DRAFT PENDING APPROVAL (re-anchoring design, ruling 5).
# Every user-visible string in this flow is tester-visible copy: the founder
# approves the verbatim wording before release. Do not treat any string below
# as final, and do not quote it in shipped documentation until approved.
# ---------------------------------------------------------------------------
_NOT_A_TERMINAL = (
    "This repair needs you at the keyboard: Dex asks for your yes before it "
    "checks anything, and again before it saves anything, and only a person "
    "can answer.\n"
    "Open the Terminal app in your Dex vault folder and run:\n"
    "    python3 -m core.update.reanchor_cli\n"
    "Nothing was changed."
)
_GATE_1_PROMPT = (
    "Compare these files with the official copy of your installed version "
    "now? This step only looks — you'll see what it found, and be asked "
    "again before anything is saved. [yes/no] "
)
_GATE_3_PROMPT = (
    "Save this proof so Dex can vouch for these files from now on? [yes/no] "
)
_DECLINED = "Understood — nothing was changed."
# --- SLICE-3 SEAM: the network-fetch fallback (consent gate 2) -------------
# When no local source verifies the installed release, founder ruling 3
# places the bounded, fetch-only retrieval of the one matching
# ``dist/release/v*`` tag HERE, inside this flow, behind its own explicit
# interactive yes/no (consent gate 2) collected exactly like gates 1 and 3 —
# never a flag, never an environment variable, never an MCP argument. The
# fetch lands in the isolated bare evidence cache (the release-awareness
# transport) and re-runs ``verify_local_release_tag`` with ``git_dir``
# pointed at that cache — the C5 variant already takes the parameter. Until
# that slice ships, the flow stops honestly with the message below. No
# network operation may ever be added upstream of this point.
# ---------------------------------------------------------------------------
_LOCAL_SOURCES_FAILED = (
    "Dex couldn't find a copy of your installed version on this computer "
    "that it can trust, so nothing was saved and nothing changed.\n"
    "What Dex found: {error}\n"
    "Checking against the official copy online is a separate step this "
    "repair can't do yet — when it can, it will always ask you first "
    "before going online."
)


class _NotInteractive(RuntimeError):
    """stdin is not a terminal; consent cannot be collected."""


def _parser() -> argparse.ArgumentParser:
    # C12 + C8: the parser deliberately defines NO arguments and NO flags.
    # There is no version, no tag, no --yes, and nothing that names an
    # operation. Adding any argument here is a frozen-consent-contract
    # change and must fail the red-when-removed tests.
    return argparse.ArgumentParser(
        prog="python3 -m core.update.reanchor_cli",
        description=(
            "Interactively re-anchor this vault's files to the installed "
            "release's verified record. Asks before running and again before "
            "writing; refuses to run without a terminal."
        ),
    )


def _root() -> Path:
    return migration_service.resolve_vault_root(
        os.environ.get("VAULT_PATH") or Path.cwd()
    )


def _stdin_is_tty() -> bool:
    try:
        return bool(sys.stdin.isatty())
    except (AttributeError, OSError, ValueError):
        return False


def _interactive_yes(prompt: str) -> bool:
    """One consent: a TTY check at the moment of the act, then a line read.

    C8: the check runs immediately before EVERY read, so a consent later in
    the flow cannot ride on a check performed earlier. Anything but an
    explicit yes — including EOF and an interrupt — declines.
    """
    if not _stdin_is_tty():
        raise _NotInteractive()
    print(prompt, end="", flush=True)
    try:
        line = sys.stdin.readline()
    except (KeyboardInterrupt, OSError):
        return False
    if not line:
        return False
    return line.strip().casefold() in {"y", "yes"}


def _unproved_paths(assessment) -> tuple[str, ...]:
    return tuple(
        exclusion.path
        for exclusion in assessment.exclusions
        if exclusion.reason == _UNPROVED_REASON
    )


def _preview_counts(
    vault_root: Path,
    generation,
    *,
    manifest_paths: frozenset[str],
    unproved: tuple[str, ...],
) -> dict[str, int]:
    """Classify what the anchor will prove, before anything is written.

    Uses the same merge-time row filter the consumer applies (C6), so the
    preview counts exactly the rows that will take effect, and the same
    centralized CRLF byte tolerance every release comparison uses.
    """
    files = generation.document["files"]
    assert isinstance(files, dict)
    rows = brain_owned_rows(files, manifest_paths=manifest_paths)
    counts = {
        "release-pristine": 0,
        "release-modified": 0,
        "missing-from-disk": 0,
        "unreadable": 0,
        "still-unproved": len(set(unproved) - set(rows)),
    }
    for path, expected_sha256 in sorted(rows.items()):
        target = vault_root / path
        try:
            present = target.is_symlink() or target.exists()
        except OSError:
            present = True
        if not present:
            counts["missing-from-disk"] += 1
            continue
        try:
            raw = bounded_read(vault_root, path, max_bytes=_PREVIEW_READ_BYTES)
        except FilesystemInspectionError:
            counts["unreadable"] += 1
            continue
        if release_bytes_match(expected_sha256, raw):
            counts["release-pristine"] += 1
        else:
            counts["release-modified"] += 1
    return counts


def _report_current_state(root: Path) -> tuple[tuple[str, ...], object]:
    """Plain-words report of the unproved state; returns (unproved, baseline)."""
    assessment = migration_service.assess(root)
    baseline = load_release_baseline(root)
    unproved = _unproved_paths(assessment)
    # FOUNDER COPY - DRAFT PENDING APPROVAL: state-report wording.
    if baseline.identity_state != "VERIFIED":
        print(
            "Dex can't tell which version is installed in this vault, so "
            "there's nothing to check these files against. The repair "
            "can't run here; nothing was changed."
        )
        return unproved, baseline
    version = baseline.release_version
    print(f"Version this vault's records say is installed: v{version}")
    if unproved:
        print(
            f"{len(unproved)} file(s) that came with Dex can't currently be "
            "proved to be Dex's own. Until they're checked, Dex plays it "
            "safe and keeps the protected update path closed."
        )
    else:
        print(
            "Every file that came with Dex in this vault is already proved "
            "to match your installed version."
        )
    if baseline.anchor_state == "verified":
        print("A proof record is already in place and checks out.")
    elif baseline.anchor_state == "rejected":
        named = next(
            (error for error in baseline.errors if "release anchor" in error),
            "the anchor could not be verified",
        )
        print(
            "A proof record exists but couldn't be trusted, so Dex is "
            f"ignoring it: {named}"
        )
    print(f"Checkup status right now: {assessment.completeness}")
    return unproved, baseline


def run(arguments: list[str] | None = None) -> int:
    _parser().parse_args(arguments)
    try:
        root = _root()

        # (a) report the current unproved state in plain words.
        unproved, baseline = _report_current_state(root)
        if baseline.identity_state != "VERIFIED":
            return 2
        if not unproved and baseline.anchor_state != "rejected":
            # FOUNDER COPY - DRAFT PENDING APPROVAL.
            print("There's nothing here for this repair to fix.")
            return 0

        # (b) consent gate 1: run the re-anchor at all. A genuine TTY read;
        # generation is unreachable without it.
        if not _interactive_yes(_GATE_1_PROMPT):
            print(_DECLINED)
            return 2

        # (c) generate from LOCAL sources only (brain-store refs as hints,
        # locally present origin-pinned verified tags as proof). No version
        # or tag can be supplied (C12). When local sources cannot prove the
        # release, stop honestly — the network-fetch fallback (consent gate
        # 2, slice 3) belongs at the seam marked above _LOCAL_SOURCES_FAILED.
        try:
            generation = generate_release_anchor(root)
        except AnchorGenerationError as error:
            print(_LOCAL_SOURCES_FAILED.format(error=error))
            return 2

        # (d) preview what the anchor will prove BEFORE anything is written.
        counts = _preview_counts(
            root,
            generation,
            manifest_paths=baseline.manifest_paths,
            unproved=unproved,
        )
        # FOUNDER COPY - DRAFT PENDING APPROVAL: preview wording.
        print()
        print("Here's what saving this proof would settle — nothing is saved yet:")
        print(f"  Version being proved: v{generation.release_version}")
        print(f"  Checked against: the official release record {generation.tag}")
        print(f"  Files this proof can vouch for: {generation.row_count}")
        print(
            f"  Exactly as shipped: {counts['release-pristine']}"
        )
        print(
            f"  Changed on this computer — these become protected "
            f"customizations: {counts['release-modified']}"
        )
        print(f"  Shipped with Dex but missing from this vault: {counts['missing-from-disk']}")
        if counts["unreadable"]:
            print(f"  Couldn't be read for this preview: {counts['unreadable']}")
        print(f"  Still unprovable after this repair: {counts['still-unproved']}")
        print(f"  Proof fingerprint: {generation.document_sha256}")
        print(f"  Will be saved to: {RELEASE_ANCHOR_PATH} (plus its receipt)")
        print()

        # (e) consent gate 3: the write. A second genuine TTY read at the
        # moment of the act; the write is unreachable without it.
        if not _interactive_yes(_GATE_3_PROMPT):
            print(_DECLINED)
            return 2

        # (f) one transaction writes anchor + receipt; the written bytes must
        # hash to exactly the digest the preview showed (C9).
        result = write_release_anchor(
            root, generation, previewed_sha256=generation.document_sha256
        )

        after = migration_service.assess(root)
        after_baseline = load_release_baseline(root)
        remaining = _unproved_paths(after)
        # FOUNDER COPY - DRAFT PENDING APPROVAL: result wording.
        if after_baseline.anchor_state == "verified":
            print("Proof saved and double-checked.")
        else:
            print(
                "The proof was saved, but re-reading it didn't check out — "
                "Dex will ignore it until it does."
            )
        print(f"  Reference: {result.get('tx_id', '')}")
        print(f"  Proof status on re-read: {after_baseline.anchor_state}")
        listed = ", ".join(remaining[:5]) + ("..." if len(remaining) > 5 else "")
        print(
            f"  Files still unprovable: {len(remaining)}"
            + (f" ({listed})" if remaining else "")
        )
        print(f"  Checkup status: {after.completeness}")
        if after.completeness == "OK":
            print(
                "  The protected update path is open again."
            )
        elif not remaining:
            print(
                "  These files no longer block the checkup; still keeping it "
                "from completing: "
                + ", ".join(after.incomplete_reasons)
            )
        return 0
    except _NotInteractive:
        print(_NOT_A_TERMINAL)
        return 2
    except migration_service.MigrationServiceError as error:
        print(error.message)
        return 2
    except AnchorGenerationError as error:
        print(f"Nothing was written: {error}")
        return 2
    except Exception:
        print("The release re-anchoring command could not complete safely.")
        return 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
