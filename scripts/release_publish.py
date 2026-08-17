#!/usr/bin/env python3
"""Draft-first release publishing, so "public" always implies "complete".

A Dex release has two halves that used to run independently: a workflow that put
the public release page up in seconds, and a separate job that built the four
files a stuck copy of Dex downloads to repair itself and attached them only after
the whole test suite passed. Every release therefore had a public-but-empty
window, and a red or queued suite left it empty indefinitely. On 2026-08-11
v1.94.0 sat as the newest release with zero assets for about ninety minutes while
Dex's own rescue instructions pointed at a download that returned "not found".

This script makes that state unreachable by construction:

  draft    Create (or refresh) the HIDDEN draft release for a version, carrying
           its CHANGELOG section as the release notes plus a note explaining why
           it is not public yet. It refuses to modify a release that is already
           public, so re-running it can never un-publish a real release.
  publish  Attach the release assets to that draft, prove every one of them by
           reading the bytes back off the release, and only then flip it public.

The flip is the last thing that happens, and it happens only after the proof.

Every step prints what it actually did -- which assets, how many bytes, which
checksums matched -- and asserts a floor on those counts. A step that cannot say
what it verified fails instead of passing quietly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# The four files every release must carry. Dex installs fetch these exact names
# from the versioned public release; docs/UPDATE-RESCUE.md pastes two of them
# into a command a stuck user runs by hand.
ASSET_TEMPLATES = (
    "dex-vault-bundle-v{version}.tar.gz",
    "dex-vault-bundle-v{version}.tar.gz.sha256",
    "dex-update-bridge-v{version}.py",
    "dex-update-bridge-v{version}.py.sha256",
)

# Assets whose bytes are covered by a sibling ".sha256" file.
CHECKSUMMED_TEMPLATES = (
    "dex-vault-bundle-v{version}.tar.gz",
    "dex-update-bridge-v{version}.py",
)

REQUIRED_ASSET_COUNT = len(ASSET_TEMPLATES)

# The draft note lives between these markers so the flip can remove exactly the
# lines this script added and nothing a human wrote.
NOTE_START = "<!-- dex-release-draft-note:start -->"
NOTE_END = "<!-- dex-release-draft-note:end -->"

# A stable version is X.Y.Z; a prerelease carries a suffix (1.62.0-beta.1).
STABLE_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
PRERELEASE_VERSION = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-[0-9A-Za-z.]+$"
)

FLEET_WORKFLOW = "historic-fleet-darwin.yml"

# GitHub applies release flag changes asynchronously; re-read before believing.
SETTLE_ATTEMPTS = 5
SETTLE_SECONDS = 3.0


class ReleasePublishError(RuntimeError):
    """A release step refused to continue. The message names the exact reason."""


def log(message: str) -> None:
    print(message, flush=True)


@dataclass(frozen=True)
class Gh:
    """Every GitHub call this script makes, in one injectable place.

    Tests substitute a fake with the same three methods, so the decision logic is
    exercised without a network or a real release.
    """

    repo: str | None = None

    def _repo_args(self) -> list[str]:
        return ["--repo", self.repo] if self.repo else []

    def run(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["gh"] + args, check=check, capture_output=True, text=True, encoding="utf-8"
        )

    def release(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
        return self.run(["release"] + args + self._repo_args(), check=check)

    def download_asset(self, api_url: str, destination: Path) -> None:
        """Fetch one asset's bytes through the API, straight to disk.

        The API asset route is used rather than `gh release download` because a
        DRAFT release is not resolvable by tag on the public route -- and a draft
        is exactly what this script verifies before making anything public.

        This is the one call that must not go through text mode: a tarball decoded
        as UTF-8 and re-encoded would not survive the round trip, and the damage
        would look exactly like a genuine checksum mismatch.
        """
        with destination.open("wb") as handle:
            result = subprocess.run(
                ["gh", "api", "-H", "Accept: application/octet-stream", api_url],
                check=False,
                stdout=handle,
                stderr=subprocess.PIPE,
            )
        if result.returncode != 0:
            raise ReleasePublishError(
                f"Could not read back {destination.name} from the release: "
                f"{(result.stderr or b'').decode('utf-8', 'replace').strip()}"
            )


def asset_names(version: str) -> list[str]:
    return [template.format(version=version) for template in ASSET_TEMPLATES]


def checksummed_names(version: str) -> list[str]:
    return [template.format(version=version) for template in CHECKSUMMED_TEMPLATES]


def validate_version(version: str, channel: str) -> None:
    if channel == "beta":
        if not PRERELEASE_VERSION.match(version):
            raise ReleasePublishError(
                f"Refusing: beta version '{version}' is not a prerelease "
                "(expected X.Y.Z-<pre>, e.g. 1.62.0-beta.1). The beta lane must "
                "carry a prerelease version so it can never overwrite a stable release."
            )
        return
    if not STABLE_VERSION.match(version):
        raise ReleasePublishError(
            f"Refusing: stable version '{version}' is not a bare X.Y.Z version."
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_digest(checksum_path: Path) -> str:
    """Read the hex digest out of a `shasum -a 256` style checksum file."""
    text = checksum_path.read_text(encoding="utf-8").strip()
    if not text:
        raise ReleasePublishError(f"{checksum_path.name} is empty.")
    field = text.split()[0]
    if not re.fullmatch(r"[0-9a-f]{64}", field):
        raise ReleasePublishError(
            f"{checksum_path.name} does not start with a sha256 digest (saw '{field}')."
        )
    return field


# --------------------------------------------------------------------------- #
# Release state
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ReleaseState:
    exists: bool
    is_draft: bool = False
    is_prerelease: bool = False
    body: str = ""
    assets: tuple[dict, ...] = ()

    @property
    def asset_names(self) -> set[str]:
        return {asset["name"] for asset in self.assets}


def read_release(gh: Gh, tag: str) -> ReleaseState:
    result = gh.release(
        ["view", tag, "--json", "isDraft,isPrerelease,body,assets"], check=False
    )
    if result.returncode != 0:
        stderr = result.stderr.lower()
        if "release not found" in stderr or "not found" in stderr:
            return ReleaseState(exists=False)
        raise ReleasePublishError(
            f"Could not read release {tag}: {result.stderr.strip()}"
        )
    payload = json.loads(result.stdout)
    return ReleaseState(
        exists=True,
        is_draft=bool(payload.get("isDraft")),
        is_prerelease=bool(payload.get("isPrerelease")),
        body=payload.get("body") or "",
        assets=tuple(payload.get("assets") or []),
    )


# --------------------------------------------------------------------------- #
# The draft note
# --------------------------------------------------------------------------- #


def fleet_proof_in_flight(gh: Gh) -> bool:
    """Is the macOS historic-updater fleet proof holding the publish lock?

    Both that workflow and the release build take the `stable-public-route`
    concurrency group without cancelling, so a release cut while the proof runs
    waits behind it -- up to several hours. The draft says so rather than looking
    mysteriously stalled.
    """
    result = gh.run(
        [
            "run",
            "list",
            "--workflow",
            FLEET_WORKFLOW,
            "--status",
            "in_progress",
            "--limit",
            "1",
            "--json",
            "databaseId",
        ]
        + (["--repo", gh.repo] if gh.repo else []),
        check=False,
    )
    if result.returncode != 0:
        # Not knowing is not an error: the note simply omits the queue sentence.
        log("  note: could not check the fleet proof's status; omitting the queue line.")
        return False
    try:
        runs = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return False
    return bool(runs)


def build_note(version: str, *, queued_behind_fleet: bool) -> str:
    lines = [
        NOTE_START,
        "",
        "---",
        "",
        f"**This release is not public yet.** Dex v{version} is being prepared. The "
        "files people download to update or repair an install are still being built "
        "and checked, and this page becomes public automatically the moment all of "
        "them are attached and verified.",
        "",
        "Nothing here is downloadable while this note is present, which is "
        "deliberate: a release is only announced once it is complete.",
    ]
    if queued_behind_fleet:
        lines += [
            "",
            "**Waiting on the macOS updater proof.** The long-running rehearsal that "
            "replays real historic updates is running right now, and it holds the "
            "single publishing lane while it does. This release is queued behind it "
            "and can wait a few hours before its files are built. That is expected, "
            "not a failure.",
        ]
    lines += ["", NOTE_END]
    return "\n".join(lines)


def strip_note(body: str) -> str:
    """Remove the draft note block, leaving everything a human wrote."""
    while NOTE_START in body and NOTE_END in body:
        start = body.index(NOTE_START)
        end = body.index(NOTE_END) + len(NOTE_END)
        body = body[:start] + body[end:]
    return body.rstrip() + "\n" if body.strip() else ""


# --------------------------------------------------------------------------- #
# Subcommand: draft
# --------------------------------------------------------------------------- #


def changelog_section(changelog: Path, version: str) -> str:
    """Pull this version's CHANGELOG entry, which becomes the release notes."""
    if not changelog.is_file():
        return ""
    lines = changelog.read_text(encoding="utf-8").splitlines()
    heading = re.compile(rf"^## \[{re.escape(version)}\]")
    any_heading = re.compile(r"^## \[")
    collected: list[str] = []
    inside = False
    for line in lines:
        if heading.match(line):
            inside = True
            continue
        if inside and any_heading.match(line):
            break
        if inside:
            collected.append(line)
    return "\n".join(collected).strip()


def command_draft(args: argparse.Namespace, gh: Gh | None = None) -> int:
    gh = gh or Gh(repo=args.repo)
    version = args.version
    tag = f"v{version}"
    validate_version(version, args.channel)

    state = read_release(gh, tag)

    if state.exists and not state.is_draft:
        # The release is already public. Touching it here could only ever make a
        # real release disappear from view, so this is a hard stop -- reported as
        # success because the release existing publicly is the desired end state.
        log(
            f"{tag} is already public; leaving it completely alone. "
            f"({len(state.assets)} asset(s) attached.)"
        )
        if len(state.assets) < REQUIRED_ASSET_COUNT:
            log(
                f"::warning::{tag} is public with only {len(state.assets)} of "
                f"{REQUIRED_ASSET_COUNT} assets. Run the publish step to repair it."
            )
        return 0

    notes = changelog_section(Path(args.changelog), version)
    if not notes:
        log(
            f"::warning::No CHANGELOG section found for [{version}]; "
            "the draft will carry only the not-public-yet note."
        )
    note = build_note(version, queued_behind_fleet=fleet_proof_in_flight(gh))
    body = f"{notes}\n\n{note}\n" if notes else f"{note}\n"

    with tempfile.TemporaryDirectory() as workdir:
        body_file = Path(workdir) / "body.md"
        body_file.write_text(body, encoding="utf-8")

        if not state.exists:
            create = ["create", tag, "--title", tag, "--draft", "--notes-file", str(body_file)]
            if args.channel == "beta":
                create.append("--prerelease")
            if args.target:
                create += ["--target", args.target]
            result = gh.release(create, check=False)
            if result.returncode != 0:
                raise ReleasePublishError(
                    f"Could not create the draft release {tag}: {result.stderr.strip()}"
                )
            log(f"Created {tag} as a HIDDEN DRAFT with its CHANGELOG notes.")
        else:
            result = gh.release(
                ["edit", tag, "--notes-file", str(body_file)], check=False
            )
            if result.returncode != 0:
                raise ReleasePublishError(
                    f"Could not refresh the draft release {tag}: {result.stderr.strip()}"
                )
            log(f"Refreshed the existing DRAFT {tag} with its CHANGELOG notes.")

    after = read_release(gh, tag)
    if not after.exists or not after.is_draft:
        raise ReleasePublishError(
            f"{tag} should be a draft after this step but reads back as "
            f"exists={after.exists} draft={after.is_draft}."
        )
    log(f"Verified: {tag} exists and is a draft. Nothing is publicly downloadable yet.")
    return 0


# --------------------------------------------------------------------------- #
# Subcommand: publish
# --------------------------------------------------------------------------- #


def verify_local_assets(
    dist: Path, version: str, extras: list[Path] | None = None
) -> list[Path]:
    """Every expected file is present, non-empty, and matches its checksum."""
    paths = []
    for name in asset_names(version):
        path = dist / name
        if not path.is_file():
            raise ReleasePublishError(f"Built asset is missing: {path}")
        if path.stat().st_size == 0:
            raise ReleasePublishError(f"Built asset is empty: {path}")
        paths.append(path)

    for path in extras or []:
        if not path.is_file():
            raise ReleasePublishError(f"Extra release asset is missing: {path}")
        if path.stat().st_size == 0:
            raise ReleasePublishError(f"Extra release asset is empty: {path}")
        log(f"  local ok (extra): {path.name} ({path.stat().st_size} bytes)")

    checked = 0
    for name in checksummed_names(version):
        artifact = dist / name
        checksum = dist / f"{name}.sha256"
        actual = sha256_file(artifact)
        wanted = expected_digest(checksum)
        if actual != wanted:
            raise ReleasePublishError(
                f"{name} does not match {checksum.name}: built {actual}, expected {wanted}."
            )
        checked += 1
        log(f"  local ok: {name} ({artifact.stat().st_size} bytes) sha256={actual[:12]}…")

    if checked != len(CHECKSUMMED_TEMPLATES):
        raise ReleasePublishError(
            f"Checked {checked} local checksums, expected {len(CHECKSUMMED_TEMPLATES)}."
        )
    log(f"Local proof: {len(paths)} assets present, {checked} checksums matched.")
    return paths


def verify_attached_assets(
    gh: Gh, tag: str, dist: Path, version: str, extras: list[Path] | None = None
) -> int:
    """Read every asset back off the release and prove it is the built byte.

    Asset presence in the API listing is not enough: an interrupted upload leaves
    a truncated or `state: starting` asset that still appears by name. This reads
    the bytes GitHub will serve and compares them to what was built.
    """
    state = read_release(gh, tag)
    if not state.exists:
        raise ReleasePublishError(f"{tag} does not exist; nothing to verify.")

    # Extra assets (for example the signed Dex Lens catalog) are verified exactly
    # like the core four; they simply do not count toward the required floor.
    extra_by_name = {path.name: path for path in extras or []}
    expected = asset_names(version) + sorted(extra_by_name)
    missing = [name for name in expected if name not in state.asset_names]
    if missing:
        raise ReleasePublishError(
            f"{tag} is missing {len(missing)} of {len(expected)} assets: {', '.join(missing)}"
        )

    by_name = {asset["name"]: asset for asset in state.assets}
    verified = 0
    pairs = 0
    with tempfile.TemporaryDirectory() as workdir:
        readback = Path(workdir)
        for name in expected:
            asset = by_name[name]
            asset_state = asset.get("state")
            if asset_state and asset_state != "uploaded":
                raise ReleasePublishError(
                    f"{name} is attached but its state is '{asset_state}', not 'uploaded'."
                )
            local = extra_by_name.get(name) or (dist / name)
            if asset.get("size") != local.stat().st_size:
                raise ReleasePublishError(
                    f"{name} is attached with {asset.get('size')} bytes but the built "
                    f"file is {local.stat().st_size} bytes."
                )
            destination = readback / name
            gh.download_asset(asset["apiUrl"], destination)
            served = sha256_file(destination)
            built = sha256_file(local)
            if served != built:
                raise ReleasePublishError(
                    f"{name} on the release does not match what was built: "
                    f"served {served}, built {built}."
                )
            verified += 1
            log(f"  attached ok: {name} ({asset.get('size')} bytes) sha256={served[:12]}…")

        # The two checksum files must describe the artefacts as SERVED, not just
        # as built -- that is the pair a stuck user's `shasum -c` actually runs.
        for name in checksummed_names(version):
            artifact = readback / name
            checksum = readback / f"{name}.sha256"
            if sha256_file(artifact) != expected_digest(checksum):
                raise ReleasePublishError(
                    f"As served from the release, {name} does not match its "
                    f"{checksum.name}. A user running `shasum -c` would see a failure."
                )
            pairs += 1
            log(f"  served checksum pair ok: {name} + {name}.sha256")

    if verified != len(expected):
        raise ReleasePublishError(
            f"Verified {verified} assets, expected exactly {len(expected)}."
        )
    if verified < REQUIRED_ASSET_COUNT:
        raise ReleasePublishError(
            f"Verified {verified} assets, below the required floor of "
            f"{REQUIRED_ASSET_COUNT}."
        )
    if pairs != len(CHECKSUMMED_TEMPLATES):
        raise ReleasePublishError(
            f"Verified {pairs} served checksum pairs, expected {len(CHECKSUMMED_TEMPLATES)}."
        )
    log(
        f"Attached proof: {verified} assets ({REQUIRED_ASSET_COUNT} required + "
        f"{len(extra_by_name)} extra) read back off {tag} and byte-identical to the "
        f"build; {pairs} checksum pairs verified."
    )
    return verified


def public_download_url(repo: str, version: str, name: str) -> str:
    return f"https://github.com/{repo}/releases/download/v{version}/{name}"


def fetch_public_status(url: str) -> int:
    """HTTP status from the anonymous public route, following redirects.

    The headers deliberately imitate `curl`, because `curl -fL` is literally what
    docs/UPDATE-RESCUE.md tells a stuck user to run. GitHub's response varies on
    `Accept`, so probing with a different Accept header checks a different cache
    entry than the one a real user hits -- and can return 200 while the user's
    curl gets 404. Verified on 2026-08-12 against a real release.
    """
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "curl/8.5.0", "Accept": "*/*"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read(1)
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except (urllib.error.URLError, TimeoutError):
        return 0


def verify_public_route(
    gh: Gh,
    tag: str,
    version: str,
    extras: list[Path] | None = None,
    *,
    repo: str | None = None,
    attempts: int = 10,
    sleep_seconds: float = 6.0,
    sleeper=None,
    status_reader=None,
) -> None:
    """Confirm the anonymous download route serves every asset, and hide it if not.

    The read-back proof in step 4 goes through the authenticated API. On
    2026-08-12 that proof passed while the public URL for one asset still returned
    404 for several seconds -- GitHub's public route lags the API. Checking only the
    API would therefore let a release go live moments before it is downloadable,
    which is a smaller version of the exact bug this whole change exists to remove.

    If the public route never comes good, the release is put back to a hidden draft:
    an invisible release is always better than a visible broken one.
    """
    sleeper = sleeper or time.sleep
    status_reader = status_reader or fetch_public_status
    repo = repo or gh.repo or _origin_repo()
    if not repo:
        log(
            "::warning::Could not work out the repository name, so the public "
            "download route was not checked."
        )
        return

    names = asset_names(version) + [path.name for path in (extras or [])]
    pending = [(name, public_download_url(repo, version, name)) for name in names]
    confirmed: list[str] = []

    for attempt in range(1, attempts + 1):
        still_pending = []
        for name, url in pending:
            status = status_reader(url)
            if status == 200:
                confirmed.append(name)
                log(f"  public ok: {name} (HTTP 200 anonymously)")
            else:
                still_pending.append((name, url))
        pending = still_pending
        if not pending:
            break
        if attempt < attempts:
            log(
                f"  {len(pending)} asset(s) not yet served publicly; waiting "
                f"{sleep_seconds:g}s (attempt {attempt}/{attempts})…"
            )
            sleeper(sleep_seconds)

    if pending:
        # Distinguish two very different situations before doing anything drastic.
        # A stale cached 404 (GitHub briefly served "not found" while the asset was
        # propagating, and that answer got cached for this request shape) still has
        # a perfectly good asset behind it, and it expires on its own. Hiding the
        # release for that would be an over-reaction; hiding it for a genuinely
        # absent asset is exactly right.
        stale, genuinely_missing = [], []
        for name, url in pending:
            separator = "&" if "?" in url else "?"
            if status_reader(f"{url}{separator}cache-bust={secrets.token_hex(6)}") == 200:
                stale.append(name)
            else:
                genuinely_missing.append(name)

        for name in stale:
            log(
                f"::warning::{name} is present and downloadable, but the public URL is "
                "currently answering with a cached 'not found' from while it was still "
                "being copied out. That cache entry expires by itself; a user retrying "
                "in a few minutes gets the file."
            )

        if genuinely_missing:
            stuck = ", ".join(genuinely_missing)
            log(f"::error::{tag} is public but {stuck} does not download. Hiding it again.")
            gh.release(["edit", tag, "--draft=true"], check=False)
            state = read_release(gh, tag)
            hidden = "hidden again" if state.is_draft else "STILL PUBLIC — fix by hand"
            raise ReleasePublishError(
                f"{tag} went public but the public download route never served: {stuck}. "
                f"The release was {hidden}."
            )
        confirmed.extend(stale)

    if len(confirmed) != len(names):
        raise ReleasePublishError(
            f"Confirmed {len(confirmed)} public downloads, expected {len(names)}."
        )
    log(
        f"Public proof: all {len(confirmed)} assets download anonymously from the "
        f"real release URLs — the route a stuck copy of Dex actually uses."
    )


def _origin_repo() -> str | None:
    """`owner/name` from the git remote, so the public URLs can be built."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    match = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
    return match.group(1) if match else None


def command_publish(args: argparse.Namespace, gh: Gh | None = None) -> int:
    gh = gh or Gh(repo=args.repo)
    version = args.version
    tag = f"v{version}"
    validate_version(version, args.channel)
    dist = Path(args.dist)
    extras = [Path(item) for item in (args.extra_asset or [])]

    log(f"Publishing {tag} ({args.channel} channel) from {dist}")
    if extras:
        log(f"  plus {len(extras)} extra asset(s): {', '.join(p.name for p in extras)}")
    log("Step 1/5 — proving the built assets locally")
    verify_local_assets(dist, version, extras)

    log("Step 2/5 — making sure a release exists to attach them to")
    state = read_release(gh, tag)
    if not state.exists:
        # The draft step normally runs first, from the tag-push workflow. If it
        # did not run at all, create the draft here so the assets still land on a
        # hidden release rather than a public empty one.
        log(f"  {tag} does not exist yet; creating it as a hidden draft.")
        create = ["create", tag, "--title", tag, "--draft", "--generate-notes"]
        if args.channel == "beta":
            create.append("--prerelease")
        if args.target:
            create += ["--target", args.target]
        result = gh.release(create, check=False)
        if result.returncode != 0:
            raise ReleasePublishError(
                f"Could not create the draft release {tag}: {result.stderr.strip()}"
            )
        state = read_release(gh, tag)
    elif state.is_draft:
        log(f"  {tag} exists as a draft, as expected.")
    else:
        # Already public. This is the state the whole change exists to prevent,
        # but it can still be reached by a release cut before this change landed.
        # Repairing it is strictly better than refusing.
        log(
            f"::warning::{tag} is ALREADY PUBLIC with {len(state.assets)} asset(s) "
            "before its assets were verified. Attaching and verifying them now as a "
            "repair; the draft-first path was bypassed for this release."
        )

    if args.channel == "beta" and state.exists and not state.is_prerelease:
        raise ReleasePublishError(
            f"Refusing: release {tag} exists but is not a prerelease; the beta lane "
            "will not clobber it."
        )

    log("Step 3/5 — attaching the assets")
    upload = (
        ["upload", tag]
        + [str(dist / name) for name in asset_names(version)]
        + [str(path) for path in extras]
        + ["--clobber"]
    )
    result = gh.release(upload, check=False)
    if result.returncode != 0:
        raise ReleasePublishError(
            f"Could not attach assets to {tag}: {result.stderr.strip()}"
        )
    log(f"  attached {REQUIRED_ASSET_COUNT + len(extras)} assets to {tag}.")

    log("Step 4/5 — reading every asset back off the release")
    verify_attached_assets(gh, tag, dist, version, extras)

    log("Step 5/6 — making the release public")
    current = read_release(gh, tag)
    want_prerelease = args.channel == "beta"
    with tempfile.TemporaryDirectory() as workdir:
        body_file = Path(workdir) / "body.md"
        body_file.write_text(strip_note(current.body), encoding="utf-8")
        # Two separate calls, deliberately. Observed on 2026-08-12 against a real
        # release: setting the prerelease flag in the SAME `gh release edit` as
        # `--draft=false` left the release marked as not-a-prerelease, which for the
        # beta lane would present a beta build to everyone as the current version.
        # Applied on its own, the flag sticks. So: set the notes and prerelease
        # state while the release is still hidden, then flip it public as its own
        # operation. A stable release cannot be marked latest while it is a draft:
        # GitHub rejects that combination with HTTP 422. Mark it latest only after
        # the public-state readback below has proved it is no longer a draft.
        flags = ["edit", tag, "--notes-file", str(body_file)]
        flags.append("--prerelease=true" if want_prerelease else "--prerelease=false")
        result = gh.release(flags, check=False)
        if result.returncode != 0:
            raise ReleasePublishError(
                f"Could not set the release flags on {tag}: {result.stderr.strip()}"
            )

        result = gh.release(["edit", tag, "--draft=false"], check=False)
        if result.returncode != 0:
            raise ReleasePublishError(
                f"Assets are verified but {tag} could not be made public: "
                f"{result.stderr.strip()}"
            )

    # GitHub settles these fields asynchronously, so read the end state more than
    # once rather than trusting the first answer. The first read after the flip has
    # been seen reporting a value that later changed.
    final = read_release(gh, tag)
    for _ in range(SETTLE_ATTEMPTS):
        if not final.is_draft and final.is_prerelease == want_prerelease:
            break
        time.sleep(SETTLE_SECONDS)
        final = read_release(gh, tag)

    if final.is_draft:
        raise ReleasePublishError(f"{tag} still reads as a draft after the flip.")
    if final.is_prerelease != want_prerelease:
        # Repair rather than refuse: a beta release that is not marked as a
        # prerelease can be presented to everyone as the current version.
        log(
            f"::warning::{tag} came back with prerelease={final.is_prerelease}, "
            f"expected {want_prerelease}. Correcting it."
        )
        gh.release(
            ["edit", tag, "--prerelease=true" if want_prerelease else "--prerelease=false"],
            check=False,
        )
        time.sleep(SETTLE_SECONDS)
        final = read_release(gh, tag)
        if final.is_prerelease != want_prerelease:
            raise ReleasePublishError(
                f"{tag} is public but its prerelease flag is {final.is_prerelease}, "
                f"and it could not be set to {want_prerelease}."
            )
    if not want_prerelease:
        latest = gh.release(["edit", tag, "--latest"], check=False)
        if latest.returncode != 0:
            raise ReleasePublishError(
                f"{tag} is public and verified but could not be marked latest: "
                f"{latest.stderr.strip()}"
            )
    still_missing = [
        name
        for name in asset_names(version) + [path.name for path in extras]
        if name not in final.asset_names
    ]
    if still_missing:
        raise ReleasePublishError(
            f"{tag} went public but is missing {', '.join(still_missing)}. "
            "This should be impossible; treat it as a publishing bug."
        )

    log("Step 6/6 — proving the PUBLIC download route actually serves the files")
    verify_public_route(gh, tag, version, extras)
    if NOTE_START in final.body:
        raise ReleasePublishError(
            f"{tag} is public but still carries the not-public-yet note."
        )
    log(
        f"PUBLISHED {tag}: public, {len(final.asset_names)} assets attached, all "
        f"{REQUIRED_ASSET_COUNT} verified byte-for-byte before the flip."
    )
    return 0


# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=os.environ.get("GH_REPO") or None)
    subparsers = parser.add_subparsers(dest="command", required=True)

    draft = subparsers.add_parser(
        "draft", help="Create or refresh the hidden draft release for a version."
    )
    draft.add_argument("--version", required=True)
    draft.add_argument("--channel", choices=("stable", "beta"), default="stable")
    draft.add_argument("--changelog", default="CHANGELOG.md")
    draft.add_argument("--target", default=None)
    draft.set_defaults(handler=command_draft)

    publish = subparsers.add_parser(
        "publish",
        help="Attach assets to the draft, verify them, then make the release public.",
    )
    publish.add_argument("--version", required=True)
    publish.add_argument("--channel", choices=("stable", "beta"), default="stable")
    publish.add_argument("--dist", default="dist")
    publish.add_argument(
        "--extra-asset",
        action="append",
        default=[],
        metavar="PATH",
        help=(
            "An additional file to attach and verify alongside the four required "
            "assets (for example the signed Dex Lens catalogue). Repeatable. Extras "
            "go through the same read-back proof and are attached before the release "
            "is made public, so nothing appears on a release after it goes live."
        ),
    )
    publish.add_argument("--target", default=None)
    publish.set_defaults(handler=command_publish)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if shutil.which("gh") is None:
        log("Refusing: the GitHub CLI (gh) is not on PATH.")
        return 1
    try:
        return args.handler(args)
    except ReleasePublishError as error:
        log(f"Release step stopped safely: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
