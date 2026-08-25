#!/usr/bin/env python3
"""Generate the explicit skill portability classification manifest."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".claude" / "skills"
DEST = ROOT / "core" / "harnesses" / "portability.json"


def _generator_module():
    path = ROOT / "scripts" / "generate-agents-skills.py"
    spec = importlib.util.spec_from_file_location("generate_agents_skills", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expected_manifest(repo_root: Path = ROOT) -> dict:
    generator = _generator_module()
    source = repo_root / ".claude" / "skills"
    entries: dict[str, dict] = {}
    for skill_md in generator.discover_canonical_skills(source):
        key = skill_md.parent.relative_to(source).as_posix()
        text = skill_md.read_text(encoding="utf-8")
        _frontmatter, body = generator._split_frontmatter(text, key)
        host = generator.HOST_ONLY_COMMAND.search(body)
        broken = None
        for match in generator.CLAUDE_SKILL_PATH.finditer(body):
            target = source / match.group(1)
            if not (target.is_file() or target.is_dir()):
                broken = f"missing .claude/skills/{match.group(1)}"
                break
        if broken is None:
            for match in generator.LOCAL_RESOURCE_PATH.finditer(body):
                target = skill_md.parent / match.group(1)
                if not (target.is_file() or target.is_dir()):
                    broken = f"missing {match.group(1)}"
                    break
        if broken is None:
            for companion in generator.companion_files(skill_md.parent):
                try:
                    companion_text = companion.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                if generator.HOST_ONLY_COMMAND.search(companion_text):
                    host = generator.HOST_ONLY_COMMAND.search(companion_text)
                    break
                for match in generator.CLAUDE_SKILL_PATH.finditer(companion_text):
                    target = source / match.group(1)
                    if not (target.is_file() or target.is_dir()):
                        broken = f"missing .claude/skills/{match.group(1)}"
                        break
                if broken is not None:
                    break
                for match in generator.LOCAL_RESOURCE_PATH.finditer(companion_text):
                    target = skill_md.parent / match.group(1)
                    if not (target.is_file() or target.is_dir()):
                        broken = f"missing {match.group(1)}"
                        break
                if broken is not None:
                    break
        entry: dict[str, object]
        if key in {"diff-adopt-profile", "feedback"}:
            # These source files intentionally contain founder-facing copy;
            # do not duplicate it into a cross-harness package by default.
            entry = {"classification": "claude-only", "reason": "contains founder-specific product copy"}
        elif key == "anthropic-canvas-design":
            # The bundled fonts must retain their licence files, and those
            # licences contain third-party personal email addresses. Keep the
            # complete skill in its native Claude distribution instead of
            # duplicating personal contact details into portable packages.
            entry = {
                "classification": "claude-only",
                "reason": "bundled font licences contain third-party personal contact details",
            }
        elif key == "granola-setup":
            # The canonical skill explicitly prohibits obsolete local-cache
            # techniques. Portable copies keep the safety boundary without
            # repeating legacy filenames that repository-wide truth gates ban.
            entry = {
                "classification": "portable",
                "reason": "official API guidance has a host-neutral portable wording",
                "body_replacements": [
                    {
                        "pattern": r"(?m)^- \*\*Official API is the only data source\.\*\*.*$",
                        "replacement": (
                            "- **Official API is the only data source.** Do not read local cache "
                            "files or use spoofed client headers or unofficial crypto helpers. "
                            "Use only the documented endpoints below with the "
                            "`Authorization: Bearer` header."
                        ),
                    }
                ],
            }
        elif broken:
            entry = {"classification": "broken", "reason": broken}
        elif host:
            # A tiny, explicit fallback keeps the high-traffic onboarding skill
            # useful on non-Claude hosts while every other host command fails
            # closed and remains classified as Claude-only.
            if key == "getting-started":
                entry = {
                    "classification": "portable",
                    "reason": "host prompt and optional integration hook have a portable fallback",
                    "body_replacements": [
                        {
                            "pattern": r"(?m)^node \.claude/hooks/integration-concierge\.cjs\s*$",
                            "replacement": "Use the harness's MCP integration flow if available; otherwise continue without optional integrations.",
                        },
                        {"pattern": r"AskUserQuestion", "replacement": "prompt_user"},
                    ],
                }
            elif key in {"daily-plan", "daily-review", "meeting-prep", "week-review"}:
                entry = {
                    "classification": "portable",
                    "reason": "Claude settings mention is explanatory only and has a host-neutral wording",
                    "body_replacements": [
                        {"pattern": r"\.claude/settings\.json", "replacement": "the host's lifecycle settings"},
                    ],
                }
            else:
                entry = {"classification": "claude-only", "reason": "contains a Claude-only body command"}
        else:
            entry = {"classification": "portable", "reason": "no host-only body command or broken local reference"}
        entries[key] = entry
    return {
        "schema_version": "1.0.0",
        "source": ".claude/skills",
        "generated_by": "scripts/generate-harness-portability.py",
        "classifications": ["portable", "conditional", "claude-only", "broken"],
        "skills": entries,
    }


def write_manifest(repo_root: Path = ROOT) -> int:
    payload = expected_manifest(repo_root)
    destination = repo_root / "core" / "harnesses" / "portability.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Generated portability manifest for {len(payload['skills'])} skills.")
    return 0


def check_manifest(repo_root: Path = ROOT) -> int:
    expected = json.dumps(expected_manifest(repo_root), indent=2, sort_keys=True) + "\n"
    destination = repo_root / "core" / "harnesses" / "portability.json"
    if not destination.is_file() or destination.read_text(encoding="utf-8") != expected:
        print("portability manifest is stale; run scripts/generate-harness-portability.py")
        return 1
    print("Portability manifest is current.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    return check_manifest() if args.check else write_manifest()


if __name__ == "__main__":
    raise SystemExit(main())
