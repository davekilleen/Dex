"""The portable-vault ownership contract: who owns every path in a Dex install.

This module is the SOURCE OF TRUTH for the ownership contract ratified in
Vault_Contract v1 (2026-06-18) — the shared spine consumed by the Brain/Vault
split (migrator), the upgrade engine (snapshot/apply/verify/rollback), and the
capability rooms. The committed JSON view in
``packages/dex-contracts/dist/portable-vault.contract.json`` is generated from
here by ``scripts/generate-portable-contract.py`` and must never be hand-edited.

Five ownership classes:

- ``brain``      release-owned; an update replaces it wholesale.
- ``vault``      the user's content; an update NEVER writes it.
- ``seed``       shipped once, then user-owned; written only if absent.
- ``generated``  machine-derived; regenerated, neither user- nor release-precious.
- ``runtime``    local machine state; never shipped, never updated.

Resolution semantics (``resolve``): the hard-deny patterns are checked first
and veto everything; then the most specific rule wins (exact file match beats
directory prefix; longer prefix beats shorter). Every tracked repo path MUST
resolve — ``scripts/check-portable-contract.sh`` fails CI otherwise — so adding
a new top-level path to the repo requires a deliberate classification here.

Design notes live in ``docs/portable-vault-contract-design.md``.
"""

from __future__ import annotations

import fnmatch
import posixpath
from dataclasses import dataclass
from typing import Iterable

CONTRACT_VERSION = 1
VAULT_SCHEMA_SUPPORTED = ">=1 <2"

OWNERSHIP_CLASSES = ("brain", "vault", "seed", "generated", "runtime")

# ---------------------------------------------------------------------------
# Hard-deny: no engine write-plan may EVER target these, regardless of class.
# From Vault_Contract §3 (secrets row) + the v1-to-v2 migrator's deny set.
# Patterns are fnmatch-style, matched against the full vault-relative path and
# against every basename segment (so "*.pem" denies a .pem anywhere).
# ---------------------------------------------------------------------------
HARD_DENY_PATTERNS = (
    ".env",
    ".env.*",
    ".git",
    ".git/*",
    "System/credentials",
    "System/credentials/*",
    "*token.json",
    "*.key",
    "*.pem",
)

# ---------------------------------------------------------------------------
# Vault regions: directories that belong to the USER in an installed vault.
# An update engine must never write inside them except to place the explicit
# `seed` files below (and only when absent). Tracked repo files under these
# regions are shipped starters, classified individually.
# ---------------------------------------------------------------------------
VAULT_REGIONS = (
    "00-Inbox",
    "01-Quarter_Goals",
    "02-Week_Priorities",
    "03-Tasks",
    "04-Projects",
    "05-Areas",
    "06-Resources",
    "07-Archives",
)


@dataclass(frozen=True)
class Rule:
    """One ownership rule. ``path`` is vault-relative, POSIX separators.

    ``kind`` is ``"file"`` (exact match) or ``"dir"`` (the path itself and
    everything under it). ``note`` documents WHY, for humans and reviews.
    """

    rule_id: str
    path: str
    kind: str  # "file" | "dir"
    ownership: str
    note: str = ""


def _r(rule_id: str, path: str, kind: str, ownership: str, note: str = "") -> Rule:
    if ownership not in OWNERSHIP_CLASSES:
        raise ValueError(f"unknown ownership class: {ownership}")
    if kind not in ("file", "dir"):
        raise ValueError(f"unknown rule kind: {kind}")
    return Rule(rule_id, path.rstrip("/"), kind, ownership, note)


# ---------------------------------------------------------------------------
# The ruleset. Order does not matter for resolution (specificity wins), but
# keep it grouped and readable: brain, seed, generated, runtime, vault.
# ---------------------------------------------------------------------------
RULES: tuple[Rule, ...] = (
    # --- brain: engine + shipped surface, replaced wholesale on update -----
    _r("brain-core", "core", "dir", "brain"),
    _r("brain-scripts", "scripts", "dir", "brain"),
    _r("brain-dot-scripts", ".scripts", "dir", "brain"),
    _r("brain-packages", "packages", "dir", "brain",
       "package sources are brain; the committed dist/ views are generated (below)"),
    _r("brain-claude", ".claude", "dir", "brain",
       "shipped skills/hooks/flows; user skills belong in .claude/skills-custom/ (vault)"),
    _r("brain-agents", ".agents", "dir", "brain"),
    _r("brain-cursor", ".cursor", "dir", "brain"),
    _r("brain-obsidian", ".obsidian", "dir", "brain",
       "shipped Obsidian defaults; a user's live workspace state is untracked"),
    _r("brain-github", ".github", "dir", "brain"),
    _r("brain-docs", "docs", "dir", "brain"),
    _r("brain-docs-legacy", "06-Resources/Dex_System", "dir", "brain",
       "system docs shipped inside a vault region; relocate to docs/ per "
       "Vault_Contract §10.1 — until then updates may replace them"),
    _r("brain-staging", "staging", "dir", "brain",
       "dev-only staging scaffolding; excluded from releases"),
    _r("brain-claude-md", "CLAUDE.md", "file", "brain",
       "pure brain per Vault_Contract §5; user instructions live in CLAUDE-custom.md"),
    _r("brain-agents-md", "AGENTS.md", "file", "brain"),
    _r("brain-readme", "README.md", "file", "brain"),
    _r("brain-changelog", "CHANGELOG.md", "file", "brain"),
    _r("brain-contributing", "CONTRIBUTING.md", "file", "brain"),
    _r("brain-license", "LICENSE", "file", "brain"),
    _r("brain-commercial-license", "COMMERCIAL_LICENSE.md", "file", "brain"),
    _r("brain-distribution-ready", "DISTRIBUTION_READY.md", "file", "brain"),
    _r("brain-install", "install.sh", "file", "brain"),
    _r("brain-package-json", "package.json", "file", "brain"),
    _r("brain-package-lock", "package-lock.json", "file", "brain"),
    _r("brain-pyproject", "pyproject.toml", "file", "brain"),
    _r("brain-requirements", "requirements.txt", "file", "brain"),
    _r("brain-requirements-dev", "requirements-dev.txt", "file", "brain"),
    _r("brain-uv-lock", "uv.lock", "file", "brain"),
    _r("brain-gitignore", ".gitignore", "file", "brain"),
    _r("brain-gitattributes", ".gitattributes", "file", "brain"),
    _r("brain-distignore", ".distignore", "file", "brain"),
    _r("brain-beta-communications", "System/Beta_Communications", "dir", "brain",
       "release-doc per the SR1 tracked-ignore baseline; candidate for deletion "
       "in the baseline-reduction follow-up"),
    _r("brain-system-readme", "System/README.md", "file", "brain"),

    # --- seed: shipped once, then the user's; update writes only if absent -
    _r("seed-templates", "System/Templates", "dir", "seed"),
    _r("seed-user-profile-live", "System/user-profile.yaml", "file", "seed",
       "shipped blank; user VALUES live here (Vault_Contract §2c) — never overwritten"),
    _r("seed-user-profile-template", "System/user-profile-template.yaml", "file", "seed",
       "canonical shipped template (the ratified doc names user-profile.example.yaml; "
       "the repo consolidated on -template — deliberate deviation)"),
    _r("seed-user-profile-example", "System/user-profile.example.yaml", "file", "seed",
       "legacy duplicate template; removal in flight (portability hygiene PR)"),
    _r("seed-pillars-live", "System/pillars.yaml", "file", "seed",
       "shipped empty; user pillar registry — never overwritten"),
    _r("seed-pillars-example", "System/pillars.example.yaml", "file", "seed"),
    _r("seed-trusted-mcps-example", "System/trusted-mcps.example.yaml", "file", "seed"),
    _r("seed-mcp-example", "System/.mcp.json.example", "file", "seed"),
    _r("seed-env-example", "env.example", "file", "seed"),
    _r("seed-integrations", "System/integrations", "dir", "seed",
       "SR1 #150: tracked reference-schema templates carrying env-var references; "
       "installed if absent, never overwritten once user-owned"),
    _r("seed-dex-backlog", "System/Dex_Backlog.md", "file", "seed"),
    _r("seed-dex-ideas", "System/Dex_Ideas.md", "file", "seed",
       "legacy duplicate of Dex_Backlog.md; removal in flight (portability hygiene PR)"),
    # PARA starters: the EXACT shipped scaffolding files, enumerated one by one.
    # The regions themselves are vault (below); an update may seed precisely
    # these paths when absent and nothing else. Adding a tracked file under a
    # vault region without listing it here turns the CI gate red on purpose.
    _r("seed-inbox-readme", "00-Inbox/README.md", "file", "seed"),
    _r("seed-inbox-daily-plans-readme", "00-Inbox/Daily_Plans/README.md", "file", "seed"),
    _r("seed-inbox-ideas-readme", "00-Inbox/Ideas/README.md", "file", "seed"),
    _r("seed-inbox-meetings-readme", "00-Inbox/Meetings/README.md", "file", "seed"),
    _r("seed-quarter-goals-file", "01-Quarter_Goals/Quarter_Goals.md", "file", "seed",
       "capability-gated room (quarter_goals)"),
    _r("seed-week-priorities-file", "02-Week_Priorities/Week_Priorities.md", "file",
       "seed"),
    _r("seed-tasks-file", "03-Tasks/Tasks.md", "file", "seed"),
    _r("seed-projects-readme", "04-Projects/README.md", "file", "seed"),
    _r("seed-areas-readme", "05-Areas/README.md", "file", "seed"),
    _r("seed-career-evidence-readme", "05-Areas/Career/Evidence/README.md", "file",
       "seed", "capability-gated room (career)"),
    _r("seed-companies-readme", "05-Areas/Companies/README.md", "file", "seed",
       "capability-gated room (companies)"),
    _r("seed-people-readme", "05-Areas/People/README.md", "file", "seed"),
    _r("seed-people-internal-readme", "05-Areas/People/Internal/README.md", "file",
       "seed"),
    _r("seed-people-external-readme", "05-Areas/People/External/README.md", "file",
       "seed"),
    _r("seed-resources-readme", "06-Resources/README.md", "file", "seed"),
    _r("seed-intel-gitkeep", "06-Resources/Intel/.gitkeep", "file", "seed"),
    _r("seed-meeting-intel-gitkeep", "06-Resources/Intel/Meeting_Intel/.gitkeep",
       "file", "seed"),
    _r("seed-learnings-readme", "06-Resources/Learnings/README.md", "file", "seed"),
    _r("seed-mistake-patterns", "06-Resources/Learnings/Mistake_Patterns.md", "file",
       "seed"),
    _r("seed-working-preferences", "06-Resources/Learnings/Working_Preferences.md",
       "file", "seed"),
    _r("seed-quarterly-reviews-readme", "06-Resources/Quarterly_Reviews/README.md",
       "file", "seed"),
    _r("seed-archives-readme", "07-Archives/README.md", "file", "seed"),
    _r("seed-archives-plans-readme", "07-Archives/Plans/README.md", "file", "seed"),
    _r("seed-archives-projects-readme", "07-Archives/Projects/README.md", "file",
       "seed"),
    _r("seed-archives-reviews-readme", "07-Archives/Reviews/README.md", "file", "seed"),

    # --- generated: machine-derived, regenerated ---------------------------
    _r("generated-contracts-dist", "packages/dex-contracts/dist", "dir", "generated",
       "committed for cross-repo consumption; regenerated by scripts/generate-*.py; "
       "drift is CI-gated"),
    _r("generated-manifest", "System/.installed-files.manifest", "file", "generated"),
    _r("generated-evidence-profile", "System/.release-evidence-profile.json", "file",
       "generated"),
    _r("generated-local-only-transition", "System/.local-only-preservation-transition.json",
       "file", "generated",
       "SR1 #148 phase marker; owned by the local-only preservation machinery"),

    # --- runtime: local machine state ---------------------------------------
    _r("runtime-session-learnings", "System/Session_Learnings", "dir", "runtime",
       "user-machine session state; three legacy files remain tracked under the "
       "SR1 27-row tracked-ignore baseline pending the baseline-reduction follow-up"),
    _r("runtime-session-memory", "System/Session_Memory", "dir", "runtime"),
    _r("runtime-usage-log", "System/usage_log.md", "file", "runtime",
       "shipped blank starter, then per-machine usage state; legacy-tracked"),
    _r("runtime-claude-state", "System/claude-code-state.json", "file", "runtime",
       "legacy-tracked runtime state"),
    _r("runtime-last-learning-check", "System/.last-learning-check", "file", "runtime",
       "legacy-tracked runtime marker"),
    _r("runtime-dex-dir", "System/.dex", "dir", "runtime"),
    _r("runtime-onboarding", "System/.onboarding", "dir", "runtime"),
    _r("runtime-onboarding-marker", "System/.onboarding-complete", "file", "runtime"),
    _r("runtime-logs", ".logs", "dir", "runtime"),

    # --- vault: the user's content and values (mostly untracked in-repo) ----
    # The PARA regions: user-owned. Updates never write inside them except to
    # place the exact seed files enumerated above, and only when absent.
    _r("vault-inbox", "00-Inbox", "dir", "vault"),
    _r("vault-quarter-goals", "01-Quarter_Goals", "dir", "vault",
       "capability-gated room (quarter_goals); absence is a valid state"),
    _r("vault-week-priorities", "02-Week_Priorities", "dir", "vault"),
    _r("vault-tasks", "03-Tasks", "dir", "vault"),
    _r("vault-projects", "04-Projects", "dir", "vault"),
    _r("vault-areas", "05-Areas", "dir", "vault",
       "Career and Companies subtrees are capability-gated rooms; absence is a "
       "valid state"),
    _r("vault-resources", "06-Resources", "dir", "vault",
       "fully user-owned per Vault_Contract §10.1; the brain docs still shipped "
       "under 06-Resources/Dex_System carry their own brain rule until they "
       "relocate to docs/"),
    _r("vault-archives", "07-Archives", "dir", "vault"),
    # Secrets: hard-denied for writes AND vault-owned (deny is orthogonal to
    # ownership — these rules give denied paths their owner).
    _r("vault-env", ".env", "file", "vault", "raw secret authority (SR1 #150 model)"),
    _r("vault-credentials", "System/credentials", "dir", "vault", "secrets; hard-denied"),
    _r("vault-mcp-json", ".mcp.json", "file", "vault",
       "REPORT-ONLY: SR1 #150's structural residual detector owns it; no engine "
       "may rewrite it"),
    _r("vault-claude-custom", "CLAUDE-custom.md", "file", "vault",
       "the one canonical home for user instructions (Vault_Contract §5)"),
    _r("vault-skills-custom", ".claude/skills-custom", "dir", "vault"),
    _r("vault-mcp-custom", "core/mcp-custom", "dir", "vault"),
    _r("vault-mcp-premium", "core/mcp-premium", "dir", "vault"),
    _r("vault-folder-paths", "System/folder-paths.yaml", "file", "vault",
       "the user's folder remapping (Vault_Contract §2a); vault-owned, travels "
       "with content"),
    _r("vault-trusted-mcps", "System/trusted-mcps.yaml", "file", "vault"),
)

# ---------------------------------------------------------------------------
# Capability rooms (Decision C, Option 2). The meetings/people/tasks spine is
# NOT a capability — it is always on and has no registry entry by design.
# State lives in System/user-profile.yaml -> capabilities.<id>.enabled
# (vault-owned values). An ABSENT room is a VALID vault state: convergence and
# repair must never recreate a room the user did not select.
# ---------------------------------------------------------------------------
CAPABILITIES: dict[str, dict[str, object]] = {
    "career": {
        "folders": ("05-Areas/Career",),
        "skills": ("career-setup", "career-coach", "resume-builder"),
        "mcp": ("career_server", "resume_server"),
        "default_enabled": False,
    },
    "companies": {
        "folders": ("05-Areas/Companies",),
        "skills": (),
        "features": ("entity-engine.company-pages",),
        "default_enabled": False,
    },
    "quarter_goals": {
        "folders": ("01-Quarter_Goals",),
        "skills": ("quarter-plan", "quarter-review"),
        "config": "quarterly_planning",
        "default_enabled": False,
    },
}


@dataclass(frozen=True)
class Resolution:
    """The contract's answer for one path."""

    path: str
    ownership: str
    rule_id: str
    denied: bool


class ContractViolation(ValueError):
    """Raised when a path cannot be resolved by the contract."""


def _normalize(path: str) -> str:
    candidate = posixpath.normpath(str(path).strip().replace("\\", "/")).lstrip("/")
    if candidate in ("", "."):
        raise ContractViolation("empty path cannot be classified")
    if candidate.startswith(".."):
        raise ContractViolation(f"path escapes the vault root: {path}")
    return candidate


def is_denied(path: str) -> bool:
    """True when the hard-deny list vetoes any write to ``path``."""
    candidate = _normalize(path)
    segments = candidate.split("/")
    for pattern in HARD_DENY_PATTERNS:
        if fnmatch.fnmatch(candidate, pattern):
            return True
        if "/" not in pattern and any(
            fnmatch.fnmatch(segment, pattern) for segment in segments
        ):
            return True
    return False


def resolve(path: str) -> Resolution:
    """Resolve ``path`` to its ownership class.

    Hard-denied paths still resolve to a class (deny is orthogonal — a denied
    path also has an owner), with ``denied=True``. Unclassifiable paths raise
    :class:`ContractViolation` — the completeness gate depends on that.
    """
    candidate = _normalize(path)
    denied = is_denied(candidate)

    best: Rule | None = None
    best_specificity = -1
    for rule in RULES:
        if rule.kind == "file":
            if candidate == rule.path:
                # Exact file match always wins outright.
                return Resolution(candidate, rule.ownership, rule.rule_id, denied)
        else:
            if candidate == rule.path or candidate.startswith(rule.path + "/"):
                specificity = rule.path.count("/") + 1
                if specificity > best_specificity:
                    best = rule
                    best_specificity = specificity
    if best is None:
        if denied:
            # Hard-denied paths without a dedicated rule (e.g. .env.local,
            # *.pem anywhere) are definitionally the user's secrets.
            return Resolution(candidate, "vault", "hard-deny-default", True)
        raise ContractViolation(f"no ownership rule classifies: {candidate}")
    return Resolution(candidate, best.ownership, best.rule_id, denied)


def unclassified(paths: Iterable[str]) -> list[str]:
    """Return the subset of ``paths`` the contract cannot classify."""
    missing: list[str] = []
    for path in paths:
        try:
            resolve(path)
        except ContractViolation:
            missing.append(str(path))
    return missing


def release_forbidden(paths: Iterable[str]) -> list[str]:
    """Paths that must never appear in a release write-plan.

    A release ships ``brain``/``seed``/``generated`` artifacts. ``vault`` and
    ``runtime`` content — and anything hard-denied — must never be written by
    a release. (Legacy-tracked runtime files are reported too: they are the
    debt the baseline-reduction follow-up retires, and listing them keeps the
    debt visible rather than grandfathered.)
    """
    forbidden: list[str] = []
    for path in paths:
        resolution = resolve(path)
        if resolution.denied or resolution.ownership == "vault":
            forbidden.append(resolution.path)
    return forbidden


def build_contract_document() -> dict[str, object]:
    """The deterministic JSON view committed to packages/dex-contracts/dist."""
    return {
        "contract_version": CONTRACT_VERSION,
        "source": "core/portable_contract.py",
        "vault_schema_supported": VAULT_SCHEMA_SUPPORTED,
        "ownership_classes": list(OWNERSHIP_CLASSES),
        "hard_deny": list(HARD_DENY_PATTERNS),
        "vault_regions": list(VAULT_REGIONS),
        "rules": [
            {
                "id": rule.rule_id,
                "path": rule.path,
                "kind": rule.kind,
                "ownership": rule.ownership,
                **({"note": rule.note} if rule.note else {}),
            }
            for rule in sorted(RULES, key=lambda rule: (rule.path, rule.rule_id))
        ],
        "capabilities": {
            name: {
                key: (list(value) if isinstance(value, tuple) else value)
                for key, value in sorted(spec.items())
            }
            for name, spec in sorted(CAPABILITIES.items())
        },
    }
