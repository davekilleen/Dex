"""DEX-243: session-wrapper stdio must forward a short MCP greeting promptly."""

from __future__ import annotations

import os
import select
import threading
import time

import pytest

from core.utils import mcp_session_lifecycle as lifecycle

pytestmark = pytest.mark.skipif(os.name != "posix", reason="pipe select is POSIX")

SHORT_MESSAGE = b'{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'
FORWARD_TIMEOUT_SECONDS = 2.0


def _read_until(fd: int, expected: bytes, timeout: float) -> bytes:
    """Read available bytes with a timeout. Must not hang if nothing arrives."""

    received = b""
    deadline = time.monotonic() + timeout
    while expected not in received:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        ready, _, _ = select.select([fd], [], [], remaining)
        if not ready:
            break
        chunk = os.read(fd, 4096)
        if not chunk:
            break
        received += chunk
    return received


def test_forward_bytes_passes_a_short_message_while_pipe_stays_open() -> None:
    """A few hundred bytes on an open pipe must be forwarded within ~2s.

    ``BufferedReader.read(n)`` waits for n bytes or EOF. MCP initialize is
    shorter than 4096 bytes and the host keeps stdin open, so the wrapper
    never forwarded the first greeting.
    """

    src_r, src_w = os.pipe()
    dst_r, dst_w = os.pipe()
    source = os.fdopen(src_r, "rb")
    dest = os.fdopen(dst_w, "wb")
    stop = threading.Event()
    thread = threading.Thread(
        target=lifecycle._forward_bytes,
        args=(source, dest, stop),
        daemon=True,
    )
    try:
        os.write(src_w, SHORT_MESSAGE)
        thread.start()
        received = _read_until(dst_r, SHORT_MESSAGE, FORWARD_TIMEOUT_SECONDS)
        assert received == SHORT_MESSAGE
    finally:
        stop.set()
        try:
            os.close(src_w)
        except OSError:
            pass
        thread.join(timeout=1)
        for handle in (source, dest):
            try:
                handle.close()
            except OSError:
                pass
        try:
            os.close(dst_r)
        except OSError:
            pass


def test_forward_bytes_exits_after_eof() -> None:
    """Closing the write end still delivers leftover bytes and then stops."""

    src_r, src_w = os.pipe()
    dst_r, dst_w = os.pipe()
    source = os.fdopen(src_r, "rb")
    dest = os.fdopen(dst_w, "wb")
    thread = threading.Thread(
        target=lifecycle._forward_bytes,
        args=(source, dest, None),
        daemon=True,
    )
    try:
        os.write(src_w, SHORT_MESSAGE)
        os.close(src_w)
        src_w = -1
        thread.start()
        received = _read_until(dst_r, SHORT_MESSAGE, FORWARD_TIMEOUT_SECONDS)
        thread.join(timeout=FORWARD_TIMEOUT_SECONDS)
        assert received == SHORT_MESSAGE
        assert not thread.is_alive()
    finally:
        if src_w >= 0:
            try:
                os.close(src_w)
            except OSError:
                pass
        thread.join(timeout=1)
        for handle in (source, dest):
            try:
                handle.close()
            except OSError:
                pass
        try:
            os.close(dst_r)
        except OSError:
            pass
