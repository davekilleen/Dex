#!/usr/bin/env python3
"""Release-owned executor for one verified historic Dex update journey.

This module is the only implementation allowed to turn the closed journey
protocol into bridge and lifecycle calls. Serialized evidence is output for
review; authority stays in the live ``ExecutorRun`` returned by this process.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import select
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.update.journey_protocol import UpdateJourneyProtocol
from scripts import dex_update_bridge

EXECUTOR_INTERFACE_VERSION = 1
_IDENTITY_FIELDS = frozenset(
    {"tag", "tag_object", "commit", "tree", "version", "channel"}
)
_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
_RELEASE_TAG = re.compile(
    r"^dist/release/v(?P<version>(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))-(?P<short>[0-9a-f]{7,40})$"
)
_LEGACY_RELEASE_TAG = re.compile(
    r"^v(?P<version>(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))$"
)
_DECLARED_LIFECYCLE_OPERATIONS = frozenset(
    {
        "deliver_latest_release",
        "build_and_preview_delivered_release",
        "execute_approved_delivered_release",
    }
)


class ExecutorError(RuntimeError):
    """The released journey executor could not prove a safe completed run."""


class ExecutorRun:
    """One live executor result that cannot be reconstructed from JSON."""

    __slots__ = ("_authority", "_case_json")

    def __init__(self, case: Mapping[str, object]) -> None:
        raise ExecutorError(
            "only the live executor can create an authoritative journey run"
        )

    def __setattr__(self, name: str, value: object) -> None:
        raise ExecutorError("executor run proof is immutable")

    @property
    def case(self) -> dict[str, object]:
        value = json.loads(self._case_json)
        if not isinstance(value, dict):
            raise ExecutorError("executor run proof is malformed")
        return value


def _cached_git(repository: Path, *arguments: str) -> str:
    """Run local-only Git against a controller-verified foundation cache."""

    environment = dex_update_bridge._bridge_environment()
    environment["GIT_ALLOW_PROTOCOL"] = "file"
    completed = subprocess.run(
        [
            str(dex_update_bridge._trusted_git_binary()),
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "credential.helper=",
            "-c",
            "fetch.fsckObjects=true",
            "-c",
            "transfer.fsckObjects=true",
            "-C",
            str(repository),
            *arguments,
        ],
        check=False,
        capture_output=True,
        env=environment,
        timeout=90,
    )
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise ExecutorError(detail or "foundation cache Git operation failed")
    try:
        return completed.stdout.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise ExecutorError("foundation cache Git output was not text") from error


def _validate_foundation_cache(
    cache: Path,
    pin: dex_update_bridge.ReleasePin = dex_update_bridge.FOUNDATION,
) -> Path:
    """Prove a private local cache contains the exact official foundation."""

    if cache.is_symlink() or not cache.is_dir():
        raise ExecutorError("foundation cache must be a private bare repository")
    status = cache.stat()
    if status.st_uid != os.getuid() or stat.S_IMODE(status.st_mode) != 0o700:
        raise ExecutorError(
            "foundation cache must be controller-owned with mode 0700"
        )
    resolved = cache.resolve(strict=True)
    expected = {
        f"refs/tags/{pin.tag}": pin.tag_object,
        f"{pin.tag}^{{commit}}": pin.commit,
        f"{pin.tag}^{{tree}}": pin.tree,
        "refs/heads/release^{commit}": pin.commit,
    }
    for revision, identity in expected.items():
        try:
            actual = _cached_git(resolved, "rev-parse", "--verify", revision)
        except ExecutorError as error:
            raise ExecutorError(
                "foundation cache does not match the pinned official release"
            ) from error
        if actual != identity:
            raise ExecutorError(
                "foundation cache does not match the pinned official release"
            )
    return resolved


def _acquire_cached_foundation_source(
    cache: Path,
    pin: dex_update_bridge.ReleasePin = dex_update_bridge.FOUNDATION,
) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    """Check out the verified cache without another network transfer."""

    verified = _validate_foundation_cache(cache, pin)
    temporary = tempfile.TemporaryDirectory(prefix="dex-cached-foundation-")
    root = Path(temporary.name)
    source = root / "foundation"
    try:
        _cached_git(
            root,
            "clone",
            "--quiet",
            "--no-checkout",
            "--no-local",
            str(verified),
            str(source),
        )
        _cached_git(source, "checkout", "--quiet", "--detach", pin.tag)
        for revision, identity in (
            (f"refs/tags/{pin.tag}", pin.tag_object),
            (f"{pin.tag}^{{commit}}", pin.commit),
            (f"{pin.tag}^{{tree}}", pin.tree),
        ):
            if _cached_git(source, "rev-parse", "--verify", revision) != identity:
                raise ExecutorError(
                    "cached foundation checkout changed immutable identity"
                )
    except Exception:
        temporary.cleanup()
        raise
    return temporary, source


def _fetch_foundation_from_cache(
    vault: Path,
    pin: dex_update_bridge.ReleasePin,
    *,
    cache: Path,
) -> None:
    """Populate only the private brain from the preverified local cache."""

    verified = _validate_foundation_cache(cache, pin)
    brain = vault / ".dex/brain.git"
    if brain.is_symlink() or not brain.is_dir():
        raise ExecutorError("topology conversion did not create a safe brain store")
    _cached_git(
        brain,
        "fetch",
        "--quiet",
        "--no-tags",
        "--no-write-fetch-head",
        "--no-recurse-submodules",
        str(verified),
        f"refs/tags/{pin.tag}:refs/tags/{pin.tag}",
        "+refs/heads/release:refs/remotes/upstream/release",
    )
    if (
        _cached_git(brain, "rev-parse", "--verify", f"refs/tags/{pin.tag}")
        != pin.tag_object
        or _cached_git(brain, "rev-parse", "--verify", f"{pin.tag}^{{commit}}")
        != pin.commit
        or _cached_git(brain, "rev-parse", "--verify", f"{pin.tag}^{{tree}}")
        != pin.tree
        or _cached_git(
            brain,
            "rev-parse",
            "--verify",
            "refs/remotes/upstream/release^{commit}",
        )
        != pin.commit
    ):
        raise ExecutorError("cached foundation fetch changed immutable identity")


class JourneyRuntime(Protocol):
    """Internal seam for the production and deterministic test adapters."""

    def bridge_to_foundation(
        self,
        vault: Path,
        foundation: Mapping[str, str],
        *,
        input_fn: Callable[[str], str],
        output_fn: Callable[[str], None],
    ) -> Mapping[str, object]: ...

    def installed_release(self, vault: Path) -> str: ...

    def doctor(self, vault: Path) -> Mapping[str, object]: ...

    def deliver_latest_release(self, vault: Path) -> Mapping[str, object]: ...

    def build_and_preview_delivered_release(
        self,
        vault: Path,
        release: Mapping[str, str],
    ) -> Mapping[str, object]: ...

    def execute_approved_delivered_release(
        self,
        vault: Path,
        preview: Mapping[str, object],
        approved_token: str,
    ) -> Mapping[str, object]: ...

    def smoke(self, vault: Path) -> Mapping[str, object]: ...


class _ProductionRuntime:
    """Closed parent adapter over a fixture-venv lifecycle runtime."""

    def __init__(self, *, foundation_cache: Path | None = None) -> None:
        self._runtime_home = tempfile.TemporaryDirectory(
            prefix="dex-release-journey-runtime-"
        )
        self._server: subprocess.Popen[bytes] | None = None
        self._server_stderr = tempfile.TemporaryFile(mode="w+b")
        self._server_vault: Path | None = None
        self._server_buffer = bytearray()
        self._foundation_cache = (
            _validate_foundation_cache(foundation_cache)
            if foundation_cache is not None
            else None
        )

    def close(self) -> None:
        process = self._server
        if process is not None and process.poll() is None:
            try:
                assert process.stdin is not None
                process.stdin.write(b'{"operation":"close"}\n')
                process.stdin.flush()
                process.wait(timeout=10)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        self._server = None
        self._server_stderr.close()
        self._runtime_home.cleanup()

    def _runtime_environment(self, vault: Path) -> dict[str, str]:
        runtime_root = Path(self._runtime_home.name)
        environment = dex_update_bridge._bridge_environment()
        environment.update(
            {
                "DEX_VAULT": str(vault),
                "HOME": str(runtime_root),
                "TMPDIR": str(runtime_root),
                "VAULT_PATH": str(vault),
                "VAULT_ROOT": str(vault),
            }
        )
        return environment

    def _server_error(self, fallback: str) -> ExecutorError:
        self._server_stderr.flush()
        self._server_stderr.seek(0)
        detail = self._server_stderr.read(64 * 1024).decode(
            "utf-8",
            "replace",
        ).strip()
        return ExecutorError(detail or fallback)

    def _read_server_message(self, *, deadline: float) -> dict[str, object]:
        process = self._server
        if process is None or process.stdout is None:
            raise ExecutorError("fixture lifecycle runtime is not running")
        while b"\n" not in self._server_buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ExecutorError("fixture lifecycle runtime timed out")
            ready, _, _ = select.select([process.stdout], [], [], remaining)
            if not ready:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                raise ExecutorError("fixture lifecycle runtime timed out")
            chunk = os.read(process.stdout.fileno(), 64 * 1024)
            if not chunk:
                raise self._server_error("fixture lifecycle runtime stopped")
            self._server_buffer.extend(chunk)
            if len(self._server_buffer) > 16 * 1024 * 1024:
                raise ExecutorError(
                    "fixture lifecycle runtime message exceeded its bound"
                )
        line, _, remainder = self._server_buffer.partition(b"\n")
        self._server_buffer = bytearray(remainder)
        try:
            message = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ExecutorError(
                "fixture lifecycle runtime returned malformed JSON"
            ) from error
        if not isinstance(message, dict):
            raise ExecutorError("fixture lifecycle runtime returned malformed JSON")
        return message

    def _ensure_server(self, vault: Path) -> None:
        root = dex_update_bridge._validate_vault(vault)
        if self._server is not None:
            if root != self._server_vault:
                raise ExecutorError("fixture lifecycle runtime changed vaults")
            if self._server.poll() is not None:
                raise self._server_error("fixture lifecycle runtime stopped")
            return
        interpreter = dex_update_bridge._installed_python(root)
        if interpreter is None:
            raise ExecutorError(
                "Dex's installed virtualenv is required for the journey runtime"
            )
        self._server_stderr.seek(0)
        self._server_stderr.truncate()
        command = [
            str(interpreter),
            str(Path(__file__).resolve()),
            "_runtime-server",
            "--vault",
            str(root),
        ]
        if self._foundation_cache is not None:
            command.extend(
                ["--foundation-cache", str(self._foundation_cache)]
            )
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            env=self._runtime_environment(root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._server_stderr,
            bufsize=0,
            start_new_session=True,
        )
        self._server = process
        self._server_vault = root
        message = self._read_server_message(deadline=time.monotonic() + 180)
        if message != {"kind": "ready"}:
            raise self._server_error("fixture lifecycle runtime did not become ready")

    def _server_call(
        self,
        vault: Path,
        operation: str,
        payload: Mapping[str, object] | None = None,
        *,
        input_fn: Callable[[str], str] | None = None,
        output_fn: Callable[[str], None] | None = None,
    ) -> Mapping[str, object]:
        if operation != "bridge" and operation not in _DECLARED_LIFECYCLE_OPERATIONS:
            raise ExecutorError(
                f"lifecycle operation is not declared by the journey: {operation}"
            )
        self._ensure_server(vault)
        process = self._server
        assert process is not None and process.stdin is not None
        request = {"operation": operation}
        if payload is not None:
            request["payload"] = dict(payload)
        process.stdin.write(
            (
                json.dumps(request, separators=(",", ":"), sort_keys=True)
                + "\n"
            ).encode("utf-8")
        )
        process.stdin.flush()
        deadline = time.monotonic() + 900
        while True:
            message = self._read_server_message(deadline=deadline)
            kind = message.get("kind")
            if kind == "output" and set(message) == {"kind", "text"}:
                text = message["text"]
                if not isinstance(text, str) or output_fn is None:
                    raise ExecutorError("fixture lifecycle output event is malformed")
                output_fn(text)
                continue
            if kind == "prompt" and set(message) == {"kind", "prompt"}:
                prompt = message["prompt"]
                if not isinstance(prompt, str) or input_fn is None:
                    raise ExecutorError("fixture lifecycle prompt event is malformed")
                answer = input_fn(prompt)
                process.stdin.write(
                    (
                        json.dumps({"answer": answer}, separators=(",", ":"))
                        + "\n"
                    ).encode("utf-8")
                )
                process.stdin.flush()
                continue
            if kind == "error" and set(message) == {"kind", "message"}:
                detail = message["message"]
                raise ExecutorError(
                    detail if isinstance(detail, str) and detail else "fixture runtime failed"
                )
            if kind == "result" and set(message) == {"kind", "value"}:
                value = message["value"]
                if not isinstance(value, Mapping):
                    raise ExecutorError("fixture lifecycle result is malformed")
                return value
            raise ExecutorError("fixture lifecycle runtime event is malformed")

    @staticmethod
    def _service_call(
        service: object,
        operation: str,
        *arguments: object,
    ) -> Mapping[str, object]:
        if operation not in _DECLARED_LIFECYCLE_OPERATIONS:
            raise ExecutorError(
                f"lifecycle operation is not declared by the journey: {operation}"
            )
        function = getattr(service, operation, None)
        if not callable(function):
            raise ExecutorError(
                f"released foundation lifecycle service lacks {operation}"
            )
        response = function(*arguments)
        if not isinstance(response, Mapping):
            raise ExecutorError(
                f"released foundation lifecycle operation {operation} "
                "returned malformed evidence"
            )
        return response

    def bridge_to_foundation(
        self,
        vault: Path,
        foundation: Mapping[str, str],
        *,
        input_fn: Callable[[str], str],
        output_fn: Callable[[str], None],
    ) -> Mapping[str, object]:
        if foundation != dex_update_bridge.FOUNDATION.identity():
            raise ExecutorError("executor foundation does not match the pinned bridge")
        return self._server_call(
            vault,
            "bridge",
            input_fn=input_fn,
            output_fn=output_fn,
        )

    def installed_release(self, vault: Path) -> str:
        root = dex_update_bridge._validate_vault(vault)
        brain = root / ".dex" / "brain.git"
        topology = dex_update_bridge._regular_json(
            root / "System" / ".dex" / "topology.json",
            "split topology marker",
        )
        brain_marker = dex_update_bridge._regular_json(
            brain / "dex-brain-v2",
            "brain Git marker",
        )
        installed = dex_update_bridge._run_git(
            brain,
            "rev-parse",
            "--verify",
            "refs/dex/installed^{commit}",
        )
        if (
            topology.get("installedRelease") != installed
            or brain_marker.get("installed") != installed
        ):
            raise ExecutorError(
                "installed release identity disagrees across topology markers"
            )
        return installed

    def _installed_json(
        self,
        vault: Path,
        module: str,
        *arguments: str,
    ) -> Mapping[str, object]:
        root = dex_update_bridge._validate_vault(vault)
        interpreter = dex_update_bridge._installed_python(root)
        if interpreter is None:
            raise ExecutorError(
                "Dex's installed virtualenv is required for journey health proof"
            )
        process = subprocess.Popen(
            [str(interpreter), "-m", module, *arguments],
            cwd=root,
            env=self._runtime_environment(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=600)
        except subprocess.TimeoutExpired as error:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise ExecutorError(f"installed {module} timed out") from error
        if len(stdout) > 16 * 1024 * 1024 or len(stderr) > 1024 * 1024:
            raise ExecutorError(f"installed {module} output exceeded its bound")
        if process.returncode:
            detail = stderr.decode("utf-8", "replace").strip()
            raise ExecutorError(detail or f"installed {module} failed")
        try:
            report = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ExecutorError(f"installed {module} returned malformed JSON") from error
        if not isinstance(report, Mapping):
            raise ExecutorError(f"installed {module} returned malformed JSON")
        return report

    def doctor(self, vault: Path) -> Mapping[str, object]:
        return self._installed_json(vault, "core.utils.doctor")

    def deliver_latest_release(self, vault: Path) -> Mapping[str, object]:
        return self._server_call(vault, "deliver_latest_release")

    def build_and_preview_delivered_release(
        self,
        vault: Path,
        release: Mapping[str, str],
    ) -> Mapping[str, object]:
        return self._server_call(
            vault,
            "build_and_preview_delivered_release",
            {"release": dict(release)},
        )

    def execute_approved_delivered_release(
        self,
        vault: Path,
        preview: Mapping[str, object],
        approved_token: str,
    ) -> Mapping[str, object]:
        return self._server_call(
            vault,
            "execute_approved_delivered_release",
            {
                "preview": dict(preview),
                "approval_token": approved_token,
            },
        )

    def smoke(self, vault: Path) -> Mapping[str, object]:
        return self._installed_json(vault, "core.utils.smoke", "--json")


def _runtime_server_emit(value: Mapping[str, object]) -> None:
    print(
        json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        flush=True,
    )


def _runtime_server_answer(prompt: str) -> str:
    _runtime_server_emit({"kind": "prompt", "prompt": prompt})
    line = sys.stdin.readline()
    try:
        response = json.loads(line)
    except json.JSONDecodeError as error:
        raise ExecutorError("journey approval response is malformed") from error
    if (
        not isinstance(response, Mapping)
        or set(response) != {"answer"}
        or not isinstance(response["answer"], str)
    ):
        raise ExecutorError("journey approval response is malformed")
    return response["answer"]


def _runtime_server(
    vault: Path,
    *,
    foundation_cache: Path | None = None,
) -> int:
    """Serve the fixed lifecycle vocabulary from the fixture virtualenv."""

    root = dex_update_bridge._validate_vault(vault)
    temporary: tempfile.TemporaryDirectory[str] | None = None
    try:
        if dex_update_bridge._foundation_is_installed(
            root,
            dex_update_bridge.FOUNDATION,
        ):
            source = root
        elif foundation_cache is not None:
            temporary, source = _acquire_cached_foundation_source(
                foundation_cache
            )

            def fetch_foundation(
                vault_root: Path,
                pin: dex_update_bridge.ReleasePin,
            ) -> None:
                _fetch_foundation_from_cache(
                    vault_root,
                    pin,
                    cache=foundation_cache,
                )
        else:
            temporary, source = dex_update_bridge.acquire_foundation_source()
        service = dex_update_bridge._load_lifecycle_service(source)
        _runtime_server_emit({"kind": "ready"})
        for line in sys.stdin:
            try:
                request = json.loads(line)
                if not isinstance(request, Mapping):
                    raise ExecutorError("fixture lifecycle request is malformed")
                operation = request.get("operation")
                if operation == "close" and set(request) == {"operation"}:
                    return 0
                if operation == "bridge" and set(request) == {"operation"}:
                    bridge_arguments: dict[str, object] = {
                        "pin": dex_update_bridge.FOUNDATION,
                        "input_fn": _runtime_server_answer,
                        "output_fn": lambda text: _runtime_server_emit(
                            {"kind": "output", "text": text}
                        ),
                    }
                    if foundation_cache is not None:
                        bridge_arguments["fetch_foundation"] = fetch_foundation
                    result = dex_update_bridge.run_bridge(
                        root,
                        service,
                        **bridge_arguments,
                    )
                elif operation == "deliver_latest_release" and set(request) == {
                    "operation"
                }:
                    result = _ProductionRuntime._service_call(
                        service,
                        operation,
                        root,
                    )
                elif operation == "build_and_preview_delivered_release":
                    payload = request.get("payload")
                    if (
                        set(request) != {"operation", "payload"}
                        or not isinstance(payload, Mapping)
                        or set(payload) != {"release"}
                        or not isinstance(payload["release"], Mapping)
                    ):
                        raise ExecutorError("fixture lifecycle request is malformed")
                    result = _ProductionRuntime._service_call(
                        service,
                        operation,
                        root,
                        payload["release"],
                    )
                elif operation == "execute_approved_delivered_release":
                    payload = request.get("payload")
                    if (
                        set(request) != {"operation", "payload"}
                        or not isinstance(payload, Mapping)
                        or set(payload) != {"preview", "approval_token"}
                        or not isinstance(payload["preview"], Mapping)
                        or not isinstance(payload["approval_token"], str)
                    ):
                        raise ExecutorError("fixture lifecycle request is malformed")
                    result = _ProductionRuntime._service_call(
                        service,
                        operation,
                        root,
                        payload["preview"],
                        payload["approval_token"],
                    )
                else:
                    raise ExecutorError(
                        f"lifecycle operation is not declared by the journey: {operation}"
                    )
                _runtime_server_emit({"kind": "result", "value": dict(result)})
            except Exception as error:  # noqa: BLE001
                _runtime_server_emit({"kind": "error", "message": str(error)})
    finally:
        if temporary is not None:
            temporary.cleanup()
    return 1


def _strict_identity(
    value: Mapping[str, object],
    context: str,
    *,
    allow_legacy: bool = False,
) -> dict[str, str]:
    if set(value) != _IDENTITY_FIELDS or not all(
        isinstance(value[field], str) for field in _IDENTITY_FIELDS
    ):
        raise ExecutorError(f"{context} release identity is malformed")
    identity = {field: str(value[field]) for field in _IDENTITY_FIELDS}
    tag_match = _RELEASE_TAG.fullmatch(identity["tag"])
    legacy_match = (
        _LEGACY_RELEASE_TAG.fullmatch(identity["tag"]) if allow_legacy else None
    )
    version = (
        tag_match.group("version")
        if tag_match is not None
        else legacy_match.group("version") if legacy_match is not None else None
    )
    if (
        any(_HEX_40.fullmatch(identity[field]) is None for field in ("tag_object", "commit", "tree"))
        or version is None
        or version != identity["version"]
        or (
            tag_match is not None
            and not identity["commit"].startswith(tag_match.group("short"))
        )
        or identity["channel"] != "stable"
    ):
        raise ExecutorError(f"{context} release identity is malformed")
    return identity


def _git_show(repo_root: Path, commit: str, relative: str) -> bytes:
    result = subprocess.run(
        [
            str(dex_update_bridge._trusted_git_binary()),
            "--no-replace-objects",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "credential.helper=",
            "-C",
            str(repo_root),
            "show",
            f"{commit}:{relative}",
        ],
        capture_output=True,
        env=dex_update_bridge._bridge_environment(),
        timeout=90,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise ExecutorError(
            detail or f"released executor source is unavailable: {relative}"
        )
    if len(result.stdout) > 16 * 1024 * 1024:
        raise ExecutorError(f"released source exceeds the executor bound: {relative}")
    return result.stdout


def _verify_released_executor(
    repo_root: Path,
    source_commit: str,
    protocol: UpdateJourneyProtocol,
    foundation: Mapping[str, str],
) -> dict[str, object]:
    if _HEX_40.fullmatch(source_commit) is None:
        raise ExecutorError("released executor source commit is malformed")
    if protocol.foundation != dict(foundation):
        raise ExecutorError("journey protocol names a different foundation release")
    artifacts = (
        (
            "fleet runner",
            protocol.runner,
            PROJECT_ROOT / protocol.runner.source_path,
        ),
        ("executor", protocol.executor, Path(__file__).resolve()),
        (
            "foundation bridge",
            protocol.bridge.artifact,
            Path(dex_update_bridge.__file__).resolve(),
        ),
    )
    evidence: dict[str, object] = {"source_commit": source_commit}
    for label, artifact, running_path in artifacts:
        running = running_path.read_bytes()
        released = _git_show(repo_root, source_commit, artifact.source_path)
        digest = hashlib.sha256(running).hexdigest()
        if digest != artifact.sha256 or running != released:
            raise ExecutorError(
                f"running {label} bytes do not match the released protocol source"
            )
        evidence[label.replace(" ", "_")] = {
            "source_path": artifact.source_path,
            "sha256": digest,
        }
    return evidence


def _write_json(path: Path, value: object) -> None:
    content = (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        view = memoryview(content)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _hash_user_owned(vault: Path, relatives: Sequence[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative in relatives:
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ExecutorError(f"user-owned evidence path is unsafe: {relative}")
        path = vault / candidate
        if path.is_symlink() or not path.is_file():
            raise ExecutorError(f"user-owned evidence file is missing: {relative}")
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not hashes:
        raise ExecutorError("journey has no user-owned hash evidence")
    return hashes


def _doctor_healthy(report: Mapping[str, object]) -> bool:
    checks = report.get("checks")
    return (
        isinstance(checks, list)
        and bool(checks)
        and all(
            isinstance(check, Mapping) and check.get("verdict") in {"OK", "OFF"}
            for check in checks
        )
    )


def _smoke_healthy(report: Mapping[str, object]) -> bool:
    journeys = report.get("journeys")
    summary = report.get("summary")
    return (
        isinstance(journeys, list)
        and bool(journeys)
        and all(
            isinstance(journey, Mapping) and journey.get("verdict") in {"OK", "OFF"}
            for journey in journeys
        )
        and isinstance(summary, Mapping)
        and summary.get("broken") == 0
        and summary.get("unknown") == 0
    )


def _transaction_receipt(value: Mapping[str, object], context: str) -> dict[str, object]:
    receipt = value.get("receipt")
    if (
        not isinstance(receipt, Mapping)
        or not isinstance(receipt.get("transaction_id"), str)
        or not receipt["transaction_id"]
    ):
        raise ExecutorError(f"{context} did not return a lifecycle transaction receipt")
    return dict(value)


def _contains_transaction_receipt(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    if isinstance(value.get("transaction_id"), str) and value["transaction_id"]:
        return True
    return any(
        _contains_transaction_receipt(nested)
        for nested in value.values()
        if isinstance(nested, Mapping)
    )


def _validate_bridge_result(
    value: Mapping[str, object],
    foundation: Mapping[str, str],
    approval_count: int,
) -> dict[str, object]:
    if set(value) != {"foundation", "topology_receipt", "delivery_receipt"}:
        raise ExecutorError("foundation bridge returned malformed evidence")
    if value["foundation"] != foundation:
        raise ExecutorError("foundation bridge returned a different release identity")
    delivery = value["delivery_receipt"]
    already_installed = {"skipped": "foundation-already-installed"}
    completed = (
        value["topology_receipt"] == already_installed
        and delivery == already_installed
    )
    if not _contains_transaction_receipt(delivery) and not completed:
        raise ExecutorError(
            "foundation bridge did not return a lifecycle transaction receipt"
        )
    if completed and approval_count != 0:
        raise ExecutorError("completed foundation bridge requested an approval")
    if not completed and approval_count == 0:
        raise ExecutorError("foundation delivery completed without an approval")
    return dict(value)


def _artifact_index(
    evidence_root: Path,
    artifacts: Mapping[str, Path],
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for name, path in artifacts.items():
        if path.is_symlink() or not path.is_file() or path.parent != evidence_root:
            raise ExecutorError(f"executor evidence artifact is missing or unsafe: {name}")
        result[name] = {
            "path": f"{evidence_root.name}/{path.name}",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return result


def _execute_journey_with_runtime(
    *,
    repo_root: Path,
    source_commit: str,
    vault_root: Path,
    evidence_root: Path,
    starting_release: Mapping[str, object],
    foundation_release: Mapping[str, object],
    follow_up_release: Mapping[str, object],
    protocol: UpdateJourneyProtocol,
    historic_surface: Mapping[str, object],
    foundation_surface: Mapping[str, object],
    user_owned_paths: Sequence[str],
    platform: str,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
    _runtime: JourneyRuntime,
) -> dict[str, object]:
    """Execute and own one closed two-hop journey in the current process."""

    if platform not in protocol.platforms:
        raise ExecutorError(f"journey platform is not declared by the protocol: {platform}")
    start = _strict_identity(starting_release, "starting", allow_legacy=True)
    foundation = _strict_identity(foundation_release, "foundation")
    follow_up = _strict_identity(follow_up_release, "follow-up")
    if foundation == follow_up:
        raise ExecutorError("foundation and follow-up releases must be different")
    executor_identity = _verify_released_executor(
        repo_root.resolve(),
        source_commit,
        protocol,
        foundation,
    )
    if evidence_root.exists():
        raise ExecutorError("journey evidence directory must be empty")
    evidence_root.mkdir(parents=True, mode=0o700)
    vault = vault_root.resolve(strict=True)
    before = _hash_user_owned(vault, user_owned_paths)
    if historic_surface.get("release") != start:
        raise ExecutorError("historic update surface is not bound to the starting release")
    if foundation_surface.get("release") != foundation:
        raise ExecutorError("foundation update surface is not bound to the foundation release")

    bridge_approvals: list[dict[str, str]] = []

    def bridge_input(prompt: str) -> str:
        answer = input_fn(prompt)
        bridge_approvals.append({"prompt": prompt, "answer": answer})
        if (
            answer != protocol.bridge.approval_word
            or len(bridge_approvals) > protocol.bridge.approval_count
        ):
            raise ExecutorError("foundation bridge approval was not exact")
        return answer

    bridge_response = dict(
        _runtime.bridge_to_foundation(
            vault,
            foundation,
            input_fn=bridge_input,
            output_fn=output_fn,
        )
    )
    if len(bridge_approvals) > protocol.bridge.approval_count:
        raise ExecutorError("foundation bridge requested too many approvals")
    bridge_result = _validate_bridge_result(
        bridge_response,
        foundation,
        len(bridge_approvals),
    )
    if _runtime.installed_release(vault) != foundation["commit"]:
        raise ExecutorError("foundation release was not installed exactly")
    after_foundation = _hash_user_owned(vault, user_owned_paths)
    if after_foundation != before:
        raise ExecutorError("user-owned content changed during foundation delivery")
    foundation_doctor = dict(_runtime.doctor(vault))
    if not _doctor_healthy(foundation_doctor):
        raise ExecutorError("foundation Doctor is unhealthy or incomplete")
    after_foundation = _hash_user_owned(vault, user_owned_paths)
    if after_foundation != before:
        raise ExecutorError("user-owned content changed during foundation health proof")

    delivered = dict(_runtime.deliver_latest_release(vault))
    if (
        delivered.get("status") != "delivered"
        or delivered.get("release") != follow_up
    ):
        raise ExecutorError("lifecycle delivery did not prove the requested follow-up release")
    preview_response = dict(
        _runtime.build_and_preview_delivered_release(vault, follow_up)
    )
    preview = preview_response.get("preview")
    approval_token = preview_response.get("approval_token")
    if not isinstance(preview, Mapping) or not isinstance(approval_token, str) or not approval_token:
        raise ExecutorError("follow-up lifecycle preview is incomplete")
    output_fn(json.dumps(preview, indent=2, sort_keys=True))
    follow_prompt = (
        f"Dex will install verified follow-up v{follow_up['version']}. "
        f"Type {protocol.follow_up.approval_word} to continue: "
    )
    follow_answer = input_fn(follow_prompt)
    if follow_answer != protocol.follow_up.approval_word:
        raise ExecutorError("follow-up lifecycle preview was not approved exactly")
    follow_receipt = _transaction_receipt(
        dict(
            _runtime.execute_approved_delivered_release(
                vault,
                preview,
                approval_token,
            )
        ),
        "follow-up lifecycle execution",
    )
    if (
        follow_receipt.get("release") != follow_up
        or _runtime.installed_release(vault) != follow_up["commit"]
    ):
        raise ExecutorError("follow-up release was not installed exactly")
    after_follow_up = _hash_user_owned(vault, user_owned_paths)
    if after_follow_up != before:
        raise ExecutorError("user-owned content changed during follow-up delivery")
    follow_doctor = dict(_runtime.doctor(vault))
    if not _doctor_healthy(follow_doctor):
        raise ExecutorError("follow-up Doctor is unhealthy or incomplete")
    smoke_report = dict(_runtime.smoke(vault))
    if not _smoke_healthy(smoke_report):
        raise ExecutorError("follow-up smoke proof is unhealthy or incomplete")
    after_follow_up = _hash_user_owned(vault, user_owned_paths)
    if after_follow_up != before:
        raise ExecutorError("user-owned content changed during follow-up health proof")

    historic_surface_path = evidence_root / "historic-update-surface.json"
    foundation_surface_path = evidence_root / "foundation-update-surface.json"
    foundation_receipt_path = evidence_root / "foundation-receipt.json"
    follow_receipt_path = evidence_root / "follow-up-receipt.json"
    foundation_doctor_path = evidence_root / "foundation-doctor.json"
    follow_doctor_path = evidence_root / "follow-up-doctor.json"
    smoke_path = evidence_root / "follow-up-smoke.json"
    transcript_path = evidence_root / "journey-transcript.json"
    for path, value in (
        (historic_surface_path, dict(historic_surface)),
        (foundation_surface_path, dict(foundation_surface)),
        (
            foundation_receipt_path,
            {"release": foundation, "receipt": bridge_result},
        ),
        (follow_receipt_path, {"release": follow_up, "receipt": follow_receipt}),
        (foundation_doctor_path, foundation_doctor),
        (follow_doctor_path, follow_doctor),
        (
            smoke_path,
            {"status": "OK", "platform": platform, "report": smoke_report},
        ),
    ):
        _write_json(path, value)

    preview_sha256 = hashlib.sha256(
        (json.dumps(dict(preview), sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    events = [
        {
            "id": "historic-update-surface",
            "command": ["git", "show", f"{start['tag']}:.claude/skills/dex-update/SKILL.md"],
            "release": start,
            "skill_sha256": historic_surface.get("skill_sha256"),
            "rescue_sha256": historic_surface.get("rescue_sha256"),
        },
        {
            "id": "historic-route-refusal",
            "command": [protocol.executor.source_path, "classify-historic-route"],
            "release": start,
            "machine_executable": historic_surface.get("machine_executable"),
        },
        {
            "id": "bridge-foundation",
            "command": [protocol.executor.source_path, protocol.bridge.adapter],
            "release": foundation,
            "approval_count": len(bridge_approvals),
            "approvals": bridge_approvals,
        },
        {
            "id": "foundation-update-surface",
            "command": ["git", "show", f"{foundation['tag']}:.claude/skills/dex-update/SKILL.md"],
            "release": foundation,
            "skill_sha256": foundation_surface.get("skill_sha256"),
            "rescue_sha256": foundation_surface.get("rescue_sha256"),
        },
        {
            "id": "foundation-preview",
            "command": list(protocol.follow_up.operations[:2]),
            "from_release": foundation,
            "target_release": follow_up,
            "preview_sha256": preview_sha256,
        },
        {
            "id": "foundation-approval",
            "command": [protocol.executor.source_path, "approve-follow-up"],
            "target_release": follow_up,
            "answer": follow_answer,
        },
        {
            "id": "foundation-receipt",
            "command": [protocol.follow_up.operations[2]],
            "release": follow_up,
        },
        {
            "id": "follow-up-installed",
            "command": [protocol.executor.source_path, "verify-installed-release"],
            "release": follow_up,
        },
        {
            "id": "follow-up-doctor",
            "command": [protocol.executor.source_path, "doctor"],
        },
        {
            "id": "follow-up-smoke",
            "command": [protocol.executor.source_path, "smoke"],
            "platform": platform,
        },
    ]
    if tuple(str(event["id"]) for event in events) != protocol.evidence:
        raise ExecutorError("executor evidence order does not match the closed protocol")
    _write_json(transcript_path, {"events": events})

    artifacts = {
        "transcript": transcript_path,
        "historic_update_surface": historic_surface_path,
        "foundation_update_surface": foundation_surface_path,
        "foundation_receipt": foundation_receipt_path,
        "follow_up_receipt": follow_receipt_path,
        "foundation_doctor": foundation_doctor_path,
        "follow_up_doctor": follow_doctor_path,
        "follow_up_smoke": smoke_path,
    }
    manifest = {
        "schema_version": 1,
        "executor": executor_identity,
        "starting_release": start,
        "foundation_release": foundation,
        "follow_up_release": follow_up,
        "events": events,
        "artifacts": _artifact_index(evidence_root, artifacts),
    }
    manifest_path = evidence_root / "evidence-manifest.json"
    _write_json(manifest_path, manifest)
    case = {
        "starting_tag": start["tag"],
        "reached_foundation": True,
        "reached_follow_up": True,
        "foundation_doctor_healthy": True,
        "follow_up_doctor_healthy": True,
        "user_hashes_before": before,
        "user_hashes_after_foundation": after_foundation,
        "user_hashes_after_follow_up": after_follow_up,
        "transcript_path": f"{evidence_root.name}/{transcript_path.name}",
        "foundation_receipt_path": f"{evidence_root.name}/{foundation_receipt_path.name}",
        "follow_up_receipt_path": f"{evidence_root.name}/{follow_receipt_path.name}",
        "foundation_doctor_path": f"{evidence_root.name}/{foundation_doctor_path.name}",
        "follow_up_doctor_path": f"{evidence_root.name}/{follow_doctor_path.name}",
        "follow_up_smoke_path": f"{evidence_root.name}/{smoke_path.name}",
        "platform": platform,
        "evidence_manifest_path": f"{evidence_root.name}/{manifest_path.name}",
        "evidence_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }
    _write_json(evidence_root / "journey-result.json", case)
    return case


def _executor_boundary():
    """Create the sole production entrypoint without exporting a proof mint."""

    authority = object()
    production_runtime_type = _ProductionRuntime
    execute_with_runtime = _execute_journey_with_runtime
    production_methods = {
        name: getattr(production_runtime_type, name)
        for name in (
            "bridge_to_foundation",
            "installed_release",
            "doctor",
            "deliver_latest_release",
            "build_and_preview_delivered_release",
            "execute_approved_delivered_release",
            "smoke",
            "close",
        )
    }

    def execute_journey(
        *,
        repo_root: Path,
        source_commit: str,
        vault_root: Path,
        evidence_root: Path,
        starting_release: Mapping[str, object],
        foundation_release: Mapping[str, object],
        follow_up_release: Mapping[str, object],
        protocol: UpdateJourneyProtocol,
        historic_surface: Mapping[str, object],
        foundation_surface: Mapping[str, object],
        user_owned_paths: Sequence[str],
        platform: str,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
        _runtime: JourneyRuntime | None = None,
    ) -> ExecutorRun:
        """Execute one released journey and retain production authority here."""

        production_owned = _runtime is None
        runtime = production_runtime_type() if production_owned else _runtime
        assert runtime is not None
        try:
            case = execute_with_runtime(
                repo_root=repo_root,
                source_commit=source_commit,
                vault_root=vault_root,
                evidence_root=evidence_root,
                starting_release=starting_release,
                foundation_release=foundation_release,
                follow_up_release=follow_up_release,
                protocol=protocol,
                historic_surface=historic_surface,
                foundation_surface=foundation_surface,
                user_owned_paths=user_owned_paths,
                platform=platform,
                input_fn=input_fn,
                output_fn=output_fn,
                _runtime=runtime,
            )
        finally:
            if production_owned:
                runtime.close()  # type: ignore[attr-defined]
        case_json = json.dumps(
            case,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        run = object.__new__(ExecutorRun)
        object.__setattr__(run, "_case_json", case_json)
        production_intact = (
            production_owned
            and type(runtime) is production_runtime_type
            and all(
                getattr(production_runtime_type, name) is function
                for name, function in production_methods.items()
            )
        )
        seal = (
            (authority, hashlib.sha256(case_json).digest())
            if production_intact
            else None
        )
        object.__setattr__(run, "_authority", seal)
        return run

    def is_authoritative_executor_run(value: object) -> bool:
        if not isinstance(value, ExecutorRun):
            return False
        seal = getattr(value, "_authority", None)
        case_json = getattr(value, "_case_json", None)
        return (
            isinstance(seal, tuple)
            and len(seal) == 2
            and seal[0] is authority
            and isinstance(seal[1], bytes)
            and isinstance(case_json, bytes)
            and seal[1] == hashlib.sha256(case_json).digest()
        )

    return execute_journey, is_authoritative_executor_run


execute_journey, is_authoritative_executor_run = _executor_boundary()
del _executor_boundary


__all__ = [
    "EXECUTOR_INTERFACE_VERSION",
    "ExecutorError",
    "ExecutorRun",
    "JourneyRuntime",
    "execute_journey",
    "is_authoritative_executor_run",
]


if __name__ == "__main__":
    valid = (
        len(sys.argv) == 4
        and sys.argv[1:3] == ["_runtime-server", "--vault"]
    ) or (
        len(sys.argv) == 6
        and sys.argv[1:3] == ["_runtime-server", "--vault"]
        and sys.argv[4] == "--foundation-cache"
    )
    if not valid:
        raise SystemExit("released journey executor has no standalone interface")
    try:
        raise SystemExit(
            _runtime_server(
                Path(sys.argv[3]),
                foundation_cache=(
                    Path(sys.argv[5]) if len(sys.argv) == 6 else None
                ),
            )
        )
    except Exception as error:  # noqa: BLE001
        raise SystemExit(f"fixture lifecycle runtime stopped safely: {error}") from error
