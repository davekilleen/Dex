#!/usr/bin/env python3
"""Check and request Reminders permission through Dex Helper."""

import sys
from pathlib import Path

_repo_root = str(Path(__file__).resolve().parents[3])
if _repo_root not in sys.path:
    sys.path.append(_repo_root)

from core.utils.macos_privacy_helper import (
    HELPER_MISSING_MESSAGE,
    helper_is_available,
    run_helper,
)


def main():
    if sys.platform != "darwin":
        print("Reminders permission is Mac-only.")
        return 1
    if not helper_is_available():
        print(HELPER_MISSING_MESSAGE)
        return 1
    print("Using Dex Helper — Reminders permission is requested under that app's name.")
    result = run_helper(["request-access"])
    if result is None:
        print(HELPER_MISSING_MESSAGE)
        return 1
    ok, output = result
    print(output)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
