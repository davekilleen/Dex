"""Keep CLAUDE.md in step with CLAUDE-custom.md between updates.

`CLAUDE.md` is composed from the release template plus the user's
`CLAUDE-custom.md` and `System/user-profile.yaml`. Until now that composition
ran only inside the delivered-release transaction, so an instruction written
into the custom block did nothing until the next update applied. On a vault
already at the newest release that is indefinite, and it is silent: the file
saves, the content is correct, and the instruction simply never loads.

The trust problem is worse than the latency one. Dex confirms the customisation
has been made and the user reasonably believes it is in force. Recomposing
between updates makes that confirmation true.

Nothing here is new state. The output is exactly what the next update would
produce from the same inputs, so this is the same result arriving earlier.
The write still takes the shared vault mutation lock — or refuses when an
update already holds it — so a hook cannot compose from a stale activation
tag and overwrite a mid-apply CLAUDE.md.

Two-stage by design. The cheap gate is a pair of `stat` calls and is what runs
on almost every invocation; the expensive path only runs when the custom file
has actually moved. See `needs_recompose`.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from core.transaction.lock import (
    LockBusyError,
    LockContentionError,
    LockError,
    acquire_owned_lock,
)
from core.update.apply_update import CompositionError, _compose_claude

CLAUDE = "CLAUDE.md"
CUSTOM = "CLAUDE-custom.md"
BRAIN_GIT = ".dex/brain.git"
ACTIVATION = "System/.dex/lifecycle/activation.json"

_RELEASE_TAG = re.compile(r"^dist/release/v(?P<version>\d+\.\d+\.\d+)-[0-9a-f]{7,64}$")


class RecomposeUnavailable(RuntimeError):
    """The release template could not be reached, so nothing can be checked.

    This is deliberately distinct from "no drift". A caller that cannot read the
    template knows nothing about whether CLAUDE.md is current, and must say so
    rather than reporting a clean result.
    """


def installed_release_tag(vault_root: Path) -> str:
    """Return the release tag matching the installed version.

    Raises RecomposeUnavailable when the brain store or the activation record
    cannot answer, rather than guessing at a tag.
    """
    import json

    activation = vault_root / ACTIVATION
    try:
        version = json.loads(activation.read_text(encoding="utf-8")).get("bridge_release_version")
    except (OSError, json.JSONDecodeError, AttributeError) as error:
        raise RecomposeUnavailable(f"activation record unreadable: {error}") from error
    if not isinstance(version, str) or not version:
        raise RecomposeUnavailable("activation record carries no release version")

    brain = vault_root / BRAIN_GIT
    if not brain.is_dir():
        raise RecomposeUnavailable(f"no brain store at {BRAIN_GIT}")
    try:
        listed = subprocess.run(
            ["git", f"--git-dir={brain}", "tag", "-l", f"dist/release/v{version}-*"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RecomposeUnavailable(f"brain store could not be read: {error}") from error

    tags = [t for t in listed.stdout.split() if _RELEASE_TAG.match(t)]
    if not tags:
        raise RecomposeUnavailable(f"no release tag found for installed version {version}")
    if len(tags) > 1:
        # Ambiguity is a fail-closed condition: composing from the wrong template
        # would silently produce a CLAUDE.md for a release that is not installed.
        raise RecomposeUnavailable(f"{len(tags)} release tags match version {version}")
    return tags[0]


def _template_at(vault_root: Path, ref: str) -> bytes:
    """Read the shipped CLAUDE.md template at one brain ref, fail closed."""
    brain = vault_root / BRAIN_GIT
    try:
        shown = subprocess.run(
            ["git", f"--git-dir={brain}", "show", f"{ref}:{CLAUDE}"],
            capture_output=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RecomposeUnavailable(f"release template could not be read: {error}") from error
    if shown.returncode != 0 or not shown.stdout:
        raise RecomposeUnavailable(f"release template missing from {ref}")
    return shown.stdout


def compose_current(vault_root: Path) -> bytes:
    """Return what CLAUDE.md should contain right now.

    Uses the shipped composer against the installed release's template, so the
    result is identical to what the next update would write. The template is
    resolved through the activation record's release tag first, then through
    the brain's ``refs/dex/installed`` pin — the same baseline Doctor's
    shipped-file drift check trusts — so an absent or lagging activation
    record does not turn a checkable vault into an unavailable one.
    """
    try:
        template = _template_at(vault_root, installed_release_tag(vault_root))
    except RecomposeUnavailable as tag_error:
        try:
            template = _template_at(vault_root, "refs/dex/installed")
        except RecomposeUnavailable:
            raise tag_error

    # The shipped composer owns the custom-file guards. A symlink
    # CLAUDE-custom.md is CompositionError on the update path and must be
    # here too, or the byte-identical claim is not locked to that composer.
    # check_live is off because this IS the baseline the live-file guard
    # measures against; guarding here would recurse.
    return _compose_claude(template, vault_root, check_live=False)


# The marker scaffolding is release-owned: composition consumes the markers
# whenever the custom block has content, so treating them as the user's own
# words would make every empty-block vault look hand-edited.
_MARKER_LINE = re.compile(rb"^## USER_EXTENSIONS_(?:START|END)\b")


def user_authored_lines(live: bytes, baseline: bytes) -> tuple[str, ...]:
    """Lines in the live CLAUDE.md that ``baseline`` does not explain.

    Line-set semantics: a live line is explained when the identical line
    appears anywhere in the baseline. Whitespace-only lines and the
    USER_EXTENSIONS marker scaffolding never count; every other line present
    only in the live file was typed there directly. First-appearance order,
    duplicates collapsed; undecodable bytes are shown with replacement
    characters rather than hidden.
    """
    explained = {line for line in baseline.splitlines() if line.strip()}
    seen: set[bytes] = set()
    found: list[str] = []
    for line in live.splitlines():
        if not line.strip() or line in explained or line in seen:
            continue
        if _MARKER_LINE.match(line):
            continue
        seen.add(line)
        found.append(line.decode("utf-8", errors="replace"))
    return tuple(found)


def detect_user_edits(vault_root: Path) -> tuple[str, ...]:
    """Direct edits in the live CLAUDE.md, measured against `compose_current`.

    Raises RecomposeUnavailable (or CompositionError from the shipped
    composer) when the baseline cannot be built: an unprovable baseline is
    UNKNOWN, never "no edits".
    """
    claude = vault_root / CLAUDE
    try:
        live = claude.read_bytes()
    except FileNotFoundError:
        return ()
    except OSError as error:
        raise RecomposeUnavailable(f"{CLAUDE} could not be read: {error}") from error
    return user_authored_lines(live, compose_current(vault_root))


def needs_recompose(vault_root: Path) -> bool:
    """Cheap gate: has CLAUDE-custom.md moved since CLAUDE.md was written?

    Two stat calls. This is what runs on nearly every invocation, and it is
    deliberately imprecise: a touch with no content change trips it, and the
    only cost of that is one recompose that writes an identical file. The exact
    test lives in `recompose_if_needed`, which compares bytes before writing.
    """
    claude = vault_root / CLAUDE
    custom = vault_root / CUSTOM
    if not custom.is_file():
        return False
    if not claude.is_file():
        return True
    try:
        return custom.stat().st_mtime > claude.stat().st_mtime
    except OSError:
        return False


def recompose_if_needed(vault_root: Path, *, force: bool = False) -> str:
    """Bring CLAUDE.md up to date when it has fallen behind the custom block.

    Returns one of: "current", "recomposed", "unavailable:<reason>".

    The everyday path is mtime-gated. Pass ``force=True`` to compare bytes
    and write when content has drifted even if CLAUDE-custom.md is not newer
    — the case Doctor detects after a restore or a raced hook write.

    Takes the shared vault mutation lock before composing or writing. If an
    update holds it, refuses rather than composing from a stale activation
    tag and overwriting the in-flight CLAUDE.md.

    Never writes a partial file. A composition failure leaves the existing
    CLAUDE.md exactly as it was, because a half-written instruction file is
    worse than a stale one.
    """
    if not force and not needs_recompose(vault_root):
        return "current"

    try:
        release = acquire_owned_lock(vault_root, "claude-composition")
    except LockBusyError as error:
        return f"unavailable:{error}"
    except (LockContentionError, LockError) as error:
        return f"unavailable:{error}"

    try:
        if not force and not needs_recompose(vault_root):
            return "current"
        try:
            expected = compose_current(vault_root)
        except RecomposeUnavailable as error:
            return f"unavailable:{error}"
        except CompositionError as error:
            return f"unavailable:composition refused: {error}"

        claude = vault_root / CLAUDE
        try:
            live = claude.read_bytes() if claude.is_file() else None
            if live == expected:
                # Content already correct; the mtime gate tripped on a touch.
                # Nudge the timestamp so the everyday gate stops firing.
                if not force:
                    claude.touch()
                return "current"
            if live is not None:
                # The live file is never a composition input, so a line typed
                # straight into CLAUDE.md exists nowhere else. Overwriting it
                # — force included — would be silent data loss; refuse instead.
                edited = user_authored_lines(live, expected)
                if edited:
                    count = len(edited)
                    noun = "line was" if count == 1 else "lines were"
                    return (
                        f"unavailable:{count} {noun} edited directly into "
                        f"{CLAUDE} and would be lost by recomposing; move them "
                        f"into {CUSTOM} (your protected block) first — Dex can "
                        "do this for you"
                    )
            tmp = claude.with_suffix(claude.suffix + ".recompose-tmp")
            tmp.write_bytes(expected)
            tmp.replace(claude)
        except OSError as error:
            return f"unavailable:could not write {CLAUDE}: {error}"
        return "recomposed"
    finally:
        release()
