from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CORE_SOURCE = PACKAGE_ROOT / "src" / "core"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _seed_identity(studio_home: Path, identity_id: str, private_key: str) -> None:
    key_dir = studio_home / "keys" / "agents" / identity_id
    key_dir.mkdir(parents=True)
    key_dir.chmod(0o700)
    key_file = key_dir / "key.json"
    key_file.write_text(
        json.dumps(
            {
                "id": identity_id,
                "name": identity_id,
                "pubkey": "a" * 64,
                "privkey": private_key,
            }
        ),
        encoding="utf-8",
    )
    key_file.chmod(0o600)


class SourceContractTests(unittest.TestCase):
    def test_source_contract_owns_the_b5_collaboration_commands(self) -> None:
        contract_path = PACKAGE_ROOT / "contract.json"

        self.assertTrue(
            contract_path.is_file(),
            "Dex Core has no package-owned B5 collaboration executable contract",
        )
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        self.assertEqual(contract["schema"], "dex-collaboration-cli-source/1")
        self.assertEqual(contract["artifact_id"], "dex-core-collaboration-cli")
        self.assertEqual(
            contract["commands"],
            [
                "identity create",
                "rooms list",
                "rooms create",
                "post",
                "timeline",
            ],
        )
        self.assertEqual(
            contract["buzz_revision"],
            "b2ac66cde81df7ce1afc50016e1571cb6e8b7779",
        )

    def test_core_executable_reports_the_frozen_contract_without_a_relay(self) -> None:
        source_path = CORE_SOURCE
        self.assertTrue(source_path.is_file(), "the package owns no Core executable source")
        self.assertTrue(source_path.stat().st_mode & 0o111, "Core source is not executable")
        result = subprocess.run(
            [source_path, "--artifact-info"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        info = json.loads(result.stdout)
        self.assertEqual(info["schema"], "dex-collaboration-cli/1")
        self.assertEqual(info["artifact_id"], "dex-core-collaboration-cli")
        self.assertEqual(
            info["commands"],
            ["identity create", "rooms list", "rooms create", "post", "timeline"],
        )

    def test_identity_create_uses_the_bundled_admin_and_keeps_the_private_key_local(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            studio_home = root / "studio"
            log_path = root / "buzz.log"
            fake_admin = root / "buzz-admin"
            fake_buzz = root / "buzz"
            _write_executable(
                fake_admin,
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' 'Public key: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'\n"
                "printf '%s\\n' 'Secret key: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'\n",
            )
            _write_executable(
                fake_buzz,
                "#!/usr/bin/env bash\n"
                "printf '%s|%s\\n' \"$BUZZ_PRIVATE_KEY\" \"$*\" >> \"$DEX_TEST_LOG\"\n"
                "printf '%s\\n' '{\"accepted\":true}'\n",
            )
            environment = {
                **os.environ,
                "DEX_STUDIO_HOME": str(studio_home),
                "DEX_BUZZ_BIN": str(fake_buzz),
                "DEX_BUZZ_ADMIN": str(fake_admin),
                "DEX_TEST_LOG": str(log_path),
            }
            result = subprocess.run(
                [CORE_SOURCE, "identity", "create", "--name", "Research Scout"],
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            identity = json.loads(result.stdout)
            self.assertEqual(
                identity,
                {
                    "id": "research-scout",
                    "name": "Research Scout",
                    "pubkey": "a" * 64,
                },
            )
            self.assertNotIn("b" * 64, result.stdout + result.stderr)
            key_dir = studio_home / "keys" / "agents" / "research-scout"
            key_file = key_dir / "key.json"
            self.assertEqual(stat.S_IMODE(studio_home.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((studio_home / "keys").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((studio_home / "keys" / "agents").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(key_dir.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(key_file.stat().st_mode), 0o600)
            self.assertEqual(json.loads(key_file.read_text(encoding="utf-8"))["privkey"], "b" * 64)
            self.assertEqual(
                log_path.read_text(encoding="utf-8").split("|", 1)[1].strip(),
                "users set-profile --name Research Scout",
            )

            duplicate = subprocess.run(
                [CORE_SOURCE, "identity", "create", "--name", "Research Scout"],
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertIn("identity already exists", json.loads(duplicate.stderr)["error"])

    def test_room_commands_use_the_selected_owner_with_an_empty_caller_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            studio_home = root / "studio"
            log_path = root / "buzz.log"
            fake_admin = root / "buzz-admin"
            fake_buzz = root / "buzz"
            _seed_identity(studio_home, "studio", "c" * 64)
            _seed_identity(studio_home, "room-owner", "d" * 64)
            _write_executable(fake_admin, "#!/bin/bash\nexit 99\n")
            _write_executable(
                fake_buzz,
                "#!/bin/bash\n"
                "printf '%s|%s\\n' \"$BUZZ_PRIVATE_KEY\" \"$*\" >> \"$DEX_TEST_LOG\"\n"
                "case \"$*\" in\n"
                "  'channels list') printf '%s\\n' '[{\"channel_id\":\"room-1\",\"name\":\"Knowledge\",\"created_at\":1}]' ;;\n"
                "  'channels create --name Knowledge --type stream --visibility open --description Shared facts') printf '%s\\n' '{\"accepted\":true,\"channel_id\":\"room-2\",\"event_id\":\"event-2\"}' ;;\n"
                "  *) printf '%s\\n' 'unexpected invocation' >&2; exit 41 ;;\n"
                "esac\n",
            )
            environment = {
                **os.environ,
                "PATH": "",
                "DEX_STUDIO_HOME": str(studio_home),
                "DEX_BUZZ_BIN": str(fake_buzz),
                "DEX_BUZZ_ADMIN": str(fake_admin),
                "DEX_TEST_LOG": str(log_path),
            }
            listed = subprocess.run(
                [CORE_SOURCE, "rooms", "list", "--as", "studio", "--json"],
                env=environment,
                capture_output=True,
                text=True,
            )
            created = subprocess.run(
                [
                    CORE_SOURCE,
                    "rooms",
                    "create",
                    "--name",
                    "Knowledge",
                    "--description",
                    "Shared facts",
                    "--as",
                    "room-owner",
                ],
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertEqual(listed.returncode, 0, listed.stdout + listed.stderr)
            self.assertEqual(json.loads(listed.stdout)[0]["channel_id"], "room-1")
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            self.assertEqual(json.loads(created.stdout)["channel_id"], "room-2")
            self.assertEqual(
                log_path.read_text(encoding="utf-8").splitlines(),
                [
                    f"{'c' * 64}|channels list",
                    f"{'d' * 64}|channels create --name Knowledge --type stream --visibility open --description Shared facts",
                ],
            )

    def test_post_and_timeline_preserve_signed_kind_nine_and_newest_tail_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            studio_home = root / "studio"
            log_path = root / "buzz.log"
            fake_admin = root / "buzz-admin"
            fake_buzz = root / "buzz"
            _seed_identity(studio_home, "studio", "c" * 64)
            _seed_identity(studio_home, "research-scout", "d" * 64)
            _write_executable(fake_admin, "#!/bin/bash\nexit 99\n")
            _write_executable(
                fake_buzz,
                "#!/bin/bash\n"
                "printf '%s|%s\\n' \"$BUZZ_PRIVATE_KEY\" \"$*\" >> \"$DEX_TEST_LOG\"\n"
                "case \"$*\" in\n"
                "  'channels get --channel room-1') printf '%s\\n' '{\"channel_id\":\"room-1\",\"name\":\"Knowledge\"}' ;;\n"
                "  'channels join --channel room-1') printf '%s\\n' '{\"accepted\":true}' ;;\n"
                "  'messages send --channel room-1 --content Finished the brief') printf '%s\\n' '{\"accepted\":true,\"event_id\":\"event-3\"}' ;;\n"
                "  'messages get --channel room-1 --limit 2') printf '%s\\n' '[{\"id\":\"event-2\",\"pubkey\":\"author\",\"kind\":9,\"content\":\"older\",\"created_at\":20,\"tags\":[]},{\"id\":\"event-3\",\"pubkey\":\"author\",\"kind\":9,\"content\":\"Finished the brief\",\"created_at\":30,\"tags\":[]}]' ;;\n"
                "  *) printf '%s\\n' 'unexpected invocation' >&2; exit 41 ;;\n"
                "esac\n",
            )
            environment = {
                **os.environ,
                "PATH": "",
                "DEX_STUDIO_HOME": str(studio_home),
                "DEX_BUZZ_BIN": str(fake_buzz),
                "DEX_BUZZ_ADMIN": str(fake_admin),
                "DEX_TEST_LOG": str(log_path),
            }
            posted = subprocess.run(
                [
                    CORE_SOURCE,
                    "post",
                    "--as",
                    "research-scout",
                    "--room",
                    "room-1",
                    "--text",
                    "Finished the brief",
                ],
                env=environment,
                capture_output=True,
                text=True,
            )
            timeline_result = subprocess.run(
                [CORE_SOURCE, "timeline", "--room", "room-1", "--limit", "2", "--json"],
                env=environment,
                capture_output=True,
                text=True,
            )

            self.assertEqual(posted.returncode, 0, posted.stdout + posted.stderr)
            self.assertEqual(json.loads(posted.stdout)["event_id"], "event-3")
            self.assertEqual(timeline_result.returncode, 0, timeline_result.stdout + timeline_result.stderr)
            timeline = json.loads(timeline_result.stdout)
            self.assertEqual([event["created_at"] for event in timeline], [20, 30])
            self.assertEqual([event["kind"] for event in timeline], [9, 9])
            self.assertEqual(timeline[-1]["content"], "Finished the brief")
            calls = log_path.read_text(encoding="utf-8").splitlines()
            self.assertIn(f"{'d' * 64}|messages send --channel room-1 --content Finished the brief", calls)
            self.assertIn(f"{'c' * 64}|messages get --channel room-1 --limit 2", calls)

    def test_invalid_identity_room_limit_and_relay_failures_are_json_and_secret_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            studio_home = root / "studio"
            fake_admin = root / "buzz-admin"
            fake_buzz = root / "buzz"
            private_key = "e" * 64
            _seed_identity(studio_home, "studio", private_key)
            _write_executable(fake_admin, "#!/bin/bash\nexit 99\n")
            _write_executable(
                fake_buzz,
                "#!/bin/bash\n"
                "case \"$*\" in\n"
                "  'channels list') printf 'relay timed out for %s\\n' \"$BUZZ_PRIVATE_KEY\" >&2; exit 42 ;;\n"
                "  'channels get --channel missing') printf '%s\\n' 'null' ;;\n"
                "  *) exit 44 ;;\n"
                "esac\n",
            )
            environment = {
                **os.environ,
                "PATH": "",
                "DEX_STUDIO_HOME": str(studio_home),
                "DEX_BUZZ_BIN": str(fake_buzz),
                "DEX_BUZZ_ADMIN": str(fake_admin),
            }
            probes = [
                subprocess.run(
                    [CORE_SOURCE, "post", "--as", "missing", "--room", "room-1", "--text", "x"],
                    env=environment,
                    capture_output=True,
                    text=True,
                ),
                subprocess.run(
                    [CORE_SOURCE, "timeline", "--room", "room-1", "--limit", "0"],
                    env=environment,
                    capture_output=True,
                    text=True,
                ),
                subprocess.run(
                    [CORE_SOURCE, "timeline", "--room", "missing", "--json"],
                    env=environment,
                    capture_output=True,
                    text=True,
                ),
                subprocess.run(
                    [CORE_SOURCE, "rooms", "list", "--json"],
                    env=environment,
                    capture_output=True,
                    text=True,
                ),
            ]

            for result in probes:
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("error", json.loads(result.stderr))
                self.assertNotIn(private_key, result.stderr)
            self.assertIn("unknown identity", json.loads(probes[0].stderr)["error"])
            self.assertIn("1 to 200", json.loads(probes[1].stderr)["error"])
            self.assertIn("unknown room", json.loads(probes[2].stderr)["error"])
            self.assertIn("relay timed out", json.loads(probes[3].stderr)["error"])

    def test_archive_verification_rejects_a_sidecar_checksum_mismatch(self) -> None:
        verifier = PACKAGE_ROOT / "verify_artifact.py"
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "artifact.tar.gz"
            archive.write_bytes(b"not the expected archive")
            Path(f"{archive}.sha256").write_text(
                f"{'0' * 64}  {archive.name}\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, verifier, archive],
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("archive SHA-256 mismatch", json.loads(result.stderr)["error"])

    def test_builder_refuses_a_runtime_not_proven_at_the_pinned_buzz_revision(self) -> None:
        builder = PACKAGE_ROOT / "build_artifact.py"
        self.assertTrue(builder.is_file(), "the package owns no artifact builder")
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [
                    "python3",
                    builder,
                    "--buzz-source",
                    PACKAGE_ROOT,
                    "--output",
                    temporary,
                ],
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(result.returncode, 0)
        error = json.loads(result.stderr)
        self.assertIn("pinned Buzz revision", error["error"])
        self.assertEqual(result.stdout, "")

    @unittest.skipUnless(
        os.environ.get("DEX_TEST_BUZZ_SOURCE"),
        "real pinned Buzz source was not supplied",
    )
    def test_real_runtime_builds_a_verified_platform_artifact(self) -> None:
        builder = PACKAGE_ROOT / "build_artifact.py"
        verifier = PACKAGE_ROOT / "verify_artifact.py"
        self.assertTrue(verifier.is_file(), "the package owns no artifact verifier")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            build_command = [
                sys.executable,
                builder,
                "--buzz-source",
                os.environ["DEX_TEST_BUZZ_SOURCE"],
                "--output",
                output,
            ]
            if os.environ.get("DEX_TEST_BUZZ_CARGO"):
                build_command.extend(["--cargo", os.environ["DEX_TEST_BUZZ_CARGO"]])
            if os.environ.get("DEX_TEST_BUZZ_TARGET_DIR"):
                build_command.extend(
                    ["--cargo-target-dir", os.environ["DEX_TEST_BUZZ_TARGET_DIR"]]
                )
            built = subprocess.run(
                build_command,
                capture_output=True,
                text=True,
            )
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            build_result = json.loads(built.stdout)
            artifact_dir = Path(build_result["artifact_dir"])
            archive = Path(build_result["archive"])
            self.assertTrue((artifact_dir / "bin" / "core").is_file())
            self.assertTrue((artifact_dir / "libexec" / "buzz").is_file())
            self.assertTrue((artifact_dir / "libexec" / "buzz-admin").is_file())
            self.assertTrue((artifact_dir / "manifest.json").is_file())
            self.assertTrue((artifact_dir / "SHA256SUMS").is_file())
            self.assertTrue(archive.is_file())
            self.assertTrue(Path(f"{archive}.sha256").is_file())

            verified = subprocess.run(
                [sys.executable, verifier, artifact_dir],
                env={**os.environ, "PATH": ""},
                capture_output=True,
                text=True,
            )
            self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
            report = json.loads(verified.stdout)
            self.assertEqual(report["status"], "verified")
            self.assertEqual(report["buzz_revision"], "b2ac66cde81df7ce1afc50016e1571cb6e8b7779")

            archive_verified = subprocess.run(
                [sys.executable, verifier, archive],
                env={**os.environ, "PATH": ""},
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                archive_verified.returncode,
                0,
                archive_verified.stdout + archive_verified.stderr,
            )
            self.assertEqual(json.loads(archive_verified.stdout)["status"], "verified")
            self.assertEqual(
                json.loads(archive_verified.stdout)["artifact"],
                str(archive.resolve()),
            )

            unexpected_directory = artifact_dir / "unexpected-empty-directory"
            unexpected_directory.mkdir()
            rejected = subprocess.run(
                [sys.executable, verifier, artifact_dir],
                capture_output=True,
                text=True,
            )
            unexpected_directory.rmdir()
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("unexpected directories", json.loads(rejected.stderr)["error"])


if __name__ == "__main__":
    unittest.main()
