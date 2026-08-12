"""Draft-first publishing: a release cannot go public before its assets are proven.

These tests drive scripts/release_publish.py against a fake GitHub CLI, so the
ordering that matters -- attach, verify, and only then flip public -- is exercised
without a network or a real release. The ordering is the whole point: on 2026-08-11
v1.94.0 was public with zero assets for about ninety minutes because publishing and
attaching were independent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import release_publish as rp

VERSION = "9.9.9"
TAG = f"v{VERSION}"


# --------------------------------------------------------------------------- #
# A fake gh that models a release well enough to catch ordering mistakes
# --------------------------------------------------------------------------- #


class FakeRelease:
    def __init__(self, *, draft: bool = True, prerelease: bool = False, body: str = ""):
        self.draft = draft
        self.prerelease = prerelease
        self.body = body
        self.assets: dict[str, bytes] = {}


class FakeGh:
    """Records every call, and refuses to serve bytes that were never uploaded."""

    def __init__(self, *, releases: dict[str, FakeRelease] | None = None, repo=None):
        self.repo = repo
        self.releases = releases or {}
        self.calls: list[list[str]] = []
        # Set to a name to simulate an upload that reports success but leaves a
        # truncated asset -- the failure asset-name-presence checks cannot see.
        self.truncate_on_readback: str | None = None
        self.fleet_running = False

    # -- helpers -----------------------------------------------------------
    def _result(self, code: int, out: str = "", err: str = "") -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=["gh"], returncode=code, stdout=out, stderr=err)

    def run(self, args, *, check=True):
        self.calls.append(list(args))
        if args[:2] == ["run", "list"]:
            payload = [{"databaseId": 1}] if self.fleet_running else []
            return self._result(0, json.dumps(payload))
        raise AssertionError(f"unexpected gh call: {args}")

    def release(self, args, *, check=True):
        self.calls.append(["release"] + list(args))
        action, tag = args[0], args[1]
        release = self.releases.get(tag)

        if action == "view":
            if release is None:
                return self._result(1, err="release not found")
            return self._result(
                0,
                json.dumps(
                    {
                        "isDraft": release.draft,
                        "isPrerelease": release.prerelease,
                        "body": release.body,
                        "assets": [
                            {
                                "name": name,
                                "size": len(data),
                                "state": "uploaded",
                                "apiUrl": f"fake://{tag}/{name}",
                            }
                            for name, data in release.assets.items()
                        ],
                    }
                ),
            )

        if action == "create":
            assert "--draft" in args, "a release must never be created already public"
            body = ""
            if "--notes-file" in args:
                body = Path(args[args.index("--notes-file") + 1]).read_text(encoding="utf-8")
            self.releases[tag] = FakeRelease(
                draft=True, prerelease="--prerelease" in args, body=body
            )
            return self._result(0)

        if action == "upload":
            assert release is not None
            for token in args[2:]:
                if token.startswith("--"):
                    continue
                path = Path(token)
                release.assets[path.name] = path.read_bytes()
            return self._result(0)

        if action == "edit":
            assert release is not None
            if "--notes-file" in args:
                release.body = Path(
                    args[args.index("--notes-file") + 1]
                ).read_text(encoding="utf-8")
            if "--draft=false" in args:
                release.draft = False
            if "--prerelease=false" in args:
                release.prerelease = False
            elif "--prerelease" in args:
                release.prerelease = True
            return self._result(0)

        raise AssertionError(f"unexpected gh release call: {args}")

    def download_asset(self, api_url: str, destination: Path) -> None:
        self.calls.append(["download", api_url])
        tag, name = api_url.removeprefix("fake://").split("/", 1)
        data = self.releases[tag].assets[name]
        if self.truncate_on_readback == name:
            data = data[: max(0, len(data) - 1)]
        destination.write_bytes(data)

    # -- assertions used by tests -----------------------------------------
    def flipped_public(self) -> bool:
        return any(
            call[0] == "release" and call[1] == "edit" and "--draft=false" in call
            for call in self.calls
        )

    def index_of(self, predicate) -> int:
        for index, call in enumerate(self.calls):
            if predicate(call):
                return index
        return -1


def _write_dist(tmp_path: Path, version: str = VERSION) -> Path:
    """Build a dist directory shaped exactly like a real release build."""
    dist = tmp_path / "dist"
    dist.mkdir()
    payloads = {
        f"dex-vault-bundle-v{version}.tar.gz": b"tarball-bytes\x00\x01\x02",
        f"dex-update-bridge-v{version}.py": b"#!/usr/bin/env python3\nprint('bridge')\n",
    }
    for name, data in payloads.items():
        (dist / name).write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        (dist / f"{name}.sha256").write_text(f"{digest}  {name}\n", encoding="utf-8")
    return dist


def _publish_args(
    dist: Path,
    *,
    version: str = VERSION,
    channel: str = "stable",
    extra_asset: list[str] | None = None,
):
    return argparse.Namespace(
        repo=None,
        version=version,
        channel=channel,
        dist=str(dist),
        target="deadbeef",
        extra_asset=extra_asset or [],
    )


def _draft_args(changelog: Path, *, version: str = VERSION, channel: str = "stable"):
    return argparse.Namespace(
        repo=None, version=version, channel=channel, changelog=str(changelog), target="deadbeef"
    )


def _publish(args, gh: FakeGh) -> int:
    """Run the publish command the way main() does, mapping a refusal to exit 1.

    Production maps ReleasePublishError to a non-zero exit in main(); these tests
    assert on that exit code, so they have to go through the same mapping rather
    than a bare call.
    """
    try:
        return rp.command_publish(args, gh=gh)
    except rp.ReleasePublishError as error:
        rp.log(f"Release step stopped safely: {error}")
        return 1


def _draft(args, gh: FakeGh) -> int:
    try:
        return rp.command_draft(args, gh=gh)
    except rp.ReleasePublishError as error:
        rp.log(f"Release step stopped safely: {error}")
        return 1


# --------------------------------------------------------------------------- #
# The draft step
# --------------------------------------------------------------------------- #


def test_draft_creates_a_hidden_release_carrying_the_changelog(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        f"# Changelog\n\n---\n\n## [{VERSION}] — (2026-08-11)\n\nReal notes here.\n\n"
        "## [9.9.8] — (2026-08-10)\n\nOlder notes.\n",
        encoding="utf-8",
    )
    gh = FakeGh()

    assert _draft(_draft_args(changelog), gh) == 0

    release = gh.releases[TAG]
    assert release.draft is True, "the draft step must never publish"
    assert "Real notes here." in release.body
    assert "Older notes." not in release.body, "only this version's section belongs"
    assert rp.NOTE_START in release.body
    assert "not public yet" in release.body
    assert not gh.flipped_public()


def test_draft_refuses_to_unpublish_an_already_public_release(tmp_path: Path) -> None:
    """Re-running the tag workflow must never pull a live release back into draft."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(f"---\n\n## [{VERSION}] — (2026-08-11)\n\nNotes.\n", encoding="utf-8")
    live = FakeRelease(draft=False, body="the published notes")
    live.assets = {name: b"x" for name in rp.asset_names(VERSION)}
    gh = FakeGh(releases={TAG: live})

    assert _draft(_draft_args(changelog), gh) == 0

    assert live.draft is False, "a public release must stay public"
    assert live.body == "the published notes", "a public release's notes must be untouched"
    assert not any(call[:2] == ["release", "edit"] for call in gh.calls)


def test_draft_says_so_when_it_is_queued_behind_the_fleet_proof(tmp_path: Path) -> None:
    """The fleet proof holds the single publish lane for hours; the draft explains it."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(f"---\n\n## [{VERSION}] — (2026-08-11)\n\nNotes.\n", encoding="utf-8")
    gh = FakeGh()
    gh.fleet_running = True

    assert _draft(_draft_args(changelog), gh) == 0

    body = gh.releases[TAG].body
    assert "macOS updater proof" in body
    assert "queued behind it" in body


def test_draft_without_the_fleet_running_omits_the_queue_note(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(f"---\n\n## [{VERSION}] — (2026-08-11)\n\nNotes.\n", encoding="utf-8")
    gh = FakeGh()
    gh.fleet_running = False

    _draft(_draft_args(changelog), gh)

    assert "macOS updater proof" not in gh.releases[TAG].body


# --------------------------------------------------------------------------- #
# The publish step
# --------------------------------------------------------------------------- #


def test_publish_attaches_verifies_then_flips_public_in_that_order(tmp_path: Path) -> None:
    dist = _write_dist(tmp_path)
    gh = FakeGh(releases={TAG: FakeRelease(draft=True, body=f"Notes\n\n{rp.build_note(VERSION, queued_behind_fleet=False)}\n")})

    assert _publish(_publish_args(dist), gh) == 0

    upload_at = gh.index_of(lambda c: c[:2] == ["release", "upload"])
    readback_at = gh.index_of(lambda c: c[0] == "download")
    flip_at = gh.index_of(lambda c: c[:2] == ["release", "edit"] and "--draft=false" in c)

    assert upload_at >= 0 and readback_at >= 0 and flip_at >= 0
    assert upload_at < readback_at < flip_at, (
        "the flip to public must come after the assets are attached AND read back; "
        f"saw upload={upload_at} readback={readback_at} flip={flip_at}"
    )

    release = gh.releases[TAG]
    assert release.draft is False
    assert set(release.assets) == set(rp.asset_names(VERSION))
    assert rp.NOTE_START not in release.body, "the not-public-yet note must be removed"
    assert "Notes" in release.body, "the CHANGELOG notes must survive the flip"


def test_publish_never_flips_public_when_an_asset_is_missing(tmp_path: Path) -> None:
    dist = _write_dist(tmp_path)
    (dist / f"dex-update-bridge-v{VERSION}.py").unlink()
    gh = FakeGh(releases={TAG: FakeRelease(draft=True)})

    assert _publish(_publish_args(dist), gh) == 1
    assert gh.releases[TAG].draft is True, "a failed publish must leave a hidden draft"
    assert not gh.flipped_public()


def test_publish_never_flips_public_when_a_checksum_does_not_match(tmp_path: Path) -> None:
    dist = _write_dist(tmp_path)
    (dist / f"dex-vault-bundle-v{VERSION}.tar.gz.sha256").write_text(
        f"{'0' * 64}  dex-vault-bundle-v{VERSION}.tar.gz\n", encoding="utf-8"
    )
    gh = FakeGh(releases={TAG: FakeRelease(draft=True)})

    assert _publish(_publish_args(dist), gh) == 1
    assert gh.releases[TAG].draft is True
    assert not gh.flipped_public()


def test_publish_catches_an_asset_that_uploaded_but_serves_wrong_bytes(tmp_path: Path) -> None:
    """A truncated upload still appears by name. Only reading it back finds it."""
    dist = _write_dist(tmp_path)
    gh = FakeGh(releases={TAG: FakeRelease(draft=True)})
    gh.truncate_on_readback = f"dex-vault-bundle-v{VERSION}.tar.gz"

    assert _publish(_publish_args(dist), gh) == 1
    assert gh.releases[TAG].draft is True, "an unverifiable asset must not go public"
    assert not gh.flipped_public()


def test_publish_creates_a_draft_when_the_tag_workflow_never_ran(tmp_path: Path) -> None:
    """Belt and braces: assets still land on a hidden release, never a public one."""
    dist = _write_dist(tmp_path)
    gh = FakeGh()

    assert _publish(_publish_args(dist), gh) == 0

    create = next(c for c in gh.calls if c[:2] == ["release", "create"])
    assert "--draft" in create
    create_at = gh.calls.index(create)
    flip_at = gh.index_of(lambda c: c[:2] == ["release", "edit"] and "--draft=false" in c)
    assert create_at < flip_at


def test_publish_repairs_a_release_that_was_already_public(tmp_path: Path, capsys) -> None:
    """A release cut before this change can still be filled in, with a warning."""
    dist = _write_dist(tmp_path)
    gh = FakeGh(releases={TAG: FakeRelease(draft=False, body="live notes")})

    assert _publish(_publish_args(dist), gh) == 0
    assert set(gh.releases[TAG].assets) == set(rp.asset_names(VERSION))
    assert "ALREADY PUBLIC" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# The beta lane's two safety guards, which used to live only in workflow bash
# --------------------------------------------------------------------------- #


def test_beta_lane_refuses_a_stable_version_number(tmp_path: Path) -> None:
    """A bare X.Y.Z from the beta branch could publish over a real stable release."""
    dist = _write_dist(tmp_path)
    gh = FakeGh()

    assert _publish(_publish_args(dist, channel="beta"), gh) == 1
    assert gh.calls == [], "it must refuse before touching GitHub at all"


def test_beta_lane_refuses_to_clobber_a_promoted_release(tmp_path: Path) -> None:
    beta_version = "9.9.9-beta.1"
    dist = _write_dist(tmp_path, version=beta_version)
    promoted = FakeRelease(draft=True, prerelease=False)
    gh = FakeGh(releases={f"v{beta_version}": promoted})

    result = _publish(_publish_args(dist, version=beta_version, channel="beta"), gh)

    assert result == 1
    assert not any(c[:2] == ["release", "upload"] for c in gh.calls), (
        "it must refuse before uploading anything"
    )


def test_beta_lane_publishes_as_a_prerelease(tmp_path: Path) -> None:
    beta_version = "9.9.9-beta.1"
    dist = _write_dist(tmp_path, version=beta_version)
    gh = FakeGh(releases={f"v{beta_version}": FakeRelease(draft=True, prerelease=True)})

    assert _publish(_publish_args(dist, version=beta_version, channel="beta"), gh) == 0

    release = gh.releases[f"v{beta_version}"]
    assert release.draft is False
    assert release.prerelease is True, "a beta release must stay marked as a prerelease"


# --------------------------------------------------------------------------- #
# Small pure pieces
# --------------------------------------------------------------------------- #


def test_strip_note_leaves_human_written_body_intact() -> None:
    note = rp.build_note("1.2.3", queued_behind_fleet=True)
    body = f"## What changed\n\nA real entry.\n\n{note}\n"
    stripped = rp.strip_note(body)
    assert "A real entry." in stripped
    assert rp.NOTE_START not in stripped
    assert "macOS updater proof" not in stripped


def test_strip_note_is_idempotent_and_safe_on_a_body_without_a_note() -> None:
    assert rp.strip_note("just notes\n").strip() == "just notes"
    assert rp.strip_note("") == ""


@pytest.mark.parametrize(
    "version,channel,ok",
    [
        ("1.94.0", "stable", True),
        ("1.94.0-beta.1", "stable", False),
        ("1.94.0-beta.1", "beta", True),
        ("1.94.0", "beta", False),
        ("01.9.0", "stable", False),
    ],
)
def test_validate_version_separates_the_channels(version: str, channel: str, ok: bool) -> None:
    if ok:
        rp.validate_version(version, channel)
    else:
        with pytest.raises(rp.ReleasePublishError):
            rp.validate_version(version, channel)


def test_expected_digest_rejects_a_checksum_file_that_is_not_a_checksum(tmp_path: Path) -> None:
    bad = tmp_path / "x.sha256"
    bad.write_text("not-a-digest  x\n", encoding="utf-8")
    with pytest.raises(rp.ReleasePublishError):
        rp.expected_digest(bad)


def test_asset_list_is_the_four_files_dex_installs_fetch() -> None:
    assert rp.asset_names("1.2.3") == [
        "dex-vault-bundle-v1.2.3.tar.gz",
        "dex-vault-bundle-v1.2.3.tar.gz.sha256",
        "dex-update-bridge-v1.2.3.py",
        "dex-update-bridge-v1.2.3.py.sha256",
    ]
    assert rp.REQUIRED_ASSET_COUNT == 4


# --------------------------------------------------------------------------- #
# Extra assets (the signed Dex Lens catalogue) ride the same verified path
# --------------------------------------------------------------------------- #


def test_extra_assets_are_attached_and_verified_before_the_flip(tmp_path: Path) -> None:
    """Nothing may appear on a release after it has gone public."""
    dist = _write_dist(tmp_path)
    catalogue = dist / f"dex-lens-catalog-v{VERSION}.json"
    catalogue.write_text('{"catalogue": true}', encoding="utf-8")
    gh = FakeGh(releases={TAG: FakeRelease(draft=True)})

    assert _publish(_publish_args(dist, extra_asset=[str(catalogue)]), gh) == 0

    release = gh.releases[TAG]
    assert catalogue.name in release.assets, "the extra asset must be attached"
    assert release.draft is False

    readback_at = gh.index_of(lambda c: c[0] == "download" and catalogue.name in c[1])
    flip_at = gh.index_of(lambda c: c[:2] == ["release", "edit"] and "--draft=false" in c)
    assert readback_at >= 0, "an extra asset must be read back like any other"
    assert readback_at < flip_at, "extras must be proven before the release goes public"


def test_a_missing_extra_asset_stops_the_release_going_public(tmp_path: Path) -> None:
    dist = _write_dist(tmp_path)
    gh = FakeGh(releases={TAG: FakeRelease(draft=True)})

    result = _publish(
        _publish_args(dist, extra_asset=[str(dist / "never-built.json")]), gh
    )

    assert result == 1
    assert gh.releases[TAG].draft is True
    assert not gh.flipped_public()


def test_an_empty_extra_asset_stops_the_release_going_public(tmp_path: Path) -> None:
    dist = _write_dist(tmp_path)
    empty = dist / f"dex-lens-catalog-v{VERSION}.json"
    empty.write_bytes(b"")
    gh = FakeGh(releases={TAG: FakeRelease(draft=True)})

    assert _publish(_publish_args(dist, extra_asset=[str(empty)]), gh) == 1
    assert gh.releases[TAG].draft is True


def test_the_four_required_assets_are_still_required_when_extras_are_present(
    tmp_path: Path,
) -> None:
    """An extra asset must never be able to stand in for a missing required one."""
    dist = _write_dist(tmp_path)
    (dist / f"dex-update-bridge-v{VERSION}.py").unlink()
    catalogue = dist / f"dex-lens-catalog-v{VERSION}.json"
    catalogue.write_text("{}", encoding="utf-8")
    gh = FakeGh(releases={TAG: FakeRelease(draft=True)})

    assert _publish(_publish_args(dist, extra_asset=[str(catalogue)]), gh) == 1
    assert gh.releases[TAG].draft is True
