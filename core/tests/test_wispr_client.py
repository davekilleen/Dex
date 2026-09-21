"""The bridge must fail honestly and must not need an MCP host to be useful."""
from __future__ import annotations

import inspect

import pytest

from core.meeting_sources import wispr_client as client


def test_the_public_api_is_synchronous(tmp_path):
    """A scheduled job has no event loop and no host. That is the point.

    If these become coroutines, the source silently reverts to only working
    while someone is signed in to an MCP client.
    """
    for name in ("search_meetings", "get_meeting", "list_tools", "call"):
        function = getattr(client, name)
        assert not inspect.iscoroutinefunction(function), f"{name} must stay callable without a loop"


def test_unreachable_is_its_own_failure_not_an_empty_result(tmp_path, monkeypatch):
    """A recorder that cannot be reached must never read as a quiet week."""

    def unreachable(*_args, **_kwargs):
        raise client.WisprUnavailable("Wispr could not be reached: connection refused")

    monkeypatch.setattr(client, "call", unreachable)

    with pytest.raises(client.WisprUnavailable):
        client.search_meetings(tmp_path)


def test_an_unexpected_response_shape_is_refused(tmp_path, monkeypatch):
    """Returning something list-shaped downstream would be worse than failing."""
    monkeypatch.setattr(client, "call", lambda *a, **k: ["not", "a", "mapping"])

    with pytest.raises(client.WisprUnavailable):
        client.search_meetings(tmp_path)


def test_payload_unwraps_json_and_passes_text_through():
    class Text:
        def __init__(self, text):
            self.text = text

    class Result:
        def __init__(self, text):
            self.content = [Text(text)]

    assert client._payload(Result('{"meetings": []}')) == {"meetings": []}
    assert client._payload(Result("plain")) == "plain"

    class Empty:
        content: list = []

    assert client._payload(Empty()) is None
