"""A person can type a topic under today's brief and see recorded decisions."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.obsidian_panel import ask_recorded_decisions, refuse_network, refuse_vault_write
from core.obsidian_panel.decisions import EMPTY_SENTENCE, format_decision_match
from core.obsidian_panel.safety import plugin_source_violations

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "packages" / "dex-obsidian-plugin"


def _write_decision_vault(root: Path) -> Path:
    meetings = root / "00-Inbox" / "Meetings"
    meetings.mkdir(parents=True)
    (root / "06-Resources" / "Decisions").mkdir(parents=True)
    (root / "04-Projects" / "Notes panel").mkdir(parents=True)
    (root / "03-Tasks").mkdir(parents=True)
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


def test_topic_ask_returns_recorded_words_with_note_and_date(tmp_path: Path) -> None:
    vault = _write_decision_vault(tmp_path / "dex")
    before = _snapshot(vault)

    result = ask_recorded_decisions(vault, "annually")

    assert result["empty"] is None
    assert result["matches"] == [
        {
            "words": "Charge annually for the notes panel",
            "note": "2026-08-15 - Pricing call",
            "date": "2026-08-15",
        }
    ]
    assert result["lines"] == [
        "Charge annually for the notes panel (note: 2026-08-15 - Pricing call, date: 2026-08-15)"
    ]
    assert _snapshot(vault) == before


def test_topic_ask_reads_decision_log_and_project_files(tmp_path: Path) -> None:
    vault = _write_decision_vault(tmp_path / "dex")

    local = ask_recorded_decisions(vault, "own files")
    assert local["matches"][0]["words"] == "Keep the notes panel on the person's own files."
    assert local["matches"][0]["note"] == "Decision_Log"
    assert local["matches"][0]["date"] == "2026-07-01"

    titled = ask_recorded_decisions(vault, "Stay local")
    assert titled["matches"][0]["words"] == "Keep the notes panel on the person's own files."

    sent = ask_recorded_decisions(vault, "send the topic")
    assert sent["matches"][0]["words"] == "Do not send the topic anywhere"
    assert sent["matches"][0]["note"] == "Decisions"
    assert "note:" in format_decision_match(sent["matches"][0])
    assert "date:" in format_decision_match(sent["matches"][0])


def test_topic_ask_says_one_honest_sentence_when_nothing_matches(tmp_path: Path) -> None:
    vault = _write_decision_vault(tmp_path / "dex")
    before = _snapshot(vault)

    missing = ask_recorded_decisions(vault, "purple elephant")
    blank = ask_recorded_decisions(vault, "   ")

    assert missing["matches"] == []
    assert missing["empty"] == EMPTY_SENTENCE
    assert blank["empty"] == EMPTY_SENTENCE
    assert _snapshot(vault) == before


def test_topic_ask_does_not_read_product_files_or_send(tmp_path: Path) -> None:
    vault = _write_decision_vault(tmp_path / "dex")
    (vault / ".claude" / "skills" / "decision-log").mkdir(parents=True)
    (vault / ".claude" / "skills" / "decision-log" / "SKILL.md").write_text(
        "**Decision:** One sentence stating the choice.\n",
        encoding="utf-8",
    )
    (vault / "packages" / "dex-obsidian-plugin").mkdir(parents=True)
    (vault / "packages" / "dex-obsidian-plugin" / "README.md").write_text(
        "## Decisions\n- Do not treat product docs as the person's notes\n",
        encoding="utf-8",
    )

    result = ask_recorded_decisions(vault, "sentence stating")
    product = ask_recorded_decisions(vault, "product docs")

    assert result["matches"] == []
    assert result["empty"] == EMPTY_SENTENCE
    assert product["matches"] == []


def test_topic_ask_refuses_writes_and_the_internet(tmp_path: Path) -> None:
    vault = _write_decision_vault(tmp_path / "dex")
    target = vault / "03-Tasks" / "Tasks.md"
    before = target.read_text(encoding="utf-8")

    with pytest.raises(PermissionError, match="does not write"):
        refuse_vault_write(target)
    with pytest.raises(PermissionError, match="does not use the internet"):
        refuse_network("https://example.invalid")

    ask_recorded_decisions(vault, "annually")
    assert target.read_text(encoding="utf-8") == before


def test_panel_source_has_the_ask_and_stays_local() -> None:
    main = (PLUGIN_ROOT / "main.js").read_text(encoding="utf-8")
    assert "Type a topic" in main
    assert EMPTY_SENTENCE in main
    assert "Look in your files" in main
    assert 'setAttribute("type", "button")' in main
    assert "What we decided" in main
    assert "getMarkdownFiles" in main
    assert "cachedRead" in main
    assert "addCommand" not in main
    assert "fetch(" not in main
    assert "requestUrl" not in main
    assert "https://" not in main
    assert "http://" not in main
    assert plugin_source_violations(PLUGIN_ROOT) == []


def test_panel_javascript_ask_matches_the_local_files() -> None:
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
const meeting = "# Pricing call\n\n## Decisions\n- Charge annually for the notes panel\n";
const log = "## 2026-07-01 — Stay local\n\n**Decision:** Keep the notes panel on the person's own files.\n";
const records = [
  ...panel.collectDecisionRecords(meeting, "00-Inbox/Meetings/2026-08-15 - Pricing call.md"),
  ...panel.collectDecisionRecords(log, "06-Resources/Decisions/Decision_Log.md"),
];
const hit = panel.matchDecisions(records, "annually");
const miss = panel.matchDecisions(records, "purple elephant");
process.stdout.write(JSON.stringify({
  hit,
  miss,
  empty: panel.EMPTY_SENTENCE,
  line: panel.formatDecisionMatch(hit[0]),
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
    assert payload["empty"] == EMPTY_SENTENCE
    assert payload["hit"][0]["words"] == "Charge annually for the notes panel"
    assert payload["hit"][0]["note"] == "2026-08-15 - Pricing call"
    assert payload["hit"][0]["date"] == "2026-08-15"
    assert payload["miss"] == []
    assert payload["line"] == (
        "Charge annually for the notes panel "
        "(note: 2026-08-15 - Pricing call, date: 2026-08-15)"
    )
