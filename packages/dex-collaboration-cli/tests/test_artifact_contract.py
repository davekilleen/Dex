from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CORE_SOURCE = PACKAGE_ROOT / "src" / "core"


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _install_test_artifact(root: Path) -> tuple[Path, Path, Path]:
    core = root / "bin" / "core"
    buzz = root / "libexec" / "buzz"
    buzz_admin = root / "libexec" / "buzz-admin"
    core.parent.mkdir(parents=True)
    buzz.parent.mkdir(parents=True)
    shutil.copyfile(CORE_SOURCE, core)
    core.chmod(0o755)
    return core, buzz, buzz_admin


def _seed_identity(studio_home: Path, identity_id: str, private_key: str) -> None:
    key_dir = studio_home / "keys" / "agents" / identity_id
    key_dir.mkdir(parents=True)
    for directory in (studio_home, studio_home / "keys", studio_home / "keys" / "agents"):
        directory.chmod(0o700)
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

    def test_core_shell_is_bsd_portable_and_uses_only_bundled_runtime_paths(self) -> None:
        source = CORE_SOURCE.read_text(encoding="utf-8")
        for utility in ("chmod", "dirname", "mkdir", "mv", "rm", "rmdir"):
            self.assertNotRegex(
                source,
                rf"(?m)^\s*{utility}\b[^\n]*\s--(?:\s|$)",
                f"{utility} uses a non-POSIX option terminator",
            )
        self.assertNotIn("DEX_BUZZ_BIN", source)
        self.assertNotIn("DEX_BUZZ_ADMIN", source)

    def test_identity_create_uses_the_bundled_admin_and_keeps_the_private_key_local(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            studio_home = root / "studio"
            log_path = root / "buzz.log"
            core, fake_buzz, fake_admin = _install_test_artifact(root / "artifact")
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
                "DEX_TEST_LOG": str(log_path),
            }
            result = subprocess.run(
                [core, "identity", "create", "--name", "Research Scout"],
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
                [core, "identity", "create", "--name", "Research Scout"],
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
            core, fake_buzz, fake_admin = _install_test_artifact(root / "artifact")
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
                "DEX_TEST_LOG": str(log_path),
            }
            listed = subprocess.run(
                [core, "rooms", "list", "--as", "studio", "--json"],
                env=environment,
                capture_output=True,
                text=True,
            )
            created = subprocess.run(
                [
                    core,
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
            core, fake_buzz, fake_admin = _install_test_artifact(root / "artifact")
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
                "DEX_TEST_LOG": str(log_path),
            }
            posted = subprocess.run(
                [
                    core,
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
                [core, "timeline", "--room", "room-1", "--limit", "2", "--json"],
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
            core, fake_buzz, fake_admin = _install_test_artifact(root / "artifact")
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
            }
            probes = [
                subprocess.run(
                    [core, "post", "--as", "missing", "--room", "room-1", "--text", "x"],
                    env=environment,
                    capture_output=True,
                    text=True,
                ),
                subprocess.run(
                    [core, "timeline", "--room", "room-1", "--limit", "0"],
                    env=environment,
                    capture_output=True,
                    text=True,
                ),
                subprocess.run(
                    [core, "timeline", "--room", "missing", "--json"],
                    env=environment,
                    capture_output=True,
                    text=True,
                ),
                subprocess.run(
                    [core, "rooms", "list", "--json"],
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

    def test_existing_identity_custody_fails_closed_on_unsafe_modes_or_symlinks(self) -> None:
        for unsafe_case in ("key-mode", "directory-mode", "key-symlink"):
            with self.subTest(unsafe_case=unsafe_case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                studio_home = root / "studio"
                core, fake_buzz, fake_admin = _install_test_artifact(root / "artifact")
                _write_executable(fake_buzz, "#!/bin/bash\nexit 99\n")
                _write_executable(fake_admin, "#!/bin/bash\nexit 99\n")
                _seed_identity(studio_home, "unsafe", "f" * 64)
                key_file = studio_home / "keys" / "agents" / "unsafe" / "key.json"
                if unsafe_case == "key-mode":
                    key_file.chmod(0o644)
                elif unsafe_case == "directory-mode":
                    key_file.parent.chmod(0o755)
                else:
                    original = key_file.with_name("original.json")
                    key_file.rename(original)
                    key_file.symlink_to(original)
                result = subprocess.run(
                    [core, "post", "--as", "unsafe", "--room", "room-1", "--text", "x"],
                    env={
                        **os.environ,
                        "PATH": "",
                        "DEX_STUDIO_HOME": str(studio_home),
                    },
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("unsafe identity custody", json.loads(result.stderr)["error"])
                self.assertNotIn("f" * 64, result.stderr)

    def test_every_selected_identity_rejects_dot_slash_and_traversal_ids(self) -> None:
        probes = (
            (".", ["rooms", "list", "--as", ".", "--json"]),
            (
                "nested/owner",
                ["rooms", "create", "--name", "Knowledge", "--as", "nested/owner"],
            ),
            (
                "../escaped",
                ["post", "--as", "../escaped", "--room", "room-1", "--text", "x"],
            ),
            (
                "../../escaped",
                ["timeline", "--room", "room-1", "--as", "../../escaped", "--json"],
            ),
        )
        for identity_id, arguments in probes:
            with self.subTest(identity_id=identity_id), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                studio_home = root / "studio"
                log_path = root / "buzz.log"
                core, fake_buzz, fake_admin = _install_test_artifact(root / "artifact")
                _seed_identity(studio_home, identity_id, "f" * 64)
                _write_executable(fake_admin, "#!/bin/bash\nexit 99\n")
                _write_executable(
                    fake_buzz,
                    "#!/bin/bash\n"
                    "printf '%s\\n' \"$*\" >> \"$DEX_TEST_LOG\"\n"
                    "case \"$*\" in\n"
                    "  'channels list') printf '%s\\n' '[]' ;;\n"
                    "  'channels create --name Knowledge --type stream --visibility open') printf '%s\\n' '{\"channel_id\":\"room-2\"}' ;;\n"
                    "  'channels get --channel room-1') printf '%s\\n' '{\"channel_id\":\"room-1\"}' ;;\n"
                    "  'channels join --channel room-1') printf '%s\\n' '{\"accepted\":true}' ;;\n"
                    "  'messages send --channel room-1 --content x') printf '%s\\n' '{\"event_id\":\"event-1\"}' ;;\n"
                    "  'messages get --channel room-1') printf '%s\\n' '[]' ;;\n"
                    "  *) exit 41 ;;\n"
                    "esac\n",
                )
                result = subprocess.run(
                    [core, *arguments],
                    env={
                        **os.environ,
                        "PATH": "",
                        "DEX_STUDIO_HOME": str(studio_home),
                        "DEX_TEST_LOG": str(log_path),
                    },
                    capture_output=True,
                    text=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("identity id is invalid", json.loads(result.stderr)["error"])
                self.assertFalse(log_path.exists(), "invalid identity reached the Buzz runtime")

    def test_identity_create_rejects_preexisting_symlinked_custody_parents(self) -> None:
        for unsafe_parent in ("studio", "keys", "agents"):
            with self.subTest(unsafe_parent=unsafe_parent), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                studio_home = root / "studio"
                external = root / "external"
                external.mkdir()
                if unsafe_parent == "studio":
                    studio_home.symlink_to(external, target_is_directory=True)
                elif unsafe_parent == "keys":
                    studio_home.mkdir()
                    (studio_home / "keys").symlink_to(external, target_is_directory=True)
                else:
                    (studio_home / "keys").mkdir(parents=True)
                    (studio_home / "keys" / "agents").symlink_to(
                        external,
                        target_is_directory=True,
                    )
                core, fake_buzz, fake_admin = _install_test_artifact(root / "artifact")
                _write_executable(
                    fake_admin,
                    "#!/bin/bash\n"
                    "printf '%s\\n' 'Public key: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'\n"
                    "printf '%s\\n' 'Secret key: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'\n",
                )
                _write_executable(fake_buzz, "#!/bin/bash\nprintf '%s\\n' '{\"accepted\":true}'\n")
                result = subprocess.run(
                    [core, "identity", "create", "--name", "Research Scout"],
                    env={**os.environ, "PATH": "", "DEX_STUDIO_HOME": str(studio_home)},
                    capture_output=True,
                    text=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("unsafe identity custody", json.loads(result.stderr)["error"])
                self.assertEqual(list(external.rglob("key.json")), [])

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

    def test_builder_has_no_caller_selected_cargo_or_target_and_redacts_diagnostics(self) -> None:
        builder = PACKAGE_ROOT / "build_artifact.py"
        help_result = subprocess.run(
            [sys.executable, builder, "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(help_result.returncode, 0)
        self.assertNotIn("--cargo", help_result.stdout)
        self.assertNotIn("--cargo-target-dir", help_result.stdout)

        sys.path.insert(0, str(PACKAGE_ROOT))
        try:
            import build_artifact

            source = Path("/private/build/buzz")
            target = Path("/private/build/target")
            diagnostic = build_artifact._bounded_cargo_diagnostic(
                "Compiling example\n"
                f"error[E0001]: failed in {source}/crates/example/src/lib.rs\n"
                f"  target: {target}/release/example\n"
                "  BUZZ_PRIVATE_KEY=super-secret-value\n"
                "warning: build failed, waiting for other jobs to finish...\n",
                source,
                target,
            )
        finally:
            sys.path.pop(0)
        self.assertIn("error[E0001]", diagnostic)
        self.assertIn("<buzz-source>", diagnostic)
        self.assertIn("<cargo-target>", diagnostic)
        self.assertNotIn("/private/build", diagnostic)
        self.assertNotIn("super-secret-value", diagnostic)
        self.assertLessEqual(len(diagnostic), 4096)

        poisoned = {
            "RUSTC": "/tmp/fake-rustc",
            "RUSTFLAGS": "--cfg injected",
            "RUSTC_WRAPPER": "/tmp/fake-wrapper",
            "CARGO_BUILD_RUSTC": "/tmp/fake-rustc",
            "CARGO_TARGET_DIR": "/tmp/prebuilt",
            "HERMIT_EXE": "/tmp/fake-hermit",
            "HERMIT_STATE_DIR": "/tmp/fake-hermit-state",
            "HOME": "/tmp/fake-home",
            "XDG_CACHE_HOME": "/tmp/fake-xdg",
        }
        with tempfile.TemporaryDirectory() as sanitized_temporary:
            target = Path(sanitized_temporary) / "fresh-target"
            environment = build_artifact._sanitized_build_environment(
                target,
                source_environment={**os.environ, **poisoned},
            )
            for key in ("RUSTC", "RUSTFLAGS", "RUSTC_WRAPPER", "CARGO_BUILD_RUSTC"):
                self.assertNotIn(key, environment)
            self.assertEqual(environment["CARGO_TARGET_DIR"], str(target))
            self.assertEqual(environment["HOME"], str(target.parent / ".hermit-home"))
            self.assertEqual(environment["XDG_CACHE_HOME"], str(target.parent / ".xdg-cache"))
            self.assertEqual(environment["HERMIT_STATE_DIR"], str(target.parent / ".hermit-state"))
            self.assertEqual(
                environment["HERMIT_EXE"],
                str(target.parent / ".hermit-state/pkg/hermit@stable/hermit"),
            )
            for key in ("HOME", "XDG_CACHE_HOME", "HERMIT_STATE_DIR", "HERMIT_EXE"):
                self.assertNotEqual(environment[key], poisoned[key])

        with tempfile.TemporaryDirectory() as temporary:
            prebuilt_output = Path(temporary)
            (prebuilt_output / ".cargo-target" / "release").mkdir(parents=True)
            _write_executable(
                prebuilt_output / ".cargo-target" / "release" / "buzz",
                "#!/bin/bash\nexit 0\n",
            )
            rejected = subprocess.run(
                [
                    sys.executable,
                    builder,
                    "--buzz-source",
                    PACKAGE_ROOT,
                    "--output",
                    prebuilt_output,
                ],
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("must be empty", json.loads(rejected.stderr)["error"])

    def test_builder_canonicalizes_relative_cli_paths_before_building(self) -> None:
        sys.path.insert(0, str(PACKAGE_ROOT))
        try:
            import build_artifact

            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with (
                    mock.patch.object(build_artifact, "build", return_value={"status": "ok"}) as build,
                    mock.patch("builtins.print"),
                ):
                    previous = Path.cwd()
                    try:
                        os.chdir(root)
                        result = build_artifact.main(
                            ["--buzz-source", "relative-buzz", "--output", "relative-output"]
                        )
                    finally:
                        os.chdir(previous)
                self.assertEqual(result, 0)
                arguments = build.call_args.args[0]
                canonical_root = root.resolve()
                self.assertEqual(arguments.buzz_source, canonical_root / "relative-buzz")
                self.assertEqual(arguments.output, canonical_root / "relative-output")
                self.assertTrue(arguments.buzz_source.is_absolute())
                self.assertTrue(arguments.output.is_absolute())
        finally:
            sys.path.pop(0)

    def test_workflow_keeps_buzz_checkout_outside_the_dex_source_tree(self) -> None:
        workflow = (
            PACKAGE_ROOT.parents[1]
            / ".github"
            / "workflows"
            / "b5-core-collaboration-artifact.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("working-directory: Dex", workflow)
        self.assertIn("path: Dex", workflow)
        self.assertIn("ref: ${{ github.event.pull_request.head.sha || github.sha }}", workflow)
        self.assertIn("path: Buzz", workflow)
        self.assertIn("${{ github.workspace }}/Buzz", workflow)
        self.assertNotIn("path: _buzz", workflow)

    def test_failed_build_removes_private_state_outside_the_deliverable_output(self) -> None:
        sys.path.insert(0, str(PACKAGE_ROOT))
        try:
            import build_artifact

            contract = json.loads((PACKAGE_ROOT / "contract.json").read_text(encoding="utf-8"))
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "buzz"
                source.mkdir()
                output = root / "deliverables"
                build_roots: list[Path] = []

                def fail_runtime(arguments, build_root=None):
                    private_root = Path(build_root) if build_root is not None else arguments.output
                    build_roots.append(private_root)
                    (private_root / ".hermit-state").mkdir(parents=True)
                    raise build_artifact.BuildError("expected build failure")

                arguments = type(
                    "Arguments",
                    (),
                    {"buzz_source": source, "output": output, "jobs": 1},
                )()
                with (
                    mock.patch.object(
                        build_artifact,
                        "_git_head",
                        return_value=contract["buzz_revision"],
                    ),
                    mock.patch.object(build_artifact, "_require_clean_source"),
                    mock.patch.object(
                        build_artifact,
                        "_build_pinned_runtime",
                        side_effect=fail_runtime,
                    ),
                    self.assertRaisesRegex(build_artifact.BuildError, "expected build failure"),
                ):
                    build_artifact.build(arguments)

                self.assertEqual(list(output.iterdir()) if output.exists() else [], [])
                self.assertEqual(list(root.glob(".dex-core-build-*")), [])
                self.assertEqual(len(build_roots), 1)
                self.assertNotEqual(build_roots[0], output)
        finally:
            sys.path.pop(0)

    def test_builder_requires_a_clean_dex_checkout_before_starting_runtime_build(self) -> None:
        sys.path.insert(0, str(PACKAGE_ROOT))
        try:
            import build_artifact

            contract = json.loads((PACKAGE_ROOT / "contract.json").read_text(encoding="utf-8"))
            dex_root = PACKAGE_ROOT.parents[1]
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "buzz"
                source.mkdir()
                output = root / "new-parent" / "output"
                arguments = type(
                    "Arguments",
                    (),
                    {"buzz_source": source, "output": output, "jobs": 1},
                )()

                def require_clean(checkout):
                    if Path(checkout) == dex_root:
                        self.assertFalse(output.parent.exists())
                        raise build_artifact.BuildError(
                            "Dex source checkout is dirty; artifact provenance is not exact"
                        )

                with (
                    mock.patch.object(
                        build_artifact,
                        "_git_head",
                        return_value=contract["buzz_revision"],
                    ),
                    mock.patch.object(
                        build_artifact,
                        "_require_clean_source",
                        side_effect=require_clean,
                    ),
                    mock.patch.object(build_artifact, "_build_pinned_runtime") as runtime_build,
                    self.assertRaisesRegex(build_artifact.BuildError, "Dex source checkout is dirty"),
                ):
                    build_artifact.build(arguments)
                runtime_build.assert_not_called()
                self.assertFalse(output.parent.exists())
        finally:
            sys.path.pop(0)

    def test_verifier_binds_complete_provenance_to_the_source_contract(self) -> None:
        sys.path.insert(0, str(PACKAGE_ROOT))
        try:
            import verify_artifact
            from artifact_support import ArtifactError, sha256_file

            contract = json.loads((PACKAGE_ROOT / "contract.json").read_text(encoding="utf-8"))
            valid = {
                "buzz_repository": contract["buzz_repository"],
                "buzz_revision": contract["buzz_revision"],
                "buzz_tree_clean": True,
                "cargo_target_fresh": True,
                "hermit_state_isolated": True,
                "dex_revision": "a" * 40,
                "dex_tree_clean": True,
                "source_contract_sha256": sha256_file(PACKAGE_ROOT / "contract.json"),
                "toolchain": {
                    "cargo": "cargo 1.95.0 (test)",
                    "rustc": "rustc 1.95.0 (test)",
                },
            }
            verify_artifact._verify_source_identity(valid, contract)
            invalid_values = {
                "buzz_repository": "https://example.invalid/buzz.git",
                "dex_revision": "not-a-revision",
                "dex_tree_clean": False,
                "source_contract_sha256": "0" * 64,
            }
            for field, value in invalid_values.items():
                with self.subTest(field=field), self.assertRaises(ArtifactError):
                    verify_artifact._verify_source_identity({**valid, field: value}, contract)
        finally:
            sys.path.pop(0)

    def test_native_dependency_policy_rejects_non_baseline_libraries(self) -> None:
        sys.path.insert(0, str(PACKAGE_ROOT))
        try:
            from artifact_support import require_baseline_dependencies

            require_baseline_dependencies(
                "linux",
                ["libc.so.6", "libm.so.6", "libgcc_s.so.1", "ld-linux-x86-64.so.2"],
            )
            with self.assertRaisesRegex(RuntimeError, "non-baseline"):
                require_baseline_dependencies("linux", ["/tmp/libinjected.so"])
            require_baseline_dependencies(
                "darwin",
                ["/usr/lib/libSystem.B.dylib", "/System/Library/Frameworks/Security.framework/Security"],
            )
            with self.assertRaisesRegex(RuntimeError, "non-baseline"):
                require_baseline_dependencies("darwin", ["@rpath/libinjected.dylib"])
        finally:
            sys.path.pop(0)

    @unittest.skipUnless(
        os.environ.get("DEX_TEST_BUZZ_LAUNCHER_SOURCE"),
        "real pinned Buzz launcher source was not supplied",
    )
    def test_build_environment_never_executes_caller_cached_hermit(self) -> None:
        source = Path(os.environ["DEX_TEST_BUZZ_LAUNCHER_SOURCE"])
        revision = subprocess.run(
            ["git", "-C", source, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.assertEqual(revision, "b2ac66cde81df7ce1afc50016e1571cb6e8b7779")

        sys.path.insert(0, str(PACKAGE_ROOT))
        try:
            import build_artifact

            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                caller_home = root / "caller-home"
                caller_xdg = root / "caller-xdg"
                target = root / "builder" / ".cargo-target"
                poison_home_marker = root / "poison-home-ran"
                poison_xdg_marker = root / "poison-xdg-ran"
                controlled_marker = root / "controlled-ran"
                fake_locations = (
                    (caller_home / ".cache/hermit/pkg/hermit@stable/hermit", poison_home_marker),
                    (caller_xdg / "hermit/pkg/hermit@stable/hermit", poison_xdg_marker),
                    (
                        target.parent / ".hermit-state/pkg/hermit@stable/hermit",
                        controlled_marker,
                    ),
                )
                for executable, marker in fake_locations:
                    executable.parent.mkdir(parents=True)
                    _write_executable(
                        executable,
                        "#!/bin/bash\n"
                        f"/usr/bin/touch '{marker}'\n"
                        "printf '%s\\n' 'cargo 1.95.0 (controlled-test)'\n",
                    )
                environment = build_artifact._sanitized_build_environment(
                    target,
                    source=source,
                    source_environment={
                        "HOME": str(caller_home),
                        "XDG_CACHE_HOME": str(caller_xdg),
                        "USER": "caller",
                    },
                )
                result = subprocess.run(
                    [source / "bin" / "cargo", "--version", "--verbose"],
                    cwd=source,
                    env=environment,
                    capture_output=True,
                    text=True,
                )

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(controlled_marker.is_file())
                self.assertFalse(poison_home_marker.exists())
                self.assertFalse(poison_xdg_marker.exists())
                self.assertNotEqual(environment.get("HOME"), str(caller_home))
                self.assertNotEqual(environment.get("XDG_CACHE_HOME"), str(caller_xdg))
        finally:
            sys.path.pop(0)

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
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {artifact_dir.name, archive.name, f"{archive.name}.sha256"},
            )
            manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
            sources = manifest["sources"]
            self.assertTrue(sources["dex_tree_clean"])
            self.assertRegex(sources["dex_revision"], r"^[0-9a-f]{40}$")
            self.assertEqual(
                sources["source_contract_sha256"],
                hashlib.sha256((PACKAGE_ROOT / "contract.json").read_bytes()).hexdigest(),
            )
            self.assertEqual(
                sources["buzz_repository"],
                "https://github.com/block/buzz.git",
            )

            rerun = subprocess.run(
                build_command,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(rerun.returncode, 0)
            self.assertIn("must be empty", json.loads(rerun.stderr)["error"])

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
