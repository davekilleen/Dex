#!/usr/bin/env python3
# LIVE surface of the shared core.soft_promise detector. This hook only offers
# capture context and must never auto-create tasks. DEX_SOFT_PROMISE_STATE_DIR
# may override the state directory for isolated tests.

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path


def _repo_root() -> Path:
    configured_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if configured_root:
        return Path(configured_root)
    return Path(__file__).resolve().parents[2]


def _state_path(repo_root: Path, session_id: object) -> Path:
    state_dir = os.environ.get("DEX_SOFT_PROMISE_STATE_DIR")
    root = (
        Path(state_dir)
        if state_dir
        else repo_root / "System" / ".dex" / "soft-promise-offered"
    )
    raw_session_id = session_id if isinstance(session_id, str) else "default"
    safe_session_id = re.sub(r"[^A-Za-z0-9_.-]", "_", raw_session_id) or "default"
    return root / f"{safe_session_id}.json"


def _commitment_hash(commitment: str) -> str:
    normalized = " ".join(commitment.casefold().split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _additional_context(candidates: list[dict]) -> str:
    lines = ["<soft_commitment_capture>"]
    for candidate in candidates:
        details = []
        if candidate.get("person"):
            details.append(f"person: {candidate['person']}")
        if candidate.get("due"):
            details.append(f"due: {candidate['due']}")
        suffix = f" ({'; '.join(details)})" if details else ""
        lines.append(f"- Detected: {candidate['commitment']}{suffix}")
    lines.extend(
        [
            "",
            "The user may have made a soft commitment. If it fits the moment "
            "(do NOT interrupt if they are mid-task or this is urgent), offer "
            "ONCE to capture it as a task — confirm before creating, never "
            "auto-create, and read the created task ID back. If they decline "
            "or ignore it, drop it.",
            "Routing: live-capture is this hook; one finished meeting is "
            "/meeting-closeout; a batch of synced meetings is "
            "/process-meetings; reconciling promises already scattered across "
            "meetings is /commitments.",
            "</soft_commitment_capture>",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        prompt = payload.get("prompt", "") if isinstance(payload, dict) else ""

        repo_root = _repo_root()
        sys.path.insert(0, str(repo_root))
        from core.soft_promise import detect_soft_promises

        candidates = detect_soft_promises(prompt)
        if not candidates:
            return 0

        state_path = _state_path(repo_root, payload.get("session_id", "default"))
        offered = set()
        if state_path.exists():
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(stored, list):
                return 0
            offered.update(item for item in stored if isinstance(item, str))

        new_candidates = []
        new_hashes = []
        for candidate in candidates:
            candidate_hash = _commitment_hash(candidate["commitment"])
            if candidate_hash in offered:
                continue
            new_candidates.append(candidate)
            new_hashes.append(candidate_hash)

        if not new_candidates:
            return 0

        state_path.parent.mkdir(parents=True, exist_ok=True)
        offered.update(new_hashes)
        state_path.write_text(
            json.dumps(sorted(offered), indent=2) + "\n",
            encoding="utf-8",
        )

        output = {
            "continue": True,
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": _additional_context(new_candidates),
            },
        }
        print(json.dumps(output))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
