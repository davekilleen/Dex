#!/usr/bin/env python3
"""Merge per-shard pytest junit reports into one <testsuites> document.

Used by the CI test-results job to stitch shard reports back together for
scripts/build-health-json.py, which already understands a <testsuites> root.
Fails loudly if an input is missing or unparsable — a silently dropped shard
would falsify release health.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="per-shard junit XML files")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    merged = ET.Element("testsuites")
    total_tests = 0
    for path in args.inputs:
        if not path.is_file():
            print(f"merge-junit: missing input {path}", file=sys.stderr)
            return 1
        root = ET.parse(path).getroot()
        suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
        if not suites:
            print(f"merge-junit: no <testsuite> elements in {path}", file=sys.stderr)
            return 1
        for suite in suites:
            merged.append(suite)
            total_tests += int(suite.get("tests", 0))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(merged).write(args.output, encoding="utf-8", xml_declaration=True)
    print(f"merge-junit: merged {len(args.inputs)} reports, {total_tests} testcases -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
