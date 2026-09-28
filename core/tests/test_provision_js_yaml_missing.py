"""provision.cjs must fail closed when YAML is required and js-yaml is missing."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVISIONER = REPO_ROOT / "core" / "provision.cjs"


def _prepare_yaml_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "core").mkdir()
    (vault / ".scripts").mkdir()
    shutil.copy(REPO_ROOT / "System/.mcp.json.example", vault / "System/.mcp.json.example")
    shutil.copy(
        REPO_ROOT / "System/user-profile-template.yaml",
        vault / "System/user-profile-template.yaml",
    )
    shutil.copy(REPO_ROOT / "core/paths.py", vault / "core/paths.py")
    shutil.copy(REPO_ROOT / "package.json", vault / "package.json")
    shutil.copy(REPO_ROOT / "CLAUDE.md", vault / "CLAUDE.md")
    return vault


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_provision_fails_closed_when_js_yaml_missing_and_yaml_is_needed(
    tmp_path: Path,
) -> None:
    vault = _prepare_yaml_vault(tmp_path)
    hide = tmp_path / "hide-js-yaml.cjs"
    hide.write_text(
        """\
'use strict';
const Module = require('module');
const original = Module._resolveFilename;
Module._resolveFilename = function resolveFilename(request, parent, isMain, options) {
  if (request === 'js-yaml') {
    const error = new Error("Cannot find module 'js-yaml'");
    error.code = 'MODULE_NOT_FOUND';
    throw error;
  }
  return original.call(this, request, parent, isMain, options);
};
""",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            "node",
            "-r",
            str(hide),
            str(PROVISIONER),
            "--path",
            str(vault),
            "--dry-run",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    combined = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode == 1, combined
    assert "js-yaml" in combined
    try:
        summary = json.loads(completed.stdout)
    except json.JSONDecodeError:
        summary = None
    if summary is not None:
        assert summary.get("ok") is False
        errors = " ".join(str(item) for item in summary.get("errors", []))
        assert "js-yaml" in errors
