#!/usr/bin/env python3
"""Generate the signed Dex Lens catalog envelope from publisher-owned Core data."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import posixpath
import re
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Mapping

import jsonschema

REGISTRY_PATH = Path("core/lens-catalog/registry.json")
LENS_CATALOG_SCHEMA_PATH = Path("core/lens-catalog/schemas/dex-lens-catalogue-v2.schema.json")
PACKAGE_PATH = Path("package.json")
CHANGELOG_PATH = Path("CHANGELOG.md")
CONTRACT_VERSION = "dex-lens-catalogue-v2"
MINIMUM_LENS_CONTRACT = "0.1.0"
REGISTRY_VERSION = 1
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.]+)?$")
KEBAB = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
FOUNDATION_CAPABILITIES = frozenset(
    {
        "ownership-portability",
        "privacy-minimal-disclosure",
        "context-orientation",
        "durable-memory-provenance",
        "scoped-agency-human-control",
        "safe-change-recovery",
        "honest-health-observability",
        "compounding-correctability",
    }
)


class LensCatalogError(RuntimeError):
    """The publisher-owned registry cannot produce a trusted Lens catalog."""


def _closed_json(path: Path) -> object:
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise LensCatalogError(f"{path} repeats JSON field {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                LensCatalogError(f"{path} contains non-finite JSON number {value}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LensCatalogError(f"cannot read {path}: {error}") from error


def _mapping(value: object, *, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise LensCatalogError(f"{context} must be a JSON object")
    return value


def _exact_fields(value: Mapping[str, object], expected: set[str], *, context: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise LensCatalogError(f"{context} fields are not closed ({'; '.join(details)})")


def _text(value: object, *, context: str, max_length: int = 512) -> str:
    if not isinstance(value, str):
        raise LensCatalogError(f"{context} must be text")
    if not value.strip():
        raise LensCatalogError(f"{context} must be non-empty")
    if len(value) > max_length:
        raise LensCatalogError(f"{context} exceeds {max_length} characters")
    if CONTROL.search(value):
        raise LensCatalogError(f"{context} contains control characters")
    return value


def _kebab(value: object, *, context: str) -> str:
    text = _text(value, context=context, max_length=128)
    if KEBAB.fullmatch(text) is None:
        raise LensCatalogError(f"{context} must be kebab-case")
    return text


def _semver(value: object, *, context: str) -> str:
    text = _text(value, context=context, max_length=64)
    if SEMVER.fullmatch(text) is None:
        raise LensCatalogError(f"{context} must be a semantic version")
    return text


def _text_tuple(value: object, *, context: str, max_length: int = 512) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise LensCatalogError(f"{context} must be a non-empty array")
    return tuple(_text(item, context=f"{context} item", max_length=max_length) for item in value)


def _relative_path(raw_path: object, *, context: str) -> str:
    path = _text(raw_path, context=context, max_length=512)
    if "\\" in path:
        raise LensCatalogError(f"{context} is not a canonical POSIX path: {path!r}")
    normalized = posixpath.normpath(path)
    if (
        normalized != path
        or normalized in ("", ".", "..")
        or normalized.startswith("/")
        or normalized.startswith("../")
    ):
        raise LensCatalogError(f"{context} is not a canonical POSIX path: {path!r}")
    return path


def _release_file(release_root: Path, raw_path: object, *, context: str) -> tuple[str, Path]:
    relative = _relative_path(raw_path, context=context)
    candidate = release_root / relative
    resolved = candidate.resolve(strict=False)
    if not resolved.is_relative_to(release_root):
        raise LensCatalogError(f"{context} escapes the release root: {relative!r}")
    if candidate.is_symlink() or not candidate.is_file():
        raise LensCatalogError(f"{context} is missing or not a regular file: {relative}")
    return relative, candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_version(release_root: Path) -> str:
    package = _mapping(_closed_json(release_root / PACKAGE_PATH), context=str(PACKAGE_PATH))
    return _semver(package.get("version"), context="package.json version")


def _changelog_versions(release_root: Path) -> set[str]:
    try:
        text = (release_root / CHANGELOG_PATH).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise LensCatalogError(f"cannot read {CHANGELOG_PATH}: {error}") from error
    return set(re.findall(r"^## \[([0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.]+)?)\]", text, re.MULTILINE))


def _skill_description(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise LensCatalogError(f"cannot read shipped skill source {path}: {error}") from error
    if not text.startswith("---\n"):
        raise LensCatalogError(f"shipped skill source has no frontmatter: {path}")
    lines = text.splitlines()
    for line in lines[1:]:
        if line == "---":
            break
        if line.startswith("description:"):
            return _text(
                line.split(":", 1)[1].strip().strip('"'),
                context=f"{path} description",
                max_length=1024,
            )
    raise LensCatalogError(f"shipped skill source has no description: {path}")


def _human_title(entry_id: str) -> str:
    return " ".join(part.capitalize() for part in entry_id.split("-"))


def _is_git_tracked(release_root: Path, relative: str) -> bool:
    git_dir = release_root / ".git"
    if not git_dir.exists():
        return True
    result = subprocess.run(
        ["git", "-C", str(release_root), "ls-files", "--error-unmatch", relative],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _parse_issued_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise LensCatalogError(f"issued_at is not an ISO-8601 timestamp: {value!r}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LensCatalogError("issued_at must include a timezone")
    return parsed.astimezone(UTC).replace(microsecond=0)


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


def _source(entry: Mapping[str, object], release_root: Path, *, context: str) -> dict[str, object]:
    raw = _mapping(entry.get("source"), context=f"{context} source")
    _exact_fields(raw, {"kind", "path", "sha256", "byte_size"}, context=f"{context} source")
    kind = _text(raw.get("kind"), context=f"{context} source kind", max_length=32)
    if kind != "skill":
        raise LensCatalogError(f"{context} source kind must be skill")
    relative, absolute = _release_file(release_root, raw.get("path"), context=f"{context} source path")
    if not relative.startswith(".claude/skills/") or not relative.endswith("/SKILL.md"):
        raise LensCatalogError(f"{context} source path must be a shipped skill SKILL.md")
    if "/_available/" in relative:
        raise LensCatalogError(f"{context} source path must not be a dormant optional skill")
    if relative.startswith(".claude/skills/anthropic-"):
        raise LensCatalogError(f"{context} source path must not be a vendored third-party skill")
    if not _is_git_tracked(release_root, relative):
        raise LensCatalogError(f"{context} source path is not tracked by the release tree: {relative}")
    declared_sha = raw.get("sha256")
    if not isinstance(declared_sha, str) or HEX_SHA256.fullmatch(declared_sha) is None:
        raise LensCatalogError(f"{context} source sha256 must be a lowercase sha256 digest")
    declared_size = raw.get("byte_size")
    if type(declared_size) is not int or declared_size < 0:
        raise LensCatalogError(f"{context} source byte_size must be a non-negative integer")
    actual_sha = _sha256(absolute)
    actual_size = absolute.stat().st_size
    if actual_sha != declared_sha or actual_size != declared_size:
        raise LensCatalogError(f"{context} source does not match its declared sha256 or byte_size")
    return {
        "kind": kind,
        "path": relative,
        "sha256": actual_sha,
        "byte_size": actual_size,
    }


def _evidence(value: object, *, context: str) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list) or not value:
        raise LensCatalogError(f"{context} evidence must be a non-empty array")
    result = []
    for index, item in enumerate(value):
        item_context = f"{context} evidence {index}"
        raw = _mapping(item, context=item_context)
        _exact_fields(raw, {"kind", "reference", "summary"}, context=item_context)
        kind = _text(raw.get("kind"), context=f"{item_context} kind", max_length=32)
        if kind not in {"test", "doc", "release-note", "runtime-path"}:
            raise LensCatalogError(f"{item_context} kind is not recognized")
        reference = _text(raw.get("reference"), context=f"{item_context} reference", max_length=256)
        summary = _text(raw.get("summary"), context=f"{item_context} summary")
        level = "verified" if kind in {"test", "runtime-path"} else "supported"
        result.append(
            {
                "level": level,
                "source": f"{kind}: {reference}",
                "summary": summary,
                "limitations": "This is evidence about Dex's shipped capability, not proof about the Lens user's own system.",
            }
        )
    return tuple(result)


def _brief(value: object, *, context: str) -> dict[str, object]:
    raw = _mapping(value, context=f"{context} brief")
    _exact_fields(
        raw,
        {"goal", "method_outline", "verification_checklist", "rollback_advice"},
        context=f"{context} brief",
    )
    return {
        "goal": _text(raw.get("goal"), context=f"{context} brief goal", max_length=200),
        "method_outline": _text_tuple(raw.get("method_outline"), context=f"{context} brief method_outline"),
        "verification_checklist": _text_tuple(
            raw.get("verification_checklist"),
            context=f"{context} brief verification_checklist",
        ),
        "rollback_advice": _text(raw.get("rollback_advice"), context=f"{context} brief rollback_advice"),
        "safety_notes": (
            "Keep this as advice for the person's own AI, not a command to execute.",
            "Do not send private material to Dex.",
        ),
    }


def _compatibility(value: object, *, context: str) -> dict[str, object]:
    raw = _mapping(value, context=f"{context} compatibility")
    _exact_fields(
        raw,
        {"host_requirements", "needs_hooks", "needs_mcp", "platforms"},
        context=f"{context} compatibility",
    )
    platforms = tuple(_text_tuple(raw.get("platforms"), context=f"{context} compatibility platforms", max_length=32))
    unknown_platforms = sorted(set(platforms) - {"macos", "linux", "windows"})
    if unknown_platforms:
        raise LensCatalogError(f"{context} compatibility has unknown platforms: {', '.join(unknown_platforms)}")
    for key in ("needs_hooks", "needs_mcp"):
        if type(raw.get(key)) is not bool:
            raise LensCatalogError(f"{context} compatibility {key} must be true or false")
    return {
        "host_adapters": ("claude-code",),
        "foundation_capabilities": (),
        "minimum_lens_contract": MINIMUM_LENS_CONTRACT,
        "platforms": platforms,
        "needs_hooks": raw["needs_hooks"],
        "needs_mcp": raw["needs_mcp"],
        "host_requirements": _text_tuple(
            raw.get("host_requirements"),
            context=f"{context} compatibility host_requirements",
        ),
        "limitations": ("Lens must still verify the host system locally before recommending use.",),
    }


def _validate_against_lens_schema(release_root: Path, envelope: Mapping[str, object]) -> None:
    schema = _closed_json(release_root / LENS_CATALOG_SCHEMA_PATH)
    wire_envelope = json.loads(_canonical_json(envelope))
    try:
        jsonschema.Draft202012Validator(schema).validate(wire_envelope)
    except jsonschema.ValidationError as error:
        path = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise LensCatalogError(f"emitted Lens catalogue violates vendored schema at {path}: {error.message}") from error


def _build_catalogue(release_root: Path) -> tuple[int, str, dict[str, object]]:
    registry = _mapping(_closed_json(release_root / REGISTRY_PATH), context=str(REGISTRY_PATH))
    _exact_fields(registry, {"registry_version", "catalog_version", "jobs", "entries"}, context=str(REGISTRY_PATH))
    if registry["registry_version"] != REGISTRY_VERSION:
        raise LensCatalogError(f"{REGISTRY_PATH} has an unsupported registry version")
    catalog_version = registry["catalog_version"]
    if type(catalog_version) is not int or catalog_version <= 0:
        raise LensCatalogError("catalog_version must be a positive integer")

    release_version = _package_version(release_root)
    released_versions = _changelog_versions(release_root)
    if release_version not in released_versions:
        raise LensCatalogError(f"package version {release_version} has no shipped source in CHANGELOG.md")

    jobs_raw = registry["jobs"]
    if not isinstance(jobs_raw, list) or not jobs_raw:
        raise LensCatalogError("jobs must be a non-empty array")
    jobs = []
    seen_jobs: set[str] = set()
    for index, raw_job in enumerate(jobs_raw):
        context = f"job {index}"
        job = _mapping(raw_job, context=context)
        _exact_fields(job, {"job_id", "title", "description"}, context=context)
        job_id = _kebab(job.get("job_id"), context=f"{context} job_id")
        if job_id in seen_jobs:
            raise LensCatalogError(f"duplicate job id {job_id!r}")
        seen_jobs.add(job_id)
        jobs.append(
            {
                "job_id": job_id,
                "label": _text(job.get("title"), context=f"{context} title", max_length=96),
                "description": _text(job.get("description"), context=f"{context} description"),
                "confirmed_gap_signals": (
                    f"The Lens session finds a gap related to {job_id.replace('-', ' ')}."
                ,),
            }
        )

    entries_raw = registry["entries"]
    if not isinstance(entries_raw, list) or not entries_raw:
        raise LensCatalogError("entries must be a non-empty array")
    entries = []
    seen_entries: set[str] = set()
    for index, raw_entry in enumerate(entries_raw):
        context = f"entry {index}"
        entry = _mapping(raw_entry, context=context)
        _exact_fields(
            entry,
            {
                "id",
                "source",
                "value",
                "jobs_served",
                "foundation_capabilities",
                "prerequisites",
                "trade_offs",
                "evidence",
                "brief",
                "compatibility",
                "docs_url",
                "since_release",
                "changed_in",
            },
            context=context,
        )
        entry_id = _kebab(entry.get("id"), context=f"{context} id")
        if entry_id in seen_entries:
            raise LensCatalogError(f"duplicate entry id {entry_id!r}")
        seen_entries.add(entry_id)
        source = _source(entry, release_root, context=context)
        if source["path"] != f".claude/skills/{entry_id}/SKILL.md":
            raise LensCatalogError(f"{context} source path must match entry id {entry_id!r}")
        jobs_served = _text_tuple(entry.get("jobs_served"), context=f"{context} jobs_served", max_length=128)
        for job_id in jobs_served:
            if job_id not in seen_jobs:
                raise LensCatalogError(f"{context} has unknown job reference: {job_id}")
        foundations = _text_tuple(
            entry.get("foundation_capabilities"), context=f"{context} foundation_capabilities", max_length=128
        )
        for foundation in foundations:
            if foundation not in FOUNDATION_CAPABILITIES:
                raise LensCatalogError(f"{context} has unknown foundation reference: {foundation}")
        since_release = _semver(entry.get("since_release"), context=f"{context} since_release")
        if since_release not in released_versions:
            raise LensCatalogError(f"{context} since_release has no shipped source in CHANGELOG.md: {since_release}")
        changed_in = entry.get("changed_in")
        if not isinstance(changed_in, list):
            raise LensCatalogError(f"{context} changed_in must be an array")
        changed = tuple(_semver(item, context=f"{context} changed_in item") for item in changed_in)
        for version in changed:
            if version not in released_versions:
                raise LensCatalogError(f"{context} changed_in has no shipped source in CHANGELOG.md: {version}")
        compatibility = _compatibility(entry.get("compatibility"), context=context)
        entries.append(
            {
                "capability_id": entry_id,
                "title": _human_title(entry_id),
                "summary": _skill_description(release_root / str(source["path"])),
                "value": _text(entry.get("value"), context=f"{context} value"),
                "jobs": jobs_served,
                "prerequisites": _text_tuple(entry.get("prerequisites"), context=f"{context} prerequisites"),
                "trade_offs": _text_tuple(entry.get("trade_offs"), context=f"{context} trade_offs"),
                "evidence": _evidence(entry.get("evidence"), context=context),
                "brief": _brief(entry.get("brief"), context=context),
                "compatibility": {
                    **compatibility,
                    "foundation_capabilities": foundations,
                },
                "portable_brief": _brief(entry.get("brief"), context=context),
                "docs_url": _text(entry.get("docs_url"), context=f"{context} docs_url", max_length=256),
                "since_release": since_release,
                "changed_in": changed,
                "source": source,
                "version_hash": f"sha256:{source['sha256']}",
                "core_release": f"v{release_version}",
                "release_provenance": "core-release",
            }
        )

    catalogue = {
        "jobs_taxonomy": jobs,
        "capabilities": [
            {
                "capability_id": entry["capability_id"],
                "title": entry["title"],
                "summary": entry["summary"],
                "value": entry["value"],
                "jobs": entry["jobs"],
                "prerequisites": entry["prerequisites"],
                "trade_offs": entry["trade_offs"],
                "evidence": entry["evidence"],
                "compatibility": entry["compatibility"],
                "docs_url": entry["docs_url"],
                "since_release": entry["since_release"],
                "changed_in": entry["changed_in"],
                "release_provenance": entry["release_provenance"],
                "portable_brief": entry["portable_brief"],
            }
            for entry in entries
        ],
        "portable_brief": {
            "format": "markdown",
            "audience": "the person's own AI system",
            "safety_boundary": "Brief only: Lens presents adaptation guidance and never applies Dex changes automatically.",
        },
    }
    return catalog_version, release_version, catalogue


def _signature(payload: str, *, signing_key_env: str, key_id: str, test_deterministic: bool) -> str:
    secret = os.environ.get(signing_key_env, "")
    if not secret:
        raise LensCatalogError(f"environment secret {signing_key_env} is not set")
    try:
        key_bytes = base64.b64decode(secret, validate=True)
    except ValueError as error:
        raise LensCatalogError(f"environment secret {signing_key_env} is not base64") from error
    if test_deterministic:
        if os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"):
            raise LensCatalogError("deterministic test signature mode is disabled in CI")
        digest = hashlib.sha512(key_bytes + b"\0" + payload.encode("utf-8")).digest()
        return base64.b64encode(digest).decode("ascii")
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as error:
        raise LensCatalogError(
            "cryptography>=42 is required to sign the Dex Lens catalog on this runner"
        ) from error
    try:
        private_key = serialization.load_pem_private_key(key_bytes, password=None)
    except ValueError as error:
        raise LensCatalogError(
            f"Ed25519 signing failed for key_id {key_id!r}; CI secret must contain a base64 PEM private key"
        ) from error
    if not isinstance(private_key, Ed25519PrivateKey):
        raise LensCatalogError(f"signing key_id {key_id!r} is not an Ed25519 private key")
    return base64.b64encode(private_key.sign(payload.encode("utf-8"))).decode("ascii")


def generate_lens_catalog(
    release_root: Path,
    *,
    output_dir: Path,
    issued_at: str | None = None,
    sign: bool = False,
    signing_key_env: str = "DEX_LENS_CATALOG_ED25519_PRIVATE_KEY_B64",
    key_id: str = "dex-core-lens-1",
    test_deterministic_signature: bool = False,
) -> tuple[Path, Path]:
    release_root = release_root.resolve()
    issued = _parse_issued_at(
        issued_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    catalog_version, release_version, catalogue = _build_catalogue(release_root)
    metadata = {
        "contract_version": CONTRACT_VERSION,
        "catalog_version": catalog_version,
        "produced_at": issued.isoformat().replace("+00:00", "Z"),
        "expires_at": (issued + timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        "producer": f"Dex Core release pipeline v{release_version}",
        "core_release": f"v{release_version}",
        "key_id": key_id,
    }
    signed_payload = {"metadata": metadata, "catalogue": catalogue}
    _validate_against_lens_schema(release_root, {**signed_payload, "signature": "schema-validation-placeholder"})
    payload = _canonical_json(signed_payload)
    signature = ""
    if sign:
        signature = _signature(
            payload,
            signing_key_env=signing_key_env,
            key_id=key_id,
            test_deterministic=test_deterministic_signature,
        )
    envelope = {**signed_payload, "signature": signature}
    encoded = (_canonical_json(envelope) + "\n").encode("utf-8")
    destination = output_dir / f"dex-lens-catalog-v{release_version}.json"
    latest = output_dir / "dex-lens-catalog-latest.json"
    _atomic_write(destination, encoded)
    _atomic_write(latest, encoded)
    digest_line = f"{hashlib.sha256(encoded).hexdigest()}  {destination.name}\n".encode("utf-8")
    _atomic_write(destination.with_suffix(destination.suffix + ".sha256"), digest_line)
    latest_digest_line = f"{hashlib.sha256(encoded).hexdigest()}  {latest.name}\n".encode("utf-8")
    _atomic_write(latest.with_suffix(latest.suffix + ".sha256"), latest_digest_line)
    return destination, latest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    parser.add_argument("--issued-at")
    parser.add_argument("--sign", action="store_true")
    parser.add_argument("--signing-key-env", default="DEX_LENS_CATALOG_ED25519_PRIVATE_KEY_B64")
    parser.add_argument("--key-id", default="dex-core-lens-1")
    parser.add_argument("--test-deterministic-signature", action="store_true")
    args = parser.parse_args(argv)

    try:
        versioned, latest = generate_lens_catalog(
            args.release_root,
            output_dir=args.output_dir,
            issued_at=args.issued_at,
            sign=args.sign,
            signing_key_env=args.signing_key_env,
            key_id=args.key_id,
            test_deterministic_signature=args.test_deterministic_signature,
        )
    except LensCatalogError as error:
        parser.exit(1, f"Dex Lens catalog generation failed: {error}\n")
    print(f"Wrote {versioned}")
    print(f"Wrote {latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
