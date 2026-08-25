#!/usr/bin/env python3
"""Refuse a release whose signed Dex Lens catalogue is missing or unverifiable.

Every Dex release must carry `dex-lens-catalog-v<version>.json`, signed with the
Ed25519 key held only in the `DEX_LENS_CATALOG_ED25519_PRIVATE_KEY_B64` CI secret.
heydex.ai pulls that asset within minutes of a release and verifies the signature
before serving it, so a release that ships without it, or with an envelope the
signature does not cover, silently strands every Lens user on the previous
catalogue with nothing to say why.

Generation already happens in the release job. This is the gate that makes it
load-bearing: it proves the exact bytes that will be (or were) attached to the
release parse, match their checksum sidecar, satisfy the vendored wire schema,
name this release, and carry a signature that verifies under the release key.

Two modes, both applying the identical checks:

  --dist dist            the built asset, before it is attached and published
  --from-release         the asset as GitHub actually serves it, after publishing

The private key never leaves the CI secret. When no public key is supplied, the
verifying key is derived in memory from that secret and discarded with the
process; nothing is written and no key material is printed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Mapping

import jsonschema

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LENS_CATALOG_SCHEMA_PATH = REPOSITORY_ROOT / "core/lens-catalog/schemas/dex-lens-catalogue-v2.schema.json"
CONTRACT_VERSION = "dex-lens-catalogue-v2"
DEFAULT_KEY_ID = "dex-core-lens-1"
SIGNING_KEY_ENV = "DEX_LENS_CATALOG_ED25519_PRIVATE_KEY_B64"
PUBLIC_KEY_ENV = "DEX_LENS_CATALOG_ED25519_PUBLIC_KEY_B64"


class LensCatalogAssetError(RuntimeError):
    """The release cannot ship: its Lens catalogue asset is missing or unproven."""


def asset_name(version: str) -> str:
    return f"dex-lens-catalog-v{version}.json"


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_asset(path: Path) -> bytes:
    if not path.is_file():
        raise LensCatalogAssetError(f"the signed Lens catalogue is missing: {path}")
    data = path.read_bytes()
    if not data:
        raise LensCatalogAssetError(f"the signed Lens catalogue is empty: {path}")
    return data


def _check_checksum_sidecar(path: Path, data: bytes) -> None:
    sidecar = path.with_suffix(path.suffix + ".sha256")
    if not sidecar.is_file():
        raise LensCatalogAssetError(f"the catalogue checksum sidecar is missing: {sidecar}")
    fields = sidecar.read_text(encoding="utf-8").split()
    if len(fields) != 2:
        raise LensCatalogAssetError(f"{sidecar.name} is not a 'digest  filename' line")
    digest, named = fields
    if named != path.name:
        raise LensCatalogAssetError(f"{sidecar.name} names {named!r}, not {path.name!r}")
    actual = _sha256(data)
    if digest != actual:
        raise LensCatalogAssetError(
            f"{path.name} does not match {sidecar.name}: file {actual}, sidecar {digest}"
        )


def _envelope(data: bytes) -> Mapping[str, object]:
    try:
        envelope = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise LensCatalogAssetError(f"the signed Lens catalogue is not readable JSON: {error}") from error
    if not isinstance(envelope, dict) or set(envelope) != {"metadata", "catalogue", "signature"}:
        raise LensCatalogAssetError("the Lens catalogue envelope is not metadata + catalogue + signature")
    # The producer writes canonical JSON and one newline. Anything else means the
    # bytes were re-serialised somewhere between signing and here, which is exactly
    # the case a signature check must not be asked to absorb quietly.
    if data != (_canonical_json(envelope) + "\n").encode("utf-8"):
        raise LensCatalogAssetError(
            "the Lens catalogue bytes are not the producer's canonical output; something rewrote the file"
        )
    return envelope


def _check_schema(envelope: Mapping[str, object]) -> None:
    schema = json.loads(LENS_CATALOG_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.Draft202012Validator(schema).validate(envelope)
    except jsonschema.ValidationError as error:
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        raise LensCatalogAssetError(
            f"the Lens catalogue violates the vendored wire schema at {location}: {error.message}"
        ) from error


def _check_identity(envelope: Mapping[str, object], *, version: str, key_id: str) -> None:
    metadata = envelope["metadata"]
    if not isinstance(metadata, dict):
        raise LensCatalogAssetError("the Lens catalogue metadata is not an object")
    if metadata.get("contract_version") != CONTRACT_VERSION:
        raise LensCatalogAssetError(
            f"the Lens catalogue declares contract {metadata.get('contract_version')!r}, expected {CONTRACT_VERSION!r}"
        )
    if metadata.get("core_release") != f"v{version}":
        raise LensCatalogAssetError(
            f"the Lens catalogue is stamped for {metadata.get('core_release')!r}, not this release v{version}"
        )
    if metadata.get("key_id") != key_id:
        raise LensCatalogAssetError(
            f"the Lens catalogue names signing key {metadata.get('key_id')!r}, expected {key_id!r}"
        )
    if str(metadata.get("expires_at", "")) <= str(metadata.get("produced_at", "")):
        raise LensCatalogAssetError("the Lens catalogue expires at or before it was produced")
    catalogue = envelope["catalogue"]
    if not isinstance(catalogue, dict) or not catalogue.get("capabilities"):
        raise LensCatalogAssetError("the Lens catalogue carries no capabilities")


def _verifying_key(*, public_key_env: str, signing_key_env: str):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

    public_secret = os.environ.get(public_key_env, "")
    if public_secret:
        try:
            key_bytes = base64.b64decode(public_secret, validate=True)
        except ValueError as error:
            raise LensCatalogAssetError(f"environment value {public_key_env} is not base64") from error
        if len(key_bytes) == 32:
            return Ed25519PublicKey.from_public_bytes(key_bytes)
        try:
            public_key = serialization.load_pem_public_key(key_bytes)
        except ValueError as error:
            raise LensCatalogAssetError(
                f"environment value {public_key_env} is neither a raw Ed25519 public key nor a PEM public key"
            ) from error
        if not isinstance(public_key, Ed25519PublicKey):
            raise LensCatalogAssetError(f"environment value {public_key_env} is not an Ed25519 public key")
        return public_key

    # No public key supplied: derive the verifying half from the CI signing secret.
    # The private key stays in the secret and in memory; it is never written out.
    signing_secret = os.environ.get(signing_key_env, "")
    if not signing_secret:
        raise LensCatalogAssetError(
            f"no verifying key available: set {public_key_env} or {signing_key_env} so the signature can be checked"
        )
    try:
        signing_bytes = base64.b64decode(signing_secret, validate=True)
    except ValueError as error:
        raise LensCatalogAssetError(f"environment secret {signing_key_env} is not base64") from error
    try:
        private_key = serialization.load_pem_private_key(signing_bytes, password=None)
    except ValueError as error:
        raise LensCatalogAssetError(
            f"environment secret {signing_key_env} must contain a base64 PEM private key"
        ) from error
    if not isinstance(private_key, Ed25519PrivateKey):
        raise LensCatalogAssetError(f"environment secret {signing_key_env} is not an Ed25519 private key")
    return private_key.public_key()


def _check_signature(envelope: Mapping[str, object], *, public_key_env: str, signing_key_env: str) -> None:
    from cryptography.exceptions import InvalidSignature

    signature = envelope["signature"]
    if not isinstance(signature, str) or not signature:
        raise LensCatalogAssetError("the Lens catalogue is unsigned; heydex.ai would reject it")
    try:
        signature_bytes = base64.b64decode(signature, validate=True)
    except ValueError as error:
        raise LensCatalogAssetError("the Lens catalogue signature is not base64") from error
    payload = _canonical_json({"metadata": envelope["metadata"], "catalogue": envelope["catalogue"]})
    verifying_key = _verifying_key(public_key_env=public_key_env, signing_key_env=signing_key_env)
    try:
        verifying_key.verify(signature_bytes, payload.encode("utf-8"))
    except InvalidSignature as error:
        raise LensCatalogAssetError(
            "the Lens catalogue signature does not verify under the release signing key; "
            "the envelope was signed with a different key or altered after signing"
        ) from error


def _gh(args: list[str], *, repo: str | None) -> subprocess.CompletedProcess[str]:
    command = ["gh", *args]
    if repo:
        command += ["--repo", repo]
    return subprocess.run(command, capture_output=True, text=True)


def _download_from_release(version: str, *, repo: str | None, destination: Path) -> Path:
    tag = f"v{version}"
    name = asset_name(version)
    listing = _gh(["release", "view", tag, "--json", "assets"], repo=repo)
    if listing.returncode != 0:
        raise LensCatalogAssetError(f"cannot read release {tag}: {listing.stderr.strip()}")
    try:
        attached = {asset["name"] for asset in json.loads(listing.stdout)["assets"]}
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise LensCatalogAssetError(f"cannot read the asset list for {tag}: {error}") from error
    missing = [item for item in (name, f"{name}.sha256") if item not in attached]
    if missing:
        raise LensCatalogAssetError(
            f"release {tag} is missing {', '.join(missing)}; every release must attach the signed Lens catalogue"
        )
    for item in (name, f"{name}.sha256"):
        result = _gh(
            ["release", "download", tag, "--pattern", item, "--dir", str(destination), "--clobber"],
            repo=repo,
        )
        if result.returncode != 0:
            raise LensCatalogAssetError(f"cannot download {item} from {tag}: {result.stderr.strip()}")
    return destination / name


def check_lens_catalog_asset(
    path: Path,
    *,
    version: str,
    key_id: str = DEFAULT_KEY_ID,
    public_key_env: str = PUBLIC_KEY_ENV,
    signing_key_env: str = SIGNING_KEY_ENV,
) -> None:
    """Every check the release gate applies, in the order that reports best."""
    data = _read_asset(path)
    _check_checksum_sidecar(path, data)
    envelope = _envelope(data)
    # Checked ahead of the schema so an unsigned catalogue reports as unsigned
    # rather than as a minLength violation on a field nobody outside here knows.
    if not envelope["signature"]:
        raise LensCatalogAssetError(
            "the Lens catalogue is unsigned; heydex.ai would reject it. The release job must "
            "run the producer with --sign and the signing secret in the environment"
        )
    _check_schema(envelope)
    _check_identity(envelope, version=version, key_id=key_id)
    _check_signature(envelope, public_key_env=public_key_env, signing_key_env=signing_key_env)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="the release version, without a leading v")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dist", type=Path, help="directory holding the built catalogue asset")
    source.add_argument(
        "--from-release",
        action="store_true",
        help="verify the asset as attached to the published release instead of the built copy",
    )
    parser.add_argument("--repo", help="owner/name, when the release is not this checkout's origin")
    parser.add_argument("--key-id", default=DEFAULT_KEY_ID)
    parser.add_argument("--public-key-env", default=PUBLIC_KEY_ENV)
    parser.add_argument("--signing-key-env", default=SIGNING_KEY_ENV)
    args = parser.parse_args(argv)

    try:
        with tempfile.TemporaryDirectory() as workdir:
            if args.from_release:
                path = _download_from_release(args.version, repo=args.repo, destination=Path(workdir))
                where = f"release v{args.version}"
            else:
                path = args.dist / asset_name(args.version)
                where = str(args.dist)
            check_lens_catalog_asset(
                path,
                version=args.version,
                key_id=args.key_id,
                public_key_env=args.public_key_env,
                signing_key_env=args.signing_key_env,
            )
    except LensCatalogAssetError as error:
        print(f"Dex Lens catalogue release gate failed: {error}", file=sys.stderr)
        return 1
    print(f"Lens catalogue proof: {asset_name(args.version)} in {where} verifies under key {args.key_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
