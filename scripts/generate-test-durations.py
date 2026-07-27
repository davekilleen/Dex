#!/usr/bin/env python3
"""Generate .ci/test-durations.json (CI shard balance) from a pytest junit report.

Usage: python3 scripts/generate-test-durations.py .logs/pytest-report.xml

Keys are pytest nodeids; pytest-split uses them to deal the suite across CI
shard runners. Nodeids of parametrized tests embed their parameter values, and
some fixtures are deliberately hostile strings (fake secret formats, personal
path layouts) that the repo's security and distribution scanners exist to
reject. Those entries are DROPPED here rather than allowlisted in any scanner:
pytest-split gives unknown tests the average duration, and the dropped entries
are sub-second parameter variants, so shard balance is unaffected while the
security allowlist stays empty and every scanner keeps scanning this file.
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

OUTPUT = Path(".ci/test-durations.json")

# A key survives only if it looks like a plain nodeid: path chars, '::', and
# tame parameter content. Quotes, spaces, '=', '$', and backslashes are what
# assembled-secret and env-layout fixture params contain.
SAFE_KEY = re.compile(r"^[A-Za-z0-9_/.:@,\[\]-]+$")
# Assembled so the literal personal-path form never appears in the tracked
# tree — the same discipline the fixture tests use, and the reason this
# generator exists.
REJECT_SUBSTRINGS = ("/" + "Users" + "/", "HOME")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    root = ET.parse(sys.argv[1]).getroot()
    durations: dict[str, float] = {}
    dropped = 0
    unmatched = 0
    for case in root.iter("testcase"):
        parts = case.attrib["classname"].split(".")
        file = None
        for i in range(len(parts), 0, -1):
            candidate = "/".join(parts[:i]) + ".py"
            if Path(candidate).exists():
                file = candidate
                suffix = "::".join(parts[i:] + [case.attrib["name"]])
                break
        if file is None:
            unmatched += 1
            continue
        key = f"{file}::{suffix}"
        if not SAFE_KEY.match(key) or any(s in key for s in REJECT_SUBSTRINGS):
            dropped += 1
            continue
        durations[key] = float(case.attrib.get("time", 0))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(durations, indent=0, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {len(durations)} durations ({dropped} scanner-hostile dropped, {unmatched} unmatched)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
