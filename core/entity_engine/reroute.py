"""Recompute person page Internal/External routing from recorded emails.

Routing is normally decided once, when a page is created. After the configured
internal email domains change, existing pages keep their old folders. This
module re-derives each routed person's location from the emails recorded on
the page and — only outside dry-run — moves pages between People/Internal and
People/External, rewriting the ``location:`` frontmatter (and its
``dex_last_written`` mirror) through the engine's own merge path.

Safety rules, in order of precedence:

- Nothing is ever deleted or overwritten. A move whose target filename already
  exists is skipped with a warning.
- A page with no recorded emails (frontmatter ``emails:`` falling back to the
  ``dex_last_written`` mirror) is ambiguous and never guessed at.
- A page whose ``location`` is user-owned (pinned, or hand-edited away from
  the mirror) is skipped rather than half-migrated.
- ``People/CPO_Network`` and any other sibling folders are never touched.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .contract import (
    _normalise_field,
    _split_frontmatter,
    parse_entity_page,
)
from .write import fingerprint_page, mutate_page

_ROUTED_FOLDERS = {"Internal": "internal", "External": "external"}
_FOLDER_FOR_LOCATION = {"internal": "Internal", "external": "External"}


def normalise_domains(domains: Any) -> set[str]:
    """Lower-case, strip, and de-@ a supplied internal-domain collection."""
    if not domains:
        return set()
    return {
        str(value).strip().lower().lstrip("@")
        for value in domains
        if str(value).strip().lstrip("@")
    }


def _email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].strip().lower() if "@" in email else ""


def _recorded_emails(
    parsed: dict[str, Any],
    frontmatter: dict[str, Any] | None,
) -> tuple[list[str], str]:
    """Return recorded emails and their source, mirror-falling-back."""
    emails = parsed.get("emails") or []
    if emails:
        return list(emails), "frontmatter"
    mirror = (
        frontmatter.get("dex_last_written")
        if isinstance(frontmatter, dict)
        else None
    )
    if isinstance(mirror, dict):
        mirror_emails = _normalise_field("emails", mirror.get("emails"))
        if mirror_emails:
            return mirror_emails, "dex_last_written"
    return [], "none"


def _classify(emails: list[str], internal_domains: set[str]) -> tuple[str, str]:
    """Return (location, deciding email): any internal email wins."""
    for email in emails:
        if _email_domain(email) in internal_domains:
            return "internal", email
    return "external", emails[0]


def _location_user_owned(
    frontmatter: dict[str, Any] | None,
    effective_location: str | None,
) -> str | None:
    """Return why the user owns ``location``, or ``None`` when the engine may write it."""
    if not isinstance(frontmatter, dict):
        return None
    pinned = frontmatter.get("dex_pinned")
    if isinstance(pinned, dict) and pinned.get("location") == "user":
        return "location is pinned by the user"
    mirror = frontmatter.get("dex_last_written")
    if isinstance(mirror, dict) and "location" in mirror:
        mirror_location = _normalise_field("location", mirror.get("location"))
        if effective_location != mirror_location:
            return "location was hand-edited since the last engine write"
    return None


def _collision(target_dir: Path, filename: str) -> bool:
    if not target_dir.exists():
        return False
    return any(
        child.is_file() and child.name.casefold() == filename.casefold()
        for child in target_dir.iterdir()
    )


def _relative(path: Path, vault_root: Path) -> str:
    try:
        return path.resolve().relative_to(vault_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _move_without_overwrite(source: Path, target: Path) -> str:
    """Move a page, refusing to replace an existing target file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, target)
    except FileExistsError:
        return "collision"
    except OSError:
        # Filesystems without hard links: fall back to a checked rename.
        if target.exists():
            return "collision"
        source.rename(target)
        return "moved"
    source.unlink()
    return "moved"


def _rewrite_location(page_path: Path, location: str) -> str:
    """Rewrite ``location:`` (and its mirror) through the engine merge path."""
    try:
        result = mutate_page(
            page_path,
            fingerprint_page(page_path),
            field_changes={"location": location},
        )
    except OSError as exc:
        return f"failed: {exc}"
    if result.status in {"updated", "noop"}:
        return "updated" if result.changed else "unchanged"
    return f"failed: {result.status}"


def _evaluate_page(
    page: Path,
    current_location: str,
    internal_domains: set[str],
    people_dir: Path,
    vault_root: Path,
) -> dict[str, Any]:
    """Classify one routed person page and plan the action it needs."""
    entry: dict[str, Any] = {
        "path": _relative(page, vault_root),
        "name": page.stem.replace("_", " "),
        "current_location": current_location,
    }
    try:
        parsed = parse_entity_page(page)
        text = page.read_text(encoding="utf-8-sig")
        frontmatter, _body, _had_frontmatter, quarantined = _split_frontmatter(
            text
        )
    except Exception as exc:  # A page that cannot be parsed is never guessed.
        entry["action"] = "ambiguous"
        entry["reason"] = f"page could not be parsed: {exc}"
        return entry
    if quarantined:
        frontmatter = None
    if parsed.get("name"):
        entry["name"] = parsed["name"]

    emails, email_source = _recorded_emails(parsed, frontmatter)
    if not emails:
        entry["action"] = "ambiguous"
        entry["reason"] = "no recorded emails; location cannot be recomputed"
        return entry

    recomputed, deciding_email = _classify(emails, internal_domains)
    entry["recomputed_location"] = recomputed
    entry["deciding_email"] = deciding_email
    entry["email_source"] = email_source

    effective_location = parsed.get("location")
    needs_relabel = (
        frontmatter is not None and effective_location != recomputed
    )
    if needs_relabel:
        owned_reason = _location_user_owned(frontmatter, effective_location)
        if owned_reason is not None:
            entry["action"] = "skip"
            entry["reason"] = owned_reason
            return entry

    if recomputed == current_location:
        if needs_relabel:
            entry["action"] = "relabel"
            return entry
        entry["action"] = "none"
        return entry

    target_dir = people_dir / _FOLDER_FOR_LOCATION[recomputed]
    if _collision(target_dir, page.name):
        entry["action"] = "skip"
        entry["reason"] = (
            f"target filename already exists in "
            f"{_relative(target_dir, vault_root)}; never overwritten"
        )
        return entry

    entry["action"] = "move"
    entry["target_path"] = _relative(target_dir / page.name, vault_root)
    entry["frontmatter_update"] = needs_relabel
    return entry


def reroute_people(
    vault_root: Path,
    people_dir: Path,
    internal_domains: set[str],
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Plan (and, outside dry-run, apply) Internal/External re-routing."""
    domains = normalise_domains(internal_domains)
    if not domains:
        return {
            "success": False,
            "error": "No internal email domains supplied; refusing to reroute.",
        }

    moves: list[dict[str, Any]] = []
    relabels: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    warnings: list[str] = []
    already_correct = 0
    scanned = 0

    for folder, current_location in _ROUTED_FOLDERS.items():
        directory = people_dir / folder
        if not directory.exists():
            continue
        for page in sorted(directory.glob("*.md")):
            if page.name == "README.md":
                continue
            scanned += 1
            entry = _evaluate_page(
                page,
                current_location,
                domains,
                people_dir,
                vault_root,
            )
            action = entry.pop("action")
            if action == "none":
                already_correct += 1
            elif action == "ambiguous":
                ambiguous.append(entry)
            elif action == "skip":
                skipped.append(entry)
                warnings.append(f"{entry['path']}: {entry['reason']}")
            elif action == "relabel":
                relabels.append(entry)
            else:
                moves.append(entry)

    result: dict[str, Any] = {
        "success": True,
        "dry_run": dry_run,
        "internal_domains": sorted(domains),
        "scanned": scanned,
        "already_correct": already_correct,
        "moves": moves,
        "relabels": relabels,
        "ambiguous": ambiguous,
        "skipped": skipped,
        "warnings": warnings,
    }
    if dry_run:
        return result

    applied = {"moved": 0, "relabeled": 0, "failed": 0}
    for entry in moves:
        source = vault_root / entry["path"]
        target = vault_root / entry["target_path"]
        outcome = _move_without_overwrite(source, target)
        if outcome != "moved":
            entry["moved"] = False
            entry["frontmatter"] = "unchanged"
            applied["failed"] += 1
            warnings.append(
                f"{entry['path']}: target appeared before the move; "
                "skipped, never overwritten"
            )
            continue
        entry["moved"] = True
        if entry.pop("frontmatter_update", False):
            entry["frontmatter"] = _rewrite_location(
                target,
                entry["recomputed_location"],
            )
        else:
            entry["frontmatter"] = "unchanged"
        if str(entry["frontmatter"]).startswith("failed"):
            applied["failed"] += 1
            warnings.append(
                f"{entry['target_path']}: page moved but its location "
                f"frontmatter could not be rewritten ({entry['frontmatter']})"
            )
        applied["moved"] += 1
    for entry in relabels:
        entry["frontmatter"] = _rewrite_location(
            vault_root / entry["path"],
            entry["recomputed_location"],
        )
        if entry["frontmatter"] == "updated":
            applied["relabeled"] += 1
        else:
            applied["failed"] += 1
            warnings.append(
                f"{entry['path']}: location frontmatter could not be "
                f"rewritten ({entry['frontmatter']})"
            )

    result["applied"] = applied
    return result
