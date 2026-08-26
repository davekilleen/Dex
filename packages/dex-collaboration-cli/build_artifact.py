#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

from artifact_support import (
    ArtifactError,
    canonical_json_bytes,
    host_arch,
    host_platform,
    native_identity,
    require_regular_executable,
    sha256_file,
)

PACKAGE_ROOT = Path(__file__).resolve().parent


class BuildError(ArtifactError):
    pass


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
        raise BuildError("Buzz source cleanliness could not be verified")
    if result.stdout:
        raise BuildError("Buzz source checkout is dirty; runtime provenance is not exact")


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


def _build_pinned_runtime(args: argparse.Namespace) -> tuple[Path, Path]:
    cargo = args.cargo
    if cargo is None:
        source_cargo = args.buzz_source / "bin" / "cargo"
        cargo = source_cargo if source_cargo.is_file() else Path("cargo")
    environment = None
    target_dir = args.cargo_target_dir
    if target_dir is not None:
        import os

        environment = {**os.environ, "CARGO_TARGET_DIR": str(target_dir)}
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
        detail = (result.stderr or result.stdout).strip().splitlines()
        final_line = detail[-1] if detail else "unknown Cargo failure"
        raise BuildError(f"pinned Buzz release build failed: {final_line}")
    target_root = target_dir if target_dir is not None else args.buzz_source / "target"
    buzz = target_root / "release" / "buzz"
    buzz_admin = target_root / "release" / "buzz-admin"
    return buzz, buzz_admin


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
    contract = json.loads((PACKAGE_ROOT / "contract.json").read_text(encoding="utf-8"))
    expected_revision = contract["buzz_revision"]
    actual_revision = _git_head(args.buzz_source)
    if actual_revision != expected_revision:
        raise BuildError(
            "runtime is not proven at the pinned Buzz revision "
            f"{expected_revision} (found {actual_revision or 'none'})"
        )
    _require_clean_source(args.buzz_source)

    buzz_bin, buzz_admin_bin = _build_pinned_runtime(args)
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

    args.output.mkdir(parents=True, exist_ok=True)
    artifact_name = f"{contract['artifact_id']}-{platform_label}-{architecture}"
    artifact_dir = args.output / artifact_name
    if artifact_dir.exists():
        raise BuildError(f"artifact output already exists: {artifact_dir}")
    artifact_dir.mkdir()

    payload = (
        (PACKAGE_ROOT / "src" / "core", artifact_dir / "bin" / "core", 0o755),
        (buzz_bin, artifact_dir / "libexec" / "buzz", 0o755),
        (buzz_admin_bin, artifact_dir / "libexec" / "buzz-admin", 0o755),
        (buzz_license, artifact_dir / "LICENSES" / "Buzz-LICENSE", 0o644),
    )
    for source, destination, mode in payload:
        _copy_payload(source, destination, mode)

    dex_root = PACKAGE_ROOT.parents[1]
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
            entry.update({"format": binary_format, "architecture": binary_arch})
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
            "dex_revision": _git_head(dex_root),
            "source_contract_sha256": sha256_file(PACKAGE_ROOT / "contract.json"),
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

    archive = args.output / f"{artifact_name}.tar.gz"
    _write_deterministic_archive(artifact_dir, archive, _source_epoch(dex_root))
    archive_checksum = sha256_file(archive)
    checksum_file = Path(f"{archive}.sha256")
    checksum_file.write_text(f"{archive_checksum}  {archive.name}\n", encoding="utf-8")
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
    parser.add_argument("--cargo", type=Path)
    parser.add_argument("--cargo-target-dir", type=Path)
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
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
