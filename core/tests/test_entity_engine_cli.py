from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

from core.entity_engine import cli
import core.entity_engine.contract as entity_contract
from core.entity_engine.contract import render_update_log


def _run_cli(payload: object, *, vault: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["VAULT_PATH"] = str(vault)
    return subprocess.run(
        [sys.executable, "-m", "core.entity_engine.cli"],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_cli_applies_mixed_create_and_mutate_batch(tmp_path: Path) -> None:
    existing = tmp_path / "05-Areas" / "People" / "External" / "Existing.md"
    existing.parent.mkdir(parents=True)
    existing.write_text(
        "---\n"
        "type: person\n"
        "name: Existing Person\n"
        "company: Old Co\n"
        "dex_pinned: {}\n"
        "dex_last_written: {company: Old Co}\n"
        "---\n"
        "# Existing Person\n",
        encoding="utf-8",
    )
    base_fingerprint = hashlib.sha256(existing.read_bytes()).hexdigest()
    created = existing.with_name("Created.md")
    content = "# Created Person\n"

    completed = _run_cli(
        {
            "ops": [
                {
                    "op": "create",
                    "path": str(created),
                    "content": content,
                    "allowed_root": str(tmp_path),
                },
                {
                    "op": "mutate",
                    "path": str(existing),
                    "base_fingerprint": base_fingerprint,
                    "field_changes": {"company": "New Co"},
                },
            ]
        },
        vault=tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    response = json.loads(completed.stdout)
    assert [result["status"] for result in response["results"]] == [
        "created",
        "updated",
    ]
    assert response["results"][0] == {
        "path": str(created),
        "status": "created",
        "fingerprint": hashlib.sha256(content.encode()).hexdigest(),
    }
    assert response["results"][1]["path"] == str(existing)
    assert len(response["results"][1]["fingerprint"]) == 64
    assert created.read_text(encoding="utf-8") == content
    assert "company: New Co" in existing.read_text(encoding="utf-8")


def test_cli_rejects_malformed_op_before_applying_batch(tmp_path: Path) -> None:
    target = tmp_path / "05-Areas" / "People" / "External" / "Never.md"

    completed = _run_cli(
        {
            "ops": [
                {
                    "op": "create",
                    "path": str(target),
                    "content": "# Must not be created\n",
                    "allowed_root": str(tmp_path),
                },
                {"op": "mutate", "path": str(target)},
            ]
        },
        vault=tmp_path,
    )

    assert completed.returncode == 2
    assert json.loads(completed.stdout) == {
        "error": {
            "code": "invalid_batch",
            "message": "ops[1].base_fingerprint must be a SHA-256 hex string",
        }
    }
    assert not target.exists()


def test_run_validates_and_dispatches_mixed_batch_in_process(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "05-Areas" / "People" / "External" / "Existing.md"
    existing.parent.mkdir(parents=True)
    existing.write_text(
        "---\n"
        "type: person\n"
        "name: Existing Person\n"
        "company: Old Co\n"
        "dex_pinned: {}\n"
        "dex_last_written: {company: Old Co}\n"
        "---\n"
        "# Existing Person\n",
        encoding="utf-8",
    )
    created = existing.with_name("Created.md")
    content = "# Created Person\n"

    response = cli.run(
        {
            "ops": [
                {
                    "op": "create",
                    "path": str(created),
                    "content": content,
                    "allowed_root": str(tmp_path),
                },
                {
                    "op": "create",
                    "path": str(created),
                    "content": "# Must not replace\n",
                    "allowed_root": str(tmp_path),
                },
                {
                    "op": "mutate",
                    "path": str(existing),
                    "base_fingerprint": hashlib.sha256(
                        existing.read_bytes()
                    ).hexdigest(),
                    "replacement_content": existing.read_text(encoding="utf-8"),
                    "field_changes": {"company": "New Co"},
                    "ensure_regions": ["relationships"],
                    "region_projections": {
                        "relationships": "- works with [[Created Person]]"
                    },
                },
            ]
        }
    )

    assert [result["status"] for result in response["results"]] == [
        "created",
        "exists",
        "updated",
    ]
    assert response["results"][1]["fingerprint"] == hashlib.sha256(
        content.encode()
    ).hexdigest()
    assert created.read_text(encoding="utf-8") == content
    updated = existing.read_text(encoding="utf-8")
    assert "company: New Co" in updated
    assert "- works with [[Created Person]]" in updated


def test_run_applies_materialized_relationship_mutation_in_process(
    tmp_path: Path,
) -> None:
    page = tmp_path / "05-Areas" / "People" / "External" / "Related.md"
    page.parent.mkdir(parents=True)
    page.write_text(
        "---\n"
        "type: person\n"
        "name: Related Person\n"
        "dex_pinned: {}\n"
        "dex_last_written: {type: person, name: Related Person}\n"
        "---\n"
        "# Related Person\n",
        encoding="utf-8",
    )
    relationships = [
        {
            "type": "works_at",
            "target": "[[Acme]]",
            "status": "suggested",
            "source": {"kind": "domain-match", "id": "acme.test"},
            "date": "2026-07-23",
        }
    ]

    response = cli.run(
        {
            "ops": [
                {
                    "op": "mutate",
                    "path": str(page),
                    "base_fingerprint": hashlib.sha256(
                        page.read_bytes()
                    ).hexdigest(),
                    "field_changes": {"relationships": relationships},
                    "ensure_regions": ["relationships", "update-log"],
                    "region_projections": {
                        "relationships": entity_contract.render_relationships(
                            relationships
                        ),
                        "update-log": render_update_log(
                            relationship_provenance=relationships
                        ),
                    },
                }
            ]
        }
    )

    assert response["results"][0]["status"] == "updated"
    updated = page.read_text(encoding="utf-8")
    assert "### works_at\n- [[Acme]] (suggested)" in updated
    assert (
        "- 2026-07-23 — relationship · works_at — [[Acme]]"
        in updated
    )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (None, "request must be an object"),
        ({}, "request.ops must be an array"),
        ({"ops": [None]}, "ops[0] must be an object"),
        (
            {"ops": [{"op": 1, "path": "Person.md"}]},
            "ops[0].op must be a string",
        ),
        (
            {"ops": [{"op": "create", "path": 1, "content": "page"}]},
            "ops[0].path must be a string",
        ),
        (
            {"ops": [{"op": "create", "path": "Person.md", "content": 1}]},
            "ops[0].content must be a string",
        ),
        (
            {
                "ops": [
                    {
                        "op": "create",
                        "path": "Person.md",
                        "content": "page",
                        "allowed_root": 1,
                    }
                ]
            },
            "ops[0].allowed_root must be a string",
        ),
        (
            {"ops": [{"op": "delete", "path": "Person.md"}]},
            "ops[0].op must be create or mutate",
        ),
        (
            {
                "ops": [
                    {
                        "op": "mutate",
                        "path": "Person.md",
                        "base_fingerprint": "not-a-fingerprint",
                    }
                ]
            },
            "ops[0].base_fingerprint must be a SHA-256 hex string",
        ),
        (
            {
                "ops": [
                    {
                        "op": "mutate",
                        "path": "Person.md",
                        "base_fingerprint": "0" * 64,
                        "field_changes": [],
                    }
                ]
            },
            "ops[0].field_changes must be an object",
        ),
        (
            {
                "ops": [
                    {
                        "op": "mutate",
                        "path": "Person.md",
                        "base_fingerprint": "0" * 64,
                        "replacement_content": 1,
                    }
                ]
            },
            "ops[0].replacement_content must be a string",
        ),
        (
            {
                "ops": [
                    {
                        "op": "mutate",
                        "path": "Person.md",
                        "base_fingerprint": "0" * 64,
                        "ensure_regions": [1],
                    }
                ]
            },
            "ops[0].ensure_regions must be an array of strings",
        ),
        (
            {
                "ops": [
                    {
                        "op": "mutate",
                        "path": "Person.md",
                        "base_fingerprint": "0" * 64,
                        "region_projections": [],
                    }
                ]
            },
            "ops[0].region_projections must be an object",
        ),
    ],
)
def test_run_rejects_invalid_batch_shapes_in_process(
    payload: object,
    message: str,
) -> None:
    with pytest.raises(cli.InvalidBatch) as error:
        cli.run(payload)
    assert str(error.value) == message


def test_main_formats_success_as_sorted_json_in_process(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli.sys, "stdin", StringIO('{"ops": []}'))

    assert cli.main() == 0
    assert capsys.readouterr().out == '{"results": []}\n'


@pytest.mark.parametrize(
    ("stdin", "run_error", "exit_code", "error_code"),
    [
        ("{", None, 2, "invalid_batch"),
        ('{"ops": []}', OSError("disk unavailable"), 1, "engine_failure"),
    ],
)
def test_main_formats_errors_as_json_in_process(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stdin: str,
    run_error: OSError | None,
    exit_code: int,
    error_code: str,
) -> None:
    monkeypatch.setattr(cli.sys, "stdin", StringIO(stdin))
    if run_error is not None:
        monkeypatch.setattr(
            cli,
            "run",
            lambda _payload: (_ for _ in ()).throw(run_error),
        )

    assert cli.main() == exit_code
    assert json.loads(capsys.readouterr().out)["error"]["code"] == error_code
