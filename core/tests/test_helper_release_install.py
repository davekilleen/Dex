"""Install Dex Helper from a pinned zip without writing inside the app."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from core.utils import macos_privacy_helper as helper


def _native_app(root: Path, version: str = "1.1.0") -> Path:
    app = root / "Dex Helper.app"
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    (macos / "DexHelper").write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 24)
    (macos / "DexHelper").chmod(0o755)
    (app / "Contents" / "Info.plist").write_text(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<plist version=\"1.0\"><dict>"
        f"<key>CFBundleIdentifier</key><string>{helper.HELPER_BUNDLE_ID}</string>"
        f"<key>CFBundleShortVersionString</key><string>{version}</string>"
        "</dict></plist>\n",
        encoding="utf-8",
    )
    (app / "Contents" / "Resources").mkdir(parents=True, exist_ok=True)
    return app


def _zip_app(app: Path, zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in app.rglob("*"):
            archive.write(path, path.relative_to(app.parent))
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    return digest


def test_checksum_mismatch_refuses_to_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    app = _native_app(tmp_path / "src")
    zip_path = tmp_path / "DexHelper-v1.1.0.zip"
    _zip_app(app, zip_path)
    destination = tmp_path / "Applications" / "Dex Helper.app"
    result = helper.install_or_update_helper_from_release(
        vault_root=tmp_path / "vault",
        manifest={
            "helper_version": "1.1.0",
            "bundle_id": helper.HELPER_BUNDLE_ID,
            "team_id": helper.HELPER_TEAM_ID,
            "asset_name": zip_path.name,
            "sha256": "0" * 64,
        },
        zip_path=zip_path,
        destination_app=destination,
        support_dir=tmp_path / "support",
    )
    assert result["ok"] is False
    assert result["reason"] == "checksum_mismatch"
    assert not destination.exists()


def test_verified_zip_copies_the_whole_app_and_does_not_write_inside_it(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    monkeypatch.setattr(
        helper,
        "read_signing_identity",
        lambda _app: {
            "kind": "developer_id",
            "team_id": helper.HELPER_TEAM_ID,
            "bundle_id": helper.HELPER_BUNDLE_ID,
        },
    )
    monkeypatch.setattr(helper, "_verify_release_app", lambda *_args, **_kwargs: None)
    app = _native_app(tmp_path / "src")
    zip_path = tmp_path / "DexHelper-v1.1.0.zip"
    digest = _zip_app(app, zip_path)
    destination = tmp_path / "Applications" / "Dex Helper.app"
    result = helper.install_or_update_helper_from_release(
        vault_root=tmp_path / "vault",
        manifest={
            "helper_version": "1.1.0",
            "bundle_id": helper.HELPER_BUNDLE_ID,
            "team_id": helper.HELPER_TEAM_ID,
            "asset_name": zip_path.name,
            "sha256": digest,
        },
        zip_path=zip_path,
        destination_app=destination,
        support_dir=tmp_path / "support",
    )
    assert result["ok"] is True
    assert destination.is_dir()
    assert helper.read_installed_version(destination) == "1.1.0"
    assert not (destination / "Contents" / "Resources" / "dex-root.txt").exists()
    record = tmp_path / "vault" / "System" / ".dex" / "helpers" / "installed.json"
    assert json.loads(record.read_text(encoding="utf-8"))["version"] == "1.1.0"


def test_rollback_restores_previous_app(tmp_path, monkeypatch):
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    current = _native_app(tmp_path / "current", "1.1.0")
    previous_src = _native_app(tmp_path / "previous-src", "1.0.1")
    destination = tmp_path / "Applications" / "Dex Helper.app"
    helper.shutil.copytree(current, destination)
    support = tmp_path / "support"
    previous = support / "previous" / helper.HELPER_APP_NAME
    previous.parent.mkdir(parents=True)
    helper.shutil.copytree(previous_src, previous)
    result = helper.rollback_helper(
        destination_app=destination,
        support_dir=support,
        vault_root=tmp_path / "vault",
    )
    assert result["ok"] is True
    assert helper.read_installed_version(destination) == "1.0.1"


def test_empty_sha256_is_not_a_download(monkeypatch):
    called = []

    def fail_download(*_args, **_kwargs):
        called.append(True)
        raise AssertionError("must not download")

    monkeypatch.setattr(helper.sys, "platform", "darwin")
    monkeypatch.setattr(helper, "_download_helper_zip", fail_download)
    result = helper.install_or_update_helper_from_release(
        manifest={"sha256": "", "helper_version": "1.1.0"}
    )
    assert result["reason"] == "not_in_release"
    assert called == []
