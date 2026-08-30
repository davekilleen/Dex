#!/usr/bin/env python3
"""Generate plain-English founder test pages from harness adapter JSON.

Each adapter with a written install path becomes one page: numbered steps,
what the person should see, one checkbox per outcome, and the exact failure
sentence to send back. Pages are derived from
``core/harnesses/adapters/*.json`` so they cannot silently drift.

The chatgpt-work page stops at the vault-folder grant. It does not claim a
live install and does not invent that grant. No page includes a publish,
sign, store, or invite step.

The family (copilot-cli) page records the fixture-proved PreToolUse refusal.
The VS Code page stays advisory. Every page ends with the same honesty:
nobody has walked it; this is not a live install.

Unreleased. Do not merge. Do not publish.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAB_ISSUE = "https://github.com/davekilleen/dex-product-gtm-lab/issues/484"
GENERATOR = "scripts/generate-founder-test-cards.py"
WORK_ID = "chatgpt-work"
FAMILY_ID = "copilot-cli"
ADVISORY_EDITOR_ID = "vscode"
SENTENCE_SPLIT = re.compile(r"(?<=\.)\s+(?=[A-Z0-9`~])")
LOCAL_OR_MARKETPLACE = re.compile(
    r"\s+or\s+a\s+future\s+marketplace\b.*", re.IGNORECASE
)
ACTION_PREFIXES = (
    "copy ",
    "add ",
    "update ",
    "restart ",
    "reload ",
    "open ",
    "install ",
    "start ",
    "run ",
    "build ",
    "select ",
    "grant ",
    "upload ",
    "confirm ",
    "turn on ",
    "turn off ",
    "from the ",
    "on macos",
    "in ",
)
STEP_FIELD_KEYS = (
    "enable_setting",
    "plugin_locations_setting",
    "plugin_locations_entry",
    "install_command",
    "inspect_command",
)
FORBIDDEN_STEP_ACTION = re.compile(
    r"(?i)\b(publish|sign|store the secret|invite)\b"
)
MODEL_OR_VENDOR = re.compile(
    r"(?i)\b(openai|anthropic|anysphere|gpt-4|gpt-5|grok|sonnet|opus|haiku|llama)\b"
)
HONEST_CLOSE = (
    "Nobody has walked this path. This is not a live install. "
    "Do not publish. Do not sign, store, or invite anyone."
)
FAMILY_REFUSAL = (
    "A fixture sent a destructive command through the family PreToolUse "
    "protocol. The gate refused it (`permissionDecision: deny`, exit 2). "
    "That is a fixture, not a person opening this host. Nobody has walked "
    "this path. This is not a live install."
)
ADVISORY_EDITOR = (
    "Safety on this editor stays advisory. The family PreToolUse refusal "
    "file is in the shipped package, but this page does not claim a live "
    "intercept. The bundled safety check remains advisory unless a trusted "
    "pre-tool hook actually blocks the action. Nobody has walked this path. "
    "This is not a live install."
)


def _sentences(text: str) -> list[str]:
    cleaned = " ".join(text.strip().split())
    if not cleaned:
        return []
    if not cleaned.endswith("."):
        cleaned += "."
    return [part.strip() for part in SENTENCE_SPLIT.split(cleaned) if part.strip()]


def _local_clause(sentence: str) -> tuple[str, str | None]:
    match = LOCAL_OR_MARKETPLACE.search(sentence)
    if not match:
        return sentence, None
    local = sentence[: match.start()].rstrip(" .") + "."
    rest = match.group(0).strip()
    if rest.lower().startswith("or "):
        rest = rest[3:].lstrip()
        rest = rest[:1].upper() + rest[1:]
    if rest and not rest.endswith("."):
        rest = rest.rstrip(".") + "."
    return local, rest or None


def _is_step(sentence: str, adapter: dict | None = None) -> bool:
    stripped = sentence.lower().lstrip()
    if "marketplace release" in stripped or "future marketplace" in stripped:
        return False
    if any(stripped.startswith(prefix) for prefix in ACTION_PREFIXES):
        return True
    example = (adapter or {}).get("example") or {}
    for key in STEP_FIELD_KEYS:
        value = example.get(key)
        if isinstance(value, str) and value and value.lower() in stripped:
            return True
    return False


def load_written_adapters(repo_root: Path = ROOT) -> list[dict]:
    adapter_root = repo_root / "core" / "harnesses" / "adapters"
    adapters: list[dict] = []
    for path in sorted(adapter_root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        example = payload.get("example") or {}
        if not isinstance(example, dict):
            continue
        if not example.get("install_guide") and not example.get("note"):
            continue
        payload["_source_path"] = path.relative_to(repo_root).as_posix()
        adapters.append(payload)
    return adapters


def split_guide(adapter: dict) -> tuple[list[str], list[str], bool]:
    example = adapter["example"]
    prose = example.get("install_guide") or example.get("note") or ""
    steps: list[str] = []
    limits: list[str] = []
    stopped = False
    grant = (example.get("vault_grant") or "").strip()
    stop_at_grant = adapter.get("harness_id") == WORK_ID and bool(grant)
    for raw in _sentences(prose):
        local, remainder = _local_clause(raw)
        if remainder:
            limits.append(remainder if remainder.endswith(".") else remainder.rstrip(".") + ".")
        sentence = local
        is_grant = bool(grant) and grant.lower() in sentence.lower()
        if stop_at_grant and is_grant:
            steps.append(sentence)
            stopped = True
            continue
        if stopped:
            limits.append(sentence)
            continue
        if _is_step(sentence, adapter):
            steps.append(sentence)
        else:
            limits.append(sentence)
    if not steps:
        paths = adapter.get("native_paths") or []
        listed = ", ".join(str(item) for item in paths) if paths else "the reviewed local package"
        steps.append(f"Confirm the reviewed local files exist: {listed}.")
    return steps, limits, stopped


def expected_sight(sentence: str, *, stop: bool) -> str:
    if stop:
        return (
            "The host reaches the point where it asks for the Dex vault folder. "
            "Stop there. This is not a live install."
        )
    lower = sentence.lower()
    if "plugin list" in lower or "appears in" in lower:
        return (
            "Dex is listed by that inspect command. "
            "This is still a written path, not a live install."
        )
    if "open plugins" in lower or "install dex" in lower:
        return (
            "The unreleased local build is listed so it can be selected. "
            "This is still a written path, not a live install."
        )
    if "open the dex folder" in lower:
        return (
            "The Dex folder is open in that editor. "
            "This is still a written path, not a live install."
        )
    if "dex folder" in lower or "working directory" in lower:
        return (
            "The current working directory is the Dex folder. "
            "This is still a written path, not a live install."
        )
    if "chat.plugins.enabled" in lower or "pluginlocations" in lower.replace(" ", ""):
        return (
            "The named setting is on this machine. "
            "This is still a written path, not a live install."
        )
    if "copy" in lower or "link" in lower or "~/" in sentence:
        return (
            "The named files are in the named place. "
            "This is still a written path, not a live install."
        )
    if "restart" in lower or "reload" in lower:
        return (
            "The host reopens after the reload. "
            "This is still a written path, not a live install."
        )
    if "run `" in lower or sentence.strip().startswith("From "):
        return (
            "The named command finishes. "
            "This is still a written path, not a live install."
        )
    return (
        "The named action is possible on this machine. "
        "This is still a written path, not a live install."
    )


def failure_sentence(harness_id: str, number: int, sight: str) -> str:
    return f"{harness_id} step {number} failed: {sight}"


def _named_fields(example: dict) -> list[tuple[str, str]]:
    order = (
        "install_command",
        "inspect_command",
        "vault_grant",
        "enable_setting",
        "plugin_locations_setting",
        "plugin_locations_entry",
        "personal_plugin_copy",
        "personal_marketplace",
        "personal_marketplace_root",
        "repo_marketplace",
        "local_package",
        "install_cache",
        "direct_install_cache",
        "artifact",
        "manifest",
        "mcp_config",
        "mcp_file",
    )
    fields: list[tuple[str, str]] = []
    for key in order:
        value = example.get(key)
        if isinstance(value, str) and value.strip():
            fields.append((key, value.strip()))
    return fields


def _index_annotation(harness_id: str) -> str:
    if harness_id == WORK_ID:
        return " — stops at the folder grant"
    if harness_id == FAMILY_ID:
        return " — family PreToolUse refusal (fixture, not a live walk)"
    if harness_id == ADVISORY_EDITOR_ID:
        return " — advisory; nobody has walked this"
    return ""


def render_card(adapter: dict) -> str:
    harness_id = adapter["harness_id"]
    example = adapter["example"]
    prose = example.get("install_guide") or example.get("note") or ""
    steps, limits, stopped = split_guide(adapter)
    lines = [
        f"<!-- Generated by {GENERATOR}. Do not edit by hand. -->",
        "",
        f"# Written host path: `{harness_id}`",
        "",
        "Unreleased. Not a live install. Do not publish. Do not merge.",
        "",
        f"**Lab issue (leave open):** {LAB_ISSUE}",
        "",
        f"**Adapter source:** `{adapter['_source_path']}`",
        "",
        "## Adapter text (quoted — source of truth)",
        "",
        f"> {prose}",
        "",
    ]
    named = _named_fields(example)
    if named:
        lines.extend(["## Named adapter fields", ""])
        for key, value in named:
            lines.append(f"- `{key}`: `{value}`")
        lines.append("")
    lines.extend(["## Steps", ""])
    for index, sentence in enumerate(steps, start=1):
        is_stop = stopped and index == len(steps) and harness_id == WORK_ID
        sight = expected_sight(sentence, stop=is_stop)
        fail = failure_sentence(harness_id, index, sight)
        if FORBIDDEN_STEP_ACTION.search(sentence):
            raise RuntimeError(f"{harness_id} step {index} has a forbidden action: {sentence}")
        lines.extend(
            [
                f"### Step {index}",
                "",
                f"{index}. {sentence}",
                "",
                f"**What you should see:** {sight}",
                "",
                "- [ ] I saw that.",
                "",
                f"**If this fails, send back this exact sentence:** `{fail}`",
                "",
            ]
        )
    if harness_id == WORK_ID:
        lines.extend(
            [
                "## This card stops at the folder grant",
                "",
                "Do not continue after the grant step. Do not claim a live install. "
                "The vault-folder grant is still a person-on-desktop leftover "
                "(lab 455). This page does not invent that grant.",
                "",
            ]
        )
        if not stopped:
            raise RuntimeError("chatgpt-work card must stop at the folder grant")
    if harness_id == FAMILY_ID:
        lines.extend(
            [
                "## Family PreToolUse refusal (fixture, not a live walk)",
                "",
                FAMILY_REFUSAL,
                "",
            ]
        )
    if harness_id == ADVISORY_EDITOR_ID:
        lines.extend(
            [
                "## This editor stays advisory",
                "",
                ADVISORY_EDITOR,
                "",
            ]
        )
    if limits:
        lines.extend(["## Limits from the adapter (not steps)", ""])
        for limit in limits:
            lines.append(f"- {limit}")
        lines.append("")
    lines.extend(
        [
            "## After the last checkbox",
            "",
            "If every box is checked, send this exact sentence:",
            "",
            f"`{harness_id} written path matched the adapter. Not a live install.`",
            "",
            "If any box is unchecked, send only the failure sentence from that step. "
            "Do not continue past a failed step. Do not publish. Do not invite anyone.",
            "",
            "## Honest close",
            "",
            HONEST_CLOSE,
            "",
        ]
    )
    text = "\n".join(lines)
    sourced = "\n".join([prose, *[value for _key, value in named]])
    for match in MODEL_OR_VENDOR.finditer(text):
        token = match.group(0)
        if token.lower() not in sourced.lower():
            raise RuntimeError(
                f"{harness_id} card introduces {token!r} which is not in the adapter"
            )
    return text


def render_index(adapters: list[dict]) -> str:
    lines = [
        f"<!-- Generated by {GENERATOR}. Do not edit by hand. -->",
        "",
        "# Founder test cards — written host paths",
        "",
        "Unreleased. Not a live install. Do not publish. Do not merge.",
        "",
        f"**Lab issue (leave open):** {LAB_ISSUE}",
        "",
        "One page per written host path in `core/harnesses/adapters/*.json`. "
        "If an adapter changes, regenerate these pages. CI fails on drift.",
        "",
        "The chatgpt-work page stops at the vault-folder grant. It does not "
        "invent that grant and does not claim a live install.",
        "",
        "The family (`copilot-cli`) page records the fixture-proved PreToolUse "
        "refusal. The VS Code page stays advisory. Nobody has walked these "
        "paths. No card is a live install.",
        "",
        "## Cards",
        "",
    ]
    for adapter in adapters:
        harness_id = adapter["harness_id"]
        lines.append(f"- [`{harness_id}`](./{harness_id}.md){_index_annotation(harness_id)}")
    lines.extend(
        [
            "",
            "## How to regenerate",
            "",
            f"`python3 {GENERATOR} --write`",
            "",
            "## Honest close",
            "",
            HONEST_CLOSE,
            "",
        ]
    )
    return "\n".join(lines)


def expected_pages(repo_root: Path = ROOT) -> dict[Path, str]:
    adapters = load_written_adapters(repo_root)
    output = repo_root / "docs" / "founder-test-cards"
    expected = {output / "README.md": render_index(adapters)}
    for adapter in adapters:
        expected[output / f"{adapter['harness_id']}.md"] = render_card(adapter)
    return expected


def write_pages(repo_root: Path = ROOT) -> int:
    expected = expected_pages(repo_root)
    output = repo_root / "docs" / "founder-test-cards"
    output.mkdir(parents=True, exist_ok=True)
    for path, text in expected.items():
        path.write_text(text, encoding="utf-8")
    for stale in output.glob("*.md"):
        if stale not in expected:
            stale.unlink()
    cards = len(expected) - 1
    print(f"Generated {cards} founder test cards under {output}.")
    return 0


def check_pages(repo_root: Path = ROOT) -> int:
    expected = expected_pages(repo_root)
    errors: list[str] = []
    output = repo_root / "docs" / "founder-test-cards"
    for path, text in expected.items():
        relative = path.relative_to(repo_root).as_posix()
        if not path.is_file():
            errors.append(f"missing {relative}")
        elif path.read_text(encoding="utf-8") != text:
            errors.append(f"drifted {relative}")
    if output.is_dir():
        for extra in output.glob("*.md"):
            if extra not in expected:
                errors.append(f"unexpected {extra.relative_to(repo_root).as_posix()}")
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        print(
            f"Founder test cards drifted. Run python3 {GENERATOR} --write and commit.",
            file=sys.stderr,
        )
        return 1
    print(f"Founder test cards are current ({len(expected) - 1} cards).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    return check_pages() if args.check else write_pages()


if __name__ == "__main__":
    raise SystemExit(main())
