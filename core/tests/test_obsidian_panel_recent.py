"""Decided lately appears under today's brief without typing."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.obsidian_panel import recent_recorded_decisions, refuse_network, refuse_vault_write
from core.obsidian_panel.decisions import (
    LATELY_EMPTY,
    LATELY_LIMIT,
    format_decision_match,
)
from core.obsidian_panel.safety import plugin_source_violations

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "packages" / "dex-obsidian-plugin"


def _write_decision_vault(root: Path) -> Path:
    meetings = root / "00-Inbox" / "Meetings"
    meetings.mkdir(parents=True)
    (root / "06-Resources" / "Decisions").mkdir(parents=True)
    (root / "04-Projects" / "Notes panel").mkdir(parents=True)
    (root / "03-Tasks").mkdir(parents=True)
    (meetings / "2026-08-28 - Coverage call.md").write_text(
        "# Coverage call\n\n## Decisions\n- Keep Decided lately on the person's own files\n",
        encoding="utf-8",
    )
    (meetings / "2026-08-15 - Pricing call.md").write_text(
        "# Pricing call\n\n## Decisions\n- Charge annually for the notes panel\n\n## Next Steps\n- None\n",
        encoding="utf-8",
    )
    (root / "06-Resources" / "Decisions" / "Decision_Log.md").write_text(
        "## 2026-07-01 — Stay local\n\n**Decision:** Keep the notes panel on the person's own files.\n\n",
        encoding="utf-8",
    )
    (root / "04-Projects" / "Notes panel" / "Decisions.md").write_text(
        "# Notes panel\n\n## Decisions\n- Do not send the topic anywhere\n",
        encoding="utf-8",
    )
    (root / "03-Tasks" / "Tasks.md").write_text(
        "- [ ] Leave this task file unchanged\n",
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


def test_decided_lately_shows_newest_dated_words_without_a_topic(tmp_path: Path) -> None:
    vault = _write_decision_vault(tmp_path / "dex")
    before = _snapshot(vault)

    result = recent_recorded_decisions(vault)

    assert result["empty"] is None
    assert result["matches"][0] == {
        "words": "Keep Decided lately on the person's own files",
        "note": "2026-08-28 - Coverage call",
        "date": "2026-08-28",
    }
    assert result["matches"][1]["date"] == "2026-08-15"
    assert result["matches"][1]["words"] == "Charge annually for the notes panel"
    assert result["lines"][0] == (
        "Keep Decided lately on the person's own files "
        "(note: 2026-08-28 - Coverage call, date: 2026-08-28)"
    )
    assert _snapshot(vault) == before


def test_decided_lately_skips_undated_notes_and_caps_the_list(tmp_path: Path) -> None:
    vault = _write_decision_vault(tmp_path / "dex")
    (vault / "00-Inbox" / "Meetings" / "2026-08-20 - Extra.md").write_text(
        "## Decisions\n- Third dated decision for the cap\n",
        encoding="utf-8",
    )
    (vault / "00-Inbox" / "Meetings" / "2026-08-10 - Older extra.md").write_text(
        "## Decisions\n- Fourth dated decision stays off the list\n",
        encoding="utf-8",
    )

    result = recent_recorded_decisions(vault)

    assert LATELY_LIMIT == 3
    assert [row["date"] for row in result["matches"]] == [
        "2026-08-28",
        "2026-08-20",
        "2026-08-15",
    ]
    assert "Do not send the topic anywhere" not in result["lines"]
    assert "Fourth dated decision stays off the list" not in result["lines"]
    assert "note:" in format_decision_match(result["matches"][0])


def test_decided_lately_says_one_honest_sentence_when_nothing_is_there(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "empty"
    (vault / "04-Projects" / "Notes").mkdir(parents=True)
    (vault / "04-Projects" / "Notes" / "Decisions.md").write_text(
        "## Decisions\n- Undated words do not count as lately\n",
        encoding="utf-8",
    )
    before = _snapshot(vault)

    result = recent_recorded_decisions(vault)

    assert result["matches"] == []
    assert result["empty"] == LATELY_EMPTY
    assert result["lines"] == []
    assert _snapshot(vault) == before


def test_decided_lately_does_not_read_product_files_or_send(tmp_path: Path) -> None:
    vault = tmp_path / "product"
    (vault / "04-Projects").mkdir(parents=True)
    (vault / ".claude" / "skills" / "decision-log").mkdir(parents=True)
    (vault / ".claude" / "skills" / "decision-log" / "SKILL.md").write_text(
        "## 2026-08-29 — Skill copy\n\n**Decision:** One sentence stating the choice.\n",
        encoding="utf-8",
    )
    (vault / "packages" / "dex-obsidian-plugin").mkdir(parents=True)
    (vault / "packages" / "dex-obsidian-plugin" / "README.md").write_text(
        "## Decisions\n- Do not treat product docs as the person's notes\n",
        encoding="utf-8",
    )

    result = recent_recorded_decisions(vault)

    assert result["matches"] == []
    assert result["empty"] == LATELY_EMPTY


def test_decided_lately_refuses_writes_and_the_internet(tmp_path: Path) -> None:
    vault = _write_decision_vault(tmp_path / "dex")
    target = vault / "03-Tasks" / "Tasks.md"
    before = target.read_text(encoding="utf-8")

    with pytest.raises(PermissionError, match="does not write"):
        refuse_vault_write(target)
    with pytest.raises(PermissionError, match="does not use the internet"):
        refuse_network("https://example.invalid")

    recent_recorded_decisions(vault)
    assert target.read_text(encoding="utf-8") == before


def test_panel_source_has_decided_lately_without_typing() -> None:
    main = (PLUGIN_ROOT / "main.js").read_text(encoding="utf-8")
    assert "Decided lately" in main
    assert LATELY_EMPTY in main
    assert "renderLately" in main
    assert "recentDecisions" in main
    assert "Type a topic" in main
    assert 'setAttribute("type", "button")' in main
    assert "getMarkdownFiles" in main
    assert "cachedRead" in main
    assert "addCommand" not in main
    assert "fetch(" not in main
    assert "requestUrl" not in main
    assert "https://" not in main
    assert "http://" not in main
    assert plugin_source_violations(PLUGIN_ROOT) == []


def test_panel_javascript_lately_matches_the_local_files() -> None:
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
const newer = "# Coverage call\n\n## Decisions\n- Keep Decided lately on the person's own files\n";
const meeting = "# Pricing call\n\n## Decisions\n- Charge annually for the notes panel\n";
const log = "## 2026-07-01 — Stay local\n\n**Decision:** Keep the notes panel on the person's own files.\n";
const undated = "## Decisions\n- Undated words do not count as lately\n";
const records = [
  ...panel.collectDecisionRecords(newer, "00-Inbox/Meetings/2026-08-28 - Coverage call.md"),
  ...panel.collectDecisionRecords(meeting, "00-Inbox/Meetings/2026-08-15 - Pricing call.md"),
  ...panel.collectDecisionRecords(log, "06-Resources/Decisions/Decision_Log.md"),
  ...panel.collectDecisionRecords(undated, "04-Projects/Notes panel/Decisions.md"),
];
const lately = panel.recentDecisions(records, panel.LATELY_LIMIT);
process.stdout.write(JSON.stringify({
  lately,
  empty: panel.LATELY_EMPTY,
  heading: "Decided lately",
  line: panel.formatDecisionMatch(lately[0]),
  limit: panel.LATELY_LIMIT,
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
    assert payload["empty"] == LATELY_EMPTY
    assert payload["heading"] == "Decided lately"
    assert payload["limit"] == LATELY_LIMIT
    assert payload["lately"][0]["words"] == "Keep Decided lately on the person's own files"
    assert payload["lately"][0]["note"] == "2026-08-28 - Coverage call"
    assert payload["lately"][0]["date"] == "2026-08-28"
    assert payload["lately"][1]["date"] == "2026-08-15"
    assert payload["line"] == (
        "Keep Decided lately on the person's own files "
        "(note: 2026-08-28 - Coverage call, date: 2026-08-28)"
    )
    assert all(row["date"] != "no date in that note" for row in payload["lately"])
