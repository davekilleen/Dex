#!/usr/bin/env python3
"""Reject personal data added by a pull request."""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from core.paths import ARCHIVES_DIR, INBOX_DIR, SYSTEM_DIR

EMAIL_RE = re.compile(r"(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])", re.IGNORECASE)
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
IDENTITY_FIELD_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?"
    r"(?:consent[ _-]identity|consent[ _-]by|email|e-mail|name|identity|user(?:[ _-]id)?|"
    r"visitor(?:[ _-]id)?|account(?:[ _-]id)?|workspace(?:[ _-]id)?|team(?:[ _-]id)?|"
    r"tenant(?:[ _-]id)?|domain|company|organization)"
    r"(?:\*\*)?\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)
IDENTITY_ANY_FIELD_RE = re.compile(
    r"(?:^|[{,\s])[\"']?"
    r"(?:consent[ _-]identity|consent[ _-]by|email|e-mail|name|identity|user(?:[ _-]id)?|"
    r"visitor(?:[ _-]id)?|account(?:[ _-]id)?|workspace(?:[ _-]id)?|team(?:[ _-]id)?|"
    r"tenant(?:[ _-]id)?|domain|company|organization)"
    r"[\"']?\s*:\s*([^,}\n]+)",
    re.IGNORECASE,
)
PLACEHOLDER_VALUES = {
    "",
    '""',
    "''",
    "[]",
    "{}",
    "false",
    "null",
    "none",
    "not yet configured",
    "not configured",
    "(not yet configured)",
    "(set during onboarding)",
    "(auto-populated)",
    "(not applicable)",
}


@dataclass(frozen=True)
class AddedLine:
    path: str
    number: int
    text: str


def _run_diff(merge_base: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--no-ext-diff",
            "--no-color",
            "--unified=0",
            "--diff-filter=ACMR",
            f"{merge_base}...HEAD",
            "--",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _changed_paths(merge_base: str) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "-z",
            "--diff-filter=ACMR",
            f"{merge_base}...HEAD",
            "--",
        ],
        check=True,
        capture_output=True,
    )
    return [os.fsdecode(path) for path in result.stdout.split(b"\0") if path]


def _added_lines(patch: str) -> list[AddedLine]:
    added: list[AddedLine] = []
    path: str | None = None
    next_line: int | None = None
    in_hunk = False
    for raw_line in patch.splitlines():
        if raw_line.startswith("diff --git "):
            path = None
            next_line = None
            in_hunk = False
            continue
        if not in_hunk and raw_line.startswith("+++ "):
            marker = raw_line[4:]
            path = None if marker == "/dev/null" else marker.removeprefix("b/")
            continue
        hunk = HUNK_RE.match(raw_line)
        if hunk:
            next_line = int(hunk.group(1))
            in_hunk = True
            continue
        if path is None or next_line is None:
            continue
        if raw_line.startswith("+"):
            added.append(AddedLine(path, next_line, raw_line[1:]))
            next_line += 1
        elif raw_line.startswith(" "):
            next_line += 1
        elif raw_line.startswith("\\ No newline") or raw_line.startswith("-"):
            continue
    return added


def _load_allowlist() -> list[str]:
    path = Path(__file__).with_name("pii-allowlist.txt")
    return [
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _email_allowed(email: str, allowlist: list[str]) -> bool:
    local, domain = email.lower().rsplit("@", 1)
    if local == "noreply":
        return True
    if domain in {"example.com", "example.org", "anthropic.com"}:
        return True
    if domain == "users.noreply.github.com" or domain.endswith(".users.noreply.github.com"):
        return True
    return any(fnmatch.fnmatchcase(email.lower(), pattern) for pattern in allowlist)


def _is_fixture(path: str) -> bool:
    return path == "core/tests/fixtures" or path.startswith("core/tests/fixtures/")


def _logical_path(path: str) -> str:
    parts = Path(path).parts
    marker_indexes = [
        parts.index(marker)
        for marker in (SYSTEM_DIR.name, INBOX_DIR.name, ARCHIVES_DIR.name)
        if marker in parts
    ]
    if marker_indexes:
        return "/".join(parts[min(marker_indexes) :])
    return path


def _repo_file(path: str) -> Path:
    return Path.cwd() / path


def _first_added(lines: list[AddedLine], path: str) -> AddedLine:
    return next(line for line in lines if line.path == path)


def _placeholder(value: str) -> bool:
    normalized = value.strip().strip("`\"'").lower()
    return normalized in PLACEHOLDER_VALUES or normalized.startswith("example ")


def _integration_has_real_identity(path: str) -> bool:
    target = _repo_file(path)
    if not target.is_file():
        return False
    text = target.read_text(encoding="utf-8", errors="replace")
    enabled = bool(re.search(r"\benabled\s*:\s*true\b", text, re.IGNORECASE))
    if not enabled:
        lines = text.splitlines()
        for index, line in enumerate(lines):
            match = re.match(r"^(\s*)enabled\s*:\s*(?:#.*)?$", line, re.IGNORECASE)
            if not match:
                continue
            parent_indent = len(match.group(1))
            for child in lines[index + 1 :]:
                if not child.strip() or child.lstrip().startswith("#"):
                    continue
                child_indent = len(child) - len(child.lstrip())
                if child_indent <= parent_indent:
                    break
                if re.match(r"^\s*[^:#]+\s*:\s*true\b", child, re.IGNORECASE):
                    enabled = True
                    break
            if enabled:
                break
    if not enabled:
        return False
    return any(
        not _placeholder(match.group(1).split("#", 1)[0])
        for match in IDENTITY_ANY_FIELD_RE.finditer(text)
    )


def _profile_matches_template(path: str) -> bool:
    target = _repo_file(path)
    template = target.with_name("user-profile-template.yaml")
    return target.is_file() and template.is_file() and target.read_bytes() == template.read_bytes()


def _claude_profile_bounds(path: str) -> tuple[int, int] | None:
    target = _repo_file(path)
    if not target.is_file():
        return None
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    start = next((i for i, line in enumerate(lines, 1) if line.strip() == "## User Profile"), None)
    if start is None:
        return None
    end = next((i for i, line in enumerate(lines[start:], start + 1) if line.startswith("## ")), len(lines) + 1)
    return start, end


def _claude_line_has_real_value(text: str) -> bool:
    stripped = text.strip()
    if not stripped or stripped.startswith(("#", "<!--")):
        return False
    label = re.match(r"^\*\*[^*]+:\*\*\s*(.*)$", stripped)
    if label:
        value = label.group(1)
        return bool(value) and not _placeholder(value)
    bullet = re.match(r"^-\s+(.+)$", stripped)
    return bool(bullet and not _placeholder(bullet.group(1)))


def _usage_line_has_real_identity(text: str) -> bool:
    match = IDENTITY_FIELD_RE.match(text)
    return bool(match and not _placeholder(match.group(1).split("#", 1)[0]))


def find_violations(lines: list[AddedLine], changed_paths: list[str]) -> list[tuple[AddedLine, str]]:
    violations: list[tuple[AddedLine, str]] = []
    allowlist = _load_allowlist()

    for line in lines:
        if not _is_fixture(line.path):
            for email in EMAIL_RE.findall(line.text):
                if not _email_allowed(email, allowlist):
                    violations.append((line, f"email address {email!r} is not an approved placeholder"))

    paths = list(dict.fromkeys([*changed_paths, *(line.path for line in lines)]))
    for path in paths:
        logical = _logical_path(path)
        path_lines = [line for line in lines if line.path == path]
        first = path_lines[0] if path_lines else AddedLine(path, 1, "")

        if logical == f"{SYSTEM_DIR.name}/user-profile.yaml" and not _profile_matches_template(path):
            violations.append((first, "user-profile.yaml is not byte-identical to its placeholder template"))

        if logical.startswith(f"{SYSTEM_DIR.name}/integrations/") and logical.endswith((".yaml", ".yml")):
            if _integration_has_real_identity(path):
                offender = next((line for line in path_lines if IDENTITY_ANY_FIELD_RE.search(line.text)), first)
                violations.append((offender, "enabled integration config contains identity fields"))

        personal_content_roots = (f"{INBOX_DIR.name}/", f"{ARCHIVES_DIR.name}/")
        if logical.startswith(personal_content_roots) and Path(logical).name not in {
            "README.md",
            ".gitkeep",
        }:
            violations.append((first, "personal vault content must not be committed"))

        if logical == f"{SYSTEM_DIR.name}/usage_log.md":
            for line in path_lines:
                if _usage_line_has_real_identity(line.text):
                    violations.append((line, "usage consent metadata contains a real identity"))

        if logical == "CLAUDE.md":
            bounds = _claude_profile_bounds(path)
            if bounds:
                start, end = bounds
                for line in path_lines:
                    if start < line.number < end and _claude_line_has_real_value(line.text):
                        violations.append((line, "CLAUDE.md User Profile contains a non-placeholder value"))

    deduplicated: list[tuple[AddedLine, str]] = []
    seen: set[tuple[str, int, str]] = set()
    for line, reason in violations:
        key = (line.path, line.number, reason)
        if key not in seen:
            deduplicated.append((line, reason))
            seen.add(key)
    return deduplicated


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: pii_gate.py MERGE_BASE", file=sys.stderr)
        return 2
    lines = _added_lines(_run_diff(argv[1]))
    violations = find_violations(lines, _changed_paths(argv[1]))
    if not violations:
        print("PII / personal-config gate passed.")
        return 0

    print("❌ PII / personal-config gate blocked this change:", file=sys.stderr)
    for line, reason in violations:
        print(f"  {line.path}:{line.number}: {reason}", file=sys.stderr)
    print("this looks like personal data — see CONTRIBUTING.md", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
