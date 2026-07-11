"""Regression tests for Granola API list-query handling."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import urllib.error
import urllib.parse

import pytest

from core.mcp import granola_server


@pytest.fixture(autouse=True)
def _configured_api(monkeypatch):
    """Keep tests offline while exercising the connected-tool code paths."""
    monkeypatch.setenv("GRANOLA_API_KEY", "grn_test")
    granola_server._response_cache.clear()
    yield
    granola_server._response_cache.clear()


def _call_tool(name: str, arguments: dict | None = None) -> dict:
    contents = asyncio.run(granola_server.handle_call_tool(name, arguments))
    return json.loads(contents[0].text)


def test_recent_meetings_preserves_legitimate_empty_success(monkeypatch):
    def empty_page(path, params):
        assert path == "/v1/notes"
        assert "created_after" in params
        return {"notes": [], "hasMore": False}

    monkeypatch.setattr(granola_server, "_api_get", empty_page)

    result = _call_tool("granola_get_recent_meetings", {"days_back": 7})

    assert result["success"] is True
    assert result["count"] == 0
    assert result["meetings"] == []


def test_recent_meetings_returns_meetings_from_successful_page(monkeypatch):
    note = {
        "id": "note-1",
        "title": "Weekly sync",
        "created_at": "2026-07-09T10:00:00Z",
        "updated_at": "2026-07-09T11:00:00Z",
    }

    def successful_page(path, params):
        assert path == "/v1/notes"
        assert "created_after" in params
        return {"notes": [note], "hasMore": False}

    monkeypatch.setattr(granola_server, "_api_get", successful_page)

    result = _call_tool(
        "granola_get_recent_meetings",
        {"days_back": 7, "limit": 20},
    )

    assert result["success"] is True
    assert result["count"] == 1
    assert result["meetings"][0]["id"] == "note-1"
    assert result["meetings"][0]["title"] == "Weekly sync"


def test_cutoff_iso_uses_seconds_precision_rfc3339_utc():
    cutoff = granola_server._cutoff_iso(7)

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", cutoff)


def test_recent_meetings_surfaces_filtered_http_400(monkeypatch):
    def reject_request(request, timeout):
        assert timeout == 15
        assert "created_after=" in request.full_url
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "Bad Request",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"invalid created_after"}'),
        )

    monkeypatch.setattr(granola_server.urllib.request, "urlopen", reject_request)

    result = _call_tool("granola_get_recent_meetings", {"days_back": 7})

    assert result["success"] is False
    assert "HTTP 400" in result["error"]
    assert "connector may need updating" in result["error"]
    assert "invalid created_after" in result["error"]
    assert result["feature"] == "Granola meeting sync"
    assert result["feature_status"] == "broken"
    assert result["user_message"] == result["error"]
    assert result["data_source"] == "official_api"


def test_recent_meetings_surfaces_url_errors(monkeypatch):
    def reject_request(request, timeout):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(granola_server.urllib.request, "urlopen", reject_request)

    result = _call_tool("granola_get_recent_meetings", {"days_back": 7})

    assert result["success"] is False
    assert "network connection" in result["error"]


def test_api_get_retries_http_429_once(monkeypatch):
    attempts = 0

    def rate_limited(request, timeout):
        nonlocal attempts
        attempts += 1
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"rate limited"}'),
        )

    monkeypatch.setattr(granola_server.urllib.request, "urlopen", rate_limited)
    monkeypatch.setattr(granola_server.time, "sleep", lambda _seconds: None)

    with pytest.raises(granola_server.GranolaAPIError) as error_info:
        granola_server._api_get("/v1/notes", {"page_size": 1})

    assert attempts == 2
    assert error_info.value.status_code == 429


def test_check_available_uses_filtered_probe_and_surfaces_http_400(monkeypatch):
    requested_urls = []

    def reject_request(request, timeout):
        requested_urls.append(request.full_url)
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "Bad Request",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"invalid created_after"}'),
        )

    monkeypatch.setattr(granola_server.urllib.request, "urlopen", reject_request)

    result = _call_tool("granola_check_available")

    query = urllib.parse.parse_qs(urllib.parse.urlparse(requested_urls[0]).query)
    assert "created_after" in query
    assert result["available"] is False
    assert result["api"]["status"] == "unavailable"
    assert "HTTP 400" in result["error"]
    assert result["success"] is False
    assert result["feature"] == "Granola meeting sync"
    assert result["feature_status"] == "broken"
    assert result["user_message"] == result["message"]


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("granola_search_meetings", {"query": "planning"}),
        ("granola_get_today_meetings", {}),
        ("granola_get_extent", {}),
    ],
)
def test_other_list_tools_surface_api_errors(monkeypatch, tool_name, arguments):
    def fail_list_request(path, params):
        raise granola_server.GranolaAPIError(400, "invalid created_after")

    monkeypatch.setattr(granola_server, "_api_get", fail_list_request)

    result = _call_tool(tool_name, arguments)

    assert result["success"] is False
    assert "HTTP 400" in result["error"]


@pytest.mark.parametrize(
    "first_page_notes",
    [
        [],
        [
            {
                "id": "note-1",
                "title": "Planning",
                "created_at": "2026-07-10T09:00:00Z",
            }
        ],
    ],
    ids=["empty-page", "page-with-meeting"],
)
def test_list_notes_returns_collected_results_when_a_later_page_fails(
    monkeypatch,
    caplog,
    first_page_notes,
):
    responses = iter(
        [
            {"notes": first_page_notes, "hasMore": True, "cursor": "next-page"},
            granola_server.GranolaAPIError(500, "temporary failure"),
        ]
    )

    def page_then_error(path, params):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(granola_server, "_api_get", page_then_error)

    with caplog.at_level(logging.WARNING):
        notes = granola_server._list_notes(created_after=granola_server._cutoff_iso(7))

    assert notes == first_page_notes
    assert "after 1 successful page" in caplog.text


def test_meeting_details_surfaces_api_errors(monkeypatch):
    def fail_detail_request(path, params):
        raise granola_server.GranolaAPIError(503, "temporarily unavailable")

    monkeypatch.setattr(granola_server, "_api_get", fail_detail_request)

    result = _call_tool(
        "granola_get_meeting_details",
        {"meeting_id": "note-1"},
    )

    assert result["success"] is False
    assert "HTTP 503" in result["error"]


def test_extent_surfaces_detail_api_errors_after_a_successful_list(monkeypatch):
    note = {
        "id": "note-1",
        "title": "Planning",
        "created_at": "2026-07-10T09:00:00Z",
    }

    def list_then_fail_detail(path, params):
        if path == "/v1/notes":
            return {"notes": [note], "hasMore": False}
        raise granola_server.GranolaAPIError(503, "temporarily unavailable")

    monkeypatch.setattr(granola_server, "_api_get", list_then_fail_detail)

    result = _call_tool("granola_get_extent")

    assert result["success"] is False
    assert "HTTP 503" in result["error"]
