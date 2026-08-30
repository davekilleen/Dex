#!/usr/bin/env python3
"""Generate the harness-neutral ``.agents/skills`` surface.

``.claude/skills`` remains canonical.  The portability manifest decides which
skills can safely travel to a host without Claude Code hooks.  Generated
adapters copy every resource (including ``scripts/``, ``assets/``,
``references/`` and ``evals/``), preserve ``*-custom`` directories, and fail
closed when a portable skill contains a broken local reference or a host-only
command.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT / ".claude" / "skills"
DEST_ROOT = REPO_ROOT / ".agents" / "skills"
MANIFEST_PATH = REPO_ROOT / "core" / "harnesses" / "portability.json"
GENERATOR_PATH = "scripts/generate-agents-skills.py"

CLAUDE_ONLY_FRONTMATTER = frozenset({"hooks", "context", "model_routing"})
FRONTMATTER_KEY = re.compile(r"^([A-Za-z0-9_-]+):")
GENERATED_COMMENT = "<!-- Generated from `{source}` by `{generator}`. Do not edit. -->\n"
HOST_ONLY_COMMAND = re.compile(
    r"(?:^|[\s`])(?:node|python(?:3)?|bash|sh|npx)\s+[^\n]*(?:\.claude/hooks/|\.claude/settings\.json)"
    r"|(?:^|[\s`])claude\s+mcp\s+\w+|\bAskUserQuestion\s*\(|\.claude/(?:hooks|flows)/|\.claude/settings\.json",
    re.IGNORECASE,
)
CLAUDE_SKILL_PATH = re.compile(r"\.claude/skills/([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)")
CLAUDE_SKILLS_ROOT = re.compile(r"\.claude/skills(?=[`'\" )\],]|$)")
LOCAL_RESOURCE_PATH = re.compile(
    r"(?<![A-Za-z0-9_./-])((?:scripts|references|assets|evals)/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)"
)


def _is_custom_path(path: Path) -> bool:
    return any(part.endswith("-custom") for part in path.parts)


def _is_python_cache(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix == ".pyc"


def discover_canonical_skills(source_root: Path = SOURCE_ROOT) -> list[Path]:
    """Return every shipped ``SKILL.md`` except user-owned variants."""
    return [
        path for path in sorted(source_root.rglob("SKILL.md")) if not _is_custom_path(path.relative_to(source_root))
    ]


def load_portability_manifest(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    path = repo_root / "core" / "harnesses" / "portability.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read portability manifest: {path}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0.0":
        raise ValueError("portability manifest must declare schema_version 1.0.0")
    skills = payload.get("skills")
    if not isinstance(skills, dict):
        raise ValueError("portability manifest skills must be an object")
    return payload


def strip_claude_only_frontmatter(frontmatter: str) -> str:
    """Drop Claude-only keys and their indented YAML blocks."""
    lines = frontmatter.splitlines(keepends=True)
    kept: list[str] = []
    skipping = False
    for line in lines:
        if skipping:
            if line.strip() == "":
                continue
            if line[:1] in {" ", "\t"}:
                continue
            skipping = False
        match = FRONTMATTER_KEY.match(line)
        if match and match.group(1) in CLAUDE_ONLY_FRONTMATTER:
            skipping = True
            continue
        kept.append(line)
    text = "".join(kept)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n") + ("\n" if text.strip() else "")


def _split_frontmatter(source_text: str, source_relative: str) -> tuple[str, str]:
    if not source_text.startswith("---\n"):
        raise ValueError(f"skill lacks frontmatter: {source_relative}")
    end = source_text.find("\n---", 4)
    if end < 0:
        raise ValueError(f"skill has unterminated frontmatter: {source_relative}")
    frontmatter = source_text[4:end]
    body = source_text[end + len("\n---") :].lstrip("\n")
    return frontmatter, body


def _manifest_entry(manifest: Mapping[str, Any], skill_key: str) -> dict[str, Any]:
    value = manifest.get("skills", {}).get(skill_key)
    if not isinstance(value, dict):
        raise ValueError(f"skill is missing a portability classification: {skill_key}")
    classification = value.get("classification")
    if classification not in {"portable", "conditional", "claude-only", "broken"}:
        raise ValueError(f"invalid portability classification for {skill_key}: {classification!r}")
    return value


def _skill_key(skill_md: Path, source_root: Path) -> str:
    return skill_md.parent.relative_to(source_root).as_posix()


def _path_exists(path: Path) -> bool:
    return path.is_file() or path.is_dir()


def _validate_local_references(
    text: str,
    *,
    source_skill: Path,
    source_root: Path,
    portable_keys: set[str],
    resource_root: Path | None = None,
) -> None:
    """Reject missing resources and references to skills not shipped here."""
    for match in CLAUDE_SKILL_PATH.finditer(text):
        relative = Path(match.group(1))
        target = source_root / relative
        if not _path_exists(target):
            raise ValueError(f"broken local reference in {source_skill}: .claude/skills/{relative.as_posix()}")
        target_key = relative.parts[0]
        if target_key.endswith("-custom"):
            continue
        if target_key in portable_keys:
            continue
        # A canonical path to a Claude-only skill cannot be left in a portable
        # adapter: it would point at a file the adapter intentionally omits.
        if len(relative.parts) >= 2 and relative.parts[1] == "SKILL.md":
            raise ValueError(f"portable skill references non-portable skill {target_key}: {source_skill}")
    for match in LOCAL_RESOURCE_PATH.finditer(text):
        relative = Path(match.group(1))
        target = (resource_root or source_skill.parent) / relative
        if not _path_exists(target):
            raise ValueError(f"broken local resource reference in {source_skill}: {relative.as_posix()}")


def _apply_body_replacements(text: str, entry: Mapping[str, Any], source: Path) -> str:
    replacements = entry.get("body_replacements", [])
    if replacements is None:
        replacements = []
    if not isinstance(replacements, list):
        raise ValueError(f"body_replacements must be an array for {source}")
    result = text
    for replacement in replacements:
        if not isinstance(replacement, Mapping):
            raise ValueError(f"invalid body replacement for {source}")
        pattern = replacement.get("pattern")
        value = replacement.get("replacement", "")
        if not isinstance(pattern, str) or not isinstance(value, str):
            raise ValueError(f"invalid body replacement for {source}")
        result = re.sub(pattern, value, result, flags=re.MULTILINE)
    return result


def _rewrite_existing_skill_paths(
    text: str,
    *,
    source_root: Path,
    portable_keys: set[str],
    current_key: str,
) -> str:
    def replace(match: re.Match[str]) -> str:
        relative = Path(match.group(1))
        source_target = source_root / relative
        if not _path_exists(source_target):
            raise ValueError(f"broken local reference: .claude/skills/{relative.as_posix()}")
        target_key = relative.parts[0]
        if target_key.endswith("-custom"):
            return match.group(0)
        if target_key not in portable_keys:
            raise ValueError(f"cannot rewrite path to non-portable skill: {target_key}")
        return ".agents/skills/" + relative.as_posix()

    rewritten = CLAUDE_SKILL_PATH.sub(replace, text)
    return CLAUDE_SKILLS_ROOT.sub(".agents/skills", rewritten)


def _validate_host_commands(text: str, source: Path) -> None:
    match = HOST_ONLY_COMMAND.search(text)
    if match:
        snippet = " ".join(match.group(0).split())[:120]
        raise ValueError(f"host-only body command in {source}: {snippet}")


def transform_skill_markdown(
    source_text: str,
    *,
    source_relative: str,
    source_path: Path | None = None,
    manifest_entry: Mapping[str, Any] | None = None,
    source_root: Path | None = None,
    portable_keys: set[str] | None = None,
) -> tuple[str, str, str]:
    """Return portable frontmatter, generated comment, and transformed body."""
    frontmatter, body = _split_frontmatter(source_text, source_relative)
    body = _apply_body_replacements(body, manifest_entry or {}, source_path or Path(source_relative))
    _validate_host_commands(body, source_path or Path(source_relative))
    if source_path is not None and source_root is not None:
        _validate_local_references(
            body,
            source_skill=source_path,
            source_root=source_root,
            portable_keys=portable_keys or set(),
        )
        body = _rewrite_existing_skill_paths(
            body,
            source_root=source_root,
            portable_keys=portable_keys or set(),
            current_key=source_path.parent.relative_to(source_root).as_posix(),
        )
    stripped = strip_claude_only_frontmatter(frontmatter)
    comment = GENERATED_COMMENT.format(source=source_relative, generator=GENERATOR_PATH)
    return stripped, comment, body


def _portable_skill_paths(repo_root: Path, manifest: Mapping[str, Any]) -> list[Path]:
    source_root = repo_root / ".claude" / "skills"
    paths: list[Path] = []
    for skill_md in discover_canonical_skills(source_root):
        entry = _manifest_entry(manifest, _skill_key(skill_md, source_root))
        if entry["classification"] == "portable" or entry.get("generate") is True:
            paths.append(skill_md)
    return paths


def companion_files(skill_dir: Path) -> list[Path]:
    """Return every regular resource below a skill, including scripts/assets."""
    files: list[Path] = []
    for path in sorted(skill_dir.rglob("*")):
        relative = path.relative_to(skill_dir)
        if not path.is_file() or _is_custom_path(relative) or _is_python_cache(relative):
            continue
        if path.name == "SKILL.md":
            continue
        if path.is_symlink():
            raise ValueError(f"skill resource must not be a symlink: {path}")
        files.append(path)
    return files


def expected_adapters(repo_root: Path = REPO_ROOT) -> dict[Path, str | bytes]:
    """Return generated destination paths and bytes, validating first."""
    source_root = repo_root / ".claude" / "skills"
    manifest = load_portability_manifest(repo_root)
    skill_paths = _portable_skill_paths(repo_root, manifest)
    portable_keys = {_skill_key(path, source_root).split("/", 1)[0] for path in skill_paths}
    expected: dict[Path, bytes] = {}
    for skill_md in skill_paths:
        key = _skill_key(skill_md, source_root)
        entry = _manifest_entry(manifest, key)
        source_relative = skill_md.relative_to(repo_root).as_posix()
        frontmatter, comment, body = transform_skill_markdown(
            skill_md.read_text(encoding="utf-8"),
            source_relative=source_relative,
            source_path=skill_md,
            manifest_entry=entry,
            source_root=source_root,
            portable_keys=portable_keys,
        )
        generated = f"---\n{frontmatter}---\n\n{comment}\n{body}"
        destination = repo_root / ".agents" / "skills" / key / "SKILL.md"
        expected[destination.relative_to(repo_root)] = generated
        for companion in companion_files(skill_md.parent):
            relative = companion.relative_to(skill_md.parent)
            payload = companion.read_bytes()
            try:
                companion_text = payload.decode("utf-8")
            except UnicodeDecodeError:
                # Binary assets are copied byte-for-byte; they contain no
                # textual resource path that can be safely rewritten.
                expected[(Path(".agents") / "skills" / key / relative)] = payload
                continue
            _validate_host_commands(companion_text, companion)
            _validate_local_references(
                companion_text,
                source_skill=companion,
                source_root=source_root,
                portable_keys=portable_keys,
                resource_root=skill_md.parent,
            )
            companion_text = _rewrite_existing_skill_paths(
                companion_text,
                source_root=source_root,
                portable_keys=portable_keys,
                current_key=key,
            )
            expected[(Path(".agents") / "skills" / key / relative)] = companion_text
    return expected


def _existing_generated_files(dest_root: Path, repo_root: Path) -> set[Path]:
    if not dest_root.is_dir():
        return set()
    return {
        path
        for path in dest_root.rglob("*")
        if path.is_file()
        and not _is_custom_path(path.relative_to(dest_root))
        and not _is_python_cache(path.relative_to(dest_root))
    }


def write_adapters(repo_root: Path = REPO_ROOT) -> int:
    expected = expected_adapters(repo_root)
    dest_root = repo_root / ".agents" / "skills"
    dest_root.mkdir(parents=True, exist_ok=True)
    written = 0
    for relative, payload in expected.items():
        destination = repo_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        encoded = payload.encode("utf-8") if isinstance(payload, str) else payload
        if not destination.is_file() or destination.read_bytes() != encoded:
            destination.write_bytes(encoded)
            written += 1
    expected_paths = {repo_root / relative for relative in expected}
    removed = 0
    for stale in _existing_generated_files(dest_root, repo_root):
        if stale not in expected_paths:
            stale.unlink()
            removed += 1
    print(f"Generated {len(expected)} adapter files under .agents/skills/ ({written} written, {removed} removed).")
    return 0


def check_adapters(repo_root: Path = REPO_ROOT) -> int:
    expected = expected_adapters(repo_root)
    dest_root = repo_root / ".agents" / "skills"
    errors: list[str] = []
    for relative, payload in expected.items():
        destination = repo_root / relative
        if not destination.is_file():
            errors.append(f"missing {relative.as_posix()}")
        elif destination.read_bytes() != (payload.encode("utf-8") if isinstance(payload, str) else payload):
            errors.append(f"drifted {relative.as_posix()}")
    expected_paths = {repo_root / relative for relative in expected}
    for extra in _existing_generated_files(dest_root, repo_root):
        if extra not in expected_paths:
            errors.append(f"unexpected {extra.relative_to(repo_root).as_posix()}")
    if errors:
        print("❌ .agents/skills adapters are stale or incomplete:", file=sys.stderr)
        for error in errors[:40]:
            print(f"  {error}", file=sys.stderr)
        if len(errors) > 40:
            print(f"  ... and {len(errors) - 40} more", file=sys.stderr)
        print(f"Run python3 {GENERATOR_PATH} and commit.", file=sys.stderr)
        return 1
    print(f".agents/skills adapters are current ({len(expected)} files).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify committed adapters")
    args = parser.parse_args()
    return check_adapters() if args.check else write_adapters()


if __name__ == "__main__":
    raise SystemExit(main())
