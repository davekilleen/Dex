"""Who today's plan names appears under today's brief without typing."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from core.obsidian_panel import people_named_in_today_plan, refuse_network, refuse_vault_write
from core.obsidian_panel.people import (
    NO_PLAN,
    NOBODY_NAMED,
    TODAY_HEADING,
    format_person_match,
)
from core.obsidian_panel.safety import plugin_source_violations

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "packages" / "dex-obsidian-plugin"
PEOPLE_MODULE = REPO_ROOT / "core" / "obsidian_panel" / "people.py"
TODAY = date(2026, 8, 29)


def _write_today_people_vault(root: Path) -> Path:
    internal = root / "05-Areas" / "People" / "Internal"
    external = root / "05-Areas" / "People" / "External"
    plans = root / "00-Inbox" / "Daily_Plans"
    internal.mkdir(parents=True)
    external.mkdir(parents=True)
    plans.mkdir(parents=True)
    (root / "03-Tasks").mkdir(parents=True)
    (internal / "Ada_Lovelace.md").write_text(
        "---\nname: Ada Lovelace\nrole: Founder\ncompany: Analytical Engines\n---\n"
        "# Ada Lovelace\n",
        encoding="utf-8",
    )
    (external / "José_García.md").write_text(
        "---\nname: \"José García\"\nrole: \"VP, Product\"\ncompany: \"Acme & Sons\"\n---\n"
        "# José García\n",
        encoding="utf-8",
    )
    (internal / "No_Role.md").write_text(
        "---\nname: No Role\nrole: ~\ncompany:\n---\n# No Role\n",
        encoding="utf-8",
    )
    (internal / "README.md").write_text(
        "# People\n\nname: Not A Person\nrole: Skip this\ncompany: Index\n",
        encoding="utf-8",
    )
    (plans / "2026-08-29.md").write_text(
        "# Saturday, August 29, 2026\n\n"
        "- Prep with [[José_García]]\n"
        "- Send the operating memo to Ada Lovelace\n"
        "- Catch up with No Role\n",
        encoding="utf-8",
    )
    (root / "03-Tasks" / "Tasks.md").write_text(
        "- [ ] Leave this task file unchanged. Ada Lovelace is not today's plan.\n",
        encoding="utf-8",
    )
    return root


def _snapshot(root: Path) -> dict[str, tuple[int, str]]:
    snapshot: dict[str, tuple[int, str]] = {}
    for path in root.rglob("*"):
        if path.is_file():
            snapshot[path.relative_to(root).as_posix()] = (
                path.stat().st_mtime_ns,
                path.read_text(encoding="utf-8"),
            )
    return snapshot


def test_today_people_follow_plan_order_from_own_pages(tmp_path: Path) -> None:
    vault = _write_today_people_vault(tmp_path / "dex")
    before = _snapshot(vault)

    result = people_named_in_today_plan(vault, today=TODAY)

    assert result["plan"] is True
    assert result["empty"] is None
    assert result["matches"][0] == {
        "name": "José García",
        "role": "VP, Product",
        "company": "Acme & Sons",
        "note": "José_García",
        "last_interaction": "",
        "open_items": [],
    }
    assert result["matches"][1]["name"] == "Ada Lovelace"
    assert result["matches"][1]["role"] == "Founder"
    assert result["matches"][1]["company"] == "Analytical Engines"
    assert result["matches"][2] == {
        "name": "No Role",
        "role": "",
        "company": "",
        "note": "No_Role",
        "last_interaction": "",
        "open_items": [],
    }
    assert result["lines"][0] == (
        "José García — VP, Product at Acme & Sons (note: José_García)"
    )
    assert result["lines"][2] == "No Role (note: No_Role)"
    assert "Founder" not in result["lines"][2]
    assert _snapshot(vault) == before


def test_today_people_omit_missing_fields_and_never_invent(tmp_path: Path) -> None:
    vault = _write_today_people_vault(tmp_path / "dex")
    (vault / "00-Inbox" / "Daily_Plans" / "2026-08-29.md").write_text(
        "- Catch up with No Role and a stranger named Sam Invented\n",
        encoding="utf-8",
    )

    result = people_named_in_today_plan(vault, today=TODAY)

    assert result["matches"] == [
        {
            "name": "No Role",
            "role": "",
            "company": "",
            "note": "No_Role",
            "last_interaction": "",
            "open_items": [],
        }
    ]
    assert result["lines"] == ["No Role (note: No_Role)"]
    assert "Invented" not in "".join(result["lines"])
    assert "Skip this" not in "".join(result["lines"])


def test_today_people_ignore_other_days_and_the_task_list(tmp_path: Path) -> None:
    vault = _write_today_people_vault(tmp_path / "dex")
    (vault / "00-Inbox" / "Daily_Plans" / "2026-08-28.md").write_text(
        "- Yesterday named Ada Lovelace only\n",
        encoding="utf-8",
    )
    (vault / "00-Inbox" / "Daily_Plans" / "2026-08-29.md").write_text(
        "- Prep with [[José_García]]\n",
        encoding="utf-8",
    )

    result = people_named_in_today_plan(vault, today=TODAY)

    assert [row["note"] for row in result["matches"]] == ["José_García"]
    assert "Ada Lovelace" not in "".join(result["lines"])


def test_today_people_says_one_honest_sentence_when_nobody_is_named(
    tmp_path: Path,
) -> None:
    vault = _write_today_people_vault(tmp_path / "dex")
    (vault / "00-Inbox" / "Daily_Plans" / "2026-08-29.md").write_text(
        "# Saturday, August 29, 2026\n\n- Ship the notes panel\n",
        encoding="utf-8",
    )
    before = _snapshot(vault)

    result = people_named_in_today_plan(vault, today=TODAY)

    assert result["plan"] is True
    assert result["matches"] == []
    assert result["empty"] == NOBODY_NAMED
    assert result["lines"] == []
    assert _snapshot(vault) == before


def test_today_people_says_one_honest_sentence_when_there_is_no_plan(
    tmp_path: Path,
) -> None:
    vault = _write_today_people_vault(tmp_path / "dex")
    (vault / "00-Inbox" / "Daily_Plans" / "2026-08-29.md").unlink()
    before = _snapshot(vault)

    result = people_named_in_today_plan(vault, today=TODAY)

    assert result["plan"] is False
    assert result["matches"] == []
    assert result["empty"] == NO_PLAN
    assert _snapshot(vault) == before


def test_today_people_does_not_read_product_files_or_person_context(
    tmp_path: Path,
) -> None:
    vault = _write_today_people_vault(tmp_path / "dex")
    (vault / "packages" / "dex-obsidian-plugin").mkdir(parents=True)
    (vault / "packages" / "dex-obsidian-plugin" / "Ada_Lovelace.md").write_text(
        "---\nname: Ada Lovelace\nrole: Product copy\ncompany: Not a person page\n---\n",
        encoding="utf-8",
    )
    people_source = PEOPLE_MODULE.read_text(encoding="utf-8")
    main = (PLUGIN_ROOT / "main.js").read_text(encoding="utf-8")
    import subprocess

    result = people_named_in_today_plan(vault, today=TODAY)
    person_context_diff = subprocess.run(
        ["git", "diff", "--", "core/context/person_context.py"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    ada = next(row for row in result["matches"] if row["name"] == "Ada Lovelace")
    assert ada["role"] == "Founder"
    assert "Product copy" not in "".join(result["lines"])
    assert "person_context" not in people_source
    assert "get_person_context" not in people_source
    assert "person_context" not in main
    assert person_context_diff.stdout == ""
    assert "granted=true" not in people_source
    assert "granted=true" not in main


def test_today_people_refuses_writes_and_the_internet(tmp_path: Path) -> None:
    vault = _write_today_people_vault(tmp_path / "dex")
    target = vault / "03-Tasks" / "Tasks.md"
    before = target.read_text(encoding="utf-8")

    with pytest.raises(PermissionError, match="does not write"):
        refuse_vault_write(target)
    with pytest.raises(PermissionError, match="does not use the internet"):
        refuse_network("https://example.invalid")

    people_named_in_today_plan(vault, today=TODAY)
    assert target.read_text(encoding="utf-8") == before


def test_panel_source_has_today_people_without_typing_and_stays_local() -> None:
    main = (PLUGIN_ROOT / "main.js").read_text(encoding="utf-8")
    assert TODAY_HEADING in main
    assert NOBODY_NAMED in main
    assert NO_PLAN in main
    assert "renderTodayPeople" in main
    assert "peopleNamedInPlan" in main
    assert "Type a person's name" in main
    assert "addCommand" not in main
    assert "fetch(" not in main
    assert "requestUrl" not in main
    assert "https://" not in main
    assert "http://" not in main
    assert "granted=true" not in main
    assert plugin_source_violations(PLUGIN_ROOT) == []


def test_panel_javascript_today_people_matches_the_local_files() -> None:
    script = r"""
const Module = require("module");
const original = Module.prototype.require;
Module.prototype.require = function (id) {
  if (id === "obsidian") {
    return { ItemView: class {}, Plugin: class {} };
  }
  return original.apply(this, arguments);
};
const panel = require("./packages/dex-obsidian-plugin/main.js");
const ada = "---\nname: Ada Lovelace\nrole: Founder\ncompany: Analytical Engines\n---\n# Ada Lovelace\n";
const jose = "---\nname: \"José García\"\nrole: \"VP, Product\"\ncompany: \"Acme & Sons\"\n---\n# José García\n";
const none = "---\nname: No Role\nrole: ~\ncompany:\n---\n# No Role\n";
const records = [
  panel.collectPersonRecord(ada, "05-Areas/People/Internal/Ada_Lovelace.md"),
  panel.collectPersonRecord(jose, "05-Areas/People/External/José_García.md"),
  panel.collectPersonRecord(none, "05-Areas/People/Internal/No_Role.md"),
].filter(Boolean);
const plan = "- Prep with [[José_García]]\n- Send the operating memo to Ada Lovelace\n- Catch up with No Role\n";
const hit = panel.peopleNamedInPlan(records, plan);
const nobody = panel.peopleNamedInPlan(records, "- Ship the notes panel\n");
process.stdout.write(JSON.stringify({
  hit,
  nobody,
  nobodyEmpty: panel.NOBODY_NAMED,
  noPlan: panel.NO_PLAN,
  heading: panel.TODAY_PEOPLE_HEADING,
  lines: hit.map(panel.formatPersonMatch),
  missing: panel.formatPersonMatch(hit[2]),
}));
"""
    import json
    import subprocess

    completed = subprocess.run(
        ["node", "-e", script],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["heading"] == TODAY_HEADING
    assert payload["nobodyEmpty"] == NOBODY_NAMED
    assert payload["noPlan"] == NO_PLAN
    assert payload["nobody"] == []
    assert payload["hit"][0]["name"] == "José García"
    assert payload["hit"][1]["name"] == "Ada Lovelace"
    assert payload["hit"][2]["role"] == ""
    assert payload["lines"][0] == (
        "José García — VP, Product at Acme & Sons (note: José_García)"
    )
    assert payload["missing"] == "No Role (note: No_Role)"
    assert "note:" in format_person_match(payload["hit"][0])
