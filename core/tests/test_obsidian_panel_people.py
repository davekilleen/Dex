"""A person can type a person's name and see who they are from their own files."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.obsidian_panel import ask_who_they_are, refuse_network, refuse_vault_write
from core.obsidian_panel.people import EMPTY_SENTENCE, format_person_match
from core.obsidian_panel.safety import plugin_source_violations

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "packages" / "dex-obsidian-plugin"
PEOPLE_MODULE = REPO_ROOT / "core" / "obsidian_panel" / "people.py"


def _write_people_vault(root: Path) -> Path:
    internal = root / "05-Areas" / "People" / "Internal"
    external = root / "05-Areas" / "People" / "External"
    internal.mkdir(parents=True)
    external.mkdir(parents=True)
    (root / "03-Tasks").mkdir(parents=True)
    (internal / "Ada_Lovelace.md").write_text(
        "---\nname: Ada Lovelace\nrole: Founder\ncompany: Analytical Engines\n---\n"
        "# Ada Lovelace\n\n- [ ] Send the operating memo\n",
        encoding="utf-8",
    )
    (external / "José_García.md").write_text(
        "---\nname: \"José García\"\nrole: \"VP, Product\"\ncompany: \"Acme & Sons\"\n---\n"
        "# José García\n\nMet at ProductConf.\n",
        encoding="utf-8",
    )
    (internal / "README.md").write_text(
        "# People\n\nname: Not A Person\nrole: Skip this\ncompany: Index\n",
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


def test_person_ask_returns_who_they_are_from_own_files(tmp_path: Path) -> None:
    vault = _write_people_vault(tmp_path / "dex")
    before = _snapshot(vault)

    result = ask_who_they_are(vault, "Ada Lovelace")

    assert result["empty"] is None
    assert result["matches"] == [
        {
            "name": "Ada Lovelace",
            "role": "Founder",
            "company": "Analytical Engines",
            "note": "Ada_Lovelace",
        }
    ]
    assert result["lines"] == [
        "Ada Lovelace — Founder at Analytical Engines (note: Ada_Lovelace)"
    ]
    assert _snapshot(vault) == before


def test_person_ask_matches_filename_and_quoted_fields(tmp_path: Path) -> None:
    vault = _write_people_vault(tmp_path / "dex")

    folded = ask_who_they_are(vault, "ada lovelace")
    assert folded["matches"][0]["name"] == "Ada Lovelace"

    stem = ask_who_they_are(vault, "Ada_Lovelace")
    assert stem["matches"][0]["company"] == "Analytical Engines"

    quoted = ask_who_they_are(vault, "José García")
    assert quoted["matches"][0]["role"] == "VP, Product"
    assert quoted["matches"][0]["company"] == "Acme & Sons"
    assert "note:" in format_person_match(quoted["matches"][0])
    assert "VP, Product at Acme & Sons" in quoted["lines"][0]


def test_person_ask_says_one_honest_sentence_when_nothing_matches(tmp_path: Path) -> None:
    vault = _write_people_vault(tmp_path / "dex")
    before = _snapshot(vault)

    missing = ask_who_they_are(vault, "purple elephant")
    blank = ask_who_they_are(vault, "   ")

    assert missing["matches"] == []
    assert missing["empty"] == EMPTY_SENTENCE
    assert blank["empty"] == EMPTY_SENTENCE
    assert _snapshot(vault) == before


def test_person_ask_does_not_read_product_files_or_send(tmp_path: Path) -> None:
    vault = _write_people_vault(tmp_path / "dex")
    (vault / "packages" / "dex-obsidian-plugin").mkdir(parents=True)
    (vault / "packages" / "dex-obsidian-plugin" / "Ada_Lovelace.md").write_text(
        "---\nname: Ada Lovelace\nrole: Product copy\ncompany: Not a person page\n---\n",
        encoding="utf-8",
    )
    (vault / ".claude" / "skills").mkdir(parents=True)
    (vault / ".claude" / "skills" / "Ada_Lovelace.md").write_text(
        "---\nname: Ada Lovelace\nrole: Skill copy\ncompany: Not a person page\n---\n",
        encoding="utf-8",
    )

    result = ask_who_they_are(vault, "Ada Lovelace")

    assert result["matches"] == [
        {
            "name": "Ada Lovelace",
            "role": "Founder",
            "company": "Analytical Engines",
            "note": "Ada_Lovelace",
        }
    ]
    assert "Product copy" not in result["lines"][0]
    assert "Skill copy" not in result["lines"][0]


def test_person_ask_skips_readme_and_does_not_use_person_context(tmp_path: Path) -> None:
    vault = _write_people_vault(tmp_path / "dex")
    people_source = PEOPLE_MODULE.read_text(encoding="utf-8")
    main = (PLUGIN_ROOT / "main.js").read_text(encoding="utf-8")
    import subprocess

    result = ask_who_they_are(vault, "Not A Person")
    person_context_diff = subprocess.run(
        ["git", "diff", "--", "core/context/person_context.py"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result["matches"] == []
    assert result["empty"] == EMPTY_SENTENCE
    assert "person_context" not in people_source
    assert "get_person_context" not in people_source
    assert "person_context" not in main
    assert person_context_diff.stdout == ""
    assert "granted=true" not in people_source
    assert "granted=true" not in main


def test_person_ask_refuses_writes_and_the_internet(tmp_path: Path) -> None:
    vault = _write_people_vault(tmp_path / "dex")
    target = vault / "03-Tasks" / "Tasks.md"
    before = target.read_text(encoding="utf-8")

    with pytest.raises(PermissionError, match="does not write"):
        refuse_vault_write(target)
    with pytest.raises(PermissionError, match="does not use the internet"):
        refuse_network("https://example.invalid")

    ask_who_they_are(vault, "Ada Lovelace")
    assert target.read_text(encoding="utf-8") == before


def test_panel_source_has_the_person_ask_and_stays_local() -> None:
    main = (PLUGIN_ROOT / "main.js").read_text(encoding="utf-8")
    assert "Type a person's name" in main
    assert "Who they are" in main
    assert EMPTY_SENTENCE in main
    assert "Look in your files" in main
    assert 'setAttribute("type", "button")' in main
    assert "renderPerson" in main
    assert "getMarkdownFiles" in main
    assert "cachedRead" in main
    assert "addCommand" not in main
    assert "fetch(" not in main
    assert "requestUrl" not in main
    assert "https://" not in main
    assert "http://" not in main
    assert "granted=true" not in main
    assert plugin_source_violations(PLUGIN_ROOT) == []


def test_panel_javascript_person_ask_matches_the_local_files() -> None:
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
const product = "---\nname: Ada Lovelace\nrole: Product copy\ncompany: Not a person page\n---\n";
const records = [
  panel.collectPersonRecord(ada, "05-Areas/People/Internal/Ada_Lovelace.md"),
  panel.collectPersonRecord(jose, "05-Areas/People/External/José_García.md"),
].filter(Boolean);
const hit = panel.matchPeople(records, "Ada Lovelace");
const miss = panel.matchPeople(records, "purple elephant");
const productRecord = panel.collectPersonRecord(
  product,
  "packages/dex-obsidian-plugin/Ada_Lovelace.md",
);
process.stdout.write(JSON.stringify({
  hit,
  miss,
  empty: panel.PERSON_EMPTY,
  line: panel.formatPersonMatch(hit[0]),
  heading: "Who they are",
  ownFile: panel.isPersonMarkdown("05-Areas/People/Internal/Ada_Lovelace.md"),
  productFile: panel.isPersonMarkdown("packages/dex-obsidian-plugin/Ada_Lovelace.md"),
  readme: panel.isPersonMarkdown("05-Areas/People/Internal/README.md"),
  productName: productRecord && productRecord.name,
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
    assert payload["heading"] == "Who they are"
    assert payload["hit"][0]["name"] == "Ada Lovelace"
    assert payload["hit"][0]["role"] == "Founder"
    assert payload["hit"][0]["company"] == "Analytical Engines"
    assert payload["hit"][0]["note"] == "Ada_Lovelace"
    assert payload["miss"] == []
    assert payload["line"] == (
        "Ada Lovelace — Founder at Analytical Engines (note: Ada_Lovelace)"
    )
    assert payload["ownFile"] is True
    assert payload["productFile"] is False
    assert payload["readme"] is False
    assert payload["productName"] == "Ada Lovelace"
