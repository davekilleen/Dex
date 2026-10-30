#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path


class ProofError(RuntimeError):
    pass


def _decode_json(value: str, label: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise ProofError(f"{label} did not return JSON") from error


def _call(core: Path, environment: dict[str, str], *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [core, *arguments],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
    )


def _success(
    transcripts: list[str],
    core: Path,
    environment: dict[str, str],
    *arguments: str,
) -> object:
    result = _call(core, environment, *arguments)
    transcripts.extend((result.stdout, result.stderr))
    if result.returncode != 0 or result.stderr:
        raise ProofError(f"core {' '.join(arguments)} failed")
    return _decode_json(result.stdout, f"core {' '.join(arguments)}")


def _failure(
    transcripts: list[str],
    core: Path,
    environment: dict[str, str],
    *arguments: str,
) -> str:
    result = _call(core, environment, *arguments)
    transcripts.extend((result.stdout, result.stderr))
    if result.returncode == 0 or result.stdout:
        raise ProofError(f"core {' '.join(arguments)} unexpectedly succeeded")
    error = _decode_json(result.stderr, f"core {' '.join(arguments)} error")
    if not isinstance(error, dict) or not isinstance(error.get("error"), str):
        raise ProofError(f"core {' '.join(arguments)} error contract is invalid")
    return str(error["error"])


def prove(artifact: Path, relay: str) -> dict[str, object]:
    core = artifact / "bin" / "core"
    buzz = artifact / "libexec" / "buzz"
    manifest_path = artifact / "manifest.json"
    if not core.is_file() or not buzz.is_file() or not manifest_path.is_file():
        raise ProofError("verified artifact layout is required")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    transcripts: list[str] = []

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        studio_home = root / "studio"
        environment = {
            "PATH": "",
            "HOME": str(root / "home"),
            "DEX_STUDIO_HOME": str(studio_home),
            "BUZZ_RELAY_URL": relay,
        }
        suffix = f"{datetime.now(UTC):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}"
        identity_name = f"B5 Evidence {suffix}"
        identity = _success(
            transcripts,
            core,
            environment,
            "identity",
            "create",
            "--name",
            identity_name,
        )
        if not isinstance(identity, dict):
            raise ProofError("identity result is not an object")
        identity_id = str(identity.get("id", ""))
        pubkey = str(identity.get("pubkey", ""))
        if not identity_id or len(pubkey) != 64:
            raise ProofError("identity result is incomplete")
        duplicate_error = _failure(
            transcripts,
            core,
            environment,
            "identity",
            "create",
            "--name",
            identity_name,
        )
        if "already exists" not in duplicate_error:
            raise ProofError("identity overwrite was not refused")

        key_file = studio_home / "keys" / "agents" / identity_id / "key.json"
        key_document = json.loads(key_file.read_text(encoding="utf-8"))
        private_key = str(key_document.get("privkey", ""))
        private_directories = (studio_home, studio_home / "keys", studio_home / "keys" / "agents", key_file.parent)
        if (
            len(private_key) != 64
            or stat.S_IMODE(key_file.stat().st_mode) != 0o600
            or any(stat.S_IMODE(path.stat().st_mode) != 0o700 for path in private_directories)
        ):
            raise ProofError("identity key custody contract is invalid")

        room_name = f"B5 evidence {suffix}"
        description = "Disposable local proof for Dex Core B5"
        created = _success(
            transcripts,
            core,
            environment,
            "rooms",
            "create",
            "--name",
            room_name,
            "--description",
            description,
            "--as",
            identity_id,
        )
        if not isinstance(created, dict) or not created.get("channel_id"):
            raise ProofError("room creation result is incomplete")
        room_id = str(created["channel_id"])

        rooms = _success(
            transcripts,
            core,
            environment,
            "rooms",
            "list",
            "--as",
            identity_id,
            "--json",
        )
        if not isinstance(rooms, list) or not any(
            room.get("channel_id") == room_id and room.get("name") == room_name
            for room in rooms
            if isinstance(room, dict)
        ):
            raise ProofError("created room is absent from rooms list")

        # Buzz's NIP-29 canonical channel metadata is relay-signed. Its
        # `pubkey` is therefore the relay authority, not a creator field. The
        # selected creator identity is proven by the Core invocation above,
        # the identity profile, and the signed message round-trip below.
        room_result = subprocess.run(
            [buzz, "channels", "get", "--channel", room_id],
            env={**environment, "BUZZ_PRIVATE_KEY": private_key},
            capture_output=True,
            text=True,
            timeout=20,
        )
        transcripts.extend((room_result.stdout, room_result.stderr))
        room_detail = _decode_json(room_result.stdout, "packaged room detail lookup")
        if (
            room_result.returncode != 0
            or not isinstance(room_detail, dict)
            or room_detail.get("channel_id") != room_id
            or room_detail.get("name") != room_name
            or room_detail.get("description") != description
        ):
            raise ProofError("room name or description was not preserved by the relay")
        relay_metadata_pubkey = str(room_detail.get("pubkey", ""))

        posted_ids: list[str] = []
        for sequence in range(1, 4):
            posted = _success(
                transcripts,
                core,
                environment,
                "post",
                "--as",
                identity_id,
                "--room",
                room_id,
                "--text",
                f"B5 proof message {sequence} ({suffix})",
            )
            if not isinstance(posted, dict) or not posted.get("event_id"):
                raise ProofError("post result is incomplete")
            posted_ids.append(str(posted["event_id"]))
            if sequence < 3:
                # Nostr timestamps have one-second precision. Distinct seconds
                # make the newest-tail assertion deterministic rather than
                # assigning an artificial order to simultaneous events.
                time.sleep(1.05)

        timeline: object = []
        for _ in range(10):
            timeline = _success(
                transcripts,
                core,
                environment,
                "timeline",
                "--as",
                identity_id,
                "--room",
                room_id,
                "--limit",
                "2",
                "--json",
            )
            if isinstance(timeline, list) and [event.get("id") for event in timeline] == posted_ids[-2:]:
                break
            time.sleep(0.2)
        if not isinstance(timeline, list) or [event.get("id") for event in timeline] != posted_ids[-2:]:
            raise ProofError("timeline did not return the newest two posts")
        if any(event.get("kind") != 9 or event.get("pubkey") != pubkey for event in timeline):
            raise ProofError("timeline contains a wrong-kind or wrong-author post")
        created_times = [event.get("created_at") for event in timeline]
        if any(not isinstance(value, int) for value in created_times) or created_times != sorted(created_times):
            raise ProofError("timeline is not ascending with snake_case created_at values")

        invalid_limit = _failure(
            transcripts,
            core,
            environment,
            "timeline",
            "--room",
            room_id,
            "--limit",
            "0",
        )
        unknown_identity = _failure(
            transcripts,
            core,
            environment,
            "post",
            "--as",
            "missing-identity",
            "--room",
            room_id,
            "--text",
            "must fail",
        )
        unknown_room = _failure(
            transcripts,
            core,
            environment,
            "timeline",
            "--as",
            identity_id,
            "--room",
            str(uuid.uuid4()),
            "--json",
        )
        relay_failure = _failure(
            transcripts,
            core,
            {**environment, "BUZZ_RELAY_URL": "ws://127.0.0.1:1"},
            "rooms",
            "list",
            "--as",
            identity_id,
            "--json",
        )
        required_errors = (
            (invalid_limit, "1 to 200"),
            (unknown_identity, "unknown identity"),
            (unknown_room, "unknown room"),
        )
        for actual, expected in required_errors:
            if expected not in actual:
                raise ProofError(f"expected failure was not explicit: {expected}")
        if not relay_failure:
            raise ProofError("relay failure returned no detail")
        if any(private_key in transcript for transcript in transcripts):
            raise ProofError("private identity material leaked into command output")

        return {
            "schema": "dex-collaboration-cli-proof/1",
            "status": "verified",
            "artifact": str(artifact.resolve()),
            "platform": manifest.get("platform"),
            "architecture": manifest.get("architecture"),
            "buzz_revision": manifest.get("sources", {}).get("buzz_revision"),
            "relay": relay,
            "fresh_home": True,
            "empty_caller_path": True,
            "identity": {"id": identity_id, "pubkey": pubkey, "overwrite_refused": True},
            "room": {
                "channel_id": room_id,
                "selected_creator_identity_verified": True,
                "relay_metadata_pubkey": relay_metadata_pubkey,
                "requested_type": "stream",
                "requested_visibility": "open",
                "canonical_tags_independently_verified": False,
            },
            "posts": {
                "relay_returned_kind": 9,
                "author_pubkey_matched": True,
                "cryptographic_signature_independently_verified": False,
                "count": len(posted_ids),
            },
            "timeline": {"limit": 2, "newest_tail": True, "ascending": True},
            "negative_paths": ["invalid_limit", "unknown_identity", "unknown_room", "relay_failure"],
            "private_key_leaked": False,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--relay", default=os.environ.get("BUZZ_RELAY_URL", "ws://127.0.0.1:34000"))
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prove(args.artifact, args.relay), separators=(",", ":")))
        return 0
    except (ProofError, OSError, KeyError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"error": str(error)}, separators=(",", ":")), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
