#!/usr/bin/env python3
# LIVE surface of core.utils.ritual_timing. Records when a heavy skill starts
# (PreToolUse on the Skill tool), when it first hands the turn back (Stop),
# and when it completes (the ritual's own *_completed analytics call), so
# Doctor can tell a user their morning plan got slower, and with which release.
#
# Fail open: exit 0 always, print nothing. A run that cannot be timed is no
# worse off than before this hook existed.

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    try:
        # Import from the shipped tree that contains this hook, not from
        # CLAUDE_PROJECT_DIR — tests (and some hosts) point that env at a
        # vault that does not contain core/.
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from core.utils.ritual_timing import main as ritual_timing_main

        return ritual_timing_main()
    except Exception:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
