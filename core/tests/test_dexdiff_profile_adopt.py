"""Tests for core/dexdiff_profile_adopt.py."""

from __future__ import annotations

import importlib
import io
import json
import urllib.error
from pathlib import Path

import pytest

dexdiff_profile_adopt = importlib.import_module("core.dexdiff_profile_adopt")


def _configure_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dexdiff_profile_adopt, "VAULT_ROOT", tmp_path)
    monkeypatch.setattr(
        dexdiff_profile_adopt,
        "DEXDIFF_PROFILE_DRAFTS_DIR",
        tmp_path / "04-Projects" / "DexDiff" / "beta" / "profile",
    )
    monkeypatch.setattr(
        dexdiff_profile_adopt,
        "DEX_RUNTIME_DIR",
        tmp_path / "System" / ".dex",
    )
    monkeypatch.setattr(
        dexdiff_profile_adopt,
        "PROFILE_ADOPTIONS_DIR",
        tmp_path / "System" / ".dex" / "adoptions" / "profiles",
    )


def _bundle() -> dict:
    return {
        "contractVersion": "2026-04-10",
        "profile": {
            "handle": "dave",
            "displayName": "Dave Killeen",
            "role": "Field CPO, EMEA",
            "company": "Pendo",
        },
        "workflows": [
            {
                "diffId": "meeting-prep",
                "name": "Meeting Prep",
                "methodology": 'dexdiff_schema: "2.0"\nname: Meeting Prep\n',
            },
            {
                "diffId": "follow-through",
                "name": "Follow Through",
                "methodology": 'dexdiff_schema: "2.0"\nname: Follow Through\n',
            },
        ],
        "loveLetter": {
            "text": "Dex made my work calmer.",
        },
    }


def test_build_profile_bundle_url_trims_at_prefix():
    url = dexdiff_profile_adopt.build_profile_bundle_url("https://example.test/", "@dave")
    assert url == "https://example.test/api/profile-bundle?handle=dave"


def test_build_profile_bundle_url_defaults_to_api_host(monkeypatch):
    monkeypatch.delenv("DEXDIFF_API_BASE", raising=False)
    url = dexdiff_profile_adopt.build_profile_bundle_url(handle="@dave")
    assert url == "https://api.heydex.ai/api/profile-bundle?handle=dave"


def test_api_base_env_override(monkeypatch):
    monkeypatch.setenv("DEXDIFF_API_BASE", "http://127.0.0.1:9999/")
    url = dexdiff_profile_adopt.build_profile_bundle_url(handle="dave")
    assert url == "http://127.0.0.1:9999/api/profile-bundle?handle=dave"


@pytest.mark.parametrize(
    "argument,expected",
    [
        ("@dave", "dave"),
        ("dave", "dave"),
        ("https://heydex.ai/diff/dave/", "dave"),
        ("https://heydex.ai/diff/davekilleen", "davekilleen"),
        (f"https://heydex.ai/diff/{'@'}dave/", "dave"),
    ],
)
def test_parse_handle_argument(argument, expected):
    assert dexdiff_profile_adopt.parse_handle_argument(argument) == expected


def test_methodology_quality_warnings_flags_v1_summaries():
    bundle = _bundle()
    bundle["workflows"][0]["methodology"] = "One sentence summary."
    warnings = dexdiff_profile_adopt.methodology_quality_warnings(bundle)
    # workflow 0: no schema marker (v1 summary); workflow 1: marker present but thin
    assert len(warnings) == 2
    assert "meeting-prep" in warnings[0] and "v1 summary" in warnings[0]
    assert "follow-through" in warnings[1] and "thin" in warnings[1]


def test_methodology_quality_warnings_passes_real_v2_documents():
    bundle = _bundle()
    real_v2 = 'dexdiff_schema: "2.0"\n' + ("methodology:\n  problem: |\n    x\n" * 100)
    for workflow in bundle["workflows"]:
        workflow["methodology"] = real_v2
    assert dexdiff_profile_adopt.methodology_quality_warnings(bundle) == []


def test_validate_profile_bundle_requires_supported_contract_version():
    with pytest.raises(ValueError):
        dexdiff_profile_adopt.validate_profile_bundle(
            {
                "contractVersion": "bad-version",
                "profile": {"handle": "dave"},
                "workflows": [{"diffId": "meeting-prep", "methodology": "x"}],
            }
        )


@pytest.fixture
def stub_server(monkeypatch):
    """Install a deterministic urllib transport without opening a local port."""
    base_url = "https://stub.dex.test"

    def start(status: int, body: str) -> str:
        payload = body.encode("utf-8")

        class Response:
            def __init__(self):
                self.status = status

            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def fake_urlopen(request, timeout):
            assert request.full_url.startswith(f"{base_url}/api/profile-bundle?handle=")
            assert timeout > 0
            if status >= 400:
                raise urllib.error.HTTPError(
                    request.full_url,
                    status,
                    "stub response",
                    {},
                    io.BytesIO(payload),
                )
            return Response()

        monkeypatch.setattr(dexdiff_profile_adopt.urllib.request, "urlopen", fake_urlopen)
        return base_url

    return start


def test_fetch_profile_bundle_happy_path(stub_server):
    base = stub_server(200, json.dumps(_bundle()))
    bundle = dexdiff_profile_adopt.fetch_profile_bundle("@dave", base_url=base)
    assert bundle["profile"]["handle"] == "dave"
    assert len(bundle["workflows"]) == 2


def test_fetch_profile_bundle_404_raises_not_found(stub_server):
    base = stub_server(404, '{"error":"Profile bundle not found"}')
    with pytest.raises(dexdiff_profile_adopt.ProfileBundleNotFoundError) as excinfo:
        dexdiff_profile_adopt.fetch_profile_bundle("@ghost", base_url=base)
    assert "No public profile found for @ghost" in excinfo.value.user_message


def test_fetch_profile_bundle_500_raises_http_error(stub_server):
    base = stub_server(500, "oops")
    with pytest.raises(dexdiff_profile_adopt.ProfileBundleHTTPError) as excinfo:
        dexdiff_profile_adopt.fetch_profile_bundle("@dave", base_url=base)
    assert "HTTP 500" in excinfo.value.user_message


def test_fetch_profile_bundle_non_json_raises_payload_error(stub_server):
    base = stub_server(200, "<html>not json</html>")
    with pytest.raises(dexdiff_profile_adopt.ProfileBundlePayloadError):
        dexdiff_profile_adopt.fetch_profile_bundle("@dave", base_url=base)


def test_fetch_profile_bundle_wrong_contract_raises_payload_error(stub_server):
    bad = _bundle()
    bad["contractVersion"] = "1999-01-01"
    base = stub_server(200, json.dumps(bad))
    with pytest.raises(dexdiff_profile_adopt.ProfileBundlePayloadError) as excinfo:
        dexdiff_profile_adopt.fetch_profile_bundle("@dave", base_url=base)
    assert "malformed" in excinfo.value.user_message


def test_fetch_profile_bundle_connection_refused_raises_network_error():
    with pytest.raises(dexdiff_profile_adopt.ProfileBundleNetworkError) as excinfo:
        dexdiff_profile_adopt.fetch_profile_bundle(
            "@dave", base_url="http://127.0.0.1:1", timeout=2
        )
    assert "internet connection" in excinfo.value.user_message
    assert "Nothing was changed locally" in excinfo.value.user_message


def test_write_profile_bundle_creates_manifest_workflows_love_letter_and_log(monkeypatch, tmp_path):
    _configure_paths(monkeypatch, tmp_path)

    result = dexdiff_profile_adopt.write_profile_bundle(
        _bundle(),
        source="https://heydex.ai/api/profile-bundle?handle=dave",
    )

    assert result["manifest_path"].is_file()
    assert [path.name for path in result["workflow_paths"]] == [
        "01-meeting-prep.yaml",
        "02-follow-through.yaml",
    ]
    assert result["love_letter_path"].is_file()
    assert result["adoption_log_path"].is_file()

    manifest = json.loads(result["manifest_path"].read_text(encoding="utf-8"))
    assert manifest["profile"]["handle"] == "dave"
    assert manifest["workflows"][0]["diffId"] == "meeting-prep"

    adoption_log = json.loads(result["adoption_log_path"].read_text(encoding="utf-8"))
    assert adoption_log["profile_handle"] == "dave"
    assert adoption_log["workflow_ids"] == ["meeting-prep", "follow-through"]
    assert adoption_log["manifest_path"] == "04-Projects/DexDiff/beta/profile/adopted/dave/profile-bundle.json"
    assert adoption_log["love_letter_path"] == "04-Projects/DexDiff/beta/profile/adopted/dave/love-letter.md"
