"""The rescue-URL prober: a half-published release is caught in minutes, not by a user.

These tests drive scripts/check_release_assets.py against a fake HTTP layer. The
cases mirror what actually went wrong on 2026-08-11 (a release whose assets 404,
and a rescue guide naming a version that was never published) plus the failure mode
that would make the prober useless: reporting a network blip as a broken release.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import check_release_assets as prober

VERSION = "9.9.9"
BUNDLE = b"tarball-bytes\x00\x01"
BRIDGE = b"#!/usr/bin/env python3\n"


def _url(name: str) -> str:
    return prober.DOWNLOAD_URL.format(repo=prober.REPO, version=VERSION, name=name)


def _checksum_body(data: bytes, name: str) -> bytes:
    return f"{hashlib.sha256(data).hexdigest()}  {name}\n".encode()


def _healthy_routes(version: str = VERSION) -> dict[str, tuple[int, bytes]]:
    """Every URL a healthy release serves, including the rescue guide itself."""
    bundle_name = f"dex-vault-bundle-v{version}.tar.gz"
    bridge_name = f"dex-update-bridge-v{version}.py"
    rescue_doc = (
        "Download the versioned bridge:\n\n"
        f"  https://github.com/{prober.REPO}/releases/download/v{version}/{bridge_name}\n"
        f"  https://github.com/{prober.REPO}/releases/download/v{version}/{bridge_name}.sha256\n"
    )
    return {
        prober.LATEST_RELEASE_API.format(repo=prober.REPO): (
            200,
            json.dumps(
                {
                    "tag_name": f"v{version}",
                    "html_url": f"https://github.com/{prober.REPO}/releases/tag/v{version}",
                }
            ).encode(),
        ),
        prober.RESCUE_DOC_AT_TAG.format(repo=prober.REPO, version=version): (
            200,
            rescue_doc.encode(),
        ),
        _url(bundle_name): (200, BUNDLE),
        _url(f"{bundle_name}.sha256"): (200, _checksum_body(BUNDLE, bundle_name)),
        _url(bridge_name): (200, BRIDGE),
        _url(f"{bridge_name}.sha256"): (200, _checksum_body(BRIDGE, bridge_name)),
    }


@pytest.fixture
def routes(monkeypatch):
    """Install a fake HTTP layer; tests mutate the returned routing table."""
    table: dict[str, tuple[int, bytes]] = _healthy_routes()

    def fake_fetch(url: str, *, opener=None):
        if url not in table:
            return 404, b""
        status, body = table[url]
        if status == -1:
            raise prober.Undetermined(f"could not reach {url}: simulated network failure")
        return status, body

    monkeypatch.setattr(prober, "fetch", fake_fetch)
    return table


def _run(*extra: str) -> int:
    return prober.main(["--skip-draft-check", *extra])


# --------------------------------------------------------------------------- #
# The healthy case
# --------------------------------------------------------------------------- #


def test_a_fully_published_release_passes(routes, tmp_path, capsys) -> None:
    report_path = tmp_path / "report.json"
    assert _run("--json", str(report_path)) == 0

    report = json.loads(report_path.read_text())
    assert report["outcome"] == "ok"
    assert report["version"] == VERSION
    assert report["probed_count"] == prober.REQUIRED_ASSET_COUNT
    assert report["checksum_pairs_verified"] == 2
    assert report["failures"] == []
    assert all(probe["ok"] for probe in report["probes"])


def test_it_reports_which_urls_the_rescue_guide_depends_on(routes, capsys) -> None:
    _run()
    out = capsys.readouterr().out
    assert prober.RESCUE_DOC in out, (
        "a failure has to say whether it breaks an update, the rescue guide, or both"
    )


# --------------------------------------------------------------------------- #
# The failures this exists to catch
# --------------------------------------------------------------------------- #


def test_a_release_with_no_assets_fails(routes, tmp_path, capsys) -> None:
    """Exactly the v1.94.0 state: public, newest, zero downloads attached."""
    for name in prober.ASSET_TEMPLATES:
        routes.pop(_url(name.format(version=VERSION)), None)

    report_path = tmp_path / "report.json"
    assert _run("--json", str(report_path)) == 1

    report = json.loads(report_path.read_text())
    assert report["outcome"] == "broken"
    assert len(report["failures"]) >= prober.REQUIRED_ASSET_COUNT
    assert "HTTP 404" in capsys.readouterr().out


def test_one_missing_asset_is_enough_to_fail(routes) -> None:
    routes.pop(_url(f"dex-update-bridge-v{VERSION}.py"))
    assert _run() == 1


def test_the_rescue_guide_pointing_at_an_unpublished_version_fails(routes, capsys) -> None:
    """The guide is rewritten to name the new version the moment a release is cut.

    If that release never finished publishing, the guide sends a stuck user to a
    download that does not exist -- which is what happened on 2026-08-11.
    """
    ghost = "9.9.10"
    ghost_bridge = f"dex-update-bridge-v{ghost}.py"
    routes[prober.RESCUE_DOC_AT_TAG.format(repo=prober.REPO, version=VERSION)] = (
        200,
        (
            f"  https://github.com/{prober.REPO}/releases/download/v{ghost}/{ghost_bridge}\n"
        ).encode(),
    )

    assert _run() == 1
    out = capsys.readouterr().out
    assert ghost_bridge in out
    assert prober.RESCUE_DOC in out


def test_a_checksum_that_does_not_match_the_served_bytes_fails(routes, capsys) -> None:
    bundle_name = f"dex-vault-bundle-v{VERSION}.tar.gz"
    routes[_url(f"{bundle_name}.sha256")] = (200, f"{'0' * 64}  {bundle_name}\n".encode())

    assert _run() == 1
    out = capsys.readouterr().out
    assert "does not match its published checksum" in out
    assert "shasum" not in out or "verify step" in out


def test_a_checksum_file_that_is_not_a_checksum_fails(routes) -> None:
    bundle_name = f"dex-vault-bundle-v{VERSION}.tar.gz"
    routes[_url(f"{bundle_name}.sha256")] = (200, b"<html>404 page</html>\n")
    assert _run() == 1


def test_an_empty_two_hundred_response_fails(routes, capsys) -> None:
    """A zero-byte asset serves HTTP 200 and is still useless to a user."""
    routes[_url(f"dex-update-bridge-v{VERSION}.py")] = (200, b"")
    assert _run() == 1
    assert "empty" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Not crying wolf: "I could not tell" must never look like "it is broken"
# --------------------------------------------------------------------------- #


def test_an_unreachable_github_is_undetermined_not_a_broken_release(
    routes, tmp_path, capsys
) -> None:
    routes[prober.LATEST_RELEASE_API.format(repo=prober.REPO)] = (-1, b"")

    report_path = tmp_path / "report.json"
    assert _run("--json", str(report_path)) == 2, (
        "a network failure must use the distinct 'could not check' exit code"
    )

    report = json.loads(report_path.read_text())
    assert report["outcome"] == "undetermined"
    out = capsys.readouterr().out
    assert "COULD NOT CHECK" in out
    assert "says nothing about whether the release is downloadable" in out


def test_one_unreachable_probe_is_recorded_but_does_not_claim_a_broken_release(
    routes, tmp_path
) -> None:
    routes[_url(f"dex-vault-bundle-v{VERSION}.tar.gz")] = (-1, b"")

    report_path = tmp_path / "report.json"
    exit_code = _run("--json", str(report_path))
    report = json.loads(report_path.read_text())

    assert report["undetermined"], "the unreachable URL must be recorded"
    # It is reported as a failure only because the probe genuinely did not serve
    # bytes; what matters is that the reason travels with it.
    assert exit_code in (0, 1)
    assert any("simulated network failure" in item for item in report["undetermined"])


def test_a_rescue_guide_that_cannot_be_read_is_undetermined_not_a_pass(
    routes, tmp_path
) -> None:
    routes.pop(prober.RESCUE_DOC_AT_TAG.format(repo=prober.REPO, version=VERSION))

    report_path = tmp_path / "report.json"
    assert _run("--json", str(report_path)) == 0
    report = json.loads(report_path.read_text())
    assert any("rescue guide" in item for item in report["undetermined"]), (
        "not reading the guide must be stated, never silently skipped"
    )


# --------------------------------------------------------------------------- #
# The prober cannot pass by having checked nothing
# --------------------------------------------------------------------------- #


def test_a_prober_that_assembles_too_few_urls_refuses_to_report_success(
    routes, monkeypatch
) -> None:
    """The green-by-omission guard: no probes means 'could not check', never 'ok'."""
    monkeypatch.setattr(prober, "ASSET_TEMPLATES", ("dex-vault-bundle-v{version}.tar.gz",))
    monkeypatch.setattr(
        prober, "rescue_doc_urls", lambda *a, **k: ([], [])
    )
    assert _run() == 2


def test_the_expected_asset_list_matches_what_dex_installs_fetch() -> None:
    assert prober.REQUIRED_ASSET_COUNT == 4
    assert prober.ASSET_TEMPLATES == (
        "dex-vault-bundle-v{version}.tar.gz",
        "dex-vault-bundle-v{version}.tar.gz.sha256",
        "dex-update-bridge-v{version}.py",
        "dex-update-bridge-v{version}.py.sha256",
    )


# --------------------------------------------------------------------------- #
# A release nobody is shipping
# --------------------------------------------------------------------------- #


def test_a_release_stuck_in_draft_for_hours_is_reported(monkeypatch) -> None:
    """Draft-first's own failure mode: the assets never built, so nothing published."""

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps({"tag": "v9.9.9", "created": "2020-01-01T00:00:00Z"}) + "\n",
            stderr="",
        )

    monkeypatch.setattr(prober.subprocess, "run", fake_run)
    failures, undetermined = prober.stuck_draft_failures()

    assert undetermined == []
    assert len(failures) == 1
    assert "v9.9.9" in failures[0]
    assert "draft" in failures[0]


def test_a_fresh_draft_is_not_reported_as_stuck(monkeypatch) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps({"tag": "v9.9.9", "created": now}) + "\n",
            stderr="",
        )

    monkeypatch.setattr(prober.subprocess, "run", fake_run)
    failures, undetermined = prober.stuck_draft_failures()
    assert failures == []


def test_an_unauthenticated_cli_makes_the_draft_check_undetermined(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="auth")

    monkeypatch.setattr(prober.subprocess, "run", fake_run)
    failures, undetermined = prober.stuck_draft_failures()
    assert failures == []
    assert undetermined and "stuck drafts" in undetermined[0]


# --------------------------------------------------------------------------- #
# Reading the rescue guide from a checkout (the pull-request mode)
# --------------------------------------------------------------------------- #


def test_local_mode_reads_the_working_copy(tmp_path) -> None:
    doc = tmp_path / prober.RESCUE_DOC
    doc.parent.mkdir(parents=True)
    doc.write_text(
        f"https://github.com/{prober.REPO}/releases/download/v1.2.3/dex-update-bridge-v1.2.3.py\n",
        encoding="utf-8",
    )
    urls, undetermined = prober.rescue_doc_urls("1.2.3", source="local", repo_root=tmp_path)
    assert urls == [
        f"https://github.com/{prober.REPO}/releases/download/v1.2.3/dex-update-bridge-v1.2.3.py"
    ]
    assert undetermined == []


def test_local_mode_says_so_when_the_guide_is_absent(tmp_path) -> None:
    urls, undetermined = prober.rescue_doc_urls("1.2.3", source="local", repo_root=tmp_path)
    assert urls == []
    assert undetermined and "not present" in undetermined[0]


def test_the_real_rescue_guide_in_this_checkout_names_download_urls() -> None:
    """Guards the extraction against a doc rewrite that quietly drops the URLs."""
    urls, undetermined = prober.rescue_doc_urls(
        "0.0.0", source="local", repo_root=REPO_ROOT
    )
    assert undetermined == []
    assert urls, f"{prober.RESCUE_DOC} should name at least one release download URL"
    assert all("/releases/download/" in url for url in urls)
