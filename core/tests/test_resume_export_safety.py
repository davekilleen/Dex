from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from core.mcp import resume_server


def _session() -> resume_server.ResumeSession:
    return resume_server.ResumeSession(
        session_id="session-1",
        created_at="2026-08-12T10:00:00",
        last_modified="2026-08-12T10:00:00",
        phase=resume_server.PhaseEnum.SETUP,
        approach="from_scratch",
    )


def _payload(result: list[object]) -> dict[str, object]:
    return json.loads(result[0].text)


def test_export_uses_a_new_filename_and_preserves_existing_bytes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    resume_dir = tmp_path / "05-Areas/Career/Resume"
    resume_dir.mkdir(parents=True)
    existing = resume_dir / "Leadership Resume.markdown"
    existing.write_text("user-owned bytes\n", encoding="utf-8")
    session = _session()
    monkeypatch.setattr(resume_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(resume_server, "RESUME_DIR", resume_dir)
    monkeypatch.setattr(resume_server, "sessions", {session.session_id: session})
    monkeypatch.setattr(resume_server, "format_resume", lambda *_args, **_kwargs: "verified resume\n")
    monkeypatch.setattr(resume_server, "auto_save_session", lambda _session: None)

    result = _payload(
        asyncio.run(
            resume_server.handle_export_resume(
                {
                    "session_id": session.session_id,
                    "format": "markdown",
                    "filename": "Leadership Resume",
                }
            )
        )
    )

    assert result["success"] is True
    assert existing.read_text(encoding="utf-8") == "user-owned bytes\n"
    exported = tmp_path / str(result["filepath"])
    assert exported != existing
    assert exported.read_text(encoding="utf-8") == "verified resume\n"
    assert result["byte_size"] == len(b"verified resume\n")
    assert result["sha256"] == hashlib.sha256(b"verified resume\n").hexdigest()
    assert result["read_back_verified"] is True


def test_export_rejects_path_traversal_without_mutation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    resume_dir = tmp_path / "05-Areas/Career/Resume"
    session = _session()
    monkeypatch.setattr(resume_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(resume_server, "RESUME_DIR", resume_dir)
    monkeypatch.setattr(resume_server, "sessions", {session.session_id: session})
    monkeypatch.setattr(resume_server, "auto_save_session", lambda _session: None)

    result = _payload(
        asyncio.run(
            resume_server.handle_export_resume(
                {"session_id": session.session_id, "filename": "../../outside"}
            )
        )
    )

    assert result["success"] is False
    assert "filename" in str(result["error"]).lower()
    assert not resume_dir.exists()
    assert not (tmp_path / "outside.markdown").exists()


def test_export_rejects_symlinked_resume_directory_without_outside_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    career_dir = tmp_path / "05-Areas/Career"
    career_dir.mkdir(parents=True)
    resume_dir = career_dir / "Resume"
    resume_dir.symlink_to(outside, target_is_directory=True)
    session = _session()
    monkeypatch.setattr(resume_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(resume_server, "RESUME_DIR", resume_dir)
    monkeypatch.setattr(resume_server, "sessions", {session.session_id: session})
    monkeypatch.setattr(resume_server, "format_resume", lambda *_args, **_kwargs: "private\n")
    monkeypatch.setattr(resume_server, "auto_save_session", lambda _session: None)

    result = _payload(
        asyncio.run(
            resume_server.handle_export_resume(
                {"session_id": session.session_id, "filename": "Resume"}
            )
        )
    )

    assert result["success"] is False
    assert "unsafe" in str(result["error"]).lower()
    assert list(outside.iterdir()) == []
    assert session.phase is resume_server.PhaseEnum.SETUP


def test_export_fails_if_read_back_differs_from_written_content(
    tmp_path: Path,
    monkeypatch,
) -> None:
    resume_dir = tmp_path / "05-Areas/Career/Resume"
    session = _session()
    monkeypatch.setattr(resume_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(resume_server, "RESUME_DIR", resume_dir)
    monkeypatch.setattr(resume_server, "sessions", {session.session_id: session})
    monkeypatch.setattr(resume_server, "format_resume", lambda *_args, **_kwargs: "expected\n")
    monkeypatch.setattr(resume_server, "auto_save_session", lambda _session: None)
    original_read_bytes = Path.read_bytes

    def mismatched_read_back(path: Path) -> bytes:
        if path.parent == resume_dir:
            return b"different\n"
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", mismatched_read_back)

    result = _payload(
        asyncio.run(
            resume_server.handle_export_resume(
                {"session_id": session.session_id, "filename": "Resume"}
            )
        )
    )

    assert result["success"] is False
    assert "read-back" in str(result["error"]).lower()
    assert session.phase is resume_server.PhaseEnum.SETUP
