import os

from core.update import apply_update
from core.utils.os_flags import binary_write_flags


WINDOWS_O_BINARY = 0x8000


def test_binary_write_flags_or_platform_flag(monkeypatch):
    monkeypatch.setattr(os, "O_BINARY", WINDOWS_O_BINARY, raising=False)
    assert binary_write_flags(os.O_WRONLY | os.O_CREAT) == (
        os.O_WRONLY | os.O_CREAT | WINDOWS_O_BINARY
    )


def test_binary_write_flags_noop_when_platform_has_no_obinary(monkeypatch):
    monkeypatch.delattr(os, "O_BINARY", raising=False)
    assert binary_write_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL) == (
        os.O_WRONLY | os.O_CREAT | os.O_EXCL
    )


def _simulate_windows_crt_translation(monkeypatch):
    """Treat missing O_BINARY as CRT text mode: LF becomes CRLF on os.write."""
    monkeypatch.setattr(os, "O_BINARY", WINDOWS_O_BINARY, raising=False)
    opened_flags: dict[int, int] = {}
    seen_flags: list[int] = []
    real_open = os.open
    real_write = os.write
    real_close = os.close

    def tracking_open(path, flags, mode=0o777, **kwargs):
        descriptor = real_open(path, flags, mode, **kwargs)
        opened_flags[descriptor] = flags
        seen_flags.append(flags)
        return descriptor

    def translating_write(descriptor, data):
        payload = bytes(data)
        if not (opened_flags.get(descriptor, 0) & WINDOWS_O_BINARY):
            payload = payload.replace(b"\n", b"\r\n")
        return real_write(descriptor, payload)

    def tracking_close(descriptor):
        opened_flags.pop(descriptor, None)
        return real_close(descriptor)

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "write", translating_write)
    monkeypatch.setattr(os, "close", tracking_close)
    return seen_flags


def test_simulated_windows_write_without_obinary_introduces_crlf(tmp_path, monkeypatch):
    _simulate_windows_crt_translation(monkeypatch)
    path = tmp_path / "text-mode.json"
    payload = b'{"ok": true}\n'
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
    assert path.read_bytes() == b'{"ok": true}\r\n'


def test_simulated_windows_write_with_helper_keeps_lf(tmp_path, monkeypatch):
    _simulate_windows_crt_translation(monkeypatch)
    path = tmp_path / "binary-mode.json"
    payload = b'{"ok": true}\n'
    descriptor = os.open(
        path,
        binary_write_flags(os.O_WRONLY | os.O_CREAT | os.O_EXCL),
        0o600,
    )
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
    assert path.read_bytes() == payload
    assert b"\r\n" not in path.read_bytes()


def test_atomic_json_uses_binary_flags_so_crlf_is_not_introduced(tmp_path, monkeypatch):
    seen_flags = _simulate_windows_crt_translation(monkeypatch)

    path = tmp_path / "plan.json"
    apply_update._atomic_json(path, {"ok": True})
    raw = path.read_bytes()
    assert raw == b'{\n  "ok": true\n}\n'
    assert b"\r\n" not in raw
    assert any(flags & WINDOWS_O_BINARY for flags in seen_flags)
