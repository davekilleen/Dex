#!/usr/bin/env python3
"""Deterministic half of /diff-adopt-profile, standalone edition.

This script travels WITH the skill (installed by the heydex.ai bootstrap as
well as by a normal dex-core install), so it must not import anything from
dex-core: vaults bootstrapped before the DexDiff surface shipped in dex-core
do not have core/dexdiff_profile_adopt.py. It mirrors that module exactly;
core/tests/test_dexdiff_adopt_profile_script.py enforces parity.

What it does:
  1. fetch  GET <api>/api/profile-bundle?handle=<handle>   (api.heydex.ai)
  2. validate the 2026-04-10 bundle contract
  3. save   04-Projects/DexDiff/beta/profile/adopted/<handle>/...
  4. log    System/.dex/adoptions/profiles/<handle>.json

It never deletes anything, never overwrites user-authored files (it only
writes inside the adopted/<handle> mirror and the adoption log), and every
failure path prints a plain-language explanation. Stdlib only, Python 3.9+.

Exit codes: 0 ok, 2 usage, 3 network, 4 profile not found,
            5 bad payload/server response, 6 vault problem.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

PROFILE_BUNDLE_CONTRACT_VERSION = "2026-04-10"
HEYDEX_API_BASE_URL = "https://api.heydex.ai"

PROFILE_DRAFTS_RELATIVE = Path("04-Projects/DexDiff/beta/profile")
ADOPTION_LOG_RELATIVE = Path("System/.dex/adoptions/profiles")


# ---------------------------------------------------------------------------
# Errors, user_message is always safe to show a non-technical user
# ---------------------------------------------------------------------------
class BundleError(Exception):
    exit_code = 5

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


class NetworkError(BundleError):
    exit_code = 3


class NotFoundError(BundleError):
    exit_code = 4


class PayloadError(BundleError):
    exit_code = 5


class VaultError(BundleError):
    exit_code = 6


# ---------------------------------------------------------------------------
# Handle + URL helpers
# ---------------------------------------------------------------------------
def normalize_handle(handle: str) -> str:
    normalized = handle.strip()
    if normalized.startswith("@"):
        normalized = normalized[1:]
    if not normalized:
        raise ValueError("Profile handle is required")
    return normalized


def parse_handle_argument(argument: str) -> str:
    candidate = argument.strip()
    match = re.search(r"/diff/(?:@)?([^/?#]+)", candidate)
    if match:
        candidate = match.group(1)
    return normalize_handle(candidate)


def get_api_base_url(cli_value: "str | None" = None) -> str:
    return (cli_value or os.environ.get("DEXDIFF_API_BASE") or HEYDEX_API_BASE_URL).rstrip("/")


def build_profile_bundle_url(base_url: "str | None", handle: str) -> str:
    return f"{get_api_base_url(base_url)}/api/profile-bundle?handle={quote(normalize_handle(handle))}"


# ---------------------------------------------------------------------------
# Vault resolution, never write outside a real Dex vault
# ---------------------------------------------------------------------------
def resolve_vault_root() -> Path:
    candidate = Path(os.environ.get("VAULT_PATH") or Path.cwd())
    if not (candidate / ".claude").is_dir():
        raise VaultError(
            f"{candidate} does not look like a Dex vault (no .claude folder). "
            "Run this from inside your Dex folder, or set VAULT_PATH to it. "
            "Nothing was changed."
        )
    return candidate


# ---------------------------------------------------------------------------
# Fetch + validate
# ---------------------------------------------------------------------------
def fetch_profile_bundle(handle: str, base_url: "str | None" = None, timeout: float = 20.0) -> dict:
    normalized_handle = normalize_handle(handle)
    url = build_profile_bundle_url(base_url, normalized_handle)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise NotFoundError(
                f"No public profile found for @{normalized_handle}. "
                "The profile may be private, or the handle may be misspelled. "
                f"Check https://heydex.ai/diff/{normalized_handle}/ in a browser."
            )
        raise PayloadError(
            f"The Heydex API answered with HTTP {error.code} for @{normalized_handle}. "
            "This is a server-side problem, not something wrong with your setup. "
            "Try again in a minute."
        )
    except (urllib.error.URLError, TimeoutError, OSError):
        raise NetworkError(
            f"Could not reach {get_api_base_url(base_url)}, check your internet "
            "connection and try again. Nothing was changed locally."
        )

    if status != 200:
        raise PayloadError(
            f"The Heydex API answered with HTTP {status} for @{normalized_handle}. "
            "Try again in a minute."
        )

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise PayloadError(
            "The Heydex API returned something that is not valid JSON. "
            "This is a server-side problem, try again in a minute."
        )

    try:
        return validate_profile_bundle(payload)
    except ValueError as error:
        raise PayloadError(
            f"The profile bundle for @{normalized_handle} is malformed: {error}. "
            "The published profile may need to be re-published, nothing was "
            "changed locally."
        )


def validate_profile_bundle(bundle: dict) -> dict:
    contract_version = bundle.get("contractVersion")
    if contract_version != PROFILE_BUNDLE_CONTRACT_VERSION:
        raise ValueError(f"Unsupported profile bundle contract version: {contract_version!r}")

    profile = bundle.get("profile")
    if not isinstance(profile, dict):
        raise ValueError("Profile bundle is missing profile metadata")

    handle = normalize_handle(str(profile.get("handle", "")))
    workflows = bundle.get("workflows")
    if not isinstance(workflows, list) or len(workflows) == 0:
        raise ValueError("Profile bundle must include at least one workflow")

    normalized_workflows = []
    for workflow in workflows:
        if not isinstance(workflow, dict):
            raise ValueError("Workflow entry must be an object")
        diff_id = str(workflow.get("diffId", "")).strip()
        methodology = str(workflow.get("methodology", "")).strip()
        if not diff_id or not methodology:
            raise ValueError("Each workflow requires diffId and methodology")
        normalized = dict(workflow)
        normalized["diffId"] = diff_id
        normalized["methodology"] = methodology
        normalized_workflows.append(normalized)

    love_letter = bundle.get("loveLetter")
    if love_letter is not None and not isinstance(love_letter, dict):
        raise ValueError("loveLetter must be null or an object")

    result = dict(bundle)
    result["profile"] = dict(profile)
    result["profile"]["handle"] = handle
    result["workflows"] = normalized_workflows
    result["loveLetter"] = love_letter
    return result


def methodology_quality_warnings(bundle: dict) -> list:
    warnings = []
    for workflow in bundle.get("workflows", []):
        methodology = workflow.get("methodology", "")
        diff_id = workflow.get("diffId", "?")
        if "dexdiff_schema" not in methodology:
            warnings.append(
                f"{diff_id}: methodology has no dexdiff_schema marker, looks "
                "like a v1 summary, too thin to regenerate a workflow from"
            )
        elif len(methodology) < 1000:
            warnings.append(
                f"{diff_id}: methodology is only {len(methodology)} characters, "
                "suspiciously thin for a v2 document"
            )
    return warnings


# ---------------------------------------------------------------------------
# Write artifacts (mirror of core/dexdiff_profile_adopt.write_profile_bundle)
# ---------------------------------------------------------------------------
def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return cleaned or "workflow"


def _relative_to_vault(path: Path, vault_root: Path) -> str:
    try:
        return str(path.relative_to(vault_root))
    except ValueError:
        return str(path)


def write_profile_bundle(bundle: dict, source: str, vault_root: Path) -> dict:
    validated = validate_profile_bundle(bundle)
    handle = validated["profile"]["handle"]

    storage_dir = vault_root / PROFILE_DRAFTS_RELATIVE / "adopted" / handle
    workflows_dir = storage_dir / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = storage_dir / "profile-bundle.json"
    manifest_payload = dict(validated)
    manifest_payload["saved_at"] = datetime.now(timezone.utc).isoformat()
    manifest_payload["source"] = source
    manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    workflow_paths = []
    for index, workflow in enumerate(validated["workflows"], start=1):
        file_name = "%02d-%s.yaml" % (index, _slugify(workflow["diffId"]))
        workflow_path = workflows_dir / file_name
        workflow_path.write_text(workflow["methodology"].rstrip() + "\n", encoding="utf-8")
        workflow_paths.append(workflow_path)

    love_letter_path = None
    if validated["loveLetter"] and validated["loveLetter"].get("text"):
        love_letter_path = storage_dir / "love-letter.md"
        love_letter_path.write_text(
            "# Love Letter\n\n" + validated["loveLetter"]["text"].strip() + "\n",
            encoding="utf-8",
        )

    adoptions_dir = vault_root / ADOPTION_LOG_RELATIVE
    adoptions_dir.mkdir(parents=True, exist_ok=True)
    adoption_log_path = adoptions_dir / f"{_slugify(handle)}.json"
    adoption_payload = {
        "profile_handle": handle,
        "profile_display_name": validated["profile"].get("displayName"),
        "adopted_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "bundle_contract_version": validated["contractVersion"],
        "manifest_path": _relative_to_vault(manifest_path, vault_root),
        "workflow_ids": [workflow["diffId"] for workflow in validated["workflows"]],
        "workflow_paths": [_relative_to_vault(path, vault_root) for path in workflow_paths],
        "love_letter_path": _relative_to_vault(love_letter_path, vault_root) if love_letter_path else None,
    }
    adoption_log_path.write_text(
        json.dumps(adoption_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return {
        "storage_dir": storage_dir,
        "manifest_path": manifest_path,
        "workflow_paths": workflow_paths,
        "love_letter_path": love_letter_path,
        "adoption_log_path": adoption_log_path,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _human_summary(result: dict) -> str:
    lines = ["Profile: %s (@%s)" % (result.get("displayName") or result["handle"], result["handle"])]
    if "manifest" in result:
        lines.append("Saved bundle manifest: %s" % result["manifest"])
        lines.extend("  workflow: %s" % path for path in result["workflows"])
        if result.get("loveLetter"):
            lines.append("  love letter: %s" % result["loveLetter"])
        lines.append("Adoption log: %s" % result["adoptionLog"])
    else:
        lines.extend(
            "  workflow: %s (%d chars)" % (w["diffId"], w["methodologyChars"])
            for w in result["workflows"]
        )
    for warning in result.get("warnings", []):
        lines.append("WARNING: %s" % warning)
    return "\n".join(lines)


def main(argv: "list | None" = None) -> int:
    parser = argparse.ArgumentParser(
        prog="adopt_profile.py",
        description="Fetch a published Heydex profile bundle and save it into this vault.",
    )
    parser.add_argument("handle", help="@handle or public profile URL")
    parser.add_argument("--base-url", default=None, help="API base (default: DEXDIFF_API_BASE or https://api.heydex.ai)")
    parser.add_argument("--fetch-only", action="store_true", help="fetch and report, write nothing")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    try:
        handle = parse_handle_argument(args.handle)
    except ValueError:
        print("A profile handle is required, e.g. @davekilleen", flush=True)
        return 2

    try:
        bundle = fetch_profile_bundle(handle, base_url=args.base_url)
        warnings = methodology_quality_warnings(bundle)

        if args.fetch_only:
            result = {
                "handle": bundle["profile"]["handle"],
                "displayName": bundle["profile"].get("displayName"),
                "workflows": [
                    {"diffId": w["diffId"], "name": w.get("name"), "methodologyChars": len(w["methodology"])}
                    for w in bundle["workflows"]
                ],
                "warnings": warnings,
            }
            print(json.dumps(result, indent=2) if args.json else _human_summary(result))
            return 0

        vault_root = resolve_vault_root()
        source = build_profile_bundle_url(args.base_url, handle)
        try:
            written = write_profile_bundle(bundle, source=source, vault_root=vault_root)
        except OSError as error:
            raise VaultError(
                "Could not save the bundle into this vault (%s). Check the "
                "vault is writable." % error
            )

        result = {
            "handle": bundle["profile"]["handle"],
            "displayName": bundle["profile"].get("displayName"),
            "manifest": str(written["manifest_path"]),
            "workflows": [str(path) for path in written["workflow_paths"]],
            "loveLetter": str(written["love_letter_path"]) if written["love_letter_path"] else None,
            "adoptionLog": str(written["adoption_log_path"]),
            "warnings": warnings,
        }
        print(json.dumps(result, indent=2) if args.json else _human_summary(result))
        return 0
    except NotFoundError as error:
        print("PROFILE NOT FOUND: %s" % error.user_message, flush=True)
        return error.exit_code
    except NetworkError as error:
        print("NETWORK ERROR: %s" % error.user_message, flush=True)
        return error.exit_code
    except VaultError as error:
        print("VAULT PROBLEM: %s" % error.user_message, flush=True)
        return error.exit_code
    except BundleError as error:
        print("BAD RESPONSE: %s" % error.user_message, flush=True)
        return error.exit_code


if __name__ == "__main__":
    sys.exit(main())
