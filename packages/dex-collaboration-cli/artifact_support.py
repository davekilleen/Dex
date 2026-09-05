from __future__ import annotations

import hashlib
import os
import platform
import re
import stat
import struct
import subprocess
import sys
from pathlib import Path


class ArtifactError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def host_platform() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    raise ArtifactError(f"unsupported build platform: {sys.platform}")


def normalize_arch(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"x86_64", "amd64"}:
        return "x86_64"
    if normalized in {"arm64", "aarch64"}:
        return "arm64"
    raise ArtifactError(f"unsupported architecture: {value}")


def host_arch() -> str:
    return normalize_arch(platform.machine())


def executable_mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def require_regular_executable(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ArtifactError(f"{label} is missing: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ArtifactError(f"{label} must be a regular file")
    if metadata.st_mode & 0o111 == 0:
        raise ArtifactError(f"{label} is not executable")


def native_identity(path: Path) -> tuple[str, str, str]:
    data = path.read_bytes()[:4096]
    if data.startswith(b"\x7fELF"):
        if len(data) < 20:
            raise ArtifactError(f"native executable header is truncated: {path}")
        byte_order = "<" if data[5] == 1 else ">" if data[5] == 2 else ""
        if not byte_order:
            raise ArtifactError(f"native executable byte order is invalid: {path}")
        machine = struct.unpack(f"{byte_order}H", data[18:20])[0]
        arch = {62: "x86_64", 183: "arm64"}.get(machine)
        if not arch:
            raise ArtifactError(f"unsupported ELF architecture {machine}: {path}")
        return "elf", "linux", arch

    magic = data[:4]
    macho_orders = {
        b"\xcf\xfa\xed\xfe": "<",
        b"\xfe\xed\xfa\xcf": ">",
        b"\xce\xfa\xed\xfe": "<",
        b"\xfe\xed\xfa\xce": ">",
    }
    byte_order = macho_orders.get(magic)
    if byte_order:
        if len(data) < 8:
            raise ArtifactError(f"native executable header is truncated: {path}")
        cpu_type = struct.unpack(f"{byte_order}I", data[4:8])[0]
        arch = {0x01000007: "x86_64", 0x0100000C: "arm64"}.get(cpu_type)
        if not arch:
            raise ArtifactError(f"unsupported Mach-O architecture {cpu_type}: {path}")
        return "mach-o", "darwin", arch

    raise ArtifactError(f"runtime is not a supported native executable: {path}")


def native_dependencies(path: Path, platform_label: str) -> list[str]:
    if platform_label == "linux":
        result = subprocess.run(
            ["/usr/bin/readelf", "-d", path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ArtifactError(f"ELF dependency closure could not be read: {path.name}")
        if "(RPATH)" in result.stdout or "(RUNPATH)" in result.stdout:
            raise ArtifactError(f"native runtime has a non-baseline search path: {path.name}")
        dependencies = re.findall(r"\(NEEDED\).*Shared library: \[([^]]+)\]", result.stdout)
    elif platform_label == "darwin":
        result = subprocess.run(
            ["/usr/bin/otool", "-L", path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ArtifactError(f"Mach-O dependency closure could not be read: {path.name}")
        dependencies = [
            line.strip().split(" (", 1)[0]
            for line in result.stdout.splitlines()[1:]
            if line.strip()
        ]
    else:
        raise ArtifactError(f"unsupported dependency platform: {platform_label}")
    require_baseline_dependencies(platform_label, dependencies)
    return sorted(set(dependencies))


def require_baseline_dependencies(platform_label: str, dependencies: list[str]) -> None:
    if not dependencies:
        raise ArtifactError("native runtime dependency closure is empty")
    if platform_label == "linux":
        allowed = {
            "libc.so.6",
            "libdl.so.2",
            "libgcc_s.so.1",
            "libm.so.6",
            "libpthread.so.0",
            "libresolv.so.2",
            "librt.so.1",
            "libutil.so.1",
            "ld-linux-x86-64.so.2",
            "ld-linux-aarch64.so.1",
        }
        rejected = [dependency for dependency in dependencies if dependency not in allowed]
    elif platform_label == "darwin":
        rejected = [
            dependency
            for dependency in dependencies
            if not dependency.startswith("/usr/lib/")
            and not dependency.startswith("/System/Library/Frameworks/")
        ]
    else:
        raise ArtifactError(f"unsupported dependency platform: {platform_label}")
    if rejected:
        raise ArtifactError(f"native runtime has non-baseline dependencies: {', '.join(rejected)}")


def canonical_json_bytes(document: object) -> bytes:
    import json

    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def require_mode(path: Path, expected: int) -> None:
    actual = executable_mode(path)
    if actual != expected:
        raise ArtifactError(f"{path.name} mode is {actual:04o}, expected {expected:04o}")


def safe_relative_files(root: Path) -> list[Path]:
    result: list[Path] = []
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in directory_names:
            candidate = directory_path / name
            if candidate.is_symlink():
                raise ArtifactError(f"artifact contains a symlink: {candidate.relative_to(root)}")
        for name in file_names:
            candidate = directory_path / name
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise ArtifactError(f"artifact contains a non-regular file: {candidate.relative_to(root)}")
            result.append(candidate.relative_to(root))
    return sorted(result, key=lambda item: item.as_posix())
