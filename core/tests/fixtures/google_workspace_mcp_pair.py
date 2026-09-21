#!/usr/bin/env python3
"""Stand-in for the google-workspace-mcp process pair.

The real connector is ``npx`` plus a node child that can ignore a polite
stop. This fixture forks the same shape: a parent and a child that both
ignore SIGTERM, so only a process-group kill actually clears them.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path


def _ignore_stop(_signum: int, _frame: object | None) -> None:
    return


def main() -> int:
    if len(sys.argv) < 2:
        return 2
    marker = Path(sys.argv[1])
    signal.signal(signal.SIGTERM, _ignore_stop)
    child_pid = os.fork()
    if child_pid == 0:
        signal.signal(signal.SIGTERM, _ignore_stop)
        marker.write_text(f"{os.getppid()} {os.getpid()}\n", encoding="utf-8")
        while True:
            time.sleep(0.1)
    marker.write_text(f"{os.getpid()} {child_pid}\n", encoding="utf-8")
    while True:
        time.sleep(0.1)


if __name__ == "__main__":
    # Keep the real connector's tokens in argv so lifecycle matching works.
    if "google-workspace-mcp" not in sys.argv:
        sys.argv.extend(["google-workspace-mcp", "serve"])
    raise SystemExit(main())
