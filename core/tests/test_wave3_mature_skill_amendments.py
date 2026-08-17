"""Targeted evidence, authority, and recovery checks for mature Wave 3 skills.

These skills already contain substantial role methods. The Wave 3 bar therefore
checks their known truth and safety gaps rather than rewarding a mechanical rewrite
or a file-size threshold. Like the deeper role contract, this is supporting evidence.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

MATURE_SKILLS = {
    "account-plan": ".claude/skills/_available/sales/account-plan/SKILL.md",
    "call-prep": ".claude/skills/_available/sales/call-prep/SKILL.md",
    "deal-review": ".claude/skills/_available/sales/deal-review/SKILL.md",
    "pipeline-health": ".claude/skills/_available/sales/pipeline-health/SKILL.md",
    "pipeline-sync": ".claude/skills/pipeline-sync/SKILL.md",
    "customer-intel": ".claude/skills/_available/product/customer-intel/SKILL.md",
    "feature-decision": ".claude/skills/_available/product/feature-decision/SKILL.md",
    "roadmap": ".claude/skills/_available/product/roadmap/SKILL.md",
    "career-setup": ".claude/skills/_available/capabilities/career/skills/career-setup/SKILL.md",
    "career-coach": ".claude/skills/_available/capabilities/career/skills/career-coach/SKILL.md",
    "resume-builder": ".claude/skills/_available/capabilities/career/skills/resume-builder/SKILL.md",
    "quarter-plan": ".claude/skills/_available/capabilities/quarter_goals/skills/quarter-plan/SKILL.md",
    "quarter-review": ".claude/skills/_available/capabilities/quarter_goals/skills/quarter-review/SKILL.md",
}

AMENDMENT_HEADING = "## Evidence, authority, and recovery"

ROLE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "account-plan": (
        r"per-field provenance|field provenance",
        r"unknown.*do not infer|do not infer.*unknown",
        r"write preview|preview the exact",
        r"read back.*saved plan|saved plan.*read back",
    ),
    "call-prep": (
        r"freshness.*as-of|as-of.*freshness",
        r"unknown objective.*unknown objection|unknown objection.*unknown objective",
        r"invented intent|do not infer intent",
        r"read-only",
    ),
    "deal-review": (
        r"canonical activity date",
        r"unchecked deal",
        r"unknown value.*exclude|exclude.*unknown value",
        r"denominator.*coverage|coverage.*denominator",
    ),
    "pipeline-health": (
        r"configured.*confirmed.*stage|confirmed.*configured.*stage",
        r"missing.*zero|zero.*missing",
        r"benchmark.*source|source.*benchmark",
        r"denominator.*arithmetic|arithmetic.*denominator",
    ),
    "pipeline-sync": (
        r"companion.*prerequisite|prerequisite.*companion",
        r"partial read|incomplete read",
        r"idempot.*retry|retry.*idempot",
        r"read back.*reconcil|reconcil.*read back",
    ),
    "customer-intel": (
        r"source id.*source date|source date.*source id",
        r"deduplicat",
        r"quote fidelity|exact quote",
        r"insufficient evidence",
    ),
    "feature-decision": (
        r"recommendation.*decision authority|decision authority.*recommendation",
        r"unknown effort.*unknown evidence|unknown evidence.*unknown effort",
        r"preview.*confirm|confirm.*preview",
        r"preserve.*earlier decision|earlier decision.*preserve",
    ),
    "roadmap": (
        r"canonical status.*status date|status date.*canonical status",
        r"unknown.*blocked|blocked.*unknown",
        r"denominator",
        r"source.*evidence|evidence.*source",
        r"one row per observed canonical status|every observed canonical status.*row",
    ),
    "career-setup": (
        r"05-areas/career/evidence",
        r"consent.*sensitive|sensitive.*consent",
        r"hook failure|capture failure",
        r"room.*mcp.*verif|mcp.*room.*verif",
    ),
    "career-coach": (
        r"missing evidence.*missing competency|missing competency.*missing evidence",
        r"confidence.*source|source.*confidence",
        r"hr.*manager.*limit|manager.*hr.*limit",
        r"save preview.*confirm|confirm.*save preview",
    ),
    "resume-builder": (
        r"invented metric|do not invent metrics",
        r"supplied estimate|estimate label",
        r"render.*pagination|pagination.*render",
        r"cross-file.*confirm|confirm.*cross-file",
    ),
    "quarter-plan": (
        r"fiscal.*quarter boundar|quarter boundar.*fiscal",
        r"preview every.*mutation|mutation.*preview every",
        r"preserve.*conflict.*bytes|conflict.*preserve.*bytes",
        r"read back",
    ),
    "quarter-review": (
        r"source every statistic|statistic source",
        r"unknown",
        r"separate.*consent.*mutation|consent.*separate.*mutation",
        r"idempotent.*completion percentage|completion percentage.*idempotent",
    ),
}

UNSUPPORTED_ASSUMPTIONS: dict[str, tuple[str, ...]] = {
    "call-prep": (
        r"pays for itself in 3 months",
        r"2-week rollout",
        r"3 other customers have requested",
    ),
    "deal-review": (
        r"fresh:\*{0,2}\s*updated within last 5 days",
        r"aging:\*{0,2}\s*6-10 days without update",
        r"stale:\*{0,2}\s*11\+ days without update",
    ),
    "pipeline-health": (
        r"3x\+? coverage\s*=\s*healthy",
        r"2-3x coverage\s*=\s*adequate",
        r"contract stage deals\s*\(90% probability\)",
        r"negotiation \+ contract\s*\(75%\+ probability\)",
        r"flag deals exceeding average by 50%\+",
        r"pipeline < 3x target",
    ),
    "roadmap": (
        r"flag if > 14 days old",
        r"\*\*health score:\*\*",
    ),
    "career-setup": (
        r"hook may append",
        r"may append a candidate",
    ),
    "career-coach": (
        r"early career\s*-\s*0-3 years",
        r"mid-level\s*-\s*3-7 years",
        r"senior\s*\(7\+ years",
        r"append to `05-areas/career/review_history\.md` as informal feedback",
        r"same challenge 3 times",
    ),
    "resume-builder": (
        r"character limit:\s*220 characters",
        r"character limit:\s*2,600 characters",
        r"linkedin shows top 3 prominently",
        r"focus on top 3 most important",
        r"team of 15 people on a \$5m project",
        r"headline uses most of 220 character limit",
        r"skills section prioritized correctly \(top 3 most important\)",
    ),
    "pipeline-sync": (
        r"platform migration \(acme\).*£250k",
        r"data warehouse \(initech\).*40%",
    ),
    "quarter-plan": (r"in progress \(80%\)",),
    "quarter-review": (
        r"realized we need better onboarding docs.*improve customer activation rate",
        r"qmd finds 4 meetings.*2 tasks",
    ),
}

CATALOGUE_UNSUPPORTED_CLAIMS: dict[str, tuple[str, ...]] = {
    "call-prep": ("pays for itself in 3 months", "2-week rollout"),
    "deal-review": ("updated within last 5 days", "11+ days without update"),
    "pipeline-health": ("3x coverage = healthy", "90% probability"),
    "roadmap": ("health denominators", "calculate health"),
}

STRUCTURED_METHOD_SKILLS = tuple(MATURE_SKILLS)

PROVENANCE_EXAMPLE_SKILLS: dict[str, tuple[str, ...]] = {
    "account-plan": ("acme corp", "$180,000", "sarah chen"),
    "customer-intel": ("23 meetings", "productx", "7 mentions"),
    "feature-decision": ("60% of user base", "$180k arr", "3-4 weeks"),
}


def mature_skill_amendment_errors(skill_id: str, text: str) -> list[str]:
    lowered = text.lower()
    errors = []
    if AMENDMENT_HEADING not in text:
        errors.append(f"missing heading {AMENDMENT_HEADING!r}")
    common = {
        "provenance": ("source", "date", "as-of"),
        "uncertainty": ("unknown", "contradict"),
        "honesty": ("never invent",),
        "controlled change": ("preview", "confirm", "human"),
        "verification": ("read back", "fail"),
    }
    for label, terms in common.items():
        missing = [term for term in terms if term not in lowered]
        if missing:
            errors.append(f"{label} is incomplete; missing {', '.join(missing)}")
    for pattern in ROLE_REQUIREMENTS[skill_id]:
        if re.search(pattern, lowered, re.DOTALL) is None:
            errors.append(f"known role gap remains; expected /{pattern}/")
    for pattern in UNSUPPORTED_ASSUMPTIONS.get(skill_id, ()):
        if re.search(pattern, lowered, re.DOTALL):
            errors.append(f"unsupported rule or invented claim remains; found /{pattern}/")

    if skill_id in STRUCTURED_METHOD_SKILLS:
        for heading in ("## Method", "## Output contract"):
            body = _level_two_section(text, heading)
            if body is None or len(body.split()) < 35:
                errors.append(f"missing substantive {heading} section")

    if skill_id == "career-setup" and "06-resources/career_evidence" in lowered:
        errors.append("contradictory legacy career evidence path remains")
    if skill_id == "resume-builder" and re.search(r"</?thinking>", text, re.I):
        errors.append("reasoning-tag exposure remains")
    return errors


def _level_two_section_bounds(
    text: str,
    heading: str,
) -> tuple[list[str], int, int] | None:
    lines = text.splitlines(keepends=True)
    heading_index: int | None = None
    fence_marker: str | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        fence = re.match(r"^(```+|~~~+)", stripped)
        if fence:
            marker = fence.group(1)[0]
            if fence_marker is None:
                fence_marker = marker
            elif marker == fence_marker:
                fence_marker = None
            continue
        if fence_marker is not None:
            continue
        if heading_index is None:
            if stripped == heading:
                heading_index = index
            continue
        if re.match(r"^##(?:\s|$)", line):
            return lines, heading_index, index
    if heading_index is None:
        return None
    return lines, heading_index, len(lines)


def _level_two_section(text: str, heading: str) -> str | None:
    bounds = _level_two_section_bounds(text, heading)
    if bounds is None:
        return None
    lines, heading_index, end = bounds
    return "".join(lines[heading_index + 1 : end]).strip()


def _without_level_two_section(text: str, heading: str) -> tuple[str, bool]:
    bounds = _level_two_section_bounds(text, heading)
    if bounds is None:
        return text, False
    lines, heading_index, end = bounds
    return "".join((*lines[:heading_index], *lines[end:])), True


@pytest.mark.parametrize("skill_id", tuple(MATURE_SKILLS))
def test_mature_wave3_skill_closes_its_known_evidence_and_depth_gaps(
    skill_id: str,
) -> None:
    text = (REPO_ROOT / MATURE_SKILLS[skill_id]).read_text(encoding="utf-8")
    errors = mature_skill_amendment_errors(skill_id, text)

    assert not errors, f"{skill_id} Wave 3 amendment gaps:\n- " + "\n- ".join(errors)


def test_mature_skill_gate_detects_loss_of_a_known_method() -> None:
    skill_id = "pipeline-health"
    text = (REPO_ROOT / MATURE_SKILLS[skill_id]).read_text(encoding="utf-8")
    assert not mature_skill_amendment_errors(skill_id, text), "positive control must pass"

    mutated = re.sub(r"(?i)denominator", "sample", text)
    assert mutated != text
    errors = mature_skill_amendment_errors(skill_id, mutated)
    assert any("denominator" in error for error in errors)


@pytest.mark.parametrize("skill_id", STRUCTURED_METHOD_SKILLS)
@pytest.mark.parametrize("heading", ("## Method", "## Output contract"))
def test_mature_skill_gate_rejects_deleted_method_or_output_section(
    skill_id: str,
    heading: str,
) -> None:
    text = (REPO_ROOT / MATURE_SKILLS[skill_id]).read_text(encoding="utf-8")
    mutated, removed = _without_level_two_section(text, heading)

    assert removed, f"positive control needs {heading} in {skill_id}"
    errors = mature_skill_amendment_errors(skill_id, mutated)
    assert any(heading in error for error in errors)


@pytest.mark.parametrize("skill_id", STRUCTURED_METHOD_SKILLS)
@pytest.mark.parametrize("heading", ("## Method", "## Output contract"))
def test_mature_skill_gate_rejects_fenced_decoy_after_section_deletion(
    skill_id: str,
    heading: str,
) -> None:
    text = (REPO_ROOT / MATURE_SKILLS[skill_id]).read_text(encoding="utf-8")
    mutated, removed = _without_level_two_section(text, heading)

    assert removed, f"positive control needs {heading} in {skill_id}"
    decoy = (
        f"\n~~~markdown\n{heading}\n"
        "This deliberately long fenced example cannot replace a real instruction "
        "section. It contains enough words to catch an implementation that merely "
        "counts prose, while the actual top-level method or output contract has been "
        "deleted. Publication must fail closed for this mutation every time.\n"
        "~~~\n"
    )
    errors = mature_skill_amendment_errors(skill_id, mutated + decoy)

    assert any(heading in error for error in errors)


@pytest.mark.parametrize("skill_id", tuple(PROVENANCE_EXAMPLE_SKILLS))
def test_examples_use_provenance_placeholders_instead_of_fabricated_facts(
    skill_id: str,
) -> None:
    text = (REPO_ROOT / MATURE_SKILLS[skill_id]).read_text(encoding="utf-8")
    heading = next(
        (line for line in text.splitlines() if line.startswith("## Example")),
        None,
    )
    example = _level_two_section(text, heading).lower() if heading is not None else None

    assert example is not None, f"{skill_id} needs one bounded example section"
    for required in ("[source id]", "[source date]", "[as-of date]", "unknown"):
        assert required in example, f"{skill_id} example is missing {required}"
    for fabricated in PROVENANCE_EXAMPLE_SKILLS[skill_id]:
        assert fabricated not in example, f"{skill_id} retains fabricated example fact: {fabricated}"


def test_resume_examples_do_not_supply_realistic_fabricated_facts() -> None:
    text = (REPO_ROOT / MATURE_SKILLS["resume-builder"]).read_text(encoding="utf-8")
    fabricated = (
        "$2.1M ARR",
        "team of 12",
        "500+ users",
        "$180K annually",
        "Ex-Google",
        "Stanford MBA",
        "$50M+",
        "10x User Growth",
        "$2M product launch",
        "50K users",
        "Senior Product Manager at TechCo",
    )

    for claim in fabricated:
        assert claim.lower() not in text.lower(), f"fabricated resume example remains: {claim}"
    for placeholder in ("[source id]", "[source date]", "[user-confirmed metric]"):
        assert placeholder in text


def test_resume_lists_sessions_before_confirmed_persistent_session_creation() -> None:
    text = (REPO_ROOT / MATURE_SKILLS["resume-builder"]).read_text(encoding="utf-8")
    usage = _level_two_section(text, "## MCP Tool Usage")

    assert usage is not None
    assert usage.index("list_sessions") < usage.index("start_session")
    assert "`start_session` creates a persistent file" in usage
    assert "exact preview" in usage
    assert "explicit confirmation" in usage


def test_pipeline_sync_reports_only_read_back_receipts_and_has_no_rating_write() -> None:
    text = (REPO_ROOT / MATURE_SKILLS["pipeline-sync"]).read_text(encoding="utf-8")

    assert "capture_skill_rating" not in text
    assert "Updated 2 tracker rows" not in text
    for required in ("read-back receipt", "zero changes", "partial", "failure"):
        assert required in text


def test_career_coach_queries_match_the_selected_review_period() -> None:
    text = (REPO_ROOT / MATURE_SKILLS["career-coach"]).read_text(encoding="utf-8")
    monthly = _level_two_section(text, "## Mode 2: Monthly Reflection")

    assert monthly is not None
    assert "last-6-months" not in monthly
    assert "selected review period" in monthly
    assert "coverage" in monthly
    assert "returns 42 files" not in text
    assert "returns 8 competencies" not in text
    assert "returns 12 goals" not in text


def test_quarter_review_surfaces_missing_coverage_and_uses_configured_policies() -> None:
    text = (REPO_ROOT / MATURE_SKILLS["quarter-review"]).read_text(encoding="utf-8")
    lowered = text.lower()

    for forbidden in ("skip this step silently", "skip silently", "score >= 85", ">6 months old", "if 3+ high-priority"):
        assert forbidden not in lowered
    for required in ("coverage", "unknown", "configured", "policy source", "policy date"):
        assert required in lowered


def test_feature_decision_does_not_supply_generic_effort_durations() -> None:
    text = (REPO_ROOT / MATURE_SKILLS["feature-decision"]).read_text(encoding="utf-8")

    assert "Small: <1 week" not in text
    assert "Medium: 1-4 weeks" not in text
    assert "Large: 1-3 months" not in text
    assert "configured or user-confirmed sizing scale" in text


def test_career_setup_gates_phase_six_and_skip_writes_at_the_point_of_action() -> None:
    text = (REPO_ROOT / MATURE_SKILLS["career-setup"]).read_text(encoding="utf-8")
    phase_five = re.search(r"(?ms)^### Phase 5:[^\n]*\n(.*?)(?=^### Phase 6:)", text)
    phase_six = re.search(r"(?ms)^### Phase 6:[^\n]*\n(.{0,700})", text)
    skip_flow = re.search(
        r"(?ms)^### If They Want to Skip Sections\s*$\n(.*?)(?=^###\s|^##\s|\Z)",
        text,
    )

    assert phase_five is not None and phase_six is not None and skip_flow is not None
    for body in (phase_five.group(1), phase_six.group(1), skip_flow.group(1)):
        lowered = body.lower()
        assert "exact preview" in lowered
        assert "explicit confirmation" in lowered
        assert "before" in lowered or "only after" in lowered


def test_career_setup_describes_the_hook_as_a_read_only_candidate_detector() -> None:
    text = (REPO_ROOT / MATURE_SKILLS["career-setup"]).read_text(encoding="utf-8")
    lowered = text.lower()

    for forbidden in ("hook may append", "may append a candidate"):
        assert forbidden not in lowered
    for required in (
        "read-only",
        "candidate only",
        "nothing was saved",
        "exact preview",
        "explicit confirmation",
        "read back",
    ):
        assert required in lowered


def test_career_coach_uses_confirmed_criteria_and_gates_every_history_append() -> None:
    text = (REPO_ROOT / MATURE_SKILLS["career-coach"]).read_text(encoding="utf-8")
    lowered = text.lower()

    for forbidden in (
        "0-3 years",
        "3-7 years",
        "7+ years",
        "append to `05-areas/career/review_history.md` as informal feedback",
        "same challenge 3 times",
    ):
        assert forbidden not in lowered
    for required in (
        "configured or user-confirmed career level",
        "configured or user-confirmed recurrence criterion",
        "review-history append",
        "exact preview",
        "explicit confirmation",
        "read back",
    ):
        assert required in lowered


def test_resume_linkedin_guidance_uses_sourced_limits_and_provenance_placeholders() -> None:
    text = (REPO_ROOT / MATURE_SKILLS["resume-builder"]).read_text(encoding="utf-8")
    lowered = text.lower()

    for forbidden in (
        "220 characters",
        "2,600 characters",
        "top 3",
        "team of 15 people",
        "$5m project",
    ):
        assert forbidden not in lowered
    for required in (
        "current, cited first-party linkedin source",
        "unknown",
        "[source id]",
        "[source date]",
        "[user-confirmed metric]",
    ):
        assert required in lowered


@pytest.mark.parametrize(
    ("skill_id", "fabricated"),
    (
        ("pipeline-sync", "Platform Migration (Acme)  value        £250k"),
        ("quarter-plan", "In progress (80%)"),
        (
            "quarter-review",
            'Learning "Realized we need better onboarding docs" semantically matches goal '
            '"Improve customer activation rate"',
        ),
        ("quarter-review", "QMD finds 4 meetings about European partnerships and 2 tasks"),
    ),
)
def test_operational_examples_do_not_use_realistic_fabricated_facts(
    skill_id: str,
    fabricated: str,
) -> None:
    text = (REPO_ROOT / MATURE_SKILLS[skill_id]).read_text(encoding="utf-8")

    assert fabricated.lower() not in text.lower()
    for placeholder in ("[source id]", "[source date]", "[as-of date]"):
        assert placeholder in text.lower()


@pytest.mark.parametrize(
    ("skill_id", "contradiction"),
    (
        ("pipeline-health", "3x coverage = Healthy"),
        ("deal-review", "Fresh: Updated within last 5 days"),
        ("roadmap", "**Health score:** Good"),
        ("call-prep", "Cost response: pays for itself in 3 months"),
        ("career-setup", "The hook may append a candidate"),
        ("career-coach", "Early Career - 0-3 years"),
        ("resume-builder", "Character limit: 220 characters"),
        ("pipeline-sync", "Platform Migration (Acme) value £250k"),
        ("quarter-plan", "In progress (80%)"),
        (
            "quarter-review",
            'Learning "Realized we need better onboarding docs" semantically matches goal '
            '"Improve customer activation rate"',
        ),
    ),
)
def test_mature_skill_gate_detects_unsupported_rules_and_invented_claims(
    skill_id: str,
    contradiction: str,
) -> None:
    text = (REPO_ROOT / MATURE_SKILLS[skill_id]).read_text(encoding="utf-8")
    errors = mature_skill_amendment_errors(skill_id, f"{text}\n{contradiction}\n")

    assert any("unsupported rule or invented claim" in error for error in errors)


def _catalogue_claim_errors(skill_id: str, entry: dict[str, object]) -> list[str]:
    rendered = json.dumps(entry, sort_keys=True).lower()
    return [
        claim
        for claim in CATALOGUE_UNSUPPORTED_CLAIMS[skill_id]
        if claim in rendered
    ]


@pytest.mark.parametrize("skill_id", tuple(CATALOGUE_UNSUPPORTED_CLAIMS))
def test_catalogue_copy_does_not_reintroduce_removed_assumptions(skill_id: str) -> None:
    registry = json.loads(
        (REPO_ROOT / "core/lens-catalog/registry.json").read_text(encoding="utf-8")
    )
    entry = next(item for item in registry["entries"] if item["id"] == skill_id)

    assert not _catalogue_claim_errors(skill_id, entry)


def test_catalogue_copy_gate_detects_a_removed_assumption() -> None:
    entry = {"id": "roadmap", "brief": {"method_outline": ["Calculate health"]}}

    assert _catalogue_claim_errors("roadmap", entry) == ["calculate health"]
