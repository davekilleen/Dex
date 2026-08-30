"""The unpublished Dex MCP box cannot be installed from a public catalogue."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

REPO_ROOT_PACKAGE = "dex-mcp"
CATALOGUE_NAME = "io.github.davekilleen/dex"
OUR_REPOSITORY = "github.com/davekilleen/Dex"
NPM_REGISTRY = "https://registry.npmjs.org/dex-mcp"
MCP_REGISTRY = "https://registry.modelcontextprotocol.io/v0.1"
USER_AGENT = "Dex-unpublished-check/1.0"

_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}


def _get(url: str) -> tuple[int, Any]:
    request = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
            payload: Any = json.loads(body) if body.strip() else {}
            return int(response.status), payload
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            payload = {}
        return int(error.code), payload
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as error:
        raise AssertionError(f"could not reach {url}: {error}") from error


def _server_names(payload: Any) -> set[str]:
    names: set[str] = set()
    if not isinstance(payload, dict):
        return names
    servers = payload.get("servers")
    if not isinstance(servers, list):
        return names
    for item in servers:
        if not isinstance(item, dict):
            continue
        server = item.get("server") if isinstance(item.get("server"), dict) else item
        name = server.get("name") if isinstance(server, dict) else None
        if isinstance(name, str) and name:
            names.add(name)
    return names


def test_official_catalogue_does_not_list_this_box() -> None:
    search = f"{MCP_REGISTRY}/servers?{urllib.parse.urlencode({'search': CATALOGUE_NAME})}"
    status, payload = _get(search)
    assert status == 200, f"official catalogue search returned {status}"
    assert CATALOGUE_NAME not in _server_names(payload)

    encoded = urllib.parse.quote(CATALOGUE_NAME, safe="")
    versions_status, _payload = _get(f"{MCP_REGISTRY}/servers/{encoded}/versions")
    assert versions_status == 404

    latest_status, _payload = _get(f"{MCP_REGISTRY}/servers/{encoded}/versions/latest")
    assert latest_status == 404


def test_npm_registry_does_not_serve_this_box() -> None:
    status, payload = _get(NPM_REGISTRY)
    if status == 404:
        return
    assert status == 200, f"npm lookup returned {status}"
    assert isinstance(payload, dict)
    tags = payload.get("dist-tags")
    assert isinstance(tags, dict)
    latest = tags.get("latest")
    assert isinstance(latest, str) and latest
    versions = payload.get("versions")
    assert isinstance(versions, dict)
    published = versions.get(latest)
    assert isinstance(published, dict)
    assert published.get("name") == REPO_ROOT_PACKAGE
    assert published.get("mcpName") != CATALOGUE_NAME
    repository = published.get("repository") or {}
    repo_url = repository.get("url") if isinstance(repository, dict) else str(repository)
    assert isinstance(repo_url, str)
    assert OUR_REPOSITORY not in repo_url.replace(".git", "")
