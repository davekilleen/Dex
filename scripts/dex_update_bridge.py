#!/usr/bin/env python3
"""One-time, pinned bootstrap for Dex lifecycle-era installations.

This is deliberately separate from an installed old Dex's update instructions.
Those releases can safely update the code they already contain, but cannot fetch
new Dex code. The bridge proves one predeclared foundation release and delegates
the topology conversion and release writes to its lifecycle service.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterator, Mapping, Protocol

OFFICIAL_REMOTE = "https://github.com/davekilleen/Dex.git"
_HEX = re.compile(r"^[0-9a-f]{40}$")
_RELEASE_TAG = re.compile(r"^dist/release/v[0-9]+\.[0-9]+\.[0-9]+-[0-9a-f]{7,40}$")
_APPROVAL_WORD = "APPLY"
_CLEAN_RUNTIME_MARKER = "DEX_UPDATE_BRIDGE_CLEAN_RUNTIME"
_TRUSTED_EXECUTABLE_DIRECTORIES = (Path("/usr/bin"), Path("/bin"), Path("/usr/local/bin"), Path("/opt/homebrew/bin"))
_TOPOLOGY_MIGRATOR_RELATIVE = Path(
    "core/migrations/v1-to-v2-brain-vault-split.cjs"
)
_TRACKED_IGNORE_POLICY_RELATIVE = Path(
    "core/migrations/tracked-ignored-policy.yaml"
)
_PRESERVATION_TRANSITION_RELATIVE = Path(
    "System/.local-only-preservation-transition.json"
)
_LEGACY_SHIPPED_SYMLINK_RELATIVE = Path(".pi/agent/extensions/dex")
_LEGACY_SHIPPED_SYMLINK_TARGET = "../../../pi-extensions/dex"
_LEGACY_SHIPPED_SYMLINK_BLOB = "f1c88c92cea996705f982e902bafb758156aef52"


class BridgeError(RuntimeError):
    """The bridge could not prove it is safe to continue."""


@dataclass(frozen=True)
class ReleasePin:
    """The closed immutable identity of the one bridge foundation release."""

    tag: str
    tag_object: str
    commit: str
    tree: str
    version: str

    def __post_init__(self) -> None:
        if _RELEASE_TAG.fullmatch(self.tag) is None:
            raise BridgeError("foundation tag is not an immutable distribution tag")
        if any(_HEX.fullmatch(value) is None for value in (self.tag_object, self.commit, self.tree)):
            raise BridgeError("foundation release identity is malformed")
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", self.version):
            raise BridgeError("foundation release version is malformed")
        if not self.tag.startswith(f"dist/release/v{self.version}-"):
            raise BridgeError("foundation tag and version disagree")

    def identity(self) -> dict[str, str]:
        return {
            "tag": self.tag,
            "tag_object": self.tag_object,
            "commit": self.commit,
            "tree": self.tree,
            "version": self.version,
            # ``release`` is the Git ref name; lifecycle identities name the
            # user-facing channel as ``stable``.
            "channel": "stable",
        }


# The first public release with the corrected self-delivery approval boundary
# and profile-safe package. This pin is intentionally in the bridge source:
# discovering a mutable "latest" release would not be a safe bootstrap.
FOUNDATION = ReleasePin(
    tag="dist/release/v1.81.0-6bc490e",
    tag_object="54b1ceef8b1f7ad4f67e4d4d045a134ea443ab53",
    commit="6bc490e7caec22f60f097c6b54bb563382f542b8",
    tree="dad3e43774e772dfc42df698f8a9818956346d78",
    version="1.81.0",
)


@dataclass(frozen=True)
class LegacyTopologyPin:
    """One immutable legacy tree allowed to use the foundation migrator."""

    tag: str
    tag_object: str
    commit: str
    tree: str


LEGACY_TOPOLOGY_FOUNDATION = LegacyTopologyPin(
    tag="v1.20.1",
    tag_object="3f7338dbe21ec98c015a3c8417d037cdd51b517d",
    commit="9e6f35d3282cb354008a4e7372b1cdb1d469ad3d",
    tree="b781bb94e417b2873d057a5a417d8c666a360bca",
)

# v1.20.1 predates the tracked-ignore transition that the topology migrator
# reads before it can even build a preview. This is the complete baseline-v1
# policy first shipped for those historical paths, pinned here by byte hash.
# The compatibility preload exposes it read-only to the verified migrator; it
# never installs these newer release files into the old combined vault.
_LEGACY_TRACKED_IGNORE_POLICY = b"""schema_version: 2
active_baseline_version: 1
baselines:
  - baseline_version: 1
    baseline_count: 27
    paths:
      - path: 00-Inbox/Daily_Plans/README.md
        classification: intentional-seed
      - path: 00-Inbox/Ideas/README.md
        classification: intentional-seed
      - path: 00-Inbox/Meetings/README.md
        classification: intentional-seed
      - path: 00-Inbox/README.md
        classification: intentional-seed
      - path: 01-Quarter_Goals/Quarter_Goals.md
        classification: intentional-seed
      - path: 02-Week_Priorities/Week_Priorities.md
        classification: intentional-seed
      - path: 03-Tasks/Tasks.md
        classification: intentional-seed
      - path: 04-Projects/README.md
        classification: intentional-seed
      - path: 05-Areas/Career/Evidence/README.md
        classification: intentional-seed
      - path: 05-Areas/Companies/README.md
        classification: intentional-seed
      - path: 05-Areas/People/External/README.md
        classification: intentional-seed
      - path: 05-Areas/People/Internal/README.md
        classification: intentional-seed
      - path: 05-Areas/People/README.md
        classification: intentional-seed
      - path: 05-Areas/README.md
        classification: intentional-seed
      - path: 07-Archives/Plans/README.md
        classification: intentional-seed
      - path: 07-Archives/Projects/README.md
        classification: intentional-seed
      - path: 07-Archives/README.md
        classification: intentional-seed
      - path: 07-Archives/Reviews/README.md
        classification: intentional-seed
      - path: System/Dex_Backlog.md
        classification: intentional-seed
      - path: System/Session_Learnings/README.md
        classification: intentional-seed
      - path: System/pillars.yaml
        classification: intentional-seed
      - path: System/usage_log.md
        classification: intentional-seed
      - path: System/user-profile.yaml
        classification: intentional-seed
      - path: System/Beta_Communications/2026-02-04_hardcoded_paths_fix.md
        classification: release-doc
      - path: System/Session_Learnings/2026-01-29.md
        classification: local-only-must-be-untracked
      - path: System/Session_Learnings/2026-01-30.md
        classification: local-only-must-be-untracked
      - path: System/integrations/slack.yaml
        classification: local-only-must-be-untracked
"""
_LEGACY_TRACKED_IGNORE_POLICY_SHA256 = (
    "bf0af119939930fb4d3b466584a3e9392edb66bf61ec09675521c9a5969f3f50"
)


def _legacy_preload_bytes() -> bytes:
    """Build the closed Node preload that supplies two absent read-only inputs."""

    policy = base64.b64encode(_LEGACY_TRACKED_IGNORE_POLICY).decode("ascii")
    return f"""'use strict';
const fs = require('node:fs');
const path = require('node:path');

if (process.env.GIT_ALLOW_PROTOCOL !== 'https') {{
  throw new Error('Dex update bridge refused an unsafe inherited Git protocol policy.');
}}
// The pinned topology migrator uses only the vault's existing local Git store.
// Replace, rather than widen, the bridge's HTTPS policy inside this one child.
process.env.GIT_ALLOW_PROTOCOL = 'file';

const root = fs.realpathSync(process.cwd());
const shippedLink = path.join(root, '{_LEGACY_SHIPPED_SYMLINK_RELATIVE.as_posix()}');
const shippedLinkParent = path.dirname(shippedLink);
const shippedLinkName = path.basename(shippedLink);
const shippedLinkTarget = '{_LEGACY_SHIPPED_SYMLINK_TARGET}';
const transitionPath = path.join(root, '{_PRESERVATION_TRANSITION_RELATIVE.as_posix()}');
const packagePath = path.join(root, 'package.json');
const inputs = new Map([
  [path.join(root, '{_TRACKED_IGNORE_POLICY_RELATIVE.as_posix()}'), Buffer.from('{policy}', 'base64')],
]);
const originalReadFileSync = fs.readFileSync.bind(fs);
const originalReaddirSync = fs.readdirSync.bind(fs);

function legacyTransition() {{
  const packageState = fs.lstatSync(packagePath);
  if (!packageState.isFile() || packageState.isSymbolicLink()) {{
    throw new Error(`Dex update bridge refused unsafe legacy package metadata ${{packagePath}}.`);
  }}
  const packageJson = JSON.parse(originalReadFileSync(packagePath, 'utf8'));
  if (
    !packageJson
    || typeof packageJson !== 'object'
    || Array.isArray(packageJson)
    || typeof packageJson.version !== 'string'
    || !/^[0-9]+\\.[0-9]+\\.[0-9]+$/.test(packageJson.version)
  ) {{
    throw new Error(`Dex update bridge refused invalid legacy package version ${{packagePath}}.`);
  }}
  return Buffer.from(`${{JSON.stringify({{
    phase: 'bootstrap-v1',
    release_version: packageJson.version,
    schema_version: 1,
  }})}}\\n`, 'utf8');
}}

let hideShippedLink = false;
let shippedLinkFound = false;
try {{
  const linkState = fs.lstatSync(shippedLink);
  shippedLinkFound = true;
  const resolvedTarget = fs.realpathSync(shippedLink);
  const expectedTarget = path.join(root, 'pi-extensions/dex');
  if (
    !linkState.isSymbolicLink()
    || fs.readlinkSync(shippedLink) !== shippedLinkTarget
    || resolvedTarget !== expectedTarget
    || !fs.lstatSync(expectedTarget).isDirectory()
  ) {{
    throw new Error(`Dex update bridge refused changed legacy release symlink ${{shippedLink}}.`);
  }}
  hideShippedLink = true;
}} catch (error) {{
  if (shippedLinkFound || !error || error.code !== 'ENOENT') throw error;
}}

fs.readFileSync = function dexLegacyCompatibilityRead(candidate, options) {{
  const supplied = Buffer.isBuffer(candidate) ? candidate.toString() : String(candidate);
  const absolute = path.resolve(supplied);
  const suppliedInput = inputs.has(absolute) || absolute === transitionPath;
  if (!suppliedInput) return originalReadFileSync(candidate, options);
  try {{
    fs.lstatSync(absolute);
  }} catch (error) {{
    if (error && error.code === 'ENOENT') {{
      const content = absolute === transitionPath
        ? legacyTransition()
        : inputs.get(absolute);
      const encoding = typeof options === 'string' ? options : options && options.encoding;
      return encoding ? content.toString(encoding) : Buffer.from(content);
    }}
    throw error;
  }}
  throw new Error(`Dex update bridge refused existing legacy compatibility input ${{absolute}}.`);
}};

fs.readdirSync = function dexLegacyCompatibilityDirectory(directory, options) {{
  const entries = originalReaddirSync(directory, options);
  if (
    hideShippedLink
    && path.resolve(String(directory)) === shippedLinkParent
    && options
    && typeof options === 'object'
    && options.withFileTypes === true
  ) {{
    return entries.filter((entry) => entry.name !== shippedLinkName);
  }}
  return entries;
}};
""".encode()


class LifecycleService(Protocol):
    def build_and_preview_topology_migration(self, vault_root: str | Path) -> Mapping[str, Any]: ...
    def execute_approved_topology_migration(self, vault_root: str | Path, preview: Mapping[str, Any], approved_token: str) -> Mapping[str, Any]: ...
    def build_and_preview_delivered_release(self, vault_root: str | Path, release: Mapping[str, Any]) -> Mapping[str, Any]: ...
    def execute_approved_delivered_release(self, vault_root: str | Path, preview: Mapping[str, Any], approved_token: str) -> Mapping[str, Any]: ...
    def build_and_preview_mcp_registration(self, vault_root: str | Path) -> Mapping[str, Any]: ...
    def execute_approved_mcp_registration(self, vault_root: str | Path, preview: Mapping[str, Any], approved_token: str) -> Mapping[str, Any]: ...


def _trusted_executable(name: str) -> Path | None:
    """Find a system-installed executable without consulting caller PATH."""
    for directory in _TRUSTED_EXECUTABLE_DIRECTORIES:
        candidate = directory / name
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    return None


def _trusted_git_binary() -> Path:
    git = _trusted_executable("git")
    if git is None:
        raise BridgeError("trusted system Git is required for the one-time Dex update bridge")
    return git


def _bridge_environment() -> dict[str, str]:
    """Return the small, non-interactive environment used by the bridge.

    The bridge fetches one public, pinned release; it must never inherit a
    caller's Git repository selection, configuration, credential helpers,
    Python import path, or executable lookup.  The foundation's Node migrator
    inherits this exact environment, so its Git children receive the same
    boundary.
    """
    executable_directories = [str(_trusted_git_binary().parent)]
    node = _trusted_executable("node")
    if node is not None:
        executable_directories.append(str(node.parent))
    executable_directories.extend(str(directory) for directory in _TRUSTED_EXECUTABLE_DIRECTORIES)
    return {
        "PATH": os.pathsep.join(dict.fromkeys(executable_directories)),
        "GCM_INTERACTIVE": "Never",
        "GIT_ALLOW_PROTOCOL": "https",
        "GIT_ASKPASS": "false",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _run_git(directory: Path, *arguments: str) -> str:
    """Run a non-interactive Git operation with hooks and non-HTTPS blocked."""
    completed = subprocess.run(
        [
            str(_trusted_git_binary()),
            "--no-replace-objects",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "credential.helper=",
            "-c",
            "fetch.fsckObjects=true",
            "-c",
            "transfer.fsckObjects=true",
            "-C",
            str(directory),
            *arguments,
        ],
        check=False,
        capture_output=True,
        env=_bridge_environment(),
        timeout=90,
    )
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise BridgeError(detail or "Git could not retrieve the pinned Dex release")
    try:
        return completed.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise BridgeError("Git returned non-text release metadata") from error


def _assert_equal(actual: str, expected: str, description: str) -> None:
    if actual != expected:
        raise BridgeError(f"pinned foundation {description} did not match")


def _verify_pin(repository: Path, pin: ReleasePin) -> None:
    _assert_equal(_run_git(repository, "rev-parse", "--verify", f"refs/tags/{pin.tag}"), pin.tag_object, "annotated tag")
    _assert_equal(_run_git(repository, "rev-parse", "--verify", f"{pin.tag}^{{commit}}"), pin.commit, "commit")
    _assert_equal(_run_git(repository, "rev-parse", "--verify", f"{pin.tag}^{{tree}}"), pin.tree, "tree")


def _supported_legacy_topology(
    vault_root: Path,
    pin: LegacyTopologyPin = LEGACY_TOPOLOGY_FOUNDATION,
) -> bool:
    """Prove the exact legacy base allowed to borrow the foundation migrator."""

    root = Path(vault_root)
    git_directory = root / ".git"
    if (
        git_directory.is_symlink()
        or not git_directory.is_dir()
        or (root / _TOPOLOGY_MIGRATOR_RELATIVE).exists()
        or (root / _TOPOLOGY_MIGRATOR_RELATIVE).is_symlink()
    ):
        return False
    try:
        tag_object = _run_git(
            root,
            "for-each-ref",
            "--format=%(objectname)",
            f"refs/tags/{pin.tag}",
        )
        if tag_object:
            if tag_object != pin.tag_object:
                return False
            if _run_git(root, "cat-file", "-t", pin.tag_object) != "tag":
                return False
            identity = pin.tag
        else:
            # Historic installers retained their own release tag but could
            # prune older tag labels. The pinned commit remains a safe proof
            # only when its object type, commit identity, tree, and ancestry
            # all match the closed v1.20.1 foundation.
            if _run_git(root, "cat-file", "-t", pin.commit) != "commit":
                return False
            identity = pin.commit
        if _run_git(root, "rev-parse", "--verify", f"{identity}^{{commit}}") != pin.commit:
            return False
        if _run_git(root, "rev-parse", "--verify", f"{identity}^{{tree}}") != pin.tree:
            return False
        head = _run_git(root, "rev-parse", "--verify", "HEAD^{commit}")
        if _HEX.fullmatch(head) is None:
            return False
        _run_git(root, "merge-base", "--is-ancestor", pin.commit, head)
    except BridgeError:
        return False
    return True


def acquire_foundation_source(pin: ReleasePin = FOUNDATION) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    """Fetch only the pinned foundation tag into a disposable source checkout."""
    temporary = tempfile.TemporaryDirectory(prefix="dex-update-bridge-")
    root = Path(temporary.name)
    bare = root / "evidence.git"
    source = root / "foundation"
    try:
        _run_git(root, "init", "--bare", "--quiet", str(bare))
        _run_git(bare, "fetch", "--quiet", "--no-tags", "--no-write-fetch-head", "--no-recurse-submodules", OFFICIAL_REMOTE, f"refs/tags/{pin.tag}:refs/tags/{pin.tag}")
        _verify_pin(bare, pin)
        # A linked worktree keeps the verified objects in the disposable bare
        # evidence store. It avoids opening the local ``file`` transport, which
        # this bridge deliberately blocks for every network-facing Git call.
        _run_git(bare, "worktree", "add", "--quiet", "--detach", str(source), pin.tag)
        _verify_pin(source, pin)
    except Exception:
        temporary.cleanup()
        raise
    return temporary, source


def _validate_vault(vault_root: Path) -> Path:
    supplied = Path(vault_root).expanduser()
    if ".." in supplied.parts:
        raise BridgeError("Dex vault path must not contain parent-directory traversal")
    # ``resolve()`` follows links, so it is only safe after every component of
    # the path supplied by the caller has been checked.  Otherwise a symlinked
    # root would appear to be an ordinary target directory by the time the
    # lifecycle service sees it.
    lexical = Path(os.path.abspath(supplied))
    path_component = Path(lexical.anchor)
    for component in lexical.parts[1:]:
        path_component /= component
        if path_component.is_symlink():
            raise BridgeError("Dex vault path contains a symlink")
    root = lexical.resolve()
    if not root.is_dir():
        raise BridgeError("Dex vault is not a safe directory")
    if (root / ".git").is_symlink() or not (root / ".git").exists():
        raise BridgeError("Dex vault does not have a safe Git history")
    if (root / "System").is_symlink() or not (root / "System").is_dir():
        raise BridgeError("Dex vault does not have a safe System directory")
    for private_parent in (".venv", ".dex"):
        candidate = root / private_parent
        if candidate.is_symlink():
            raise BridgeError(f"Dex vault {private_parent} must not be a symlink")
        if candidate.exists() and not candidate.is_dir():
            raise BridgeError(f"Dex vault {private_parent} must be a directory")
    return root


def _installed_python(vault_root: Path) -> Path | None:
    """Return Dex's already-created POSIX virtualenv interpreter, if present.

    The foundation lifecycle service needs the same runtime dependencies that
    the historical Dex installer already put in ``.venv``.  The bridge never
    downloads Python packages at update time.  This is deliberately a POSIX
    seam; Windows gets its own reviewed bridge rather than guessed paths.
    """
    venv = vault_root / ".venv"
    if venv.is_symlink() or (venv.exists() and not venv.is_dir()):
        return None
    candidate = venv / "bin" / "python"
    config = venv / "pyvenv.cfg"
    # POSIX venvs normally expose Python as a symlink to the system interpreter;
    # executing that entrypoint is what makes its dependency site-packages
    # available, so reject only a missing/non-executable resolved target.
    if not candidate.exists() or not candidate.resolve().is_file() or not os.access(candidate, os.X_OK):
        return None
    if config.is_symlink() or not config.is_file():
        return None
    return candidate


def _running_in_selected_runtime(interpreter: Path) -> bool:
    """Prove this process was launched through the selected vault virtualenv.

    Virtualenv Python binaries may be symlinks to the host binary, so comparing
    resolved executables would accept a host-Python invocation.  Preserve the
    invocation path and require the virtualenv's runtime prefixes as well.
    """
    selected_prefix = interpreter.parent.parent
    return (
        os.path.abspath(sys.executable) == str(interpreter)
        and os.path.abspath(sys.prefix) == str(selected_prefix)
        and os.path.abspath(sys.exec_prefix) == str(selected_prefix)
    )


def _reexec_in_installed_runtime(vault_root: Path, argv: list[str]) -> None:
    """Enter one clean process before loading any foundation code.

    The installed venv can resolve to the same binary as the invoking Python,
    but running it by its venv path still selects the installed dependencies.
    Never trust a caller-supplied runtime marker: it is accepted only when the
    complete environment already equals the closed runtime environment and the
    running Python identifies as the selected vault virtualenv.
    """
    interpreter = _installed_python(vault_root)
    if interpreter is None:
        raise BridgeError("Dex's installed virtualenv is required for the one-time update bridge")
    environment = _bridge_environment()
    environment[_CLEAN_RUNTIME_MARKER] = "1"
    if (
        os.environ.get(_CLEAN_RUNTIME_MARKER) == "1"
        and dict(os.environ) == environment
        and _running_in_selected_runtime(interpreter)
    ):
        return
    os.execve(
        str(interpreter),
        [str(interpreter), str(Path(__file__).resolve()), *argv],
        environment,
    )


class _FoundationLifecycleService:
    """Bind a verified foundation migrator to one legacy lifecycle call.

    The foundation service normally launches the migrator shipped inside the
    vault. v1.20.1 predates that file. For only that exact immutable base, this
    adapter lets the same lifecycle preview/approval/execute path launch the
    migrator from the already-verified disposable foundation checkout. No
    bridge file is copied into the vault and unknown layouts stay fail-closed.
    """

    def __init__(
        self,
        service: ModuleType,
        engine: ModuleType,
        apply_update: ModuleType,
        source: Path,
    ) -> None:
        self._service = service
        self._engine = engine
        self._apply_update = apply_update
        self._source = Path(source).resolve()
        self._migrator = self._source / _TOPOLOGY_MIGRATOR_RELATIVE
        engine_relative = getattr(engine, "TOPOLOGY_MIGRATOR_RELATIVE", None)
        if (
            not isinstance(engine_relative, Path)
            or engine_relative != _TOPOLOGY_MIGRATOR_RELATIVE
        ):
            raise BridgeError("pinned foundation topology migrator path changed")
        if (
            self._migrator.is_symlink()
            or not self._migrator.is_file()
            or not self._migrator.resolve().is_relative_to(self._source)
        ):
            raise BridgeError("pinned foundation topology migrator is missing or unsafe")
        self._migrator_sha256 = hashlib.sha256(self._migrator.read_bytes()).hexdigest()
        if (
            hashlib.sha256(_LEGACY_TRACKED_IGNORE_POLICY).hexdigest()
            != _LEGACY_TRACKED_IGNORE_POLICY_SHA256
        ):
            raise BridgeError("pinned legacy tracked-ignore policy changed")
        compatibility = Path(
            tempfile.mkdtemp(
                prefix="dex-v1201-compat-",
                dir=self._source.parent,
            )
        )
        self._preload = compatibility / "read-only-inputs.cjs"
        with self._preload.open("xb") as handle:
            handle.write(_legacy_preload_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        self._preload.chmod(0o400)
        self._preload_sha256 = hashlib.sha256(self._preload.read_bytes()).hexdigest()
        if not callable(getattr(engine, "topology_state", None)) or not callable(
            getattr(engine, "_migrator_command", None)
        ):
            raise BridgeError("pinned foundation topology engine is incomplete")
        if not callable(getattr(apply_update, "_tree_entries", None)) or not callable(
            getattr(apply_update, "_verify_manifest", None)
        ):
            raise BridgeError("pinned foundation release planner is incomplete")

    def _verify_compatibility_runtime(self) -> None:
        if (
            self._migrator.is_symlink()
            or not self._migrator.is_file()
            or self._migrator.resolve().parent != (
                self._source / _TOPOLOGY_MIGRATOR_RELATIVE.parent
            ).resolve()
            or hashlib.sha256(self._migrator.read_bytes()).hexdigest()
            != self._migrator_sha256
        ):
            raise BridgeError("pinned foundation topology migrator changed after verification")
        if (
            self._preload.is_symlink()
            or not self._preload.is_file()
            or not self._preload.resolve().is_relative_to(self._source.parent.resolve())
            or hashlib.sha256(self._preload.read_bytes()).hexdigest()
            != self._preload_sha256
        ):
            raise BridgeError("pinned legacy compatibility preload changed after verification")

    @contextmanager
    def _topology_source(self) -> Iterator[None]:
        self._verify_compatibility_runtime()
        original_state = self._engine.topology_state
        original_command = self._engine._migrator_command
        authorized_roots: set[Path] = set()

        def topology_state(vault_root: Path) -> str:
            state = original_state(vault_root)
            root = Path(vault_root).resolve()
            candidate = root / _TOPOLOGY_MIGRATOR_RELATIVE
            if (
                state == "invalid-combined"
                and not candidate.exists()
                and not candidate.is_symlink()
                and _supported_legacy_topology(root)
            ):
                authorized_roots.add(root)
                return "combined"
            return state

        def migrator_command(vault_root: Path, mode: str) -> list[str]:
            root = Path(vault_root).resolve()
            candidate = root / _TOPOLOGY_MIGRATOR_RELATIVE
            if (
                root not in authorized_roots
                or candidate.exists()
                or candidate.is_symlink()
                or mode not in {"--dry-run", "--auto", "--resume"}
            ):
                return original_command(vault_root, mode)
            self._verify_compatibility_runtime()
            node = _trusted_executable("node")
            if node is None:
                raise BridgeError(
                    "trusted system Node.js is required for the foundation topology migrator"
                )
            return [
                str(node),
                "--require",
                str(self._preload),
                str(self._migrator),
                mode,
            ]

        self._engine.topology_state = topology_state
        self._engine._migrator_command = migrator_command
        try:
            yield
        finally:
            self._engine.topology_state = original_state
            self._engine._migrator_command = original_command

    @contextmanager
    def _legacy_delivery_source(self) -> Iterator[None]:
        """Let the planner read the one exact pre-manifest legacy release.

        v1.20.1 has one shipped symlink and no installed-files manifest. The
        foundation planner correctly refuses either shape for a modern target.
        For only the already-pinned installed tree, this read adapter omits the
        known symlink and unclassified retired release paths. The lifecycle
        transaction remains the sole writer; omitted legacy paths stay in
        place as user-controlled/unmanaged content.
        """

        original_tree_entries = self._apply_update._tree_entries
        original_verify_manifest = self._apply_update._verify_manifest
        authorized_legacy_signatures: set[tuple[tuple[str, int, str], ...]] = set()
        release_error = getattr(
            self._apply_update,
            "ReleaseVerificationError",
            RuntimeError,
        )
        contract_violation = getattr(
            self._apply_update.portable_contract,
            "ContractViolation",
            RuntimeError,
        )
        tree_entry = getattr(self._apply_update, "TreeEntry", None)
        if not callable(tree_entry):
            raise BridgeError("pinned foundation release entry type is unavailable")

        def signature(entries: tuple[Any, ...]) -> tuple[tuple[str, int, str], ...]:
            return tuple(
                (entry.path, entry.mode, entry.object_id) for entry in entries
            )

        def legacy_tree_entries(
            vault_root: Path,
            brain_git: Path,
            commit: str,
        ) -> tuple[Any, ...]:
            if commit != LEGACY_TOPOLOGY_FOUNDATION.commit:
                return original_tree_entries(vault_root, brain_git, commit)
            if (
                _run_git(Path(brain_git), "rev-parse", "--verify", f"{commit}^{{tree}}")
                != LEGACY_TOPOLOGY_FOUNDATION.tree
            ):
                raise BridgeError("installed legacy release tree changed before delivery")
            raw = self._apply_update._brain_output(
                vault_root,
                brain_git,
                "ls-tree",
                "-r",
                "-z",
                "--full-tree",
                commit,
            )
            entries: list[Any] = []
            seen: set[str] = set()
            for record in raw.split(b"\0"):
                if not record:
                    continue
                try:
                    metadata, raw_path = record.split(b"\t", 1)
                    raw_mode, object_type, object_id = (
                        metadata.decode("ascii").split(" ")
                    )
                    relative = raw_path.decode("utf-8")
                except (ValueError, UnicodeDecodeError) as error:
                    raise release_error(
                        "legacy release tree contains a malformed entry"
                    ) from error
                if relative in seen or object_type != "blob":
                    raise release_error("legacy release tree is ambiguous")
                seen.add(relative)
                if raw_mode == "120000":
                    if (
                        relative
                        != _LEGACY_SHIPPED_SYMLINK_RELATIVE.as_posix()
                        or object_id != _LEGACY_SHIPPED_SYMLINK_BLOB
                        or self._apply_update._brain_output(
                            vault_root,
                            brain_git,
                            "cat-file",
                            "blob",
                            object_id,
                        )
                        != _LEGACY_SHIPPED_SYMLINK_TARGET.encode()
                    ):
                        raise release_error(
                            "legacy release contains an unknown symlink"
                        )
                    continue
                if raw_mode not in {"100644", "100755"}:
                    raise release_error(
                        "legacy release contains an unsupported entry"
                    )
                try:
                    self._apply_update.portable_contract.resolve(relative)
                except contract_violation:
                    # Retired release paths that the current contract does not
                    # own are deliberately preserved rather than pruned.
                    continue
                entries.append(
                    tree_entry(
                        relative,
                        0o755 if raw_mode == "100755" else 0o644,
                        object_id,
                    )
                )
            result = tuple(sorted(entries, key=lambda entry: entry.path))
            authorized_legacy_signatures.add(signature(result))
            return result

        def verify_manifest(
            vault_root: Path,
            brain_git: Path,
            entries: tuple[Any, ...],
        ) -> None:
            try:
                original_verify_manifest(vault_root, brain_git, entries)
            except release_error:
                if signature(entries) not in authorized_legacy_signatures:
                    raise
                installed = _run_git(
                    Path(brain_git),
                    "rev-parse",
                    "--verify",
                    "refs/dex/installed^{commit}",
                )
                if installed != LEGACY_TOPOLOGY_FOUNDATION.commit:
                    raise

        self._apply_update._tree_entries = legacy_tree_entries
        self._apply_update._verify_manifest = verify_manifest
        try:
            yield
        finally:
            self._apply_update._tree_entries = original_tree_entries
            self._apply_update._verify_manifest = original_verify_manifest

    def build_and_preview_topology_migration(
        self,
        vault_root: str | Path,
    ) -> Mapping[str, Any]:
        with self._topology_source():
            return self._service.build_and_preview_topology_migration(vault_root)

    def execute_approved_topology_migration(
        self,
        vault_root: str | Path,
        preview: Mapping[str, Any],
        approved_token: str,
    ) -> Mapping[str, Any]:
        with self._topology_source():
            return self._service.execute_approved_topology_migration(
                vault_root,
                preview,
                approved_token,
            )

    def deliver_latest_release(
        self,
        vault_root: str | Path,
    ) -> Mapping[str, Any]:
        return self._service.deliver_latest_release(vault_root)

    def build_and_preview_delivered_release(
        self,
        vault_root: str | Path,
        release: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        with self._legacy_delivery_source():
            return self._service.build_and_preview_delivered_release(
                vault_root,
                release,
            )

    def execute_approved_delivered_release(
        self,
        vault_root: str | Path,
        preview: Mapping[str, Any],
        approved_token: str,
    ) -> Mapping[str, Any]:
        with self._legacy_delivery_source():
            return self._service.execute_approved_delivered_release(
                vault_root,
                preview,
                approved_token,
            )

    def build_and_preview_mcp_registration(
        self,
        vault_root: str | Path,
    ) -> Mapping[str, Any]:
        return self._service.build_and_preview_mcp_registration(vault_root)

    def execute_approved_mcp_registration(
        self,
        vault_root: str | Path,
        preview: Mapping[str, Any],
        approved_token: str,
    ) -> Mapping[str, Any]:
        return self._service.execute_approved_mcp_registration(
            vault_root,
            preview,
            approved_token,
        )


def _load_lifecycle_service(source: Path) -> LifecycleService:
    """Import only the verified foundation release's lifecycle service."""
    if not (source / "core" / "lifecycle" / "service.py").is_file():
        raise BridgeError("pinned foundation release has no lifecycle service")
    for name in tuple(sys.modules):
        if name == "core" or name.startswith("core."):
            del sys.modules[name]
    sys.path.insert(0, str(source))
    try:
        module: ModuleType = importlib.import_module("core.lifecycle.service")
    except Exception as error:  # noqa: BLE001
        raise BridgeError(f"pinned foundation lifecycle service could not start: {error}") from error
    required = (
        "build_and_preview_topology_migration",
        "execute_approved_topology_migration",
        "deliver_latest_release",
        "build_and_preview_delivered_release",
        "execute_approved_delivered_release",
        "build_and_preview_mcp_registration",
        "execute_approved_mcp_registration",
    )
    if any(not callable(getattr(module, name, None)) for name in required):
        raise BridgeError("pinned foundation lifecycle service is incomplete")
    try:
        engine = importlib.import_module("core.lifecycle.engine")
    except Exception as error:  # noqa: BLE001
        raise BridgeError(
            f"pinned foundation topology engine could not start: {error}"
        ) from error
    try:
        apply_update = importlib.import_module("core.update.apply_update")
    except Exception as error:  # noqa: BLE001
        raise BridgeError(
            f"pinned foundation release planner could not start: {error}"
        ) from error
    return _FoundationLifecycleService(module, engine, apply_update, source)


def _approved_preview(prompt: str, preview: Mapping[str, Any], approval_token: object, *, input_fn: Callable[[str], str], output_fn: Callable[[str], None]) -> tuple[Mapping[str, Any], str]:
    if not isinstance(approval_token, str) or not approval_token:
        raise BridgeError("lifecycle preview did not return an approval token")
    output_fn(json.dumps(preview, indent=2, sort_keys=True))
    if input_fn(f"{prompt} Type {_APPROVAL_WORD} to continue: ") != _APPROVAL_WORD:
        raise BridgeError("no change was made because the displayed preview was not approved")
    return preview, approval_token


def _fetch_foundation_into_brain(vault_root: Path, pin: ReleasePin) -> None:
    """Fetch one pinned release into the private brain; no vault file is written.

    The public release branch is allowed to advance after the foundation ships.
    Only the closed immutable tag identifies the first hop.  Once verified, its
    exact commit becomes the private release ref consumed by lifecycle.
    """
    brain = vault_root / ".dex" / "brain.git"
    if brain.is_symlink() or not brain.is_dir():
        raise BridgeError("topology conversion did not create a safe Dex brain store")
    _run_git(
        brain,
        "fetch",
        "--quiet",
        "--no-tags",
        "--no-write-fetch-head",
        "--no-recurse-submodules",
        OFFICIAL_REMOTE,
        f"refs/tags/{pin.tag}:refs/tags/{pin.tag}",
    )
    _verify_pin(brain, pin)
    _run_git(
        brain,
        "update-ref",
        "refs/remotes/upstream/release",
        pin.commit,
    )
    _assert_equal(
        _run_git(brain, "rev-parse", "--verify", "refs/remotes/upstream/release^{commit}"),
        pin.commit,
        "private foundation release ref",
    )


def _regular_json(path: Path, description: str) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise BridgeError(f"{description} is not a regular file")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BridgeError(f"{description} is unreadable") from error
    if not isinstance(value, dict):
        raise BridgeError(f"{description} is not an object")
    return value


def _validate_completed_foundation(vault_root: Path, pin: ReleasePin) -> None:
    """Prove every durable split marker agrees with the installed pin."""
    brain = vault_root / ".dex" / "brain.git"
    paths = {
        ".git": vault_root / ".git",
        ".dex": vault_root / ".dex",
        ".dex/brain.git": brain,
        "System/.dex": vault_root / "System" / ".dex",
    }
    for relative, path in paths.items():
        if path.is_symlink() or not path.is_dir():
            raise BridgeError(f"completed bridge has an unsafe {relative} directory")

    topology = _regular_json(vault_root / "System" / ".dex" / "topology.json", "split topology marker")
    vault_marker = _regular_json(vault_root / ".git" / "dex-vault-v2", "vault Git marker")
    brain_marker = _regular_json(brain / "dex-brain-v2", "brain Git marker")
    environment = topology.get("environment")
    wired_vault = environment.get("DEX_VAULT") if isinstance(environment, dict) else None
    try:
        wiring_matches = isinstance(wired_vault, str) and Path(wired_vault).resolve() == vault_root
    except (OSError, RuntimeError):
        wiring_matches = False
    if (
        topology.get("topology") != "brain-vault-split"
        or topology.get("vaultGitDir") != ".git"
        or topology.get("brainGitDir") != ".dex/brain.git"
        or not wiring_matches
        or topology.get("installedRelease") != pin.commit
        or vault_marker.get("role") != "vault"
        or brain_marker.get("role") != "brain"
        or brain_marker.get("installed") != pin.commit
    ):
        raise BridgeError("completed bridge markers do not agree with the pinned foundation")


def _foundation_is_installed(vault_root: Path, pin: ReleasePin) -> bool:
    """Check the local installed ref without fetching or consulting a channel.

    This is deliberately safe to call before topology conversion: an old vault
    simply has no private brain store yet, whereas a completed bridge can
    resume offline even if the public stable channel has advanced.
    """
    brain = vault_root / ".dex" / "brain.git"
    dex_root = vault_root / ".dex"
    if dex_root.is_symlink() or brain.is_symlink():
        raise BridgeError("Dex private code store must not contain a symlink")
    if not dex_root.exists() or not brain.exists():
        return False
    if not dex_root.is_dir() or not brain.is_dir():
        raise BridgeError("Dex private code store is not a safe directory")
    try:
        installed = _run_git(brain, "rev-parse", "--verify", "refs/dex/installed^{commit}")
    except BridgeError:
        return False
    if installed != pin.commit:
        return False
    _validate_completed_foundation(vault_root, pin)
    return True


def _completed_bridge_result(
    pin: ReleasePin,
    mcp_registration_receipt: Mapping[str, Any],
) -> dict[str, object]:
    return {
        "foundation": pin.identity(),
        "topology_receipt": {"skipped": "foundation-already-installed"},
        "delivery_receipt": {"skipped": "foundation-already-installed"},
        "mcp_registration_receipt": dict(mcp_registration_receipt),
    }


def _complete_mcp_registration(
    vault_root: Path,
    service: LifecycleService,
    *,
    input_fn: Callable[[str], str],
    output_fn: Callable[[str], None],
) -> Mapping[str, Any]:
    registration = service.build_and_preview_mcp_registration(vault_root)
    if registration.get("needed") is False:
        if (
            registration.get("preview") is not None
            or registration.get("approval_token") is not None
        ):
            raise BridgeError("foundation returned a malformed completed MCP registration")
        return {"skipped": "mcp-already-registered"}

    registration_preview = registration.get("preview")
    if registration.get("needed") is not True or not isinstance(
        registration_preview,
        Mapping,
    ):
        raise BridgeError("foundation could not produce an MCP registration preview")
    registration_preview, registration_token = _approved_preview(
        "Dex will add the current customization migration server to your MCP configuration.",
        registration_preview,
        registration.get("approval_token"),
        input_fn=input_fn,
        output_fn=output_fn,
    )
    return service.execute_approved_mcp_registration(
        vault_root,
        registration_preview,
        registration_token,
    )


def run_bridge(vault_root: Path, service: LifecycleService, *, pin: ReleasePin = FOUNDATION, fetch_foundation: Callable[[Path, ReleasePin], None] = _fetch_foundation_into_brain, input_fn: Callable[[str], str] = input, output_fn: Callable[[str], None] = print) -> Mapping[str, Any]:
    """Run up to three fresh approval boundaries through the foundation service."""
    root = _validate_vault(vault_root)
    # This local ref is the authoritative resume marker. Check it before
    # importing/calling lifecycle code or attempting any network operation: a
    # completed bridge must work offline and must not be disturbed merely
    # because the stable channel has subsequently advanced.
    if _foundation_is_installed(root, pin):
        return _completed_bridge_result(
            pin,
            _complete_mcp_registration(
                root,
                service,
                input_fn=input_fn,
                output_fn=output_fn,
            ),
        )

    topology = service.build_and_preview_topology_migration(root)
    preview = topology.get("preview")
    # Foundation v1.80.5 calls a completed conversion ``post-split`` and still
    # returns a read-only status document. Older service shapes used
    # ``brain-vault-split`` with no preview. Neither has an approval token, so
    # neither is an operation the bridge may repeat.
    if (
        topology.get("topology") in {"brain-vault-split", "post-split"}
        and topology.get("approval_token") is None
    ):
        topology_receipt: Mapping[str, Any] = {"skipped": "already-brain-vault-split"}
    else:
        if not isinstance(preview, Mapping):
            raise BridgeError("foundation could not produce a topology preview")
        preview, token = _approved_preview("Dex will first separate its code from your notes.", preview, topology.get("approval_token"), input_fn=input_fn, output_fn=output_fn)
        topology_receipt = service.execute_approved_topology_migration(root, preview, token)

    # This fetch touches only Dex's private code store. The following preview is
    # still the sole authority for every vault-content write.
    fetch_foundation(root, pin)
    delivery = service.build_and_preview_delivered_release(root, pin.identity())
    release_preview = delivery.get("preview")
    if not isinstance(release_preview, Mapping):
        raise BridgeError("foundation could not produce a delivered-release preview")
    release_preview, release_token = _approved_preview(f"Dex will now install verified foundation v{pin.version}.", release_preview, delivery.get("approval_token"), input_fn=input_fn, output_fn=output_fn)
    delivery_receipt = service.execute_approved_delivered_release(root, release_preview, release_token)

    mcp_registration_receipt = _complete_mcp_registration(
        root,
        service,
        input_fn=input_fn,
        output_fn=output_fn,
    )

    return {
        "foundation": pin.identity(),
        "topology_receipt": dict(topology_receipt),
        "delivery_receipt": dict(delivery_receipt),
        "mcp_registration_receipt": dict(mcp_registration_receipt),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=Path.cwd(), help="old Dex vault (defaults to current directory)")
    args = parser.parse_args(argv)
    if sys.platform.startswith("win"):
        parser.error("this P0 bridge supports macOS and Linux only")
    try:
        _trusted_git_binary()
        vault = _validate_vault(args.vault)
        # A completed bridge has all durable state locally.  Check before
        # selecting the old virtualenv or downloading source so resuming it is
        # genuinely offline and independent of a later stable-channel change.
        if _foundation_is_installed(vault, FOUNDATION):
            _reexec_in_installed_runtime(
                vault,
                sys.argv[1:] if argv is None else argv,
            )
            result = run_bridge(
                vault,
                _load_lifecycle_service(vault),
            )
        else:
            _reexec_in_installed_runtime(vault, sys.argv[1:] if argv is None else argv)
            temporary, source = acquire_foundation_source()
            try:
                result = run_bridge(vault, _load_lifecycle_service(source))
            finally:
                temporary.cleanup()
    except (BridgeError, OSError, RuntimeError) as error:
        print(f"Dex update bridge stopped safely: {error}", file=sys.stderr)
        return 1
    print("Foundation delivery is complete. Once historical support is verified, future updates use /dex-update.")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
