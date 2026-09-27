"""No-write preview sandbox for /setup-v2.

Redirects onboarding writes into a temp directory and refuses any write
outside that directory. The real vault, home config, and LaunchAgents
paths are never valid write targets. Leftover sandboxes are wiped on the
next start and at process exit.
"""

from __future__ import annotations

import atexit
import builtins
import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

PREFIX = "dex-setup-v2-preview-"
_BLOCKED_SUBPROCESS = ("launchctl", "crontab", "install-automation")


class PreviewWriteRefused(RuntimeError):
    """Raised when preview mode blocks a write outside the sandbox."""


class _PreviewState:
    active: bool = False
    source_vault: Path | None = None
    sandbox: Path | None = None
    originals: dict[str, Any] | None = None
    installed: bool = False


_STATE = _PreviewState()
_ORIGINAL_OPEN = builtins.open
_PATCHED: dict[str, tuple[Any, str, Callable[..., Any]]] = {}


def is_preview_active() -> bool:
    return _STATE.active and _STATE.sandbox is not None


def preview_sandbox_root() -> Path | None:
    return _STATE.sandbox


def preview_source_vault() -> Path | None:
    return _STATE.source_vault


def _resolve(path: Path | str) -> Path:
    return Path(path).expanduser().resolve()


def _inside(path: Path | str, root: Path) -> bool:
    try:
        _resolve(path).relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _path_from_write_target(path: Path | str | int) -> Path | None:
    """Return a filesystem path for a write target, including open fds."""
    if isinstance(path, int):
        try:
            return Path(f"/proc/self/fd/{path}").resolve()
        except OSError:
            return None
    try:
        return Path(path)
    except TypeError:
        return None


def assert_preview_write_allowed(path: Path | str | int) -> Path | None:
    """Fail closed: only the active sandbox may be written."""
    if not is_preview_active() or _STATE.sandbox is None:
        resolved = _path_from_write_target(path)
        return resolved if resolved is not None else Path()
    target = _path_from_write_target(path)
    if target is None:
        raise PreviewWriteRefused(
            f"preview refuses write that cannot be resolved: {path!r}"
        )
    if _inside(target, _STATE.sandbox):
        return target
    # Pipes, /dev, and /proc fds are process I/O, not vault writes.
    try:
        posix = target.resolve().as_posix()
        if posix.startswith(("/dev/", "/proc/")) or posix in {"/dev/null", "/dev/full"}:
            return target
        if "pipe:" in posix:
            return target
    except OSError:
        pass
    raise PreviewWriteRefused(
        f"preview refuses write outside sandbox: {target}"
    )


def leftover_preview_dirs() -> list[Path]:
    parent = Path(tempfile.gettempdir())
    return sorted(
        item
        for item in parent.glob(f"{PREFIX}*")
        if item.is_dir()
    )


def cleanup_stale_previews() -> list[str]:
    """Wipe leftover preview sandboxes from earlier runs."""
    removed: list[str] = []
    for item in leftover_preview_dirs():
        if _STATE.sandbox is not None and _resolve(item) == _STATE.sandbox.resolve():
            continue
        shutil.rmtree(item, ignore_errors=True)
        removed.append(str(item))
    return removed


def _wrap_path_write(method_name: str) -> None:
    original = getattr(Path, method_name, None)
    if original is None:
        return

    def wrapped(self: Path, *args: Any, **kwargs: Any):
        if is_preview_active():
            assert_preview_write_allowed(self)
        return original(self, *args, **kwargs)

    setattr(Path, method_name, wrapped)
    _PATCHED[f"Path.{method_name}"] = (Path, method_name, original)


def _wrap_path_open() -> None:
    original = Path.open

    def wrapped(self: Path, mode: str = "r", *args: Any, **kwargs: Any):
        if is_preview_active() and any(flag in mode for flag in "wax+"):
            assert_preview_write_allowed(self)
        return original(self, mode, *args, **kwargs)

    Path.open = wrapped  # type: ignore[method-assign]
    _PATCHED["Path.open"] = (Path, "open", original)


def _wrap_builtin_open() -> None:
    def wrapped(file, mode="r", *args, **kwargs):
        if is_preview_active() and isinstance(mode, str) and any(
            flag in mode for flag in "wax+"
        ):
            assert_preview_write_allowed(file)
        return _ORIGINAL_OPEN(file, mode, *args, **kwargs)

    builtins.open = wrapped  # type: ignore[assignment]
    _PATCHED["builtins.open"] = (builtins, "open", _ORIGINAL_OPEN)


def _wrap_io_open() -> None:
    original = io.open

    def wrapped(file, mode="r", *args, **kwargs):
        if is_preview_active() and isinstance(mode, str) and any(
            flag in mode for flag in "wax+"
        ):
            assert_preview_write_allowed(file)
        return original(file, mode, *args, **kwargs)

    io.open = wrapped  # type: ignore[assignment]
    _PATCHED["io.open"] = (io, "open", original)


def _wrap_os_fn(name: str, path_args: tuple[int, ...] = (0,)) -> None:
    original = getattr(os, name, None)
    if original is None:
        return

    def wrapped(*args: Any, **kwargs: Any):
        if is_preview_active():
            for index in path_args:
                if len(args) > index:
                    assert_preview_write_allowed(args[index])
        return original(*args, **kwargs)

    setattr(os, name, wrapped)
    _PATCHED[f"os.{name}"] = (os, name, original)


def _wrap_os_open() -> None:
    original = os.open

    def wrapped(path, flags, *args, **kwargs):
        if is_preview_active():
            write_flags = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
            if flags & write_flags:
                assert_preview_write_allowed(path)
        return original(path, flags, *args, **kwargs)

    os.open = wrapped  # type: ignore[assignment]
    _PATCHED["os.open"] = (os, "open", original)


def _wrap_shutil_dst(name: str) -> None:
    original = getattr(shutil, name)

    def wrapped(src: Any, dst: Any, *args: Any, **kwargs: Any):
        if is_preview_active():
            assert_preview_write_allowed(dst)
        return original(src, dst, *args, **kwargs)

    setattr(shutil, name, wrapped)
    _PATCHED[f"shutil.{name}"] = (shutil, name, original)


def _wrap_shutil_rmtree() -> None:
    original = shutil.rmtree

    def wrapped(path: Any, *args: Any, **kwargs: Any):
        if is_preview_active():
            assert_preview_write_allowed(path)
        return original(path, *args, **kwargs)

    shutil.rmtree = wrapped  # type: ignore[assignment]
    _PATCHED["shutil.rmtree"] = (shutil, "rmtree", original)


def _force_preview_temp_dir(kwargs: dict[str, Any]) -> dict[str, Any]:
    if is_preview_active() and kwargs.get("dir") is None:
        scratch = preview_scratch_dir()
        if scratch is not None:
            kwargs = dict(kwargs)
            kwargs["dir"] = str(scratch)
    return kwargs


def _wrap_tempfile() -> None:
    original_named = tempfile.NamedTemporaryFile
    original_mkstemp = tempfile.mkstemp
    original_mkdtemp = tempfile.mkdtemp

    def named(*args: Any, **kwargs: Any):
        return original_named(*args, **_force_preview_temp_dir(kwargs))

    def mkstemp(*args: Any, **kwargs: Any):
        return original_mkstemp(*args, **_force_preview_temp_dir(kwargs))

    def mkdtemp(*args: Any, **kwargs: Any):
        return original_mkdtemp(*args, **_force_preview_temp_dir(kwargs))

    tempfile.NamedTemporaryFile = named  # type: ignore[assignment]
    tempfile.mkstemp = mkstemp  # type: ignore[assignment]
    tempfile.mkdtemp = mkdtemp  # type: ignore[assignment]
    _PATCHED["tempfile.NamedTemporaryFile"] = (
        tempfile,
        "NamedTemporaryFile",
        original_named,
    )
    _PATCHED["tempfile.mkstemp"] = (tempfile, "mkstemp", original_mkstemp)
    _PATCHED["tempfile.mkdtemp"] = (tempfile, "mkdtemp", original_mkdtemp)


def _command_text(args: Any) -> str:
    if isinstance(args, (str, bytes)):
        return str(args)
    try:
        return " ".join(str(part) for part in args)
    except TypeError:
        return str(args)


def _guard_subprocess(args: Any) -> None:
    if not is_preview_active():
        return
    lowered = _command_text(args).lower()
    for token in _BLOCKED_SUBPROCESS:
        if token in lowered:
            raise PreviewWriteRefused(
                f"preview refuses subprocess: {_command_text(args)}"
            )


def _wrap_subprocess() -> None:
    original_run = subprocess.run
    original_popen = subprocess.Popen
    original_call = subprocess.call
    original_check_call = subprocess.check_call
    original_check_output = subprocess.check_output

    def run(args, *a, **kw):
        _guard_subprocess(args)
        return original_run(args, *a, **kw)

    class GuardedPopen(original_popen):  # type: ignore[valid-type,misc]
        def __init__(self, args, *a, **kw):
            _guard_subprocess(args)
            super().__init__(args, *a, **kw)

    def call(args, *a, **kw):
        _guard_subprocess(args)
        return original_call(args, *a, **kw)

    def check_call(args, *a, **kw):
        _guard_subprocess(args)
        return original_check_call(args, *a, **kw)

    def check_output(args, *a, **kw):
        _guard_subprocess(args)
        return original_check_output(args, *a, **kw)

    subprocess.run = run  # type: ignore[assignment]
    subprocess.Popen = GuardedPopen  # type: ignore[assignment]
    subprocess.call = call  # type: ignore[assignment]
    subprocess.check_call = check_call  # type: ignore[assignment]
    subprocess.check_output = check_output  # type: ignore[assignment]
    _PATCHED["subprocess.run"] = (subprocess, "run", original_run)
    _PATCHED["subprocess.Popen"] = (subprocess, "Popen", original_popen)
    _PATCHED["subprocess.call"] = (subprocess, "call", original_call)
    _PATCHED["subprocess.check_call"] = (subprocess, "check_call", original_check_call)
    _PATCHED["subprocess.check_output"] = (
        subprocess,
        "check_output",
        original_check_output,
    )


def _install_write_guard() -> None:
    if _STATE.installed:
        return
    _wrap_path_write("write_text")
    _wrap_path_write("write_bytes")
    _wrap_path_write("touch")
    _wrap_path_write("mkdir")
    _wrap_path_write("unlink")
    _wrap_path_write("rmdir")
    _wrap_path_write("replace")
    _wrap_path_write("rename")
    _wrap_path_write("chmod")
    _wrap_path_write("symlink_to")
    _wrap_path_write("hardlink_to")
    _wrap_path_open()
    _wrap_builtin_open()
    _wrap_io_open()
    _wrap_os_open()
    _wrap_os_fn("replace", (0, 1))
    _wrap_os_fn("rename", (0, 1))
    _wrap_os_fn("remove")
    _wrap_os_fn("unlink")
    _wrap_os_fn("rmdir")
    _wrap_os_fn("removedirs")
    _wrap_os_fn("renames", (0, 1))
    _wrap_os_fn("mkdir")
    _wrap_os_fn("makedirs")
    _wrap_os_fn("chmod")
    _wrap_os_fn("link", (1,))
    _wrap_os_fn("symlink", (1,))
    _wrap_shutil_dst("copyfile")
    _wrap_shutil_dst("copy2")
    _wrap_shutil_dst("copy")
    _wrap_shutil_dst("copytree")
    _wrap_shutil_dst("move")
    _wrap_shutil_rmtree()
    _wrap_tempfile()
    _wrap_subprocess()
    _STATE.installed = True


def _uninstall_write_guard() -> None:
    for _key, (owner, name, original) in list(_PATCHED.items()):
        setattr(owner, name, original)
    _PATCHED.clear()
    builtins.open = _ORIGINAL_OPEN
    _STATE.installed = False


def _snapshot_path_module() -> dict[str, Path]:
    import core.paths as paths

    return {
        name: value
        for name, value in vars(paths).items()
        if isinstance(value, Path)
    }


def _rebase_path_module(sandbox: Path) -> dict[str, Path]:
    import core.paths as paths

    snapshot = _snapshot_path_module()
    old_root = paths.VAULT_ROOT.resolve()
    for name, value in snapshot.items():
        try:
            relative = value.resolve().relative_to(old_root)
        except ValueError:
            continue
        setattr(paths, name, sandbox / relative)
    paths.VAULT_ROOT = sandbox
    return snapshot


def _restore_path_module(snapshot: dict[str, Path]) -> None:
    import core.paths as paths

    for name, value in snapshot.items():
        setattr(paths, name, value)


def _seed_sandbox(sandbox: Path, repo_root: Path) -> None:
    system = sandbox / "System"
    system.mkdir(parents=True, exist_ok=True)
    (sandbox / ".scratch").mkdir(parents=True, exist_ok=True)
    (sandbox / ".home").mkdir(parents=True, exist_ok=True)
    (sandbox / ".scripts").mkdir(parents=True, exist_ok=True)
    copies = (
        ("System/user-profile-template.yaml", system / "user-profile-template.yaml"),
        ("System/.mcp.json.example", system / ".mcp.json.example"),
        ("core/paths.py", sandbox / "core" / "paths.py"),
        ("package.json", sandbox / "package.json"),
        ("CLAUDE.md", sandbox / "CLAUDE.md"),
    )
    for relative, dest in copies:
        source = repo_root / relative
        if source.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(source.read_bytes())


def begin_preview(source_vault: Path, *, repo_root: Path | None = None) -> Path:
    """Redirect onboarding writes into a fresh temp sandbox."""
    if is_preview_active():
        discard_preview()
    cleanup_stale_previews()

    source = _resolve(source_vault)
    sandbox = Path(tempfile.mkdtemp(prefix=PREFIX))
    repo = repo_root or Path(__file__).resolve().parents[2]

    from core.mcp import onboarding_server

    originals = {
        "BASE_DIR": onboarding_server.BASE_DIR,
        "SESSION_FILE": onboarding_server.SESSION_FILE,
        "MARKER_FILE": onboarding_server.MARKER_FILE,
        "MCP_CONFIG_EXAMPLE": onboarding_server.MCP_CONFIG_EXAMPLE,
        "VAULT_PATH": os.environ.get("VAULT_PATH"),
        "CLAUDE_PROJECT_DIR": os.environ.get("CLAUDE_PROJECT_DIR"),
        "DEX_VAULT_PATH": os.environ.get("DEX_VAULT_PATH"),
        "HOME": os.environ.get("HOME"),
        "XDG_CONFIG_HOME": os.environ.get("XDG_CONFIG_HOME"),
        "fire_analytics": onboarding_server._fire_analytics_event,
        "paths": None,
    }
    _STATE.source_vault = source
    _STATE.sandbox = sandbox
    _STATE.originals = originals
    _STATE.active = True
    _install_write_guard()
    originals["paths"] = _rebase_path_module(sandbox)
    _seed_sandbox(sandbox, repo)

    onboarding_server.BASE_DIR = sandbox
    onboarding_server.SESSION_FILE = sandbox / "System" / ".onboarding-session.json"
    onboarding_server.MARKER_FILE = sandbox / "System" / ".onboarding-complete"
    onboarding_server.MCP_CONFIG_EXAMPLE = sandbox / "System" / ".mcp.json.example"
    os.environ["VAULT_PATH"] = str(sandbox)
    os.environ["CLAUDE_PROJECT_DIR"] = str(sandbox)
    os.environ["DEX_VAULT_PATH"] = str(sandbox)
    os.environ["HOME"] = str(sandbox / ".home")
    os.environ["XDG_CONFIG_HOME"] = str(sandbox / ".home" / ".config")

    def _preview_analytics(event_name, properties=None):
        return {
            "sent": False,
            "reason": "preview",
            "event": event_name,
        }

    onboarding_server._fire_analytics_event = _preview_analytics
    atexit.register(_atexit_cleanup)
    return sandbox


def discard_preview() -> dict[str, Any]:
    """Wipe the sandbox and put every pointer back. Nothing on the source remains."""
    sandbox = _STATE.sandbox
    originals = _STATE.originals or {}
    _uninstall_write_guard()
    if sandbox is not None:
        shutil.rmtree(sandbox, ignore_errors=True)
    from core.mcp import onboarding_server

    if "BASE_DIR" in originals:
        onboarding_server.BASE_DIR = originals["BASE_DIR"]
        onboarding_server.SESSION_FILE = originals["SESSION_FILE"]
        onboarding_server.MARKER_FILE = originals["MARKER_FILE"]
        onboarding_server.MCP_CONFIG_EXAMPLE = originals["MCP_CONFIG_EXAMPLE"]
        onboarding_server._fire_analytics_event = originals["fire_analytics"]
    paths_snapshot = originals.get("paths")
    if isinstance(paths_snapshot, dict):
        _restore_path_module(paths_snapshot)
    for key in (
        "VAULT_PATH",
        "CLAUDE_PROJECT_DIR",
        "DEX_VAULT_PATH",
        "HOME",
        "XDG_CONFIG_HOME",
    ):
        value = originals.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    gone = sandbox is None or not Path(sandbox).exists()
    _STATE.active = False
    _STATE.source_vault = None
    _STATE.sandbox = None
    _STATE.originals = None
    leftover = cleanup_stale_previews()
    return {
        "discarded": True,
        "nothing_saved": True,
        "sandbox_gone": gone,
        "cleaned": leftover,
    }


def _atexit_cleanup() -> None:
    if is_preview_active():
        discard_preview()
    else:
        cleanup_stale_previews()


def preview_scratch_dir() -> Path | None:
    if not is_preview_active() or _STATE.sandbox is None:
        return None
    scratch = _STATE.sandbox / ".scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    return scratch


def no_op_background_install(kind: str) -> dict[str, Any]:
    """Launch-agent and sync installation are no-ops during preview."""
    if not is_preview_active():
        raise RuntimeError("background install is only a no-op during /setup-v2 preview")
    return {
        "installed": False,
        "noop": True,
        "kind": kind,
        "reason": "preview",
    }
