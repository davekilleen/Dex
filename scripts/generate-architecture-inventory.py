#!/usr/bin/env python3
"""Generate the code-derived Dex architecture inventory."""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs/architecture/INVENTORY.md"
GENERATOR_PATH = "scripts/generate-architecture-inventory.py"
TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
TRIGGER = re.compile(r"\b(?:when|whenever)\b", re.IGNORECASE)
OWNERSHIP_ORDER = ("brain", "seed", "generated", "vault", "runtime")
UNDER_SURFACED_MAX = 0
OVER_SURFACED_MIN = 11


class InventoryError(RuntimeError):
    """Raised when source code cannot yield a trustworthy inventory."""


@dataclass(frozen=True)
class Engine:
    source: str
    server_name: str
    tools: tuple[str, ...]
    has_feature_status: bool


@dataclass(frozen=True)
class Skill:
    name: str
    source: str
    description: str
    body: str

    @property
    def has_trigger(self) -> bool:
        return TRIGGER.search(self.description) is not None


@dataclass(frozen=True)
class OwnershipRule:
    rule_id: str
    path: str
    kind: str
    ownership: str


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _keyword_string(call: ast.Call, keyword: str) -> str | None:
    for item in call.keywords:
        if item.arg == keyword:
            return _string(item.value)
    return None


def _literal_tool_names(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return {
            value
            for item in node.elts
            if (value := _string(item)) is not None and TOOL_NAME.fullmatch(value)
        }
    value = _string(node)
    if value is not None and TOOL_NAME.fullmatch(value):
        return {value}
    return set()


def _dispatch_tool_names(compare: ast.Compare) -> set[str]:
    """Extract literal ``name`` dispatch values, including reversed equality."""
    names: set[str] = set()
    operands = [compare.left, *compare.comparators]
    for index, operator in enumerate(compare.ops):
        left = operands[index]
        right = operands[index + 1]
        left_is_name = isinstance(left, ast.Name) and left.id == "name"
        right_is_name = isinstance(right, ast.Name) and right.id == "name"
        if isinstance(operator, ast.Eq):
            if left_is_name:
                names.update(_literal_tool_names(right))
            elif right_is_name:
                names.update(_literal_tool_names(left))
        elif isinstance(operator, ast.In) and left_is_name:
            names.update(_literal_tool_names(right))
    return names


def discover_engines(repo_root: Path) -> list[Engine]:
    engines: list[Engine] = []
    for path in sorted((repo_root / "core/mcp").glob("*_server.py")):
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as error:
            raise InventoryError(f"cannot parse MCP server {path}: {error}") from error

        server_names: set[str] = set()
        registered_tools: set[str] = set()
        dispatched_tools: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                call_name = _call_name(node)
                if call_name == "Server" and node.args:
                    if (server_name := _string(node.args[0])) is not None:
                        server_names.add(server_name)
                elif call_name == "Tool":
                    tool_name = _keyword_string(node, "name")
                    if tool_name is None and node.args:
                        tool_name = _string(node.args[0])
                    if tool_name is not None and TOOL_NAME.fullmatch(tool_name):
                        registered_tools.add(tool_name)
            elif isinstance(node, ast.Compare):
                dispatched_tools.update(_dispatch_tool_names(node))

        if len(server_names) != 1:
            relative = path.relative_to(repo_root).as_posix()
            raise InventoryError(
                f"expected exactly one literal Server name in {relative}; "
                f"found {sorted(server_names)}"
            )
        tools = tuple(sorted(registered_tools | dispatched_tools))
        if not tools:
            raise InventoryError(f"no exposed tools found in {path.relative_to(repo_root)}")
        engines.append(
            Engine(
                source=path.relative_to(repo_root).as_posix(),
                server_name=next(iter(server_names)),
                tools=tools,
                has_feature_status="feature_status" in source,
            )
        )
    return sorted(engines, key=lambda engine: (engine.server_name, engine.source))


def _frontmatter_value(frontmatter: str, key: str) -> str | None:
    lines = frontmatter.splitlines()
    for index, line in enumerate(lines):
        match = re.fullmatch(rf"{re.escape(key)}:\s*(.*)", line)
        if match is None:
            continue
        raw = match.group(1).strip()
        if raw in {"|", ">"}:
            continuation: list[str] = []
            for following in lines[index + 1 :]:
                if following and not following[0].isspace():
                    break
                continuation.append(following.strip())
            separator = "\n" if raw == "|" else " "
            return separator.join(continuation).strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
            try:
                value = ast.literal_eval(raw)
            except (SyntaxError, ValueError):
                return raw[1:-1]
            return value if isinstance(value, str) else raw
        return raw
    return None


def discover_skills(repo_root: Path) -> list[Skill]:
    skills: list[Skill] = []
    for path in sorted((repo_root / ".claude/skills").glob("*/SKILL.md")):
        if path.parent.name == "_available":
            continue
        source = path.read_text(encoding="utf-8")
        if not source.startswith("---\n"):
            raise InventoryError(f"skill lacks frontmatter: {path.relative_to(repo_root)}")
        try:
            _, frontmatter, body = source.split("---", 2)
        except ValueError as error:
            raise InventoryError(
                f"skill has unterminated frontmatter: {path.relative_to(repo_root)}"
            ) from error
        name = _frontmatter_value(frontmatter, "name") or path.parent.name
        description = _frontmatter_value(frontmatter, "description")
        if description is None:
            raise InventoryError(
                f"skill lacks description frontmatter: {path.relative_to(repo_root)}"
            )
        skills.append(
            Skill(
                name=name,
                source=path.relative_to(repo_root).as_posix(),
                description=description,
                body=body,
            )
        )
    return sorted(skills, key=lambda skill: (skill.name, skill.source))


def _assignment_value(tree: ast.Module, name: str) -> ast.AST:
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        ):
            return statement.value
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == name
        ):
            return statement.value
    raise InventoryError(f"core/portable_contract.py lacks {name}")


def discover_ownership(repo_root: Path) -> tuple[list[OwnershipRule], dict[str, str]]:
    path = repo_root / "core/portable_contract.py"
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        raise InventoryError(f"cannot parse {path}: {error}") from error

    rules_node = _assignment_value(tree, "RULES")
    if not isinstance(rules_node, (ast.List, ast.Tuple)):
        raise InventoryError("portable contract RULES must be a literal list or tuple")
    rules: list[OwnershipRule] = []
    for node in rules_node.elts:
        if not isinstance(node, ast.Call) or _call_name(node) != "_r" or len(node.args) < 4:
            raise InventoryError("portable contract RULES contains a non-literal rule")
        values = [_string(argument) for argument in node.args[:4]]
        if any(value is None for value in values):
            raise InventoryError("portable contract RULES contains dynamic rule fields")
        rule_id, rule_path, kind, ownership = values
        rules.append(OwnershipRule(rule_id, rule_path, kind, ownership))  # type: ignore[arg-type]

    policy_node = _assignment_value(tree, "MUTATION_POLICY")
    if not isinstance(policy_node, ast.Dict):
        raise InventoryError("portable contract MUTATION_POLICY must be a literal dict")
    policy: dict[str, str] = {}
    for key_node, value_node in zip(policy_node.keys, policy_node.values, strict=True):
        key = _string(key_node) if key_node is not None else None
        value = _string(value_node)
        if key is None or value is None:
            raise InventoryError("portable contract MUTATION_POLICY must be string-to-string")
        policy[key] = value
    return sorted(rules, key=lambda rule: (rule.ownership, rule.path, rule.rule_id)), policy


def _markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def _references(body: str, tools: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(
        tool
        for tool in tools
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(tool)}(?![A-Za-z0-9_])", body)
    )


def render_inventory(repo_root: Path) -> str:
    engines = discover_engines(repo_root)
    skills = discover_skills(repo_root)
    rules, mutation_policy = discover_ownership(repo_root)

    skill_references: dict[str, list[tuple[str, tuple[str, ...]]]] = defaultdict(list)
    for engine in engines:
        for skill in skills:
            referenced_tools = _references(skill.body, engine.tools)
            if referenced_tools:
                skill_references[engine.server_name].append((skill.name, referenced_tools))

    lines = [
        "# Architecture Inventory",
        "",
        "This inventory is derived only from repository code and shipped skill files.",
        "",
        "## MCP engines",
        "",
        f"**Engine count:** {len(engines)}",
        "",
        "| Server | Source | Tool count | `feature_status` honesty contract | Exposed tools |",
        "| --- | --- | ---: | :---: | --- |",
    ]
    for engine in engines:
        lines.append(
            f"| `{engine.server_name}` | `{engine.source}` | {len(engine.tools)} | "
            f"{'yes' if engine.has_feature_status else 'no'} | "
            f"{', '.join(f'`{tool}`' for tool in engine.tools)} |"
        )

    lines.extend(
        [
            "",
            "## Skills",
            "",
            f"**Skill count:** {len(skills)}<br>",
            f"**Discoverability-risk count:** {sum(not skill.has_trigger for skill in skills)}",
            "",
            "A description has a trigger when its frontmatter contains the word "
            "`when` or `whenever` (case-insensitive). Length is measured in characters.",
            "",
            "| Skill | Source | Description | Length | Trigger status |",
            "| --- | --- | --- | ---: | --- |",
        ]
    )
    for skill in skills:
        status = "when" if skill.has_trigger else "**discoverability-risk**"
        lines.append(
            f"| `{_markdown(skill.name)}` | `{skill.source}` | "
            f"{_markdown(skill.description)} | {len(skill.description)} | {status} |"
        )

    lines.extend(
        [
            "",
            "## MCP-to-skill connectedness",
            "",
            "References are exact tool-name matches in skill bodies (frontmatter excluded). "
            "Under-surfaced means 0 referencing skills; over-surfaced means more than 10.",
            "",
            "| Server | Referencing skill count | Surface status | Skills (referenced tools) |",
            "| --- | ---: | --- | --- |",
        ]
    )
    for engine in engines:
        references = sorted(skill_references[engine.server_name])
        count = len(references)
        if count <= UNDER_SURFACED_MAX:
            status = "**under-surfaced**"
        elif count >= OVER_SURFACED_MIN:
            status = "**over-surfaced**"
        else:
            status = "normal"
        reference_text = "; ".join(
            f"`{skill}` ({', '.join(f'`{tool}`' for tool in tools)})"
            for skill, tools in references
        ) or "—"
        lines.append(
            f"| `{engine.server_name}` | {count} | {status} | {reference_text} |"
        )

    under = [
        engine for engine in engines if len(skill_references[engine.server_name]) == 0
    ]
    over = [
        engine
        for engine in engines
        if len(skill_references[engine.server_name]) >= OVER_SURFACED_MIN
    ]
    lines.extend(["", "### Under-surfaced servers", ""])
    lines.extend(
        [
            f"- `{engine.server_name}` — 0 skills reference its {len(engine.tools)} tools."
            for engine in under
        ]
        or ["None."]
    )
    lines.extend(["", "### Over-surfaced servers", ""])
    lines.extend(
        [
            f"- `{engine.server_name}` — "
            f"{len(skill_references[engine.server_name])} skills reference its tools."
            for engine in over
        ]
        or ["None."]
    )

    rules_by_class: dict[str, list[OwnershipRule]] = defaultdict(list)
    for rule in rules:
        rules_by_class[rule.ownership].append(rule)
    lines.extend(
        [
            "",
            "## Portable ownership classes",
            "",
            "Derived from `core/portable_contract.py` `RULES` and `MUTATION_POLICY`.",
            "",
            "| Class | Rule count | Update action |",
            "| --- | ---: | --- |",
        ]
    )
    for ownership in OWNERSHIP_ORDER:
        class_rules = rules_by_class[ownership]
        lines.append(
            f"| `{ownership}` | {len(class_rules)} | `{mutation_policy[ownership]}` |"
        )
    for ownership in OWNERSHIP_ORDER:
        lines.extend(
            [
                "",
                f"<details><summary><code>{ownership}</code> declared paths "
                f"({len(rules_by_class[ownership])})</summary>",
                "",
            ]
        )
        for rule in rules_by_class[ownership]:
            lines.append(f"- `{rule.path}` ({rule.kind}; `{rule.rule_id}`)")
        lines.extend(["", "</details>"])

    return "\n".join(lines) + "\n"


def generated_document(repo_root: Path) -> tuple[str, str]:
    body = render_inventory(repo_root)
    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return (
        (
            "<!-- GENERATED FILE — DO NOT EDIT BY HAND. -->\n"
            f"<!-- Generator: {GENERATOR_PATH} -->\n"
            f"<!-- Content SHA-256: {content_hash} -->\n\n"
            f"{body}"
        ),
        content_hash,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    document, digest = generated_document(REPO_ROOT)
    output.write_text(document, encoding="utf-8")
    print(f"Generated {output} ({digest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
