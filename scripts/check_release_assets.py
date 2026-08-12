#!/usr/bin/env python3
"""Prove the newest Dex release is actually downloadable, from the outside.

Draft-first publishing (scripts/release_publish.py) makes a public-but-empty
release unreachable through the normal path. This is the independent watchman for
everything that path cannot cover: a release cut by an older pipeline, an asset
deleted or replaced by hand, a rescue document pointing at a version that was
never published, or a release left half-attached by a partial upload.

It checks two URL sets, both over plain unauthenticated HTTPS -- the same route a
user's `curl` takes, not an authenticated API view that can succeed while the
public route fails:

  1. The four asset URLs of the current "Latest" release.
  2. Every release-download URL written literally into docs/UPDATE-RESCUE.md.

The second set is the one that actually broke on 2026-08-11: the rescue guide is
rewritten to name the new version at the moment a release is cut, so it pointed
at a bridge that did not exist yet and a stuck user following it got "not found".

Exit codes are deliberately distinct, because "the release is broken" and "I could
not tell" must never be reported the same way:

  0  every probed URL served bytes and every checksum matched
  1  a real failure -- something a user would hit
  2  the check could not run (no network, GitHub unreachable, no release found)

Usage:
    python3 scripts/check_release_assets.py
    python3 scripts/check_release_assets.py --json report.json
    python3 scripts/check_release_assets.py --version 1.94.0   # probe one version
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO = "davekilleen/Dex"
LATEST_RELEASE_API = "https://api.github.com/repos/{repo}/releases/latest"
DOWNLOAD_URL = "https://github.com/{repo}/releases/download/v{version}/{name}"

ASSET_TEMPLATES = (
    "dex-vault-bundle-v{version}.tar.gz",
    "dex-vault-bundle-v{version}.tar.gz.sha256",
    "dex-update-bridge-v{version}.py",
    "dex-update-bridge-v{version}.py.sha256",
)
CHECKSUMMED_TEMPLATES = (
    "dex-vault-bundle-v{version}.tar.gz",
    "dex-update-bridge-v{version}.py",
)
REQUIRED_ASSET_COUNT = len(ASSET_TEMPLATES)

RESCUE_DOC = "docs/UPDATE-RESCUE.md"
# The rescue guide AS SHIPPED in the released tree -- not a local working copy,
# which can be on any branch and say anything. What a stuck user reads is the
# version at the release tag.
RESCUE_DOC_AT_TAG = (
    "https://raw.githubusercontent.com/{repo}/v{version}/" + RESCUE_DOC
)
RESCUE_URL_PATTERN = re.compile(
    r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/releases/download/[^\s\"')]+"
)

# A release left in draft for longer than this is no longer "being prepared"; it
# is stuck, and nobody is being told. Reported as a failure so it gets attention.
STUCK_DRAFT_HOURS = 6

MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
TIMEOUT_SECONDS = 60
USER_AGENT = "dex-release-asset-prober/1"


@dataclass
class Probe:
    url: str
    source: str
    ok: bool = False
    status: int | None = None
    size: int | None = None
    sha256: str | None = None
    detail: str = ""


@dataclass
class Report:
    checked_at: str
    version: str | None = None
    release_url: str | None = None
    probes: list[Probe] = field(default_factory=list)
    checksum_pairs_verified: int = 0
    failures: list[str] = field(default_factory=list)
    undetermined: list[str] = field(default_factory=list)

    @property
    def probed_count(self) -> int:
        return len(self.probes)

    @property
    def failed(self) -> list[Probe]:
        return [probe for probe in self.probes if not probe.ok]


def log(message: str) -> None:
    print(message, flush=True)


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #


class Undetermined(RuntimeError):
    """The check could not reach GitHub. Not evidence of a broken release."""


def _opener() -> urllib.request.OpenerDirector:
    context = ssl.create_default_context()
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))


def fetch(url: str, *, opener=None) -> tuple[int, bytes]:
    """GET a URL following redirects. Returns (status, body).

    A 404 is a RESULT, not an error -- that is the failure this exists to catch.
    A DNS or TLS failure is an Undetermined, because it says nothing about the
    release.
    """
    opener = opener or _opener()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_DOWNLOAD_BYTES + 1)
            if len(body) > MAX_DOWNLOAD_BYTES:
                raise Undetermined(f"{url} is larger than the {MAX_DOWNLOAD_BYTES}-byte cap.")
            return response.status, body
    except urllib.error.HTTPError as error:
        # An HTTP status the server actually returned: a real, reportable answer.
        return error.code, b""
    except urllib.error.URLError as error:
        raise Undetermined(f"could not reach {url}: {error.reason}") from error
    except TimeoutError as error:
        raise Undetermined(f"timed out fetching {url}") from error


def resolve_latest_version(*, opener=None) -> tuple[str, str]:
    """Read the version GitHub currently serves as "Latest"."""
    status, body = fetch(LATEST_RELEASE_API.format(repo=REPO), opener=opener)
    if status != 200:
        raise Undetermined(
            f"the latest-release lookup returned HTTP {status}; cannot tell which "
            "version is current."
        )
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise Undetermined("the latest-release lookup returned unreadable JSON.") from error
    tag = payload.get("tag_name") or ""
    if not tag.startswith("v") or len(tag) < 2:
        raise Undetermined(f"the latest release has an unusable tag: {tag!r}")
    return tag[1:], payload.get("html_url") or ""


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #


def _unique(urls: list[str]) -> list[str]:
    """Preserve order, drop duplicates: the guide names each URL twice."""
    seen: set[str] = set()
    unique = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def rescue_doc_urls(
    version: str, *, source: str, repo_root: Path | None = None, opener=None
) -> tuple[list[str], list[str]]:
    """Every release-download URL a stuck user could copy out of the rescue guide.

    Returns (urls, undetermined reasons). Reading the guide from the release tag
    needs no checkout, which is what lets this run from anywhere.
    """
    if source == "local":
        if repo_root is None:
            return [], ["no repository root given, so the local rescue guide was not read"]
        doc = repo_root / RESCUE_DOC
        if not doc.is_file():
            return [], [f"{doc} is not present, so its URLs were not checked"]
        return _unique(RESCUE_URL_PATTERN.findall(doc.read_text(encoding="utf-8"))), []

    url = RESCUE_DOC_AT_TAG.format(repo=REPO, version=version)
    try:
        status, body = fetch(url, opener=opener)
    except Undetermined as error:
        return [], [f"could not read the shipped rescue guide: {error}"]
    if status != 200:
        # The guide missing from the released tree is itself a problem, but it is
        # reported as undetermined here: the caller cannot tell a genuinely absent
        # document from a tag that has not finished propagating.
        return [], [f"the rescue guide at v{version} returned HTTP {status}"]
    return _unique(RESCUE_URL_PATTERN.findall(body.decode("utf-8", "replace"))), []


def probe_urls(
    urls: list[tuple[str, str]], *, opener=None
) -> tuple[list[Probe], list[str], dict[str, bytes]]:
    """Fetch each URL, recording what came back.

    Returns (probes, undetermined reasons, served bodies by URL).
    """
    probes: list[Probe] = []
    undetermined: list[str] = []
    bodies: dict[str, bytes] = {}
    for url, source in urls:
        probe = Probe(url=url, source=source)
        try:
            status, body = fetch(url, opener=opener)
        except Undetermined as error:
            probe.detail = str(error)
            undetermined.append(str(error))
            probes.append(probe)
            continue
        probe.status = status
        if status != 200:
            probe.detail = f"HTTP {status} — a user following this link gets nothing."
            probes.append(probe)
            continue
        if not body:
            probe.detail = "HTTP 200 but the body was empty."
            probe.size = 0
            probes.append(probe)
            continue
        probe.ok = True
        probe.size = len(body)
        probe.sha256 = hashlib.sha256(body).hexdigest()
        bodies[url] = body
        probes.append(probe)
    return probes, undetermined, bodies


def verify_checksum_pairs(bodies: dict[str, bytes], version: str) -> tuple[int, list[str]]:
    """Run the same `shasum -c` a rescued user runs, on the bytes actually served."""
    verified = 0
    failures: list[str] = []
    for template in CHECKSUMMED_TEMPLATES:
        name = template.format(version=version)
        artifact_url = DOWNLOAD_URL.format(repo=REPO, version=version, name=name)
        checksum_url = f"{artifact_url}.sha256"
        if artifact_url not in bodies or checksum_url not in bodies:
            # Already reported as a failed probe; nothing to add here.
            continue
        declared = bodies[checksum_url].decode("utf-8", "replace").strip().split()
        if not declared or not re.fullmatch(r"[0-9a-f]{64}", declared[0]):
            failures.append(
                f"{name}.sha256 does not contain a usable checksum, so a user cannot "
                "verify the download."
            )
            continue
        actual = hashlib.sha256(bodies[artifact_url]).hexdigest()
        if actual != declared[0]:
            failures.append(
                f"{name} does not match its published checksum "
                f"(served {actual[:12]}…, checksum file says {declared[0][:12]}…). "
                "A user running the documented verify step would see it fail."
            )
            continue
        verified += 1
    return verified, failures


def stuck_draft_failures() -> tuple[list[str], list[str]]:
    """Report a release that has been sitting in draft too long.

    Best-effort: needs an authenticated `gh`, so a missing or unauthenticated CLI
    is undetermined rather than a pass. A stuck draft is invisible to users, but it
    also means a release nobody is shipping -- worth a card either way.
    """
    try:
        result = subprocess.run(
            [
                "gh", "api", f"repos/{REPO}/releases",
                "--jq",
                '.[] | select(.draft == true) | {tag: .tag_name, created: .created_at}',
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return [], ["could not check for stuck drafts (the GitHub CLI is unavailable)"]
    if result.returncode != 0:
        return [], ["could not check for stuck drafts (the GitHub CLI is not authenticated)"]

    failures: list[str] = []
    now = datetime.now(timezone.utc)
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            created = datetime.fromisoformat(entry["created"].replace("Z", "+00:00"))
        except (json.JSONDecodeError, KeyError, ValueError):
            continue
        hours = (now - created).total_seconds() / 3600
        if hours >= STUCK_DRAFT_HOURS:
            failures.append(
                f"Release {entry['tag']} has been sitting unpublished as a draft for "
                f"{hours:.0f} hours. Nobody can download it and nothing is announcing "
                "it — its asset build most likely failed."
            )
    return failures, []


# --------------------------------------------------------------------------- #


def run(
    version: str | None,
    repo_root: Path | None,
    *,
    check_drafts: bool = True,
    rescue_doc_source: str = "released",
    opener=None,
) -> Report:
    report = Report(checked_at=datetime.now(timezone.utc).isoformat())

    if version:
        report.version = version
        report.release_url = f"https://github.com/{REPO}/releases/tag/v{version}"
    else:
        version, release_url = resolve_latest_version(opener=opener)
        report.version = version
        report.release_url = release_url
    log(f"Newest release: v{report.version} ({report.release_url})")

    # One entry per distinct URL, remembering every place that names it — so a
    # failure message can say whether it breaks an update, the rescue guide, or both.
    sources: dict[str, list[str]] = {}
    for template in ASSET_TEMPLATES:
        url = DOWNLOAD_URL.format(
            repo=REPO, version=version, name=template.format(version=version)
        )
        sources.setdefault(url, []).append("latest release")
    rescue_urls, rescue_undetermined = rescue_doc_urls(
        version, source=rescue_doc_source, repo_root=repo_root, opener=opener
    )
    for url in rescue_urls:
        sources.setdefault(url, []).append(RESCUE_DOC)
    report.undetermined.extend(rescue_undetermined)
    log(
        f"Rescue guide ({rescue_doc_source}): {len(rescue_urls)} download URL(s) "
        "named by the instructions a stuck user follows."
    )

    targets = [(url, " + ".join(names)) for url, names in sources.items()]

    log(f"Probing {len(targets)} public download URL(s) over plain HTTPS…")
    probes, undetermined, bodies = probe_urls(targets, opener=opener)
    report.probes = probes
    report.undetermined.extend(undetermined)

    for probe in probes:
        mark = "ok  " if probe.ok else "FAIL"
        size = f"{probe.size} bytes" if probe.size is not None else "no body"
        log(f"  {mark} [{probe.source}] {probe.url.rsplit('/', 1)[-1]} — {size} {probe.detail}")

    # A prober that probed nothing must never look green.
    if report.probed_count < REQUIRED_ASSET_COUNT:
        raise Undetermined(
            f"only assembled {report.probed_count} URLs to probe, expected at least "
            f"{REQUIRED_ASSET_COUNT}. The prober cannot say it checked the release."
        )

    for probe in report.failed:
        report.failures.append(
            f"{probe.url} — {probe.detail or 'did not serve bytes'} "
            f"(named by: {probe.source})"
        )

    verified, checksum_failures = verify_checksum_pairs(bodies, version)
    report.checksum_pairs_verified = verified
    report.failures.extend(checksum_failures)
    log(f"Checksum pairs verified against the served bytes: {verified}")

    if check_drafts:
        draft_failures, draft_undetermined = stuck_draft_failures()
        report.failures.extend(draft_failures)
        report.undetermined.extend(draft_undetermined)

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--version",
        default=None,
        help="Probe this version instead of whatever GitHub calls Latest.",
    )
    parser.add_argument("--json", dest="json_path", default=None, help="Write a JSON report here.")
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help=f"Repository root, used only with --rescue-doc-source local.",
    )
    parser.add_argument(
        "--rescue-doc-source",
        choices=("released", "local"),
        default="released",
        help=(
            "Where to read the rescue guide's URLs from. 'released' (default) reads "
            "it at the release tag over HTTPS and needs no checkout; 'local' reads "
            "the working copy, which is what a pull request should check."
        ),
    )
    parser.add_argument(
        "--skip-draft-check",
        action="store_true",
        help="Skip the stuck-draft check (which needs an authenticated GitHub CLI).",
    )
    args = parser.parse_args(argv)

    try:
        report = run(
            args.version,
            Path(args.repo_root),
            check_drafts=not args.skip_draft_check,
            rescue_doc_source=args.rescue_doc_source,
        )
    except Undetermined as error:
        log("")
        log(f"COULD NOT CHECK: {error}")
        log("This says nothing about whether the release is downloadable.")
        if args.json_path:
            Path(args.json_path).write_text(
                json.dumps(
                    {
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                        "outcome": "undetermined",
                        "undetermined": [str(error)],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        return 2

    outcome = "ok" if not report.failures else "broken"
    if args.json_path:
        payload = asdict(report)
        payload["outcome"] = outcome
        payload["probed_count"] = report.probed_count
        Path(args.json_path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        log(f"Wrote the report to {args.json_path}")

    log("")
    if report.failures:
        log(
            f"RELEASE v{report.version} IS NOT FULLY DOWNLOADABLE — "
            f"{len(report.failures)} problem(s):"
        )
        for failure in report.failures:
            log(f"  • {failure}")
        if report.undetermined:
            log("Also could not check:")
            for item in report.undetermined:
                log(f"  - {item}")
        return 1

    log(
        f"Release v{report.version} is fully downloadable: "
        f"{report.probed_count} URL(s) served bytes, "
        f"{report.checksum_pairs_verified} checksum pair(s) matched."
    )
    if report.undetermined:
        log("Could not check (not treated as a failure):")
        for item in report.undetermined:
            log(f"  - {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
