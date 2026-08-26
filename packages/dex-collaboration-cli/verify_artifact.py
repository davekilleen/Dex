#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

from artifact_support import (
    ArtifactError,
    canonical_json_bytes,
    host_arch,
    host_platform,
    native_dependencies,
    native_identity,
    require_mode,
    safe_relative_files,
    sha256_file,
)

EXPECTED_COMMANDS = ["identity create", "rooms list", "rooms create", "post", "timeline"]
MAX_ARCHIVE_FILES = 64
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024


def _read_sums(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ArtifactError("SHA256SUMS is empty")
    for line in lines:
        if len(line) < 67 or line[64:66] != "  ":
            raise ArtifactError("SHA256SUMS is malformed")
        checksum, relative = line[:64], line[66:]
        if len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
            raise ArtifactError("SHA256SUMS contains an invalid checksum")
        if not relative or relative.startswith("/") or ".." in Path(relative).parts or relative in result:
            raise ArtifactError("SHA256SUMS contains an invalid path")
        result[relative] = checksum
    canonical = "".join(f"{result[key]}  {key}\n" for key in sorted(result))
    if canonical != path.read_text(encoding="utf-8"):
        raise ArtifactError("SHA256SUMS is not canonical")
    return result


def verify(root: Path, expected_platform: str, expected_arch: str) -> dict[str, str]:
    if not root.is_dir() or root.is_symlink():
        raise ArtifactError("artifact must be an extracted regular directory")
    manifest_path = root / "manifest.json"
    sums_path = root / "SHA256SUMS"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ArtifactError("manifest.json is missing")
    if not sums_path.is_file() or sums_path.is_symlink():
        raise ArtifactError("SHA256SUMS is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest_path.read_bytes() != canonical_json_bytes(manifest):
        raise ArtifactError("manifest.json is not canonical")
    if manifest.get("schema") != "dex-collaboration-cli-artifact/1":
        raise ArtifactError("artifact manifest schema is unsupported")
    if manifest.get("artifact_id") != "dex-core-collaboration-cli":
        raise ArtifactError("artifact id is invalid")
    if manifest.get("platform") != expected_platform or manifest.get("architecture") != expected_arch:
        raise ArtifactError(
            f"artifact targets {manifest.get('platform')}/{manifest.get('architecture')}, "
            f"expected {expected_platform}/{expected_arch}"
        )
    if manifest.get("commands") != EXPECTED_COMMANDS:
        raise ArtifactError("artifact command contract is invalid")
    relay = manifest.get("relay")
    if not isinstance(relay, dict) or relay.get("environment") != "BUZZ_RELAY_URL" or not relay.get("default"):
        raise ArtifactError("artifact relay contract is invalid")

    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ArtifactError("artifact file manifest is invalid")
    entry_by_path: dict[str, dict[str, object]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ArtifactError("artifact file entry is invalid")
        relative = str(entry["path"])
        if relative.startswith("/") or ".." in Path(relative).parts or relative in entry_by_path:
            raise ArtifactError("artifact file entry path is invalid")
        entry_by_path[relative] = entry
    required_payload = {
        "bin/core",
        "libexec/buzz",
        "libexec/buzz-admin",
        "LICENSES/Buzz-LICENSE",
    }
    if set(entry_by_path) != required_payload:
        raise ArtifactError("artifact payload set is incomplete or contains extras")

    actual_files = {path.as_posix() for path in safe_relative_files(root)}
    expected_files = required_payload | {"manifest.json", "SHA256SUMS"}
    if actual_files != expected_files:
        raise ArtifactError("artifact directory contains missing or unexpected files")
    actual_directories = {
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_dir()
    }
    if actual_directories != {"bin", "libexec", "LICENSES"}:
        raise ArtifactError("artifact directory contains missing or unexpected directories")

    sums = _read_sums(sums_path)
    if set(sums) != required_payload | {"manifest.json"}:
        raise ArtifactError("SHA256SUMS payload set is incomplete or contains extras")
    for relative, expected_hash in sums.items():
        if sha256_file(root / relative) != expected_hash:
            raise ArtifactError(f"SHA-256 mismatch: {relative}")
    for relative, entry in entry_by_path.items():
        path = root / relative
        expected_mode = int(str(entry.get("mode", "")), 8)
        require_mode(path, expected_mode)
        if entry.get("sha256") != sha256_file(path):
            raise ArtifactError(f"manifest SHA-256 mismatch: {relative}")

    core = root / "bin" / "core"
    require_mode(core, 0o755)
    for relative in ("libexec/buzz", "libexec/buzz-admin"):
        runtime = root / relative
        require_mode(runtime, 0o755)
        binary_format, binary_platform, binary_arch = native_identity(runtime)
        entry = entry_by_path[relative]
        if (binary_platform, binary_arch) != (expected_platform, expected_arch):
            raise ArtifactError(f"native runtime target mismatch: {relative}")
        if entry.get("format") != binary_format or entry.get("architecture") != binary_arch:
            raise ArtifactError(f"native runtime manifest mismatch: {relative}")
        dependencies = native_dependencies(runtime, expected_platform)
        if entry.get("dependencies") != dependencies:
            raise ArtifactError(f"native runtime dependency manifest mismatch: {relative}")

    with tempfile.TemporaryDirectory() as temporary:
        environment = {
            "PATH": "",
            "HOME": str(Path(temporary) / "home"),
            "DEX_STUDIO_HOME": str(Path(temporary) / "studio"),
        }
        result = subprocess.run(
            [core, "--artifact-info"],
            env=environment,
            capture_output=True,
            text=True,
        )
    if result.returncode != 0 or result.stderr:
        raise ArtifactError("packaged Core executable is not runnable with an empty caller PATH")
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ArtifactError("packaged Core executable did not emit JSON") from error
    if info.get("schema") != "dex-collaboration-cli/1" or info.get("commands") != EXPECTED_COMMANDS:
        raise ArtifactError("packaged Core executable contract does not match its manifest")

    sources = manifest.get("sources")
    if (
        not isinstance(sources, dict)
        or sources.get("buzz_revision") != "b2ac66cde81df7ce1afc50016e1571cb6e8b7779"
        or sources.get("buzz_tree_clean") is not True
        or sources.get("cargo_target_fresh") is not True
        or sources.get("hermit_state_isolated") is not True
    ):
        raise ArtifactError("pinned Buzz source identity is missing")
    toolchain = sources.get("toolchain")
    if (
        not isinstance(toolchain, dict)
        or not str(toolchain.get("cargo", "")).startswith("cargo 1.95.0 ")
        or not str(toolchain.get("rustc", "")).startswith("rustc 1.95.0 ")
    ):
        raise ArtifactError("pinned Rust toolchain identity is missing")
    return {
        "status": "verified",
        "artifact": str(root.resolve()),
        "platform": expected_platform,
        "architecture": expected_arch,
        "buzz_revision": str(sources["buzz_revision"]),
    }


def _verify_archive_checksum(archive: Path) -> str:
    if not archive.is_file() or archive.is_symlink():
        raise ArtifactError("artifact archive must be a regular file")
    sidecar = Path(f"{archive}.sha256")
    if not sidecar.is_file() or sidecar.is_symlink():
        raise ArtifactError("artifact archive SHA-256 sidecar is missing")
    expected_line = sidecar.read_text(encoding="utf-8")
    parts = expected_line.rstrip("\n").split("  ", 1)
    if (
        len(parts) != 2
        or expected_line != f"{parts[0]}  {parts[1]}\n"
        or len(parts[0]) != 64
        or any(character not in "0123456789abcdef" for character in parts[0])
        or parts[1] != archive.name
    ):
        raise ArtifactError("artifact archive SHA-256 sidecar is malformed")
    actual = sha256_file(archive)
    if actual != parts[0]:
        raise ArtifactError("archive SHA-256 mismatch")
    return actual


def _extract_archive_safely(archive: Path, destination: Path) -> Path:
    roots: set[str] = set()
    members: set[str] = set()
    extracted_bytes = 0
    extracted_files = 0
    with tarfile.open(archive, mode="r:gz") as bundle:
        for member in bundle:
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                raise ArtifactError("artifact archive contains an unsafe path")
            if member.name in members:
                raise ArtifactError("artifact archive contains a duplicate path")
            members.add(member.name)
            roots.add(relative.parts[0])
            if not member.isfile():
                raise ArtifactError("artifact archive contains a non-regular entry")
            extracted_files += 1
            extracted_bytes += member.size
            if extracted_files > MAX_ARCHIVE_FILES or extracted_bytes > MAX_ARCHIVE_BYTES:
                raise ArtifactError("artifact archive exceeds the extraction limit")
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                raise ArtifactError("artifact archive entry could not be read")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(member.mode & 0o777)
    if len(roots) != 1:
        raise ArtifactError("artifact archive must contain exactly one root directory")
    root = destination / next(iter(roots))
    if not root.is_dir():
        raise ArtifactError("artifact archive root directory is missing")
    return root


def verify_input(path: Path, expected_platform: str, expected_arch: str) -> dict[str, str]:
    if path.is_dir():
        return verify(path, expected_platform, expected_arch)
    archive_checksum = _verify_archive_checksum(path)
    with tempfile.TemporaryDirectory() as temporary:
        root = _extract_archive_safely(path, Path(temporary))
        report = verify(root, expected_platform, expected_arch)
    report.update(
        {
            "artifact": str(path.resolve()),
            "artifact_kind": "archive",
            "archive_sha256": archive_checksum,
        }
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--expect-platform", default=None)
    parser.add_argument("--expect-arch", default=None)
    args = parser.parse_args(argv)
    try:
        report = verify_input(
            args.artifact,
            args.expect_platform or host_platform(),
            args.expect_arch or host_arch(),
        )
        print(json.dumps(report, separators=(",", ":")))
        return 0
    except (ArtifactError, KeyError, OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as error:
        print(json.dumps({"error": str(error)}, separators=(",", ":")), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
