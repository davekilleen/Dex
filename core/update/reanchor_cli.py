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
- **C12 — on a VERIFIED vault the release to prove is derived, never
  supplied.** ``generate_release_anchor`` still derives the claim from the
  installed catalog. ``--baseline`` is refused on VERIFIED identity so it
  cannot override a proved version. UNKNOWN identity (DEX-135) may pass
  ``--baseline VERSION`` so a fork with no catalog can name the official
  record to start from.
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
from core.update.establish_baseline import (
    BaselineEstablishmentError,
    infer_best_match,
    preview_against_baseline,
    resolve_official_baseline,
    write_established_baseline,
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
_UNKNOWN_NO_EVIDENCE = (
    "Dex can't tell which version is installed in this vault, and it "
    "couldn't find an official version record on this computer to start "
    "from. Nothing was changed.\n"
    "When you know which official version these files came from, open "
    "the Terminal app in your Dex vault folder and run:\n"
    "    python3 -m core.update.reanchor_cli --dry-run --baseline VERSION\n"
    "That only looks. Saving a starting version always asks you first."
)
_UNKNOWN_INVALID_BASELINE = (
    "Dex can't use {version} as a starting version. {error}\n"
    "Nothing was changed."
)
_VERIFIED_REJECTS_BASELINE = (
    "This vault already has a verified version record (v{version}). "
    "Dex won't replace it with --baseline. Nothing was changed."
)
_VERIFIED_REJECTS_DRY_RUN = (
    "This vault already has a verified version record. --dry-run is for "
    "setting a starting version when Dex can't tell which one is "
    "installed. Nothing was changed."
)
_UNKNOWN_GATE_1 = (
    "Compare these files with the official record of v{version} now? "
    "This step only looks — you'll see every file it checked, and be "
    "asked again before anything is saved. [yes/no] "
)
_UNKNOWN_GATE_WRITE = (
    "Save v{version} as the starting version for this vault? Dex will "
    "write only the version paperwork — not your notes, and not the "
    "files you have changed. Those stay as they are and are listed "
    "above as customizations. [yes/no] "
)
_UNKNOWN_DRY_RUN_HEADER = (
    "This is a look-only pass against official v{version}. Nothing will "
    "be saved."
)


class _NotInteractive(RuntimeError):
    """stdin is not a terminal; consent cannot be collected."""


def _parser() -> argparse.ArgumentParser:
    # C8: there is still no --yes and no argument that substitutes for a
    # person saying yes. C12: --baseline is refused when identity is already
    # VERIFIED. UNKNOWN identity (DEX-135) may name an official version so a
    # pre-catalog fork can establish a starting record.
    parser = argparse.ArgumentParser(
        prog="python3 -m core.update.reanchor_cli",
        description=(
            "Interactively re-anchor this vault's files to a verified release "
            "record, or establish that record when Dex can't tell which "
            "version is installed. Asks before running and again before "
            "writing; refuses to write without a terminal."
        ),
    )
    parser.add_argument(
        "--baseline",
        metavar="VERSION",
        help=(
            "Official Dex version to use as the starting record when this "
            "vault has no verified version (for example 1.64.0). Rejected "
            "if the version is not in the official release record, and "
            "rejected when a verified version is already in place."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show the file-by-file customization inventory against the "
            "starting version and write nothing. For vaults whose version "
            "is unknown."
        ),
    )
    return parser


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
            "Dex can't tell which version is installed in this vault yet. "
            "There is a guided repair that can set a starting version from "
            "the official record — it only writes the version paperwork, "
            "never your notes or the files you have changed."
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


def _print_unknown_inventory(preview) -> None:
    print()
    print("Here's every official file Dex checked — nothing is saved yet:")
    print(f"  Official version: v{preview.version}")
    print(f"  Checked against: the official release record {preview.tag}")
    if preview.inferred:
        print("  This version is Dex's closest match on this computer.")
    print(f"  Exactly as shipped: {preview.counts['release-pristine']}")
    print(
        f"  Changed on this computer — these stay as your customizations: "
        f"{preview.counts['release-modified']}"
    )
    print(
        f"  Shipped with Dex but missing from this vault: "
        f"{preview.counts['missing-from-disk']}"
    )
    print(
        f"  Extra Dex-owned files this version does not account for: "
        f"{preview.counts['user-owned-addition']}"
    )
    if preview.counts["unreadable"]:
        print(f"  Couldn't be read for this preview: {preview.counts['unreadable']}")
    print(f"  Proof fingerprint: {preview.preview_sha256}")
    print(
        "  If you save, Dex writes only the version paperwork (the official "
        "file list and version record). An existing file list that differs "
        "is replaced with the official one. Your notes and edited files "
        "are not written."
    )
    print()
    print("File-by-file:")
    for row in preview.rows:
        print(f"  {row.classification}: {row.path}")
    customizations = preview.customization_paths
    if customizations:
        print()
        print(
            "These files differ from the official record and will be kept "
            "as your customizations:"
        )
        for path in customizations:
            print(f"  {path}")
    print()


def _run_unknown_identity(root: Path, *, baseline_version: str | None, dry_run: bool) -> int:
    """DEX-135: establish a starting version for an UNKNOWN-identity vault."""
    try:
        if baseline_version:
            official = resolve_official_baseline(root, baseline_version)
        else:
            official = infer_best_match(root)
    except BaselineEstablishmentError as error:
        if baseline_version:
            print(
                _UNKNOWN_INVALID_BASELINE.format(
                    version=baseline_version, error=error
                )
            )
        else:
            print(_UNKNOWN_NO_EVIDENCE)
            print(f"What Dex found: {error}")
        return 2

    if dry_run:
        print(_UNKNOWN_DRY_RUN_HEADER.format(version=official.version))
        preview = preview_against_baseline(root, official)
        _print_unknown_inventory(preview)
        print("Look-only pass finished. Nothing was changed.")
        return 0

    # Consent gate 1: look at the official record. Dry-run never reaches here.
    if not _interactive_yes(_UNKNOWN_GATE_1.format(version=official.version)):
        print(_DECLINED)
        return 2

    preview = preview_against_baseline(root, official)
    _print_unknown_inventory(preview)

    if not _interactive_yes(_UNKNOWN_GATE_WRITE.format(version=official.version)):
        print(_DECLINED)
        return 2

    result = write_established_baseline(
        root, official, previewed_sha256=preview.preview_sha256
    )
    after = load_release_baseline(root)
    assessment = migration_service.assess(root)
    if after.identity_state == "VERIFIED":
        print(f"Starting version saved: v{after.release_version}.")
    else:
        print(
            "The version paperwork was saved, but Dex still can't verify "
            "it — nothing else was changed."
        )
    print(f"  Reference: {result.get('tx_id', '')}")
    print(f"  Version status on re-read: {after.identity_state}")
    print(f"  Checkup status: {assessment.completeness}")
    if assessment.completeness == "OK":
        print("  The protected update path is open again.")
    elif after.identity_state == "VERIFIED":
        print(
            "  The starting version is in place. If the checkup still "
            "can't finish, run this same command without --baseline to "
            "prove the remaining files."
        )
    return 0


def run(arguments: list[str] | None = None) -> int:
    parsed = _parser().parse_args(arguments)
    try:
        root = _root()

        # (a) report the current unproved state in plain words.
        unproved, baseline = _report_current_state(root)
        if baseline.identity_state != "VERIFIED":
            return _run_unknown_identity(
                root,
                baseline_version=parsed.baseline,
                dry_run=parsed.dry_run,
            )
        if parsed.baseline:
            print(
                _VERIFIED_REJECTS_BASELINE.format(
                    version=baseline.release_version or "unknown"
                )
            )
            return 2
        if parsed.dry_run:
            print(_VERIFIED_REJECTS_DRY_RUN)
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
    except BaselineEstablishmentError as error:
        print(f"Nothing was written: {error}")
        return 2
    except Exception:
        print("The release re-anchoring command could not complete safely.")
        return 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
