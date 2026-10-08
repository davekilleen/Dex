#!/usr/bin/env python3
"""Run the exact Mac/Linux branch-test one-liner against GitHub in a PTY."""

from __future__ import annotations

import os
import pty
import select
import subprocess
import sys
import time
from pathlib import Path

COMMAND = (
    'curl -fsSL "https://raw.githubusercontent.com/davekilleen/Dex/cursor/beginner-install-b596/install.sh" '
    '| DEX_INSTALL_DIR="$HOME/Dex-test" DEX_INSTALL_REF="cursor/beginner-install-b596" '
    "DEX_INSTALL_NO_OPEN=1 bash"
)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/real-github-pipe.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    home = Path.home()
    target = home / "Dex-test"
    if target.exists():
        subprocess.run(["rm", "-rf", str(target)], check=False)

    recorded = bytearray()
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(str(home))
        os.execvpe("/bin/bash", ["/bin/bash", "-lc", COMMAND], os.environ.copy())

    deadline = time.time() + 900
    last_send = 0.0
    try:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                os.kill(pid, 9)
                recorded.extend(b"\n--- timed out ---\n")
                break
            ready, _, _ = select.select([fd], [], [], min(0.5, remaining))
            if ready:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                recorded.extend(chunk)
            text_so_far = recorded.decode("utf-8", errors="replace")
            if time.time() - last_send > 0.8 and (
                "Press Enter" in text_so_far[-800:]
                or "[Y/n]" in text_so_far[-400:]
                or "type another path" in text_so_far[-400:]
            ):
                try:
                    os.write(fd, b"\n")
                    last_send = time.time()
                except OSError:
                    break
            # After the finish prompt, prefer n so we do not launch Claude.
            if "Open your Dex folder now?" in text_so_far[-400:] or "Start Claude Code" in text_so_far[-400:]:
                try:
                    os.write(fd, b"n\n")
                    last_send = time.time()
                except OSError:
                    pass
            try:
                waited, status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                break
            if waited == pid:
                time.sleep(0.2)
                while True:
                    more, _, _ = select.select([fd], [], [], 0.2)
                    if not more:
                        break
                    try:
                        chunk = os.read(fd, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    recorded.extend(chunk)
                code = os.waitstatus_to_exitcode(status)
                text = recorded.decode("utf-8", errors="replace")
                extra = [
                    f"\n--- exit {code} ---",
                    f"target={target}",
                    f"exists={target.is_dir()}",
                    f"install_sh={(target / 'install.sh').is_file()}",
                    f"topology={(target / 'System' / '.dex' / 'topology.json').is_file()}",
                    f"brain={(target / '.dex' / 'brain.git').is_dir()}",
                    f"user_log={(target / 'install-log.txt').is_file()}",
                ]
                remotes = subprocess.run(
                    ["git", "-C", str(target), "remote", "-v"],
                    capture_output=True,
                    text=True,
                )
                extra.append("remotes:\n" + remotes.stdout + remotes.stderr)
                release = subprocess.run(
                    ["git", "-C", str(target), "rev-parse", "--verify", "refs/remotes/upstream/release^{commit}"],
                    capture_output=True,
                    text=True,
                )
                extra.append(f"upstream/release={release.returncode} {release.stdout.strip()}")
                if release.returncode != 0:
                    origin = subprocess.run(
                        ["git", "-C", str(target), "rev-parse", "--verify", "refs/remotes/origin/release^{commit}"],
                        capture_output=True,
                        text=True,
                    )
                    extra.append(f"origin/release={origin.returncode} {origin.stdout.strip()}")
                text += "\n".join(extra) + "\n"
                out.write_text(text, encoding="utf-8")
                print(text[-4000:])
                print(f"transcript={out}")
                return 0 if code == 0 and "Dex is installed" in text and "could not prove" not in text else 1
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    out.write_text(recorded.decode("utf-8", errors="replace"), encoding="utf-8")
    print(f"transcript={out}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
