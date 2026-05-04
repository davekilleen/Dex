import json
import re
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CODEX_SKILLS_DIR = REPO_ROOT / ".agents" / "skills"
SKILL_FRONTMATTER_CONTRACT_PATH = REPO_ROOT / "core" / "tests" / "fixtures" / "codex_skill_frontmatter_contract.json"
EXPECTED_FIRST_PARTY_CODEX_SKILLS = (
    "ai-setup",
    "ai-status",
    "atlassian-setup",
    "beta-activate",
    "beta-status",
    "calendar-setup",
    "career-coach",
    "career-setup",
    "commitment-scan",
    "create-mcp",
    "create-skill",
    "daily-plan",
    "daily-review",
    "dex-add-mcp",
    "dex-backlog",
    "dex-demo",
    "dex-improve",
    "dex-level-up",
    "dex-obsidian-setup",
    "dex-rollback",
    "dex-update",
    "dex-whats-new",
    "enable-semantic-search",
    "getting-started",
    "google-workspace-setup",
    "health-check",
    "identity-snapshot",
    "industry-truths",
    "integrate-mcp",
    "journal",
    "meeting-prep",
    "ms-teams-setup",
    "onboarding",
    "process-meetings",
    "product-brief",
    "project-health",
    "prompt-improver",
    "quarter-plan",
    "quarter-review",
    "reset",
    "resume-builder",
    "review",
    "save-insight",
    "scrape",
    "screenpipe-setup",
    "setup",
    "things-setup",
    "todoist-setup",
    "trello-setup",
    "triage",
    "week-plan",
    "week-review",
    "xray",
    "zoom-setup",
)


def _iter_first_party_codex_skill_names() -> list[str]:
    return sorted(
        skill_dir.name
        for skill_dir in CODEX_SKILLS_DIR.iterdir()
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file()
    )


def _active_surface_paths() -> list[Path]:
    paths = [
        REPO_ROOT / "AGENTS.md",
        REPO_ROOT / "README.md",
        REPO_ROOT / "install.sh",
        REPO_ROOT / ".codex" / "config.toml",
        REPO_ROOT / ".codex" / "hooks.json",
        REPO_ROOT / ".codex-plugin" / "plugin.json",
        REPO_ROOT / "System" / "Dex_Backlog.md",
        REPO_ROOT / "System" / "pillars.yaml",
        REPO_ROOT / "System" / "pillars.example.yaml",
        REPO_ROOT / "System" / "scripts" / "test-ai-connections.sh",
        REPO_ROOT / "core" / "mcp" / "CAREER_MCP_README.md",
    ]
    paths.extend((REPO_ROOT / ".agents" / "skills").rglob("SKILL.md"))
    paths.extend((REPO_ROOT / ".codex" / "hooks").glob("*"))
    paths.extend((REPO_ROOT / "core" / "integrations").rglob("*.py"))
    paths.extend((REPO_ROOT / "core" / "mcp").glob("*.py"))
    paths.extend((REPO_ROOT / "core" / "scripts").rglob("*.cjs"))
    paths.extend((REPO_ROOT / "core" / "utils").glob("preflight.py"))
    return [path for path in paths if path.is_file()]


def _load_mcp_template_servers() -> dict:
    template_path = REPO_ROOT / ".mcp.json.example"
    template = json.loads(template_path.read_text(encoding="utf-8"))
    return template["mcpServers"]


def _load_codex_runtime_servers() -> dict:
    import tomllib

    config_path = REPO_ROOT / ".codex" / "config.toml"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    return config["mcp_servers"]


def _assert_safe_mcp_server_filename(server_name: str, server_filename: str) -> None:
    server_path = Path(server_filename)
    assert not server_path.is_absolute(), f"{server_name} uses an absolute MCP server path: {server_filename}"
    assert ".." not in server_path.parts, f"{server_name} uses a parent-directory MCP server path: {server_filename}"
    assert len(server_path.parts) == 1, f"{server_name} must reference a bare MCP server filename: {server_filename}"
    assert (REPO_ROOT / "core" / "mcp" / server_filename).is_file(), (
        f"{server_name} references missing MCP server: core/mcp/{server_filename}"
    )


def _normalize_template_mcp_env(env: dict[str, str]) -> dict[str, str]:
    normalized = dict(env)
    if normalized.get("VAULT_PATH") == "{{VAULT_PATH}}":
        normalized["VAULT_PATH"] = "."
    return normalized


def _load_codex_hooks_config() -> dict:
    hooks_path = REPO_ROOT / ".codex" / "hooks.json"
    return json.loads(hooks_path.read_text(encoding="utf-8"))


def _load_skill_frontmatter(skill_path: Path) -> dict:
    text = skill_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("missing opening frontmatter delimiter")

    try:
        _, frontmatter, _ = text.split("---\n", 2)
    except ValueError as error:
        raise ValueError("missing closing frontmatter delimiter") from error

    parsed_frontmatter = yaml.safe_load(frontmatter)
    if not isinstance(parsed_frontmatter, dict):
        raise ValueError("frontmatter must parse to a mapping")

    return parsed_frontmatter


def _extract_repo_local_hook_target(command: str) -> tuple[str, Path]:
    match = re.fullmatch(r'(node|bash) "\$\(git rev-parse --show-toplevel\)/\.codex/hooks/([^"]+)"', command)
    assert match is not None, f"Hook command must target repo-local .codex/hooks via git root: {command}"

    runner, relative_target = match.groups()
    target_path = Path(relative_target)
    assert not target_path.is_absolute(), f"Hook target must stay relative: {relative_target}"
    assert ".." not in target_path.parts, f"Hook target must not escape .codex/hooks: {relative_target}"
    return runner, REPO_ROOT / ".codex" / "hooks" / target_path


def test_first_party_codex_skill_inventory_matches_expected():
    assert _iter_first_party_codex_skill_names() == list(EXPECTED_FIRST_PARTY_CODEX_SKILLS)


def test_legacy_claude_skill_and_hook_trees_are_deleted():
    assert not (REPO_ROOT / "CLAUDE.md").exists()
    assert not (REPO_ROOT / ".claude").exists()
    assert not (REPO_ROOT / ".claude-plugin").exists()


def test_active_codex_surfaces_do_not_point_at_removed_legacy_runtime_features():
    disallowed = (
        ".Codex/",
        "CLAUDE.md",
        ".claude/",
        ".claude-plugin/",
        "AskUserQuestion",
        "AskQuestion",
        "claude_desktop_config.json",
        "CLAUDE_PROJECT_DIR",
        "System/.mcp.json",
        "claude plugin ",
        "claude-code-state.json",
    )

    offenders: list[str] = []
    for path in _active_surface_paths():
        text = path.read_text(encoding="utf-8")
        for token in disallowed:
            if token in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)} -> {token}")

    assert not offenders, "Found disallowed legacy runtime references:\n" + "\n".join(offenders)


def test_codex_plugin_manifest_is_skills_only():
    manifest_path = REPO_ROOT / ".codex-plugin" / "plugin.json"

    manifest_text = manifest_path.read_text(encoding="utf-8")

    assert '"skills": "./.agents/skills/"' in manifest_text
    assert '"hooks"' not in manifest_text
    assert '"mcpServers"' not in manifest_text


def test_mcp_template_and_repo_local_runtime_stay_in_lockstep():
    template_servers = _load_mcp_template_servers()
    runtime_servers = _load_codex_runtime_servers()

    assert set(template_servers) == set(runtime_servers), "Template and .codex/config.toml server inventories diverged"

    for server_name, template_config in template_servers.items():
        runtime_config = runtime_servers[server_name]

        template_args = template_config["args"]
        runtime_args = runtime_config["args"]
        assert len(template_args) == 2, f"{server_name} template args must stay launcher + filename only"
        assert len(runtime_args) == 2, f"{server_name} runtime args must stay launcher + filename only"

        assert template_config["command"] == "node", f"{server_name} template command drifted"
        assert runtime_config["command"] == "node", f"{server_name} runtime command drifted"
        assert template_args[0] == "{{VAULT_PATH}}/core/scripts/run-dex-mcp.cjs", (
            f"{server_name} template launcher path drifted: {template_args[0]}"
        )
        assert runtime_args[0] == "./core/scripts/run-dex-mcp.cjs", (
            f"{server_name} runtime launcher path drifted: {runtime_args[0]}"
        )
        assert (REPO_ROOT / "core" / "scripts" / "run-dex-mcp.cjs").is_file()

        template_env = template_config.get("env") or {}
        runtime_env = runtime_config.get("env") or {}
        assert runtime_env == _normalize_template_mcp_env(template_env), (
            f"{server_name} runtime env drifted from template: {runtime_env} != {_normalize_template_mcp_env(template_env)}"
        )
        assert runtime_config["cwd"] == ".", f"{server_name} runtime cwd drifted"

        assert runtime_args[1] == template_args[1], f"{server_name} runtime/server filename drifted from template"
        _assert_safe_mcp_server_filename(server_name, template_args[1])


def test_codex_hooks_json_points_at_existing_repo_local_scripts():
    hooks_config = _load_codex_hooks_config()

    for event_name, matcher_blocks in hooks_config["hooks"].items():
        for matcher_block in matcher_blocks:
            for hook in matcher_block.get("hooks", []):
                assert hook.get("type") == "command", f"{event_name} hook must stay command-based"
                runner, target_path = _extract_repo_local_hook_target(hook["command"])
                assert target_path.is_file(), f"{event_name} hook references missing script: {target_path}"
                if runner == "node":
                    assert target_path.suffix == ".cjs", f"{event_name} node hook must target a .cjs script: {target_path}"
                if runner == "bash":
                    assert target_path.suffix == ".sh", f"{event_name} bash hook must target a .sh script: {target_path}"


def test_execplan_convention_doc_exists():
    assert (REPO_ROOT / "docs" / "PLANS.md").is_file()


def test_codex_skill_frontmatter_contract_is_preserved():
    contract = json.loads(SKILL_FRONTMATTER_CONTRACT_PATH.read_text(encoding="utf-8"))

    for relative_skill_path, expected_metadata in contract.items():
        actual_frontmatter = _load_skill_frontmatter(CODEX_SKILLS_DIR / relative_skill_path)
        actual_metadata = {key: actual_frontmatter.get(key) for key in expected_metadata}
        assert actual_metadata == expected_metadata, (
            f"{relative_skill_path} metadata drifted from the restored contract: "
            f"{actual_metadata} != {expected_metadata}"
        )


def test_wrapper_migration_is_complete():
    wrapper_marker = "This is the authoritative Codex entrypoint for the legacy Dex workflow documented in `.claude/skills/"

    offenders = [
        path.relative_to(REPO_ROOT)
        for path in CODEX_SKILLS_DIR.glob("*/SKILL.md")
        if wrapper_marker in path.read_text(encoding="utf-8")
    ]

    assert not offenders, f"Wrapper-based skill migrations still remain: {offenders}"


def test_all_codex_skill_files_have_valid_top_level_frontmatter():
    offenders: list[str] = []

    for skill_path in CODEX_SKILLS_DIR.rglob("SKILL.md"):
        try:
            parsed_frontmatter = _load_skill_frontmatter(skill_path)
        except (ValueError, yaml.YAMLError) as error:
            offenders.append(f"{skill_path.relative_to(REPO_ROOT)} -> {error}")
            continue

        if parsed_frontmatter.get("name") != skill_path.parent.name:
            offenders.append(f"{skill_path.relative_to(REPO_ROOT)} -> frontmatter name does not match folder")
        if not parsed_frontmatter.get("description"):
            offenders.append(f"{skill_path.relative_to(REPO_ROOT)} -> missing frontmatter description")

    assert not offenders, "Invalid Codex skill frontmatter:\n" + "\n".join(offenders)
