#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from artifact_support import (
    ArtifactError,
    canonical_json_bytes,
    host_arch,
    host_platform,
    native_dependencies,
    native_identity,
    require_regular_executable,
    sha256_file,
)

PACKAGE_ROOT = Path(__file__).resolve().parent


class BuildError(ArtifactError):
    pass


def _bounded_cargo_diagnostic(stderr: str, source: Path, target: Path) -> str:
    sanitized = stderr.replace(str(source.resolve()), "<buzz-source>")
    sanitized = sanitized.replace(str(target.resolve()), "<cargo-target>")
    user_home = str(Path.home())
    if user_home:
        sanitized = sanitized.replace(user_home, "<user-home>")
    sanitized = re.sub(
        r"(?i)\b([a-z0-9_]*(?:token|secret|password|private[_-]?key)[a-z0-9_]*)\s*[=:]\s*\S+",
        lambda match: f"{match.group(1)}=[redacted]",
        sanitized,
    )
    lines = sanitized.splitlines()
    first_error = next(
        (index for index, line in enumerate(lines) if re.match(r"^\s*(error(?:\[[^]]+\])?:|Caused by:)", line)),
        max(0, len(lines) - 12),
    )
    start = max(0, first_error - 2)
    selected = lines[start : start + 24]
    diagnostic = "\n".join(selected).strip()
    if len(diagnostic) > 4096:
        diagnostic = diagnostic[:4083] + "\n[truncated]"
    return diagnostic or "Cargo failed without diagnostic output"


def _git_head(source: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise BuildError("Buzz source is not a readable Git checkout")
    return result.stdout.strip()


def _require_clean_source(source: Path) -> None:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        label = "Dex" if source.resolve() == PACKAGE_ROOT.parents[1].resolve() else "Buzz"
        raise BuildError(f"{label} source cleanliness could not be verified")
    if result.stdout:
        label = "Dex" if source.resolve() == PACKAGE_ROOT.parents[1].resolve() else "Buzz"
        raise BuildError(f"{label} source checkout is dirty; artifact provenance is not exact")


def _copy_payload(source: Path, destination: Path, mode: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(mode)


def _source_epoch(repo: Path) -> int:
    result = subprocess.run(
        ["git", "-C", str(repo), "show", "-s", "--format=%ct", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip().isdigit():
        raise BuildError("Dex source timestamp could not be read")
    return int(result.stdout.strip())


def _toolchain_identity(source: Path, environment: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in ("cargo", "rustc"):
        executable = source / "bin" / name
        completed = subprocess.run(
            [executable, "--version", "--verbose"],
            cwd=source,
            env=environment,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise BuildError(f"pinned Buzz {name} launcher failed")
        first_line = completed.stdout.splitlines()[0] if completed.stdout else ""
        if not first_line.startswith(f"{name} 1.95.0 "):
            raise BuildError(f"pinned Buzz {name} is not version 1.95.0")
        result[name] = first_line
    return result


def _sanitized_build_environment(
    target_dir: Path,
    *,
    source_environment: dict[str, str] | None = None,
    source: Path | None = None,
) -> dict[str, str]:
    inherited = os.environ if source_environment is None else source_environment
    allowed = (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    )
    environment = {key: inherited[key] for key in allowed if inherited.get(key)}
    trusted_bin = f"{source / 'bin'}:" if source is not None else ""
    build_root = target_dir.parent
    hermit_home = build_root / ".hermit-home"
    hermit_state = build_root / ".hermit-state"
    hermit_executable = hermit_state / "pkg" / "hermit@stable" / "hermit"
    xdg_cache = build_root / ".xdg-cache"
    temporary = build_root / ".tmp"
    for directory in (hermit_home, hermit_state, xdg_cache, temporary):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
    environment.update(
        {
            "PATH": f"{trusted_bin}/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(hermit_home),
            "XDG_CACHE_HOME": str(xdg_cache),
            "TMPDIR": str(temporary),
            "HERMIT_STATE_DIR": str(hermit_state),
            "HERMIT_EXE": str(hermit_executable),
            "CARGO_TARGET_DIR": str(target_dir),
            "CARGO_TERM_COLOR": "never",
        }
    )
    return environment


def _build_pinned_runtime(
    args: argparse.Namespace,
    build_root: Path,
) -> tuple[Path, Path, dict[str, str]]:
    cargo = args.buzz_source / "bin" / "cargo"
    target_dir = build_root / ".cargo-target"
    target_dir.mkdir()
    environment = _sanitized_build_environment(target_dir, source=args.buzz_source)
    toolchain = _toolchain_identity(args.buzz_source, environment)
    result = subprocess.run(
        [
            str(cargo),
            "build",
            "--locked",
            "--release",
            "--jobs",
            str(args.jobs),
            "--package",
            "buzz-cli",
            "--package",
            "buzz-admin",
        ],
        cwd=args.buzz_source,
        env=environment,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = _bounded_cargo_diagnostic(result.stderr or result.stdout, args.buzz_source, target_dir)
        raise BuildError(f"pinned Buzz release build failed:\n{detail}")
    buzz = target_dir / "release" / "buzz"
    buzz_admin = target_dir / "release" / "buzz-admin"
    return buzz, buzz_admin, toolchain


def _write_deterministic_archive(artifact_dir: Path, archive: Path, epoch: int) -> None:
    with archive.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as tar:
                for path in sorted(artifact_dir.rglob("*"), key=lambda item: item.as_posix()):
                    if not path.is_file():
                        continue
                    relative = path.relative_to(artifact_dir.parent)
                    data = path.read_bytes()
                    info = tarfile.TarInfo(relative.as_posix())
                    info.size = len(data)
                    info.mode = path.stat().st_mode & 0o777
                    info.mtime = epoch
                    info.uid = 0
                    info.gid = 0
                    info.uname = "root"
                    info.gname = "root"
                    import io

                    tar.addfile(info, io.BytesIO(data))


def build(args: argparse.Namespace) -> dict[str, str]:
    if args.output.exists() and any(args.output.iterdir()):
        raise BuildError("artifact output directory must be empty")
    contract = json.loads((PACKAGE_ROOT / "contract.json").read_text(encoding="utf-8"))
    expected_revision = contract["buzz_revision"]
    actual_revision = _git_head(args.buzz_source)
    if actual_revision != expected_revision:
        raise BuildError(
            "runtime is not proven at the pinned Buzz revision "
            f"{expected_revision} (found {actual_revision or 'none'})"
        )
    _require_clean_source(args.buzz_source)
    dex_root = PACKAGE_ROOT.parents[1]
    _require_clean_source(dex_root)
    dex_revision = _git_head(dex_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix=".dex-core-build-",
        dir=args.output.parent,
    ) as temporary:
        build_root = Path(temporary)
        deliverables = build_root / "deliverables"
        deliverables.mkdir()
        buzz_bin, buzz_admin_bin, toolchain = _build_pinned_runtime(args, build_root)
        for path, label in (
            (buzz_bin, "Buzz client"),
            (buzz_admin_bin, "Buzz admin client"),
            (PACKAGE_ROOT / "src" / "core", "Core executable"),
        ):
            require_regular_executable(path, label)
        buzz_license = args.buzz_source / "LICENSE"
        if not buzz_license.is_file() or buzz_license.is_symlink():
            raise BuildError("pinned Buzz LICENSE is missing")

        platform_label = host_platform()
        architecture = host_arch()
        runtime_identities: dict[str, tuple[str, str, str]] = {}
        for name, path in (("buzz", buzz_bin), ("buzz-admin", buzz_admin_bin)):
            runtime_identities[name] = native_identity(path)
            _, runtime_platform, runtime_arch = runtime_identities[name]
            if (runtime_platform, runtime_arch) != (platform_label, architecture):
                raise BuildError(
                    f"{name} targets {runtime_platform}/{runtime_arch}, expected "
                    f"{platform_label}/{architecture}"
                )
            native_dependencies(path, platform_label)

        artifact_name = f"{contract['artifact_id']}-{platform_label}-{architecture}"
        artifact_dir = deliverables / artifact_name
        artifact_dir.mkdir()

        payload = (
            (PACKAGE_ROOT / "src" / "core", artifact_dir / "bin" / "core", 0o755),
            (buzz_bin, artifact_dir / "libexec" / "buzz", 0o755),
            (buzz_admin_bin, artifact_dir / "libexec" / "buzz-admin", 0o755),
            (buzz_license, artifact_dir / "LICENSES" / "Buzz-LICENSE", 0o644),
        )
        for source, destination, mode in payload:
            _copy_payload(source, destination, mode)

        files = []
        for _, destination, mode in payload:
            relative = destination.relative_to(artifact_dir).as_posix()
            entry: dict[str, object] = {
                "path": relative,
                "mode": f"{mode:04o}",
                "sha256": sha256_file(destination),
            }
            if relative.startswith("libexec/"):
                runtime_name = Path(relative).name
                binary_format, _, binary_arch = runtime_identities[runtime_name]
                entry.update(
                    {
                        "format": binary_format,
                        "architecture": binary_arch,
                        "dependencies": native_dependencies(destination, platform_label),
                    }
                )
            elif relative == "bin/core":
                entry["format"] = "bash"
            else:
                entry["format"] = "text"
            files.append(entry)

        manifest = {
            "schema": "dex-collaboration-cli-artifact/1",
            "artifact_id": contract["artifact_id"],
            "artifact_name": artifact_name,
            "platform": platform_label,
            "architecture": architecture,
            "commands": contract["commands"],
            "relay": contract["service_boundary"],
            "sources": {
                "buzz_repository": contract["buzz_repository"],
                "buzz_revision": expected_revision,
                "buzz_tree_clean": True,
                "cargo_target_fresh": True,
                "hermit_state_isolated": True,
                "dex_revision": dex_revision,
                "dex_tree_clean": True,
                "source_contract_sha256": sha256_file(PACKAGE_ROOT / "contract.json"),
                "toolchain": toolchain,
            },
            "files": sorted(files, key=lambda entry: str(entry["path"])),
        }
        manifest_path = artifact_dir / "manifest.json"
        manifest_path.write_bytes(canonical_json_bytes(manifest))
        manifest_path.chmod(0o644)

        checksum_paths = [destination.relative_to(artifact_dir) for _, destination, _ in payload]
        checksum_paths.append(Path("manifest.json"))
        sums = "".join(
            f"{sha256_file(artifact_dir / relative)}  {relative.as_posix()}\n"
            for relative in sorted(checksum_paths, key=lambda item: item.as_posix())
        )
        sums_path = artifact_dir / "SHA256SUMS"
        sums_path.write_text(sums, encoding="utf-8")
        sums_path.chmod(0o644)

        archive = deliverables / f"{artifact_name}.tar.gz"
        _write_deterministic_archive(artifact_dir, archive, _source_epoch(dex_root))
        archive_checksum = sha256_file(archive)
        checksum_file = Path(f"{archive}.sha256")
        checksum_file.write_text(f"{archive_checksum}  {archive.name}\n", encoding="utf-8")

        if args.output.exists():
            args.output.rmdir()
        deliverables.replace(args.output)

    artifact_dir = args.output / artifact_name
    archive = args.output / f"{artifact_name}.tar.gz"
    return {
        "artifact_dir": str(artifact_dir.resolve()),
        "archive": str(archive.resolve()),
        "archive_sha256": archive_checksum,
        "platform": platform_label,
        "architecture": architecture,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--buzz-source", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        args.buzz_source = args.buzz_source.resolve()
        args.output = args.output.resolve()
        if args.jobs < 1 or args.jobs > 9:
            raise BuildError("--jobs must be between 1 and 9")
        result = build(args)
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except (ArtifactError, KeyError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"error": str(error)}, separators=(",", ":")), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
