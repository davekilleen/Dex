#!/usr/bin/env python3
"""Convert Dex .claude/skills to opencode .opencode/skill format.

Copies each skill folder, rewrites SKILL.md frontmatter to keep only the
keys opencode understands (name, description, optional license/metadata),
and drops all Claude-Code/Dex-only keys (hooks, model_routing, model_hint,
integration, manifest, capability, trigger, context, disable-model-invocation, ...).

The skill bodies reference paths relative to the project root (e.g.
core/mcp/..., .claude/hooks/...) which are preserved because the repo
structure is kept intact.
"""
import re
import shutil
import sys
from pathlib import Path

import yaml

SRC = Path(".claude/skills")
DST = Path(".opencode/skill")

KEEP = {"name", "description", "license", "metadata"}


def rewrite_frontmatter(path: Path) -> tuple[bool, str]:
    """Return (changed, reason) — rewrites frontmatter in place to only KEEP keys."""
    txt = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n?", txt, re.S)
    if not m:
        return False, "no-frontmatter"

    front = m.group(1)
    try:
        data = yaml.safe_load(front)
    except Exception as e:
        return False, f"yaml-error: {e}"
    if not isinstance(data, dict):
        return False, "frontmatter-not-map"

    dropped = [k for k in data.keys() if k not in KEEP]
    kept = {k: v for k, v in data.items() if k in KEEP and v is not None}

    if not dropped and kept == {k: v for k, v in data.items() if v is not None}:
        return False, "already-clean"

    # Re-serialize preserving order: name, description first, rest after.
    new_data = {}
    for k in ("name", "description"):
        if k in kept:
            new_data[k] = kept[k]
    for k in kept:
        if k not in new_data:
            new_data[k] = kept[k]

    new_front = yaml.safe_dump(
        new_data, sort_keys=False, allow_unicode=True, default_flow_style=False
    ).strip()
    body = txt[m.end():]
    if not body.startswith("\n"):
        body = "\n" + body
    path.write_text(f"---\n{new_front}\n---{body}", encoding="utf-8")
    return True, f"dropped={dropped}"


def main() -> int:
    src = Path(SRC)
    dst = Path(DST)
    dst.mkdir(parents=True, exist_ok=True)

    stats = {"copied": 0, "rewritten": 0, "unchanged": 0, "skipped": 0}
    rewrites = []
    for skill_dir in sorted(src.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            print(f"SKIP (no SKILL.md): {skill_dir.name}")
            stats["skipped"] += 1
            continue

        target = dst / skill_dir.name
        if target.exists():
            print(f"SKIP (exists): {skill_dir.name}")
            stats["skipped"] += 1
            continue

        # copy the whole folder (keeps AGENT_INSTRUCTIONS.md, scripts, etc.)
        shutil.copytree(skill_dir, target)
        stats["copied"] += 1

        changed, reason = rewrite_frontmatter(target / "SKILL.md")
        if changed:
            stats["rewritten"] += 1
            rewrites.append((skill_dir.name, reason))
        else:
            stats["unchanged"] += 1

    print("\n=== SUMMARY ===")
    print(stats)
    print("\n=== REWRITTEN ===")
    for name, reason in rewrites:
        print(f"  {name}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
