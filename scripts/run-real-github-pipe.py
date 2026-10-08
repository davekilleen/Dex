#!/usr/bin/env python3
"""Run the exact Mac/Linux branch-test one-liner against GitHub in a PTY."""

from __future__ import annotations

import os
import pty
import re
import select
import subprocess
import sys
import time
from pathlib import Path

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _visible_tail(text: str, size: int = 400) -> str:
    return _ANSI_RE.sub("", text).replace("\r", "")[-size:]


def _waiting_for_enter(tail: str) -> bool:
    stripped = tail.rstrip()
    return (
        stripped.endswith("Press Enter to begin.")
        or stripped.endswith("type another path:")
        or stripped.endswith("Press Enter to continue.")
    )

# Branch to test; set DEX_PIPE_REF to try an unmerged branch.
PIPE_REF = os.environ.get("DEX_PIPE_REF", "main")
COMMAND = (
    f'curl -fsSL "https://raw.githubusercontent.com/davekilleen/Dex/{PIPE_REF}/install.sh" '
    f'| DEX_INSTALL_DIR="$HOME/Dex-test" DEX_INSTALL_REF="{PIPE_REF}" '
    "DEX_INSTALL_NO_OPEN=1 bash"
)


def _write_claude_shim(bin_dir: Path, log_path: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "claude"
    shim.write_text(
        "#!/bin/sh\n"
        f'printf \'%s\\n\' "$*" > "{log_path}"\n'
        'printf \'%s\\n\' "claude-shim argv: $*"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)


def _drain(fd: int, recorded: bytearray) -> None:
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


def _finish(
    recorded: bytearray,
    out: Path,
    answer: str,
    target: Path,
    shim_log: Path,
    code: int,
) -> int:
    text = recorded.decode("utf-8", errors="replace")
    extra = [
        f"\n--- exit {code} ---",
        f"answer={answer}",
        f"target={target}",
        f"exists={target.is_dir()}",
        f"install_sh={(target / 'install.sh').is_file()}",
        f"topology={(target / 'System' / '.dex' / 'topology.json').is_file()}",
        f"brain={(target / '.dex' / 'brain.git').is_dir()}",
        f"user_log={(target / 'install-log.txt').is_file()}",
        f"claude_prompt={'Would you like to start Dex in Claude Code now?' in text}",
        f"started_claude={'Starting Dex in Claude Code' in text}",
        f"manual_steps={'Copy and paste this line' in text}",
        f"beta_forbidden={'Dex is in beta' in text}",
        f"open_folder_prompt={'Open your Dex folder now?' in text}",
    ]
    if shim_log.is_file():
        extra.append("claude_shim=" + shim_log.read_text(encoding="utf-8").strip())
    else:
        extra.append("claude_shim=missing")
    text += "\n".join(extra) + "\n"
    out.write_text(text, encoding="utf-8")
    print(text[-4000:])
    print(f"transcript={out}")
    ok = (
        "Dex is installed" in text
        and "could not prove" not in text
        and "Dex is in beta" not in text
        and "Open your Dex folder now?" not in text
    )
    if answer == "y":
        ok = (
            ok
            and "Starting Dex in Claude Code" in text
            and shim_log.is_file()
                        and "set up Dex" in shim_log.read_text(encoding="utf-8")
        )
    else:
        ok = (
            ok
            and "Would you like to start Dex in Claude Code now?" in text
            and "Copy and paste this line" in text
            and "Starting Dex in Claude Code" not in text
        )
    return 0 if ok else 1


def main() -> int:
    args = [item for item in sys.argv[1:] if not item.startswith("--")]
    flags = {item for item in sys.argv[1:] if item.startswith("--")}
    out = Path(args[0]) if args else Path("/tmp/real-github-pipe.txt")
    answer = "y" if "--yes" in flags else "n"
    out.parent.mkdir(parents=True, exist_ok=True)
    home = Path.home()
    target = home / "Dex-test"
    if target.exists():
        subprocess.run(["rm", "-rf", str(target)], check=False)

    env = os.environ.copy()
    shim_log = Path("/tmp/dex-claude-shim.log")
    shim_log.unlink(missing_ok=True)
    shim_dir = Path("/tmp/dex-claude-shim")
    _write_claude_shim(shim_dir, shim_log)
    env["PATH"] = f"{shim_dir}:{env.get('PATH', '/usr/bin:/bin')}"

    recorded = bytearray()
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(str(home))
        os.execvpe("/bin/bash", ["/bin/bash", "-lc", COMMAND], env)

    deadline = time.time() + 900
    last_send = 0.0
    answered_claude = False
    enter_sends = 0
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
            tail = _visible_tail(text_so_far)
            claude_prompt = "Would you like to start Dex in Claude Code now?" in tail
            if claude_prompt and not answered_claude and time.time() - last_send > 0.4:
                try:
                    os.write(fd, b"y\n" if answer == "y" else b"n\n")
                    last_send = time.time()
                    answered_claude = True
                except OSError:
                    break
            elif (
                not answered_claude
                and enter_sends < 4
                and time.time() - last_send > 0.8
                and _waiting_for_enter(tail)
            ):
                try:
                    os.write(fd, b"\n")
                    last_send = time.time()
                    enter_sends += 1
                except OSError:
                    break
            try:
                waited, status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                _drain(fd, recorded)
                return _finish(recorded, out, answer, target, shim_log, 0)
            if waited == pid:
                time.sleep(0.2)
                _drain(fd, recorded)
                return _finish(
                    recorded,
                    out,
                    answer,
                    target,
                    shim_log,
                    os.waitstatus_to_exitcode(status),
                )
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        waited, status = os.waitpid(pid, 0)
        code = os.waitstatus_to_exitcode(status) if waited == pid else 1
    except ChildProcessError:
        code = 0
    return _finish(recorded, out, answer, target, shim_log, code)


if __name__ == "__main__":
    raise SystemExit(main())
