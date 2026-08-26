#!/usr/bin/env python3
# LIVE surface of core.utils.skill_freshness. After an update writes a new
# SKILL.md, the host slash list can still omit it until the next session.
# This hook records the on-disk skill set at SessionStart and injects any
# skill that arrived later into the current turn so it is usable now.
#
# Fail open: exit 0 always. A vault that cannot advertise a new skill is no
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
        from core.utils.skill_freshness import main as skill_freshness_main

        return skill_freshness_main()
    except Exception:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
