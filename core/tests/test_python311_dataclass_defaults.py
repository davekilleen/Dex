"""Python 3.11 must accept Dex dataclass field defaults on MCP import.

CPython 3.11 dataclasses reject a field default when
``f.default.__hash__ is None``. ``types.MappingProxyType`` instances were
unhashable then, so ``ReleaseBaseline.alternate_hashes = MappingProxyType({})``
raised ``ValueError`` while the class body ran. Eight MCP servers import that
class through ``core.lifecycle`` and died on start.

CPython 3.12 gave ``MappingProxyType`` a class ``__hash__`` and switched the
dataclass check to ``f.default.__class__.__hash__ is None``, so 3.12 CI stayed
green. This module applies the 3.11 rule even when the suite runs on 3.12.
"""

from __future__ import annotations

import ast
import importlib
from dataclasses import MISSING, fields
from pathlib import Path
from types import MappingProxyType

import pytest

from core.lifecycle.customizations import ReleaseBaseline

CORE_ROOT = Path(__file__).resolve().parents[1]

AFFECTED_MCP_SERVERS = (
    "core.mcp.work_server",
    "core.mcp.calendar_server",
    "core.mcp.career_server",
    "core.mcp.resume_server",
    "core.mcp.onboarding_server",
    "core.mcp.analytics_server",
    "core.mcp.dex_improvements_server",
    "core.mcp.customization_migration_server",
)


def _python_311_rejects_field_default(default: object) -> bool:
    """Return True when CPython 3.11 dataclasses would reject this default.

    3.11 used ``f.default.__hash__ is None``. MappingProxyType instances
    gained a working class ``__hash__`` in 3.12, so the same object is
    accepted there. Treat that type as 3.11 does so this test fails on
    3.12 CI without the production fix.
    """
    if default is MISSING:
        return False
    if type(default) is MappingProxyType:
        return True
    return default.__hash__ is None


def _is_dataclass_decorator(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "dataclass"
    if isinstance(node, ast.Attribute):
        return node.attr == "dataclass"
    if isinstance(node, ast.Call):
        return _is_dataclass_decorator(node.func)
    return False


def _is_mappingproxy_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "MappingProxyType"
    return isinstance(func, ast.Attribute) and func.attr == "MappingProxyType"


def test_release_baseline_defaults_survive_python_311_dataclass_check() -> None:
    rejected = [
        field.name
        for field in fields(ReleaseBaseline)
        if _python_311_rejects_field_default(field.default)
    ]
    assert rejected == [], (
        "Python 3.11 rejects MappingProxyType (and any other unhashable object) "
        "as a dataclass field default. Use default_factory. Rejected fields: "
        f"{rejected}"
    )


def test_core_dataclasses_do_not_use_mappingproxy_field_defaults() -> None:
    violations: list[str] = []
    for path in CORE_ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(_is_dataclass_decorator(decorator) for decorator in node.decorator_list):
                continue
            for statement in node.body:
                if not isinstance(statement, ast.AnnAssign) or statement.value is None:
                    continue
                if _is_mappingproxy_call(statement.value):
                    target = (
                        statement.target.id
                        if isinstance(statement.target, ast.Name)
                        else ast.dump(statement.target)
                    )
                    rel = path.relative_to(CORE_ROOT.parent)
                    violations.append(f"{rel}:{statement.lineno} {node.name}.{target}")
    assert violations == [], (
        "MappingProxyType({...}) is not a legal dataclass field default on "
        "Python 3.11; use field(default_factory=...). Found: "
        + ", ".join(violations)
    )


@pytest.mark.parametrize("module_path", AFFECTED_MCP_SERVERS)
def test_affected_mcp_servers_import_on_supported_python(module_path: str) -> None:
    importlib.import_module(module_path)
