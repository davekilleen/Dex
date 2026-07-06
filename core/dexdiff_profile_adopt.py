"""Helpers for whole-profile DexDiff adoption.

The hosted contract lives on ``https://api.heydex.ai`` (Convex HTTP actions).
The website host ``https://heydex.ai`` serves pages only and has no ``/api/*``
routes, fetching the bundle from there is the historical break 1 from the
2026-06-10 end-to-end review. Keep all API calls on the API host.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from core.paths import DEX_RUNTIME_DIR, DEXDIFF_PROFILE_DRAFTS_DIR, VAULT_ROOT

PROFILE_BUNDLE_CONTRACT_VERSION = "2026-04-10"
PROFILE_ADOPTIONS_DIR = DEX_RUNTIME_DIR / "adoptions" / "profiles"

# Canonical hosted API base. Override with DEXDIFF_API_BASE (used by tests and
# the sandbox rehearsal loop to point at a local stub server).
HEYDEX_API_BASE_URL = "https://api.heydex.ai"


class ProfileBundleError(Exception):
    """Base class. ``user_message`` is safe to show a non-technical user."""

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


class ProfileBundleNetworkError(ProfileBundleError):
    """Could not reach the API host at all."""


class ProfileBundleNotFoundError(ProfileBundleError):
    """The handle has no public profile bundle (404)."""


class ProfileBundleHTTPError(ProfileBundleError):
    """The API answered with an unexpected HTTP status."""


class ProfileBundlePayloadError(ProfileBundleError):
    """The response body is not a valid profile bundle."""


def get_api_base_url() -> str:
    return os.environ.get("DEXDIFF_API_BASE", HEYDEX_API_BASE_URL).rstrip("/")


def normalize_handle(handle: str) -> str:
    normalized = handle.strip()
    if normalized.startswith("@"):
        normalized = normalized[1:]
    if not normalized:
        raise ValueError("Profile handle is required")
    return normalized


def parse_handle_argument(argument: str) -> str:
    """Accept ``@handle``, ``handle``, or a public profile URL like
    ``https://heydex.ai/diff/handle/`` and return the bare handle."""
    candidate = argument.strip()
    match = re.search(r"/diff/(?:@)?([^/?#]+)", candidate)
    if match:
        candidate = match.group(1)
    return normalize_handle(candidate)


def build_profile_bundle_url(base_url: str | None = None, handle: str = "") -> str:
    resolved_base = (base_url or get_api_base_url()).rstrip("/")
    normalized_handle = normalize_handle(handle)
    return f"{resolved_base}/api/profile-bundle?handle={quote(normalized_handle)}"


def fetch_profile_bundle(
    handle: str,
    base_url: str | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Fetch and validate a hosted profile bundle.

    Raises a ProfileBundleError subclass with a plain-language
    ``user_message`` on every failure path, never fails silently.
    """
    normalized_handle = normalize_handle(handle)
    url = build_profile_bundle_url(base_url, normalized_handle)

    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise ProfileBundleNotFoundError(
                f"No public profile found for @{normalized_handle}. "
                "The profile may be private, or the handle may be misspelled. "
                f"Check https://heydex.ai/diff/{normalized_handle}/ in a browser."
            ) from error
        raise ProfileBundleHTTPError(
            f"The Heydex API answered with HTTP {error.code} for @{normalized_handle}. "
            "This is a server-side problem, not something wrong with your setup. "
            "Try again in a minute."
        ) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ProfileBundleNetworkError(
            f"Could not reach {url.split('/api/')[0]}, check your internet "
            "connection and try again. Nothing was changed locally."
        ) from error

    if status != 200:
        raise ProfileBundleHTTPError(
            f"The Heydex API answered with HTTP {status} for @{normalized_handle}. "
            "Try again in a minute."
        )

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise ProfileBundlePayloadError(
            "The Heydex API returned something that is not valid JSON. "
            "This is a server-side problem, try again in a minute."
        ) from error

    try:
        return validate_profile_bundle(payload)
    except ValueError as error:
        raise ProfileBundlePayloadError(
            f"The profile bundle for @{normalized_handle} is malformed: {error}. "
            "The published profile may need to be re-published, nothing was "
            "changed locally."
        ) from error


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return cleaned or "workflow"


def _relative_to_vault(path: Path) -> str:
    try:
        return str(path.relative_to(VAULT_ROOT))
    except ValueError:
        return str(path)


def validate_profile_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    contract_version = bundle.get("contractVersion")
    if contract_version != PROFILE_BUNDLE_CONTRACT_VERSION:
        raise ValueError(
            f"Unsupported profile bundle contract version: {contract_version!r}"
        )

    profile = bundle.get("profile")
    if not isinstance(profile, dict):
        raise ValueError("Profile bundle is missing profile metadata")

    handle = normalize_handle(str(profile.get("handle", "")))
    workflows = bundle.get("workflows")
    if not isinstance(workflows, list) or len(workflows) == 0:
        raise ValueError("Profile bundle must include at least one workflow")

    normalized_workflows: list[dict[str, Any]] = []
    for workflow in workflows:
        if not isinstance(workflow, dict):
            raise ValueError("Workflow entry must be an object")
        diff_id = str(workflow.get("diffId", "")).strip()
        methodology = str(workflow.get("methodology", "")).strip()
        if not diff_id or not methodology:
            raise ValueError("Each workflow requires diffId and methodology")
        normalized_workflows.append(
            {
                **workflow,
                "diffId": diff_id,
                "methodology": methodology,
            }
        )

    love_letter = bundle.get("loveLetter")
    if love_letter is not None and not isinstance(love_letter, dict):
        raise ValueError("loveLetter must be null or an object")

    return {
        **bundle,
        "profile": {
            **profile,
            "handle": handle,
        },
        "workflows": normalized_workflows,
        "loveLetter": love_letter,
    }


def get_profile_storage_dir(handle: str) -> Path:
    return DEXDIFF_PROFILE_DRAFTS_DIR / "adopted" / normalize_handle(handle)


def write_profile_bundle(bundle: dict[str, Any], source: str) -> dict[str, Any]:
    validated = validate_profile_bundle(bundle)
    handle = validated["profile"]["handle"]

    storage_dir = get_profile_storage_dir(handle)
    workflows_dir = storage_dir / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = storage_dir / "profile-bundle.json"
    manifest_payload = {
        "saved_at": datetime.now(UTC).isoformat(),
        "source": source,
        **validated,
    }
    manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    workflow_paths: list[Path] = []
    for index, workflow in enumerate(validated["workflows"], start=1):
        file_name = f"{index:02d}-{_slugify(workflow['diffId'])}.yaml"
        workflow_path = workflows_dir / file_name
        workflow_path.write_text(f"{workflow['methodology'].rstrip()}\n", encoding="utf-8")
        workflow_paths.append(workflow_path)

    love_letter_path: Path | None = None
    if validated["loveLetter"] and validated["loveLetter"].get("text"):
        love_letter_path = storage_dir / "love-letter.md"
        love_letter_path.write_text(
            "# Love Letter\n\n" + validated["loveLetter"]["text"].strip() + "\n",
            encoding="utf-8",
        )

    adoption_log_path = write_profile_adoption_log(
        validated,
        source=source,
        manifest_path=manifest_path,
        workflow_paths=workflow_paths,
        love_letter_path=love_letter_path,
    )

    return {
        "storage_dir": storage_dir,
        "manifest_path": manifest_path,
        "workflow_paths": workflow_paths,
        "love_letter_path": love_letter_path,
        "adoption_log_path": adoption_log_path,
    }


def write_profile_adoption_log(
    bundle: dict[str, Any],
    *,
    source: str,
    manifest_path: Path,
    workflow_paths: list[Path],
    love_letter_path: Path | None = None,
) -> Path:
    validated = validate_profile_bundle(bundle)
    handle = validated["profile"]["handle"]

    PROFILE_ADOPTIONS_DIR.mkdir(parents=True, exist_ok=True)
    adoption_path = PROFILE_ADOPTIONS_DIR / f"{_slugify(handle)}.json"
    payload = {
        "profile_handle": handle,
        "profile_display_name": validated["profile"].get("displayName"),
        "adopted_at": datetime.now(UTC).isoformat(),
        "source": source,
        "bundle_contract_version": validated["contractVersion"],
        "manifest_path": _relative_to_vault(manifest_path),
        "workflow_ids": [workflow["diffId"] for workflow in validated["workflows"]],
        "workflow_paths": [_relative_to_vault(path) for path in workflow_paths],
        "love_letter_path": _relative_to_vault(love_letter_path) if love_letter_path else None,
    }
    adoption_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return adoption_path


def methodology_quality_warnings(bundle: dict[str, Any]) -> list[str]:
    """Spot v1-era one-line summaries masquerading as v2 methodologies.

    A real v2 methodology is a full YAML document carrying the
    ``dexdiff_schema: "2.0"`` marker; the adopter's AI cannot regenerate a
    workflow from a one-sentence summary (break 3 in the 2026-06-10 review).
    """
    warnings: list[str] = []
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


def _cli(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python3 -m core.dexdiff_profile_adopt",
        description=(
            "Fetch a published Heydex profile bundle and save it into this "
            "vault's DexDiff draft area (deterministic half of /diff-adopt-profile)."
        ),
    )
    parser.add_argument("handle", help="@handle or public profile URL")
    parser.add_argument("--base-url", default=None, help="API base (default: %(default)s -> DEXDIFF_API_BASE or https://api.heydex.ai)")
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
    except ProfileBundleNotFoundError as error:
        print(f"PROFILE NOT FOUND: {error.user_message}", flush=True)
        return 4
    except ProfileBundleNetworkError as error:
        print(f"NETWORK ERROR: {error.user_message}", flush=True)
        return 3
    except (ProfileBundleHTTPError, ProfileBundlePayloadError) as error:
        print(f"BAD RESPONSE: {error.user_message}", flush=True)
        return 5

    warnings = methodology_quality_warnings(bundle)

    if args.fetch_only:
        result: dict[str, Any] = {
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

    try:
        written = write_profile_bundle(bundle, source=build_profile_bundle_url(args.base_url, handle))
    except OSError as error:
        print(
            "WRITE FAILED: could not save the bundle into this vault "
            f"({error}). Check you are running inside your Dex vault and that "
            "it is writable.",
            flush=True,
        )
        return 6

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


def _human_summary(result: dict[str, Any]) -> str:
    lines = [f"Profile: {result.get('displayName') or result['handle']} (@{result['handle']})"]
    if "manifest" in result:
        lines.append(f"Saved bundle manifest: {result['manifest']}")
        lines.extend(f"  workflow: {path}" for path in result["workflows"])
        if result.get("loveLetter"):
            lines.append(f"  love letter: {result['loveLetter']}")
        lines.append(f"Adoption log: {result['adoptionLog']}")
    else:
        lines.extend(
            f"  workflow: {w['diffId']} ({w['methodologyChars']} chars)"
            for w in result["workflows"]
        )
    for warning in result.get("warnings", []):
        lines.append(f"WARNING: {warning}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    sys.exit(_cli(sys.argv[1:]))
