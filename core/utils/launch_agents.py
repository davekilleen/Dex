"""Shared launch-agent ownership evidence for the session-start hook and Doctor.

Issue #364's invariant: if the session-start hook names ``/dex-doctor`` as the
fix for a launch agent still pointing at the vault's former location, Doctor
must be able to see the thing the hook saw.  Two independent implementations
(bash grep in the hook, Python in Doctor) diverged in verified cases —
degenerate breadcrumb roots, symlinked or moved-with-spaces paths, binary
plists, shell-string commands — so both surfaces now call this one module.

Kept dependency-free (stdlib only) so the hook can invoke it cheaply as
``python3 -m core.utils.launch_agents --stale-check``.
"""

from __future__ import annotations

import argparse
import plistlib
import re
from pathlib import Path
from typing import Iterator

# Labels Dex has ever shipped under.  This is a filename heuristic with one
# narrow job: a corrupt plist that *presents itself* as Dex's must be reported
# as unreadable rather than silently skipped.  Everything else — including
# user-installed jobs under their own labels — is claimed by path evidence
# only, so third-party products whose names merely contain "dex"
# (com.samsung.dex.*, Android dex tooling, com.dexcom.*) are never touched.
SHIPPED_LAUNCH_AGENT_PREFIXES = ("com.dex.", "com.claudesidian.")

# The pre-rename product shipped the same jobs under this prefix.
LEGACY_LABEL_PREFIX = "com.claudesidian."
CURRENT_LABEL_PREFIX = "com.dex."

STALE_JOB_SENTINEL = "stale-job-found"

# A path reference ends at a path boundary: end-of-string, a path separator,
# whitespace, quoting, or a shell delimiter.  The shell delimiters matter
# because launchd jobs routinely embed the vault path inside
# ``/bin/bash -c "cd <vault>; exec ..."`` strings; plain characters such as
# ``-`` are deliberately NOT boundaries so a former root of ``.../Dex`` never
# claims an agent working under ``.../Dex-other``.
_REFERENCE_BOUNDARY = r"(?=$|[/\s'\";:&|()=<>,])"


def is_dex_named(name: str) -> bool:
    """Return whether a plist filename presents itself as a shipped Dex agent."""
    stem = name[: -len(".plist")] if name.endswith(".plist") else name
    return stem.lower().startswith(SHIPPED_LAUNCH_AGENT_PREFIXES)


def promise_label_candidates(label: str) -> tuple[str, ...]:
    """Return the health-promise ids *label* may be registered under.

    Pre-rename installs run the same shipped jobs under the legacy prefix;
    they must map onto the ``com.dex.*`` promise register instead of being
    misread as unauditable user jobs.
    """
    if label.startswith(LEGACY_LABEL_PREFIX):
        return (label, CURRENT_LABEL_PREFIX + label[len(LEGACY_LABEL_PREFIX) :])
    return (label,)


def reference_pattern(root: Path) -> re.Pattern[str]:
    """Compile the boundary-aware pattern matching references to *root*."""
    return re.compile(re.escape(root.as_posix()) + _REFERENCE_BOUNDARY)


def iter_plist_strings(value: object) -> Iterator[str]:
    """Yield every string anywhere in a parsed plist payload."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from iter_plist_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_plist_strings(child)


def payload_references_root(payload: object, root: Path) -> bool:
    """Return whether any string in a parsed plist payload references *root*."""
    pattern = reference_pattern(root)
    return any(pattern.search(value) for value in iter_plist_strings(payload))


def stored_former_vault_root(vault_root: Path, home: Path) -> Path | None:
    """Return the breadcrumb's stored vault path when it names a former root.

    The installers write the vault's location to ``~/.config/dex/vault-path``.
    After a directory move or rename the breadcrumb keeps naming the old
    location; that stored-but-no-longer-current path is the shared ownership
    evidence for agents left behind by the move.  Guards reject corrupted
    breadcrumbs (relative paths, degenerate roots like ``/tmp`` or ``/Users``
    that would match half the machine) and moved-with-a-symlink layouts where
    the old path still resolves to the current vault.
    """
    breadcrumb = home / ".config" / "dex" / "vault-path"
    try:
        if breadcrumb.is_symlink() or not breadcrumb.is_file():
            return None
        stored = breadcrumb.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None
    if not stored:
        return None
    candidate = Path(stored).expanduser()
    # Refuse degenerate roots ("/", "/Users", "/tmp") that would match everything.
    if not candidate.is_absolute() or len(candidate.parts) < 3:
        return None
    if candidate == vault_root:
        return None
    try:
        if candidate.resolve() == vault_root.resolve():
            return None
    except (OSError, RuntimeError):
        pass
    return candidate


def load_plist_payload(plist: Path) -> object | None:
    """Parse a plist leniently for reference scanning; ``None`` when unreadable.

    plistlib raises a small zoo of exceptions for damaged files (ExpatError
    for truncated XML, ValueError for bad scalars, InvalidFileException,
    OSError); for scanning purposes every unreadable file is simply not
    evidence.  Any parseable payload counts, whatever its top-level type.
    """
    try:
        with plist.open("rb") as handle:
            return plistlib.load(handle)
    except Exception:  # noqa: BLE001 — every failure mode means "no evidence"
        return None


def any_agent_references_former_root(
    vault_root: Path,
    home: Path,
    launch_agents_dir: Path | None = None,
) -> bool:
    """Return whether any launch agent still references the former vault root."""
    from core.utils import automation_ownership

    former_root = stored_former_vault_root(vault_root, home)
    if former_root is None:
        return False
    directory = launch_agents_dir or (home / "Library" / "LaunchAgents")
    try:
        if not directory.is_dir():
            return False
        plists = sorted(directory.glob("*.plist"))
    except OSError:
        return False
    for plist in plists:
        try:
            relative = plist.relative_to(home).as_posix()
        except ValueError:
            relative = ""
        if automation_ownership.is_plist_offloaded(
            vault_root,
            relative,
            home_root=home,
        ):
            continue
        payload = load_plist_payload(plist)
        if payload is not None and payload_references_root(payload, former_root):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--stale-check", action="store_true")
    mode.add_argument("--offloaded-check", action="store_true")
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--plist-relative")
    args = parser.parse_args(argv)
    if args.offloaded_check:
        from core.utils import automation_ownership

        if not isinstance(args.plist_relative, str):
            parser.error("--offloaded-check requires --plist-relative")
        return (
            0
            if automation_ownership.is_plist_offloaded(
                args.vault,
                args.plist_relative,
                home_root=Path.home(),
            )
            else 1
        )
    if any_agent_references_former_root(args.vault, Path.home()):
        print(STALE_JOB_SENTINEL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
