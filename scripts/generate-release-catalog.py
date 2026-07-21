#!/usr/bin/env python3
"""Generate the canonical B1 release catalog for one release-shaped tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Mapping

# Importing the B1 contract from a release-shaped staging tree must not add
# __pycache__ files after that tree's installed-files manifest is frozen.
sys.dont_write_bytecode = True

CATALOG_PATH = Path("System/.release-catalog.json")
CATALOG_SOURCE_DIR = Path("core/lifecycle/catalog")
MANIFEST_PATH = Path("System/.installed-files.manifest")
PACKAGE_PATH = Path("package.json")
SCHEMA_SOURCE = Path("core/lifecycle/schemas/release-catalog-v1.schema.json")
SCHEMA_DISTRIBUTION = Path("packages/dex-contracts/dist/release-catalog-v1.schema.json")
SOURCE_VERSION = 1
FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
SHIPPABLE_OWNERSHIP = frozenset({"brain", "seed", "generated"})


class CatalogGenerationError(RuntimeError):
    """The publisher-owned inputs cannot produce a proved catalog."""


def _closed_json(path: Path) -> object:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise CatalogGenerationError(f"{path} repeats JSON field {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                CatalogGenerationError(f"{path} contains non-finite JSON number {value}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CatalogGenerationError(f"cannot read {path}: {error}") from error


def _mapping(value: object, *, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise CatalogGenerationError(f"{context} must be a JSON object")
    return value


def _exact_fields(value: Mapping[str, object], expected: set[str], *, context: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        unknown = sorted(set(value) - expected)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise CatalogGenerationError(f"{context} fields are not closed ({'; '.join(details)})")


def _release_path(release_root: Path, raw_path: object, *, context: str) -> tuple[str, Path]:
    if not isinstance(raw_path, str) or not raw_path:
        raise CatalogGenerationError(f"{context} must be a non-empty path string")
    if "\\" in raw_path or "\n" in raw_path or "\r" in raw_path:
        raise CatalogGenerationError(f"{context} is not a canonical POSIX path: {raw_path!r}")
    candidate = release_root / raw_path
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(release_root):
        raise CatalogGenerationError(f"{context} escapes the release root: {raw_path!r}")
    if candidate.is_symlink() or not candidate.is_file():
        raise CatalogGenerationError(f"{context} is missing or not a regular file: {raw_path}")
    return raw_path, candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_items(release_root: Path, portable_contract: object) -> list[dict[str, object]]:
    source_dir = release_root / CATALOG_SOURCE_DIR
    if source_dir.is_symlink() or not source_dir.is_dir():
        raise CatalogGenerationError(f"publisher catalog source is missing: {CATALOG_SOURCE_DIR}")

    items: list[dict[str, object]] = []
    seen_item_sources: dict[str, Path] = {}
    for source_path in sorted(source_dir.glob("*.json")):
        raw = _mapping(_closed_json(source_path), context=str(source_path))
        _exact_fields(
            raw,
            {"catalog_source_version", "items"},
            context=str(source_path),
        )
        if raw["catalog_source_version"] != SOURCE_VERSION:
            raise CatalogGenerationError(f"{source_path} has an unsupported source version")
        source_items = raw["items"]
        if not isinstance(source_items, list):
            raise CatalogGenerationError(f"{source_path} items must be an array")
        for index, source_item in enumerate(source_items):
            context = f"{source_path} item {index}"
            item = _mapping(source_item, context=context)
            _exact_fields(
                item,
                {"id", "kind", "version", "files", "dependencies", "capabilities"},
                context=context,
            )
            item_id = item["id"]
            if isinstance(item_id, str):
                previous_source = seen_item_sources.get(item_id)
                if previous_source is not None:
                    raise CatalogGenerationError(
                        f"duplicate catalog item id {item_id!r} in "
                        f"{previous_source} and {source_path}"
                    )
                seen_item_sources[item_id] = source_path
            files = item["files"]
            if not isinstance(files, list) or not files:
                raise CatalogGenerationError(f"{context} files must be a non-empty array")
            generated_files = []
            for file_index, raw_file in enumerate(files):
                file_context = f"{context} file {file_index}"
                declared_file = _mapping(raw_file, context=file_context)
                _exact_fields(
                    declared_file,
                    {"path", "sha256", "byte_size"},
                    context=file_context,
                )
                path, absolute = _release_path(
                    release_root,
                    declared_file["path"],
                    context=f"{file_context} path",
                )
                declared_sha256 = declared_file["sha256"]
                if (
                    not isinstance(declared_sha256, str)
                    or HEX_SHA256.fullmatch(declared_sha256) is None
                ):
                    raise CatalogGenerationError(
                        f"{file_context} sha256 must be a lowercase sha256 digest"
                    )
                declared_size = declared_file["byte_size"]
                if type(declared_size) is not int or declared_size < 0:
                    raise CatalogGenerationError(
                        f"{file_context} byte_size must be a non-negative integer"
                    )
                actual_sha256 = _sha256(absolute)
                actual_size = absolute.stat().st_size
                if actual_sha256 != declared_sha256 or actual_size != declared_size:
                    raise CatalogGenerationError(
                        f"{file_context} does not match its declared sha256 or byte_size"
                    )
                try:
                    resolution = portable_contract.resolve(path)
                except portable_contract.ContractViolation as error:
                    raise CatalogGenerationError(
                        f"{context} file is unclassified by the ownership contract: {path}"
                    ) from error
                if resolution.denied or resolution.ownership not in SHIPPABLE_OWNERSHIP:
                    raise CatalogGenerationError(
                        f"{context} file is not release-shippable: {path} ({resolution.ownership})"
                    )
                generated_files.append(
                    {
                        "path": path,
                        "sha256": actual_sha256,
                        "ownership_class": resolution.ownership,
                    }
                )
            version = item["version"]
            items.append(
                {
                    "id": item_id,
                    "kind": item["kind"],
                    "version": version,
                    "files": generated_files,
                    "dependencies": item["dependencies"],
                    "capabilities": item["capabilities"],
                    "rewind": {
                        "acknowledgement_required": True,
                        "token": f"rewind:{item_id}@{version}",
                    },
                }
            )
    return items


def _source_commit(release_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(release_root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    if result.returncode != 0 or FULL_COMMIT.fullmatch(commit) is None:
        raise CatalogGenerationError("cannot resolve the full source commit from the release tree")
    return commit


def _package_version(release_root: Path) -> str:
    package = _mapping(_closed_json(release_root / PACKAGE_PATH), context=str(PACKAGE_PATH))
    version = package.get("version")
    if not isinstance(version, str) or not version:
        raise CatalogGenerationError("package.json has no release version")
    return version


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def sync_schema(release_root: Path, *, contract_root: Path | None = None) -> Path:
    contract_root = (contract_root or release_root).resolve()
    source = contract_root / SCHEMA_SOURCE
    destination = release_root / SCHEMA_DISTRIBUTION
    try:
        content = source.read_bytes()
    except OSError as error:
        raise CatalogGenerationError(f"cannot read the B1 catalog schema: {error}") from error
    _atomic_write(destination, content)
    return destination


def generate_catalog(
    release_root: Path,
    *,
    channel: str,
    source_commit: str | None = None,
    output: Path = CATALOG_PATH,
    contract_root: Path | None = None,
) -> Path:
    release_root = release_root.resolve()
    contract_root = (contract_root or release_root).resolve()
    if channel not in {"release", "release-beta"}:
        raise CatalogGenerationError(f"unsupported release channel: {channel}")
    commit = source_commit or _source_commit(release_root)
    if FULL_COMMIT.fullmatch(commit) is None:
        raise CatalogGenerationError("source commit must be a full lowercase 40-character Git hash")

    sys.path.insert(0, str(contract_root))
    try:
        from core import portable_contract
        from core.lifecycle.catalog import canonical_catalog_bytes, loads_catalog, with_catalog_identity

        sync_schema(release_root, contract_root=contract_root)
        manifest_path = release_root / MANIFEST_PATH
        manifest_bytes = manifest_path.read_bytes()
        manifest_paths = manifest_bytes.decode("utf-8").splitlines()
        output_text = output.as_posix()
        if manifest_paths != sorted(set(manifest_paths)) or output_text not in manifest_paths:
            raise CatalogGenerationError(
                f"installed-files manifest is not canonical or omits {output_text}"
            )
        document: dict[str, object] = {
            "catalog_version": 1,
            "release": {
                "version": _package_version(release_root),
                "channel": channel,
                "immutable_distribution_tag": (
                    f"dist/{channel}/v{_package_version(release_root)}-{commit[:7]}"
                ),
                "source_commit": commit,
                "manifest": {
                    "path": MANIFEST_PATH.as_posix(),
                    "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                },
            },
            "items": _source_items(release_root, portable_contract),
            "integrity": {"catalog_sha256": "0" * 64, "signatures": []},
        }
        identified = with_catalog_identity(document)
        modeled = loads_catalog(json.dumps(identified), manifest_bytes=manifest_bytes)
        destination = release_root / output
        _atomic_write(destination, canonical_catalog_bytes(modeled))
        return destination
    except (OSError, UnicodeError) as error:
        raise CatalogGenerationError(f"release catalog generation failed: {error}") from error
    finally:
        if sys.path and sys.path[0] == str(contract_root):
            sys.path.pop(0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, default=Path.cwd())
    parser.add_argument("--contract-root", type=Path)
    parser.add_argument("--channel", choices=("release", "release-beta"), default="release")
    parser.add_argument("--source-commit")
    parser.add_argument("--output", type=Path, default=CATALOG_PATH)
    parser.add_argument("--schema-only", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.schema_only:
            destination = sync_schema(
                args.release_root.resolve(),
                contract_root=args.contract_root,
            )
        else:
            destination = generate_catalog(
                args.release_root,
                channel=args.channel,
                source_commit=args.source_commit,
                output=args.output,
                contract_root=args.contract_root,
            )
    except (CatalogGenerationError, ValueError) as error:
        parser.exit(1, f"release catalog generation failed: {error}\n")
    print(f"Wrote {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
