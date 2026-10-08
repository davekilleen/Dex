#!/usr/bin/env python3
"""Drive beginner-install journeys and write transcripts.

Journeys:
  fresh-defaults   — isolated Dex-test, press Enter through prompts
  custom-folder    — type a custom path
  existing-update  — folder already has Dex; choose Update
  missing-tool     — Node missing; stop before download
  no-tty           — detached stdin; no hang; isolated folder
"""

from __future__ import annotations

import os
import pty
import select
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _mini_checkout(root: Path) -> None:
    (root / "core" / "migrations").mkdir(parents=True)
    (root / "core" / "mcp").mkdir(parents=True)
    (root / "core" / "provision.cjs").write_text("console.log('provision')\n", encoding="utf-8")
    (root / "core" / "migrations" / "v1-to-v2-brain-vault-split.cjs").write_text(
        "process.exit(0)\n", encoding="utf-8"
    )
    (root / "core" / "mcp" / "requirements.hash.txt").write_text("# fixture\n", encoding="utf-8")
    (root / "package-lock.json").write_text('{ "lockfileVersion": 3 }\n', encoding="utf-8")
    (root / "install.sh").write_text(INSTALL_SH.read_text(encoding="utf-8"), encoding="utf-8")
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts" / "compose-vault-gitignore.py").write_text("# fixture\n", encoding="utf-8")
    (root / ".gitignore").write_text("00-Inbox/\n", encoding="utf-8")
    (root / "System").mkdir(exist_ok=True)


def _shim_bin(root: Path, *, node_ok: bool = True) -> Path:
    shim = root / "bin"
    shim.mkdir()
    real_node = shutil.which("node") or "/usr/bin/node"
    _write_executable(
        shim / "git",
        """#!/bin/sh
if [ "$1" = "--version" ]; then echo "git version 2.50.0"; exit 0; fi
if [ "$1" = "clone" ]; then
  target=""
  for arg in "$@"; do target="$arg"; done
  mkdir -p "$target"
  if [ -n "$DEX_TEST_CLONE_SRC" ] && [ -d "$DEX_TEST_CLONE_SRC" ]; then
    # Use cp, not python3: the python3 shim intercepts -c for installer probes.
    cp -a "$DEX_TEST_CLONE_SRC/." "$target/"
  fi
  exit 0
fi
exit 0
""",
    )
    if node_ok:
        _write_executable(
            shim / "node",
            f"""#!/bin/sh
if [ "$1" = "-v" ]; then echo "v22.0.0"; exit 0; fi
if [ "$1" = "-e" ]; then exec "{real_node}" "$@"; fi
exit 0
""",
        )
        _write_executable(shim / "npm", "#!/bin/sh\nexit 0\n")
        _write_executable(shim / "npx", "#!/bin/sh\nexit 0\n")
    _write_executable(
        shim / "python3",
        """#!/bin/sh
if [ "$1" = "--version" ]; then echo "Python 3.12.0"; exit 0; fi
if [ "$1" = "-c" ]; then echo "$0"; exit 0; fi
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  mkdir -p "$3/bin"
  printf '#!/bin/sh\\nexit 0\\n' > "$3/bin/pip"
  printf '#!/bin/sh\\nexit 0\\n' > "$3/bin/python"
  chmod +x "$3/bin/pip" "$3/bin/python"
  exit 0
fi
if [ "$1" = "-m" ] && [ "$2" = "core.harnesses.registry" ]; then
  echo '[]'
  exit 0
fi
exit 0
""",
    )
    _write_executable(shim / "xcode-select", "#!/bin/sh\nexit 0\n")
    return shim


def _base_env(root: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    clone_src = root / "clone-src"
    _mini_checkout(clone_src)
    extra = dict(extra or {})
    shim = _shim_bin(root, node_ok=extra.pop("DEX_TEST_NODE_OK", "1") != "0")
    env = os.environ.copy()
    for key in (
        "DEX_INSTALL_PYTHON",
        "CI",
        "DEX_INSTALL_NONINTERACTIVE",
        "DEX_INSTALL_DIR",
        "DEX_INSTALL_REF",
    ):
        env.pop(key, None)
    env.update(
        {
            "PATH": f"{shim}:/usr/bin:/bin",
            "HOME": str(root / "home"),
            "DEX_INSTALL_LOG": str(root / "install.log"),
            "DEX_INSTALL_NO_OPEN": "1",
            "DEX_TEST_CLONE_SRC": str(clone_src),
            "TERM": "xterm",
        }
    )
    (root / "home").mkdir(exist_ok=True)
    env.update(extra)
    return env


def _pipe_to_bash(script: Path, isolation: dict[str, str]) -> str:
    """Same shape as curl | VAR=... bash — vars sit on bash, not on cat."""
    assignments = " ".join(f"{key}={value!r}" for key, value in isolation.items())
    return f"cat {str(script)!r} | {assignments} bash"


def _run_pty(command: list[str], cwd: Path, env: dict[str, str], sends: list[bytes], timeout: float = 25) -> tuple[int, str]:
    recorded = bytearray()
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(cwd)
        os.execvpe(command[0], command, env)
    deadline = time.time() + timeout
    send_index = 0
    last_send = 0.0
    try:
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                os.kill(pid, 9)
                try:
                    os.waitpid(pid, 0)
                except ChildProcessError:
                    pass
                return 124, recorded.decode("utf-8", errors="replace") + "\n--- timed out ---\n"
            ready, _, _ = select.select([fd], [], [], min(0.4, remaining))
            if ready:
                try:
                    chunk = os.read(fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                recorded.extend(chunk)
            if send_index < len(sends) and time.time() - last_send > 0.35:
                try:
                    os.write(fd, sends[send_index])
                    send_index += 1
                    last_send = time.time()
                except OSError:
                    break
            try:
                waited_pid, status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                break
            if waited_pid == pid:
                code = os.waitstatus_to_exitcode(status)
                time.sleep(0.1)
                while True:
                    more, _, _ = select.select([fd], [], [], 0.1)
                    if not more:
                        break
                    try:
                        chunk = os.read(fd, 4096)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        break
                    recorded.extend(chunk)
                return code, recorded.decode("utf-8", errors="replace")
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    try:
        waited_pid, status = os.waitpid(pid, 0)
        if waited_pid == pid:
            return os.waitstatus_to_exitcode(status), recorded.decode("utf-8", errors="replace")
    except ChildProcessError:
        pass
    return 1, recorded.decode("utf-8", errors="replace")


def _write_transcript(out_dir: Path, name: str, text: str, extra: str = "") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.txt"
    path.write_text(text + extra, encoding="utf-8")
    return path


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/dex-install-journeys")
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []

    isolation_ref = "cursor/beginner-install-b596"

    # 1. fresh defaults via isolated dir + real pipe + pty
    work = out_dir / "work-fresh"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    target = work / "home" / "Dex-test"
    env = _base_env(work)
    script = work / "clone-src" / "install.sh"
    try:
        code, text = _run_pty(
            ["/bin/bash", "-lc", _pipe_to_bash(script, {
                "DEX_INSTALL_DIR": str(target),
                "DEX_INSTALL_REF": isolation_ref,
                "DEX_INSTALL_NO_OPEN": "1",
            })],
            work,
            env,
            [b"\n", b"\n", b"n\n", b"n\n"],
        )
    except TimeoutError as exc:
        code, text = 124, str(exc)
    text += f"\n--- exit {code} ---\ntarget_exists={target.is_dir()} provision={ (target / 'core' / 'provision.cjs').is_file() }\n"
    _write_transcript(out_dir, "fresh-defaults", text)
    results.append(("fresh-defaults", code == 0 and (target / "core" / "provision.cjs").is_file() and "Welcome to Dex" in text))

    # 2. custom folder
    work = out_dir / "work-custom"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    custom = work / "home" / "MyDex"
    env = _base_env(work)
    try:
        code, text = _run_pty(
            ["/bin/bash", "-lc", _pipe_to_bash(work / "clone-src" / "install.sh", {
                "DEX_INSTALL_DIR": str(work / "home" / "Dex-test"),
                "DEX_INSTALL_REF": isolation_ref,
                "DEX_INSTALL_NO_OPEN": "1",
            })],
            work,
            env,
            [b"\n", str(custom).encode() + b"\n", b"n\n", b"n\n"],
        )
    except TimeoutError as exc:
        code, text = 124, str(exc)
    text += f"\n--- exit {code} ---\ncustom={custom.is_dir()} leftover_default={(work / 'home' / 'Dex-test' / 'core').exists()}\n"
    _write_transcript(out_dir, "custom-folder", text)
    results.append(("custom-folder", code == 0 and (custom / "core" / "provision.cjs").is_file()))

    # 3. existing update
    work = out_dir / "work-update"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    existing = work / "home" / "Dex-test"
    _mini_checkout(existing)
    env = _base_env(work)
    try:
        code, text = _run_pty(
            ["/bin/bash", "-lc", _pipe_to_bash(work / "clone-src" / "install.sh", {
                "DEX_INSTALL_DIR": str(existing),
                "DEX_INSTALL_REF": isolation_ref,
                "DEX_INSTALL_NO_OPEN": "1",
            })],
            work,
            env,
            [b"\n", b"\n", b"U\n", b"n\n", b"n\n"],
        )
    except TimeoutError as exc:
        code, text = 124, str(exc)
    text += f"\n--- exit {code} ---\n"
    _write_transcript(out_dir, "existing-update", text)
    results.append(("existing-update", code == 0 and "already has Dex" in text or "already in that folder" in text or code == 0))

    # 4. missing tool
    work = out_dir / "work-missing"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    target = work / "home" / "Dex-test"
    env = _base_env(work)
    env["PATH"] = f"{work / 'bin-empty'}:/usr/bin:/bin"
    (work / "bin-empty").mkdir()
    _write_executable(work / "bin-empty" / "git", "#!/bin/sh\necho 'git version 2.50.0'\nexit 0\n")
    _write_executable(
        work / "bin-empty" / "python3",
        "#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then echo 'Python 3.12.0'; exit 0; fi\nif [ \"$1\" = \"-c\" ]; then echo \"$0\"; exit 0; fi\nexit 0\n",
    )
    try:
        code, text = _run_pty(
            ["/bin/bash", "-lc", _pipe_to_bash(work / "clone-src" / "install.sh", {
                "DEX_INSTALL_DIR": str(target),
                "DEX_INSTALL_REF": isolation_ref,
                "DEX_INSTALL_NO_OPEN": "1",
            })],
            work,
            env,
            [b"\n", b"\n", b"\n", b"\n"],
            timeout=12,
        )
    except TimeoutError as exc:
        code, text = 124, str(exc)
    cloned = (target / "core" / "provision.cjs").is_file()
    text += f"\n--- exit {code} ---\ncloned={cloned}\n"
    _write_transcript(out_dir, "missing-tool", text)
    results.append(("missing-tool", (not cloned) and ("Node.js" in text or "nodejs.org" in text)))

    # 5. no-tty — same pipe shape, vars on bash only
    work = out_dir / "work-notty"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    target = work / "home" / "Dex-test"
    env = _base_env(work)
    completed = subprocess.run(
        _pipe_to_bash(work / "clone-src" / "install.sh", {
            "DEX_INSTALL_DIR": str(target),
            "DEX_INSTALL_REF": isolation_ref,
            "DEX_INSTALL_NONINTERACTIVE": "1",
            "DEX_INSTALL_NO_OPEN": "1",
        }),
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        shell=True,
        executable="/bin/bash",
    )
    text = completed.stdout + completed.stderr
    text += f"\n--- exit {completed.returncode} ---\nprovision={(target / 'core' / 'provision.cjs').is_file()}\n"
    _write_transcript(out_dir, "no-tty", text)
    results.append(("no-tty", completed.returncode == 0 and (target / "core" / "provision.cjs").is_file() and "Dex installation complete" in completed.stdout))

    summary = ["Install journey results", ""]
    failed = 0
    for name, ok in results:
        line = f"{'PASS' if ok else 'FAIL'}  {name}"
        summary.append(line)
        print(line)
        if not ok:
            failed += 1
    _write_transcript(out_dir, "SUMMARY", "\n".join(summary) + "\n")
    print(f"transcripts: {out_dir}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
