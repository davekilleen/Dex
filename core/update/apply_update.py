#!/usr/bin/env python3
"""Apply one immutable Dex release without merging Git histories.

The release identity is supplied by the existing bounded release-evidence
flow. This module re-verifies that exact annotated ``dist/release/v*`` tag
against the selected stable/beta channel in the split brain Git store, builds
an ownership-authorized file plan, then delegates every release-tree mutation
to :class:`core.transaction.engine.Transaction`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from time import monotonic as _monotonic
from typing import Any, Callable

from core import portable_contract
from core.transaction.engine import PlanEntry, Transaction
from core.utils import release_channel
from core.utils.local_git import git_output

MANIFEST_RELATIVE = "System/.installed-files.manifest"
TOPOLOGY_RELATIVE = Path("System/.dex/topology.json")
BRAIN_RELATIVE = Path(".dex/brain.git")
VAULT_MARKER_RELATIVE = Path(".git/dex-vault-v2")
BRAIN_MARKER_NAME = "dex-brain-v2"
OFFICIAL_REMOTE = re.compile(
    r"^(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)"
    r"davekilleen/Dex(?:\.git)?/?$",
    re.IGNORECASE,
)
RELEASE_TAG = re.compile(
    r"^dist/release/v(?P<version>(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*))-(?P<short>[0-9a-f]{7,64})$"
)
FINAL_FETCH_ATTEMPT_BUDGET_SECONDS = 5.0
FINAL_FETCH_RETRY_BACKOFF_SECONDS = 0.1
PRE_DELIVERY_PROOF_RETRY_BACKOFF_SECONDS = 0.1
START_MARKER = re.compile(
    rb"^## USER_EXTENSIONS_START[^\r\n]*(?:\r?\n|$)",
    re.MULTILINE,
)
END_MARKER = re.compile(
    rb"^## USER_EXTENSIONS_END[^\r\n]*(?:\r?\n|$)",
    re.MULTILINE,
)
USER_PROFILE_RELATIVE = Path("System/user-profile.yaml")
USER_PROFILE_HEADING = "## User Profile"
USER_PROFILE_PLACEHOLDER = "Not yet configured"
USER_PROFILE_SECTION = re.compile(
    r"^## User Profile\b.*?(?=^---\s*\r?$)",
    re.MULTILINE | re.DOTALL,
)
_UNCONFIGURED_PROFILE_LABELS = frozenset(
    {
        "",
        "not configured",
        "not yet configured",
    }
)


class UpdateError(RuntimeError):
    """The update could not safely proceed."""


class ReleaseVerificationError(UpdateError):
    """The supplied immutable release identity failed closed verification."""


class CompositionError(UpdateError):
    """A release-owned composed file could not be built without data loss."""


def _extension_block(template: bytes) -> tuple[bytes, bytes]:
    try:
        template.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CompositionError("release CLAUDE.md template is not UTF-8") from error
    starts = tuple(START_MARKER.finditer(template))
    ends = tuple(END_MARKER.finditer(template))
    if len(starts) != 1 or len(ends) != 1 or ends[0].start() < starts[0].end():
        raise CompositionError(
            "release template needs exactly one ordered USER_EXTENSIONS marker pair"
        )
    return template[: starts[0].start()], template[ends[0].end() :]


def _regenerate_claude(template: bytes, custom_content: bytes) -> bytes:
    """Mirror the dependency-free CJS migrator's ``regenerateClaude``."""
    try:
        custom_content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CompositionError("CLAUDE.md composition inputs are not UTF-8") from error
    before, after = _extension_block(template)
    separator = b"\n" if custom_content and not custom_content.endswith(b"\n") else b""
    return before + custom_content + separator + after


def _configured_profile_text(value: object) -> str | None:
    """Return a non-placeholder profile string, or None when unset."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if text.casefold() in _UNCONFIGURED_PROFILE_LABELS:
        return None
    return text


def _pillar_names(value: object) -> tuple[str, ...]:
    """Accept the string or ``{name: ...}`` shapes provision already writes."""
    if not isinstance(value, list):
        return ()
    names: list[str] = []
    for item in value:
        if isinstance(item, str):
            name = _configured_profile_text(item)
        elif isinstance(item, dict):
            name = _configured_profile_text(item.get("name"))
        else:
            name = None
        if name:
            names.append(name)
    return tuple(names)


def _read_user_profile(vault_root: Path) -> dict[str, Any] | None:
    """Load ``System/user-profile.yaml`` as a mapping, or None when absent.

    A missing file is a fresh install. A present file that cannot be proved
    as a regular UTF-8 YAML object fails closed so composition cannot replace
    a populated User Profile section with placeholders.
    """
    path = vault_root / USER_PROFILE_RELATIVE
    if not path.exists() and not path.is_symlink():
        return None
    try:
        if path.is_symlink() or not path.is_file():
            raise CompositionError("System/user-profile.yaml is not a regular file")
        raw = path.read_bytes()
    except OSError as error:
        raise CompositionError("System/user-profile.yaml is unreadable") from error
    if not raw.strip():
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CompositionError("System/user-profile.yaml is not UTF-8") from error
    import yaml  # lazy: gitignore composition must import this module without PyYAML

    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise CompositionError("System/user-profile.yaml is not valid YAML") from error
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        raise CompositionError("System/user-profile.yaml is not an object")
    return parsed


def _profile_from_yaml(profile: dict[str, Any]) -> dict[str, object] | None:
    """Collect identity fields only when onboarding has actually written them."""
    name = _configured_profile_text(profile.get("name"))
    role = _configured_profile_text(profile.get("role"))
    company_size = _configured_profile_text(profile.get("company_size"))
    working_style = _configured_profile_text(profile.get("working_style"))
    communication = profile.get("communication")
    formality = None
    if isinstance(communication, dict):
        formality = _configured_profile_text(communication.get("formality"))
    pillars = _pillar_names(profile.get("pillars"))
    if not any((name, role, company_size, working_style, pillars)):
        return None
    return {
        "name": name or USER_PROFILE_PLACEHOLDER,
        "role": role or USER_PROFILE_PLACEHOLDER,
        "company_size": company_size or USER_PROFILE_PLACEHOLDER,
        "working_style": working_style or formality or USER_PROFILE_PLACEHOLDER,
        "pillars": pillars,
    }


def _render_user_profile_section(profile: dict[str, object]) -> str:
    pillars = profile["pillars"]
    names = pillars if isinstance(pillars, tuple) and pillars else (USER_PROFILE_PLACEHOLDER,)
    pillar_lines = "\n".join(f"- {name}" for name in names)
    return (
        f"{USER_PROFILE_HEADING}\n\n"
        "<!-- Updated during onboarding -->\n"
        f"**Name:** {profile['name']}\n"
        f"**Role:** {profile['role']}\n"
        f"**Company Size:** {profile['company_size']}\n"
        f"**Working Style:** {profile['working_style']}\n"
        f"**Pillars:**\n"
        f"{pillar_lines}\n\n"
    )


def _apply_user_profile(template: bytes, vault_root: Path) -> bytes:
    """Rewrite the release User Profile section from ``user-profile.yaml``.

    The yaml file is the source of truth. An unconfigured or missing profile
    leaves the shipped placeholders untouched. The custom-instructions block
    is not part of this rewrite — markers stay in the template so the
    existing splice can still run.
    """
    profile = _read_user_profile(vault_root)
    if profile is None:
        return template
    overlay = _profile_from_yaml(profile)
    if overlay is None:
        return template
    try:
        text = template.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CompositionError("release CLAUDE.md template is not UTF-8") from error
    if USER_PROFILE_HEADING not in text:
        return template
    if USER_PROFILE_SECTION.search(text) is None:
        raise CompositionError(
            "release template User Profile section is missing its closing divider"
        )
    return USER_PROFILE_SECTION.sub(
        _render_user_profile_section(overlay),
        text,
        count=1,
    ).encode("utf-8")


def _compose_claude(release_blob: bytes, vault_root: Path) -> bytes:
    _extension_block(release_blob)
    templated = _apply_user_profile(release_blob, vault_root)
    custom_path = vault_root / "CLAUDE-custom.md"
    if not custom_path.exists() and not custom_path.is_symlink():
        return templated
    try:
        if custom_path.is_symlink() or not custom_path.is_file():
            raise CompositionError("CLAUDE-custom.md is not a regular file")
        custom_content = custom_path.read_bytes()
    except OSError as error:
        raise CompositionError("CLAUDE-custom.md is unreadable") from error
    if not custom_content:
        return templated
    return _regenerate_claude(templated, custom_content)


GITIGNORE_SECTION_BEGIN = "# >>> dex-vault-mode (managed by Dex updates) >>>"
GITIGNORE_SECTION_END = "# <<< dex-vault-mode (managed by Dex updates) <<<"
GITIGNORE_MANAGED_SECTION = re.compile(
    rf"\n*{re.escape(GITIGNORE_SECTION_BEGIN)}.*?{re.escape(GITIGNORE_SECTION_END)}\n?",
    re.DOTALL,
)


def _vault_mode_gitignore_section() -> str:
    """Ignore rules that neutralize the distribution re-include block in a vault.

    The release ships the distribution repository's ``.gitignore``, whose
    "Keep Template Files" negations (``!core/``, ``!docs/`` and friends) exist
    so the development repository tracks its own product files. Inside a split
    vault those same negations leave every brain-owned file un-ignored, so one
    broad ``git add -A`` silently captures hundreds of release files into the
    user's private history — and every later update then dirties them all.

    Because ``.gitignore`` outranks ``.git/info/exclude``, the only reliable
    place to restore vault-side behavior is the end of the file itself
    (last match wins). The section is derived from the ownership contract so
    there is no second path list to drift.

    The distribution file is wrong inside a vault in BOTH directions, so this
    section corrects both. Its negations un-ignore brain-owned product files,
    handled above. Its ignore rules for the PARA folders hide the user's own
    content, handled below with ``VAULT_REGIONS``. Fixing only the first leaves
    ``git add 04-Projects/`` failing, which silently disables any pathspec-based
    staging such as the vault-autocommit hook.
    """
    tops = sorted(
        (rule for rule in portable_contract.RULES
         if rule.ownership == "brain" and "/" not in rule.path),
        key=lambda rule: rule.path,
    )
    vault_children = [
        rule for rule in portable_contract.RULES
        if rule.ownership == "vault" and "/" in rule.path
    ]
    lines = [
        GITIGNORE_SECTION_BEGIN,
        "# This repository is your private vault. The Dex product files below are",
        "# delivered and refreshed by Dex's receipt-backed updates, not tracked",
        "# here. Derived from the ownership contract; edits inside this section",
        "# are replaced on every update.",
    ]
    for top in tops:
        exceptions = sorted(
            rule.path for rule in vault_children
            if rule.path.startswith(f"{top.path}/")
        )
        for exception in exceptions:
            if exception.count("/") != top.path.count("/") + 1:
                raise CompositionError(
                    "vault-owned contract path nested deeper than one level "
                    f"under brain-owned {top.path!r}: {exception!r}"
                )
        if top.kind == "file":
            lines.append(f"/{top.path}")
        elif exceptions:
            lines.append(f"/{top.path}/*")
            lines.extend(f"!/{exception}/" for exception in exceptions)
        else:
            lines.append(f"/{top.path}/")

    # The distribution .gitignore also ignores the PARA folders, because in the
    # product repository they hold sample content. Inside a vault they are the
    # user's entire history, and ignoring them is worse than a cosmetic wart:
    # `git add 04-Projects/` fails outright with "The following paths are
    # ignored", so any pathspec-based staging (the vault-autocommit hook)
    # hard-fails and stops committing. Re-include them last so the negation
    # wins, derived from the same contract as the rules above.
    lines.append("# Vault regions are the user's own content and stay tracked.")
    lines.extend(f"!/{region}/" for region in sorted(portable_contract.VAULT_REGIONS))

    # Mirror of the brain-with-vault-children case above. The release also
    # delivers product files INTO vault regions (the Dex_System reference docs
    # under 06-Resources), and those are refreshed by every update, so tracking
    # them puts product churn in the user's private history. Re-ignore them
    # after the region negation, or last-match keeps them tracked. Emitted
    # per file rather than per directory: the contract declares individual
    # files, so a note the user writes alongside them stays theirs.
    brain_in_regions = portable_contract.brain_paths_inside_vault_regions()
    if brain_in_regions:
        lines.append("# Product files delivered inside a vault region stay untracked.")
        lines.extend(f"/{path}" for path in brain_in_regions)

    lines.append(GITIGNORE_SECTION_END)
    return "\n".join(lines)


def _compose_gitignore(release_blob: bytes, vault_root: Path) -> bytes:
    del vault_root  # the section depends only on the ownership contract
    try:
        text = release_blob.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CompositionError("release .gitignore is not UTF-8") from error
    base = GITIGNORE_MANAGED_SECTION.sub("", text).rstrip("\n")
    return f"{base}\n\n{_vault_mode_gitignore_section()}\n".encode("utf-8")


COMPOSERS: dict[str, Callable[[bytes, Path], bytes]] = {
    "CLAUDE.md": _compose_claude,
    ".gitignore": _compose_gitignore,
}


@dataclass(frozen=True)
class TreeEntry:
    path: str
    mode: int
    object_id: str


@dataclass(frozen=True)
class VerifiedReleaseRef:
    tag: str
    tag_object: str
    commit: str
    tree: str
    version: str
    channel: str
    brain_git: Path
    entries: tuple[TreeEntry, ...]


@dataclass(frozen=True)
class UpdatePlan:
    entries: tuple[PlanEntry, ...]
    replaced: tuple[str, ...]
    seeded: tuple[str, ...]
    regenerated: tuple[str, ...]
    pruned: tuple[str, ...]
    kept: tuple[str, ...]
    kept_reasons: tuple[tuple[str, str], ...]
    untouched: tuple[str, ...]


def _read_regular_json(path: Path, description: str) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise UpdateError(f"{description} is not a regular file")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise UpdateError(f"{description} is unreadable") from error
    if not isinstance(value, dict):
        raise UpdateError(f"{description} is not an object")
    return value


def _brain_output(vault_root: Path, brain_git: Path, *arguments: str) -> bytes:
    return git_output(
        vault_root,
        f"--git-dir={brain_git}",
        *arguments,
        profile="read-only",
    )


def _brain_text(vault_root: Path, brain_git: Path, *arguments: str) -> str:
    try:
        return _brain_output(vault_root, brain_git, *arguments).decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise ReleaseVerificationError("Git release metadata is not UTF-8") from error


def _tree_entries(vault_root: Path, brain_git: Path, commit: str) -> tuple[TreeEntry, ...]:
    raw = _brain_output(
        vault_root,
        brain_git,
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        commit,
    )
    entries: list[TreeEntry] = []
    seen: set[str] = set()
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            raw_mode, object_type, object_id = metadata.decode("ascii").split(" ")
            relative = raw_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            raise ReleaseVerificationError("release tree contains a malformed entry") from error
        if relative in seen or object_type != "blob" or raw_mode not in {"100644", "100755"}:
            raise ReleaseVerificationError("release tree is ambiguous or contains a symlink/unsupported entry")
        seen.add(relative)
        entries.append(TreeEntry(relative, 0o755 if raw_mode == "100755" else 0o644, object_id))
    return tuple(sorted(entries, key=lambda entry: entry.path))


def _blob(vault_root: Path, brain_git: Path, object_id: str) -> bytes:
    return _brain_output(vault_root, brain_git, "cat-file", "blob", object_id)


def _entry_map(entries: tuple[TreeEntry, ...]) -> dict[str, TreeEntry]:
    return {entry.path: entry for entry in entries}


def _verify_manifest(
    vault_root: Path,
    brain_git: Path,
    entries: tuple[TreeEntry, ...],
) -> None:
    by_path = _entry_map(entries)
    manifest = by_path.get(MANIFEST_RELATIVE)
    if manifest is None:
        raise ReleaseVerificationError("release is missing its installed-files manifest")
    try:
        source = _blob(vault_root, brain_git, manifest.object_id).decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReleaseVerificationError("release manifest is not UTF-8") from error
    paths = source.splitlines()
    if not source.endswith("\n") or "\r" in source or paths != sorted(set(paths)) or set(paths) != set(by_path):
        raise ReleaseVerificationError("release manifest contradicts the exact release tree")


def _recorded_vault_path(topology: dict[str, Any]) -> str | None:
    """Return the vault path the split marker records, if it records one.

    Kept consistent with ``core.lifecycle.engine.recorded_vault_path``: the
    marker has to record *a* path, but the value is runtime state and a moved
    or copied vault legitimately records somewhere else.
    """
    environment = topology.get("environment")
    if not isinstance(environment, dict):
        return None
    recorded = environment.get("DEX_VAULT")
    return recorded if isinstance(recorded, str) and recorded else None


def _relocated_vault(root: Path, topology: dict[str, Any]) -> bool:
    """True when a sound split records a vault path other than this one."""
    recorded = _recorded_vault_path(topology)
    if recorded is None:
        return False
    try:
        return Path(recorded).resolve() != root
    except (OSError, RuntimeError):
        return True


def _topology(vault_root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    root = Path(vault_root).resolve()
    for relative in (Path(".git"), Path(".dex"), BRAIN_RELATIVE, Path("System"), Path("System/.dex")):
        candidate = root / relative
        if candidate.is_symlink():
            raise UpdateError(f"split update refuses a symlinked {relative.as_posix()}")
    topology = _read_regular_json(root / TOPOLOGY_RELATIVE, "split topology marker")
    vault_marker = _read_regular_json(root / VAULT_MARKER_RELATIVE, "vault Git marker")
    brain_git = root / BRAIN_RELATIVE
    brain_marker = _read_regular_json(brain_git / BRAIN_MARKER_NAME, "brain Git marker")
    # The recorded vault path is deliberately *not* a condition here. It is an
    # absolute path held in runtime state, so any copied, moved, or renamed
    # vault records somewhere else; nothing in this module reads it as a path
    # (every path below derives from ``root``). A relocated vault is therefore
    # sound, and _finalize_release_metadata re-records it on install. Structural
    # damage still fails closed, and each cause now names itself.
    failures: list[str] = []
    if topology.get("topology") != "brain-vault-split":
        failures.append(
            f"{TOPOLOGY_RELATIVE.as_posix()} does not record a brain/vault split"
        )
    if topology.get("vaultGitDir") != ".git":
        failures.append(
            f"{TOPOLOGY_RELATIVE.as_posix()} records vaultGitDir "
            f"{topology.get('vaultGitDir')!r} instead of '.git'"
        )
    if topology.get("brainGitDir") != ".dex/brain.git":
        failures.append(
            f"{TOPOLOGY_RELATIVE.as_posix()} records brainGitDir "
            f"{topology.get('brainGitDir')!r} instead of '.dex/brain.git'"
        )
    if _recorded_vault_path(topology) is None:
        failures.append(
            f"{TOPOLOGY_RELATIVE.as_posix()} records no environment.DEX_VAULT path"
        )
    if vault_marker.get("role") != "vault":
        failures.append(
            f"{VAULT_MARKER_RELATIVE.as_posix()} records role "
            f"{vault_marker.get('role')!r} instead of 'vault'"
        )
    if brain_marker.get("role") != "brain":
        failures.append(
            f"{BRAIN_RELATIVE.as_posix()}/{BRAIN_MARKER_NAME} records role "
            f"{brain_marker.get('role')!r} instead of 'brain'"
        )
    if not brain_git.is_dir():
        failures.append(f"{BRAIN_RELATIVE.as_posix()} is missing or is not a directory")
    if failures:
        raise UpdateError(
            "the brain/vault split topology is incomplete or inconsistent: "
            + "; ".join(failures)
        )
    return brain_git, topology, brain_marker


def _verify_release_publisher(
    vault_root: Path,
    brain_git: Path,
    tag_object: str,
    tag_payload: str,
) -> None:
    """Refuse a release that is not signed by a trusted Dex release key.

    This is the last gate before a release can be previewed or applied, so the
    signature is re-checked here against the bytes actually fetched into this
    vault's brain store, not only against the evidence copy.

    The trust anchor is the allowed-signers file ALREADY INSTALLED in this
    vault, delivered by a release the user previously accepted — never the copy
    inside the candidate, which anyone able to forge the candidate could forge
    too. See ``core.utils.update_verifier.ALLOWED_SIGNERS_PATH`` for the
    bootstrap caveat: the first release carrying the file is trusted the old
    way, and the protection is real from the next update onward.

    While no anchor is installed this is a no-op and update behavior is
    unchanged.
    """
    from core.utils import update_verifier

    try:
        anchor = update_verifier.load_allowed_signers(vault_root)
        if anchor is None:
            return
        update_verifier.assert_signature_verifiable(
            tag_payload,
            git_version_output=git_output(
                vault_root,
                "--version",
                profile="read-only",
            ).decode("utf-8", errors="replace"),
        )
    except update_verifier.EvidenceError as error:
        raise ReleaseVerificationError(str(error)) from error
    try:
        _brain_output(
            vault_root,
            brain_git,
            *update_verifier.allowed_signers_config(anchor),
            "verify-tag",
            tag_object,
        )
    except RuntimeError as error:
        raise ReleaseVerificationError(
            update_verifier.SIGNATURE_UNTRUSTED_MESSAGE
        ) from error


def _verify_official_origin(vault_root: Path, brain_git: Path) -> None:
    configured = _brain_text(vault_root, brain_git, "config", "--get", "remote.origin.url")
    effective = _brain_text(vault_root, brain_git, "remote", "get-url", "origin")
    if not OFFICIAL_REMOTE.fullmatch(configured) or not OFFICIAL_REMOTE.fullmatch(effective):
        raise ReleaseVerificationError("brain origin is not the effective official Dex repository")


def verify_release_ref(
    vault_root: Path,
    *,
    tag: str,
    tag_object: str,
    commit: str,
    tree: str,
) -> VerifiedReleaseRef:
    """Re-verify one evidence-pinned tag against the selected release channel."""
    root = Path(vault_root).resolve()
    brain_git, _topology_value, _brain_marker = _topology(root)
    _verify_official_origin(root, brain_git)
    match = RELEASE_TAG.fullmatch(tag)
    if match is None:
        raise ReleaseVerificationError("release ref is not an immutable dist/release/v* tag")
    if not re.fullmatch(r"[0-9a-f]{40,64}", tag_object):
        raise ReleaseVerificationError("release tag object identity is malformed")
    if not re.fullmatch(r"[0-9a-f]{40,64}", commit) or not re.fullmatch(r"[0-9a-f]{40,64}", tree):
        raise ReleaseVerificationError("release commit/tree identity is malformed")

    actual_tag_object = _brain_text(root, brain_git, "rev-parse", "--verify", f"refs/tags/{tag}")
    if actual_tag_object != tag_object:
        raise ReleaseVerificationError("immutable release tag object does not match the evidence pin")
    if _brain_text(root, brain_git, "cat-file", "-t", tag_object) != "tag":
        raise ReleaseVerificationError("immutable release tag is not annotated")
    tag_payload = _brain_text(root, brain_git, "cat-file", "tag", tag_object)
    headers: dict[str, str] = {}
    for line in tag_payload.split("\n\n", 1)[0].splitlines():
        if " " not in line:
            continue
        key, value = line.split(" ", 1)
        if key in headers:
            raise ReleaseVerificationError("annotated release tag headers are ambiguous")
        headers[key] = value
    if headers.get("type") != "commit" or headers.get("tag") != tag or headers.get("object") != commit:
        raise ReleaseVerificationError("annotated release tag identity contradicts the evidence pin")
    _verify_release_publisher(root, brain_git, tag_object, tag_payload)
    if not commit.startswith(match.group("short")):
        raise ReleaseVerificationError("immutable tag suffix does not pin the full release commit")
    if _brain_text(root, brain_git, "rev-parse", "--verify", f"{commit}^{{tree}}") != tree:
        raise ReleaseVerificationError("release tree does not match the evidence pin")

    channel = release_channel.read_channel(root)
    if channel not in release_channel.VALID_CHANNELS:
        raise ReleaseVerificationError("the configured update channel is invalid")
    channel_commits = []
    for candidate in release_channel.release_ref_candidates(channel):
        try:
            channel_commits.append(
                _brain_text(
                    root,
                    brain_git,
                    "rev-parse",
                    "--verify",
                    f"refs/remotes/{candidate}^{{commit}}",
                )
            )
        except RuntimeError:
            continue
    if not channel_commits or commit not in channel_commits:
        raise ReleaseVerificationError(f"immutable release is not the pinned target of the {channel} channel")

    entries = _tree_entries(root, brain_git, commit)
    _verify_manifest(root, brain_git, entries)
    package_entry = _entry_map(entries).get("package.json")
    if package_entry is None:
        raise ReleaseVerificationError("release is missing package.json")
    try:
        package = json.loads(_blob(root, brain_git, package_entry.object_id).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseVerificationError("release package metadata is unreadable") from error
    if not isinstance(package, dict) or package.get("version") != match.group("version"):
        raise ReleaseVerificationError("release package version contradicts the immutable tag")
    return VerifiedReleaseRef(
        tag,
        tag_object,
        commit,
        tree,
        match.group("version"),
        channel,
        brain_git,
        entries,
    )


def _matches_entry(vault_root: Path, entry: TreeEntry, expected: bytes) -> bool:
    target = vault_root / entry.path
    try:
        return (
            not target.is_symlink()
            and target.is_file()
            and target.read_bytes() == expected
            and (target.stat().st_mode & 0o777) == entry.mode
        )
    except OSError:
        return False


def build_update_plan(vault_root: Path, release: VerifiedReleaseRef) -> UpdatePlan:
    """Build a fail-closed release mutation plan from contract verdicts."""
    root = Path(vault_root).resolve()
    installed = _brain_text(root, release.brain_git, "rev-parse", "--verify", "refs/dex/installed^{commit}")
    previous_entries = _tree_entries(root, release.brain_git, installed)
    _verify_manifest(root, release.brain_git, previous_entries)
    target_brain: set[str] = set()
    planned: list[PlanEntry] = []
    replaced: list[str] = []
    seeded: list[str] = []
    regenerated: list[str] = []
    kept: list[str] = []
    kept_reasons: list[tuple[str, str]] = []
    untouched: list[str] = []

    for entry in release.entries:
        target = root / entry.path
        verdict = portable_contract.update_write_verdict(entry.path, exists=target.exists())
        if verdict.action in {"deny", "unclassified-never-write"}:
            raise UpdateError(
                f"release contains a path the ownership contract refuses: {entry.path} [{verdict.action}]"
            )
        if verdict.ownership == "brain":
            target_brain.add(entry.path)
        if not verdict.allowed:
            untouched.append(entry.path)
            continue
        content = _blob(root, release.brain_git, entry.object_id)
        composer = COMPOSERS.get(entry.path)
        if composer is not None:
            try:
                content = composer(content, root)
            except CompositionError as error:
                kept.append(entry.path)
                kept_reasons.append((entry.path, str(error)))
                continue
        if _matches_entry(root, entry, content):
            untouched.append(entry.path)
            continue
        planned.append(PlanEntry(entry.path, content, entry.mode))
        if verdict.ownership == "brain":
            replaced.append(entry.path)
        elif verdict.ownership == "seed":
            seeded.append(entry.path)
        elif verdict.ownership == "generated":
            regenerated.append(entry.path)

    pruned: list[str] = []
    for previous in previous_entries:
        resolution = portable_contract.resolve(previous.path)
        if resolution.ownership != "brain" or previous.path in target_brain:
            continue
        target = root / previous.path
        if not target.exists():
            continue
        previous_content = _blob(root, release.brain_git, previous.object_id)
        if _matches_entry(root, previous, previous_content):
            verdict = portable_contract.update_write_verdict(previous.path, exists=True)
            if not verdict.allowed or verdict.ownership != "brain":
                raise UpdateError(f"ownership contract refuses pruning {previous.path}")
            planned.append(
                PlanEntry(
                    previous.path,
                    None,
                    previous.mode,
                    expected_current_sha256=hashlib.sha256(
                        previous_content
                    ).hexdigest(),
                )
            )
            pruned.append(previous.path)
        else:
            kept.append(previous.path)

    return UpdatePlan(
        tuple(planned),
        tuple(replaced),
        tuple(seeded),
        tuple(regenerated),
        tuple(pruned),
        tuple(kept),
        tuple(kept_reasons),
        tuple(untouched),
    )


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    data = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")
    temporary = path.parent / f".{path.name}.update-{os.getpid()}"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _finalize_release_metadata(
    vault_root: Path,
    *,
    brain_git: Path,
    commit: str,
    previous_commit: str,
) -> None:
    """Record the installed release, and re-record a relocated vault path.

    This is the one place that legitimately rewrites the split marker, so it is
    where a vault that was copied, moved, or renamed gets its recorded path put
    right — the same routine-staleness repair the lifecycle activation record
    already does. ``_topology`` has re-proved the layout by the time this runs,
    and the existing restore-on-failure covers the extra field.
    """
    root = Path(vault_root).resolve()
    topology_path = vault_root / TOPOLOGY_RELATIVE
    marker_path = brain_git / BRAIN_MARKER_NAME
    topology = _read_regular_json(topology_path, "split topology marker")
    marker = _read_regular_json(marker_path, "brain Git marker")
    previous_topology = dict(topology)
    previous_marker = dict(marker)
    topology["installedRelease"] = commit
    if _relocated_vault(root, topology):
        environment = topology.get("environment")
        if isinstance(environment, dict):
            topology["environment"] = {**environment, "DEX_VAULT": str(root)}
    marker["installed"] = commit
    try:
        _atomic_json(topology_path, topology)
        _atomic_json(marker_path, marker)
        git_output(
            vault_root,
            f"--git-dir={brain_git}",
            "update-ref",
            "refs/dex/installed",
            commit,
            previous_commit,
            profile="mutation",
        )
    except BaseException:
        _atomic_json(topology_path, previous_topology)
        _atomic_json(marker_path, previous_marker)
        raise


def restore_installed_release(vault_root: Path, target_commit: str) -> None:
    """Point the split identity back at ``target_commit``.

    Used when rewinding a delivered release. The live identity must currently
    agree with itself; the value being left is whatever is installed now.
    """
    root = Path(vault_root).resolve()
    brain_git, topology, marker = _topology(root)
    current = _brain_text(
        root, brain_git, "rev-parse", "--verify", "refs/dex/installed^{commit}"
    )
    if topology.get("installedRelease") != current or marker.get("installed") != current:
        raise UpdateError(
            "installed release identity disagrees across the split topology markers"
        )
    if current == target_commit:
        return
    _finalize_release_metadata(
        root,
        brain_git=brain_git,
        commit=target_commit,
        previous_commit=current,
    )


def validated_release_apply_context(
    vault_root: Path,
    release: VerifiedReleaseRef,
) -> str:
    """Return the installed commit after proving a release can replace it.

    This read-only guard is shared by the lifecycle preview and execute routes.
    It deliberately contains no mutation so an approval preview can bind both
    the installed state and the exact immutable target before execution.
    """
    root = Path(vault_root).resolve()
    brain_git, topology, marker = _topology(root)
    if brain_git != release.brain_git:
        raise UpdateError("verified release belongs to a different split brain store")
    previous_commit = _brain_text(root, brain_git, "rev-parse", "--verify", "refs/dex/installed^{commit}")
    if topology.get("installedRelease") != previous_commit or marker.get("installed") != previous_commit:
        raise UpdateError("installed release identity disagrees across the split topology markers")
    if previous_commit == release.commit:
        raise UpdateError("that immutable release is already installed")
    return previous_commit


def apply_verified_release(vault_root: Path, release: VerifiedReleaseRef) -> dict[str, Any]:
    """Apply a verified immutable release through the shared transaction core."""
    root = Path(vault_root).resolve()
    Transaction.resume(root)
    previous_commit = validated_release_apply_context(root, release)
    plan = build_update_plan(root, release)
    transaction = Transaction.begin(root, list(plan.entries), allow_empty=True)
    transaction_result = transaction.run(
        before_commit=lambda: _finalize_release_metadata(
            root,
            brain_git=release.brain_git,
            commit=release.commit,
            previous_commit=previous_commit,
        )
    )
    # Post-commit, best-effort tidy-up shared with the lifecycle service's
    # delivered-release route (issue #433): remove the previous release's
    # activation record so gated operations do not refuse until repaired.
    # See core.lifecycle.bridge.discard_superseded_activation for why the
    # record is removed rather than rewritten and why failure never blocks
    # a committed update.
    from core.lifecycle.bridge import discard_superseded_activation

    discard_superseded_activation(root, release.version)
    return {
        **transaction_result,
        "tag": release.tag,
        "commit": release.commit,
        "version": release.version,
        "channel": release.channel,
        "replaced": list(plan.replaced),
        "seeded": list(plan.seeded),
        "regenerated": list(plan.regenerated),
        "pruned": list(plan.pruned),
        "kept": list(plan.kept),
        "kept_reasons": dict(plan.kept_reasons),
        "untouched": list(plan.untouched),
    }


def _release_identity(release: VerifiedReleaseRef) -> dict[str, str]:
    """Return the closed identity a lifecycle preview must bind to."""
    return {
        "tag": release.tag,
        "tag_object": release.tag_object,
        "commit": release.commit,
        "tree": release.tree,
        "version": release.version,
        "channel": release.channel,
    }


def _is_retryable_public_proof_rejection(evidence: dict[str, object]) -> bool:
    """Accept only closed, sanitized transient public-proof classifications."""
    if set(evidence) == {"status", "reason"}:
        return evidence == {
            "status": "offline",
            "reason": "network-unavailable",
        }
    if set(evidence) == {"status", "reason", "diagnostic"}:
        return evidence == {
            "status": "UNKNOWN",
            "reason": "transient-http-rejection",
            "diagnostic": {"classification": "http-429"},
        }
    return False


def _prove_latest_release_with_bounded_retry(
    root: Path,
    channel: str,
    *,
    state_root: Path | None,
    remote_url: str,
    allow_test_transport: bool,
    git_runner: Any | None,
    wall_clock_seconds: float,
) -> dict[str, object]:
    """Retry one closed transient rejection without extending the proof deadline."""
    from core.utils.update_verifier import prove_latest_release

    initial_budget = max(0.0, wall_clock_seconds)
    proof_deadline = _monotonic() + initial_budget
    evidence: dict[str, object]
    for attempt in (1, 2):
        remaining = (
            initial_budget
            if attempt == 1
            else max(0.0, proof_deadline - _monotonic())
        )
        evidence = prove_latest_release(
            root,
            channel,
            state_root=state_root,
            remote_url=remote_url,
            allow_test_transport=allow_test_transport,
            git_runner=git_runner,
            wall_clock_seconds=remaining,
        )
        if attempt == 2 or not _is_retryable_public_proof_rejection(evidence):
            return evidence
        remaining = max(0.0, proof_deadline - _monotonic())
        if remaining <= PRE_DELIVERY_PROOF_RETRY_BACKOFF_SECONDS:
            return evidence
        time.sleep(PRE_DELIVERY_PROOF_RETRY_BACKOFF_SECONDS)
    raise AssertionError("bounded proof retry loop did not return")


def deliver_latest_release(
    vault_root: Path,
    *,
    state_root: Path | None = None,
    remote_url: str | None = None,
    allow_test_transport: bool = False,
    git_runner: Any | None = None,
    wall_clock_seconds: float = 10.0,
) -> dict[str, Any]:
    """Fetch and re-verify one evidence-pinned release without changing vault content.

    This is the read side of delivery. It proves an immutable release in a
    disposable evidence cache, fetches only that exact tag and channel ref into
    Dex's private brain store, then re-proves the fetched bytes. It deliberately
    does not build a transaction or mutate a vault file; the lifecycle service
    must turn this returned identity into the exact user-visible preview.
    """
    from core.utils.update_verifier import (
        CANONICAL_REMOTE_URL,
        STATUS_IDENTITY,
        ExecutionBudget,
        GitRunner,
        OfflineError,
    )

    root = Path(vault_root).resolve()
    channel = release_channel.read_channel(root)
    effective_remote = remote_url or CANONICAL_REMOTE_URL
    evidence = _prove_latest_release_with_bounded_retry(
        root,
        channel,
        state_root=state_root,
        remote_url=effective_remote,
        allow_test_transport=allow_test_transport,
        git_runner=git_runner,
        wall_clock_seconds=wall_clock_seconds,
    )
    if evidence.get("status") != STATUS_IDENTITY:
        return {"status": "not-delivered", "evidence": evidence}

    tag = evidence["tag"]
    tag_object = evidence["tag_object"]
    commit = evidence["commit"]
    tree = evidence["tree"]
    if not all(isinstance(value, str) for value in (tag, tag_object, commit, tree)):
        return {"status": "not-delivered", "evidence": {"status": "UNKNOWN", "reason": "identity-malformed"}}

    brain_git, _topology_value, _brain_marker = _topology(root)
    _verify_official_origin(root, brain_git)
    branch = release_channel.release_branch(channel)
    if branch is None:
        return {"status": "not-delivered", "evidence": {"status": "UNKNOWN", "reason": "channel-invalid"}}
    transport = git_runner or GitRunner(allowed_protocol="file" if allow_test_transport else "https")
    for attempt in (1, 2):
        attempt_seconds = min(
            max(0.0, wall_clock_seconds),
            FINAL_FETCH_ATTEMPT_BUDGET_SECONDS,
        )
        transport.use_budget(ExecutionBudget.start(attempt_seconds))
        try:
            transport.run(
                brain_git,
                "fetch",
                "--quiet",
                "--no-tags",
                "--no-write-fetch-head",
                "--no-recurse-submodules",
                effective_remote,
                f"refs/tags/{tag}:refs/tags/{tag}",
                f"+refs/heads/{branch}:refs/remotes/upstream/{branch}",
                network=True,
                max_output_bytes=1024,
            )
            break
        except OfflineError as error:
            if attempt == 2:
                raise OfflineError("final release delivery fetch was unavailable after attempt 2") from error
            time.sleep(FINAL_FETCH_RETRY_BACKOFF_SECONDS)
    release = verify_release_ref(
        root,
        tag=tag,
        tag_object=tag_object,
        commit=commit,
        tree=tree,
    )
    return {"status": "delivered", "release": _release_identity(release)}


def deliver_and_apply_latest_release(
    vault_root: Path,
    **kwargs: Any,
) -> dict[str, Any]:
    """Compatibility shim for the withdrawn unsafe one-step delivery API.

    Version 1.3 exposed this name before its approval-boundary flaw was found.
    Preserve its call shape, but never apply an unseen release: callers receive
    a safe refusal and must use the lifecycle deliver-preview-execute route.
    """
    del vault_root, kwargs
    return {
        "status": "not-delivered",
        "evidence": {
            "status": "deprecated",
            "reason": "use-lifecycle-deliver-preview-execute",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=Path.cwd())
    parser.add_argument("--deliver-latest", action="store_true")
    parser.add_argument("--tag")
    parser.add_argument("--tag-object")
    parser.add_argument("--commit")
    parser.add_argument("--tree")
    args = parser.parse_args(argv)
    try:
        if args.deliver_latest:
            if any(value is not None for value in (args.tag, args.tag_object, args.commit, args.tree)):
                parser.error("--deliver-latest cannot be combined with an explicit release identity")
            result = deliver_latest_release(args.vault)
        else:
            if any(value is None for value in (args.tag, args.tag_object, args.commit, args.tree)):
                parser.error("--tag, --tag-object, --commit, and --tree are required without --deliver-latest")
            parser.error(
                "direct release application is retired; core.lifecycle.service "
                "must build and execute the approved preview"
            )
    except (OSError, RuntimeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
