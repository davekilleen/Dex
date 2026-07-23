#!/usr/bin/env python3
"""Generate the portable-vault ownership contract artifacts (committed dist)."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.portable_contract import write_contract_package


def main() -> int:
    dist_dir = REPO_ROOT / "packages" / "dex-contracts" / "dist"
    document = write_contract_package(dist_dir)
    print(f"Generated {dist_dir} ({len(document['rules'])} ownership rules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
