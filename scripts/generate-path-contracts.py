#!/usr/bin/env python3
"""Generate @dex/contracts artifacts from core.paths."""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("VAULT_PATH", str(REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.path_contract import write_contract_package


def main() -> int:
    dist_dir = REPO_ROOT / "packages" / "dex-contracts" / "dist"
    contract = write_contract_package(dist_dir)
    count = len(contract["vault_relative_paths"])
    print(f"Generated {dist_dir} ({count} path constants)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
