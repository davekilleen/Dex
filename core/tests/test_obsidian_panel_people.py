"""A person can type a person's name and see who they are from their own files."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from core.obsidian_panel import (
    ask_who_they_are,
    people_named_in_today_plan,
    refuse_network,
    refuse_vault_write,
)
from core.obsidian_panel.people import (
    EMPTY_SENTENCE,
    NO_PLAN,
    NOBODY_NAMED,
    format_person_match,
)
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


TODAY = date(2026, 8, 29)
ADA_LINE = "Ada Lovelace — Founder at Analytical Engines (note: Ada_Lovelace)"
JOSE_LINE = "José García — VP, Product at Acme & Sons (note: José_García)"
LEAVE_LINE = (
    "Disable Dex in Obsidian's community plugin list, then delete "
    ".obsidian/plugins/dex-readonly from the vault. Leftover: "
    ".obsidian/community-plugins.json may still list dex-readonly until you "
    "remove that name; the workspace layout may still show an empty Dex panel slot."
)
STEP6_PROMISE = (
    "Under each person named in today's plan, the panel also shows the last "
    "interaction their page records and every unchecked to-do still on that page, "
    "without typing. A page that records neither shows neither."
)


def _write_today_open_items_vault(root: Path) -> Path:
    internal = root / "05-Areas" / "People" / "Internal"
    external = root / "05-Areas" / "People" / "External"
    plans = root / "00-Inbox" / "Daily_Plans"
    internal.mkdir(parents=True)
    external.mkdir(parents=True)
    plans.mkdir(parents=True)
    (root / "03-Tasks").mkdir(parents=True)
    (internal / "Ada_Lovelace.md").write_text(
        "---\nname: Ada Lovelace\nrole: Founder\ncompany: Analytical Engines\n"
        "last_interaction: Tuesday standup\n---\n"
        "# Ada Lovelace\n\n"
        "- [ ] Send the operating memo\n"
        "- [x] Already filed the notes\n"
        "- Prose bullet that is not a to-do\n"
        "- [ ] Review the **engine** drawings\n",
        encoding="utf-8",
    )
    (external / "José_García.md").write_text(
        "---\nname: \"José García\"\nrole: \"VP, Product\"\ncompany: \"Acme & Sons\"\n---\n"
        "# José García\n\nMet at ProductConf.\n",
        encoding="utf-8",
    )
    (internal / "Charles_Babbage.md").write_text(
        "---\nname: Charles Babbage\nrole: Engineer\ncompany: Difference Engines\n"
        "last interaction: last summer\n---\n"
        "# Charles Babbage\n\n- [ ] Invent the difference engine\n",
        encoding="utf-8",
    )
    (plans / "2026-08-29.md").write_text(
        "# Saturday, August 29, 2026\n\n"
        "- Prep with Ada Lovelace\n"
        "- Catch up with José García\n",
        encoding="utf-8",
    )
    (root / "03-Tasks" / "Tasks.md").write_text(
        "- [ ] Leave this task file unchanged. Charles Babbage is not today's plan.\n",
        encoding="utf-8",
    )
    return root


def test_today_people_render_last_interaction_and_open_items_in_page_order(
    tmp_path: Path,
) -> None:
    vault = _write_today_open_items_vault(tmp_path / "dex")
    before = _snapshot(vault)

    result = people_named_in_today_plan(vault, today=TODAY)

    assert result["plan"] is True
    assert result["empty"] is None
    assert [row["name"] for row in result["matches"]] == [
        "Ada Lovelace",
        "José García",
    ]
    assert result["matches"][0]["last_interaction"] == "Tuesday standup"
    assert result["matches"][0]["open_items"] == [
        "Send the operating memo",
        "Review the engine drawings",
    ]
    assert result["matches"][1]["last_interaction"] == ""
    assert result["matches"][1]["open_items"] == []
    assert result["lines"] == [ADA_LINE, JOSE_LINE]
    assert "Invent the difference engine" not in "".join(result["lines"])
    assert "last summer" not in "".join(
        str(row.get("last_interaction") or "") for row in result["matches"]
    )
    assert _snapshot(vault) == before


def test_today_people_open_item_disappears_when_checked_and_returns(
    tmp_path: Path,
) -> None:
    vault = _write_today_open_items_vault(tmp_path / "dex")
    page = vault / "05-Areas" / "People" / "Internal" / "Ada_Lovelace.md"
    original = page.read_text(encoding="utf-8")

    page.write_text(original.replace("- [ ] Send the operating memo", "- [x] Send the operating memo"), encoding="utf-8")
    checked = people_named_in_today_plan(vault, today=TODAY)
    assert checked["matches"][0]["open_items"] == ["Review the engine drawings"]
    assert "Send the operating memo" not in checked["matches"][0]["open_items"]

    page.write_text(original, encoding="utf-8")
    restored = people_named_in_today_plan(vault, today=TODAY)
    assert restored["matches"][0]["open_items"] == [
        "Send the operating memo",
        "Review the engine drawings",
    ]


def test_today_people_blank_last_interaction_disappears(tmp_path: Path) -> None:
    vault = _write_today_open_items_vault(tmp_path / "dex")
    page = vault / "05-Areas" / "People" / "Internal" / "Ada_Lovelace.md"
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            "last_interaction: Tuesday standup",
            "last_interaction: ",
        ),
        encoding="utf-8",
    )

    result = people_named_in_today_plan(vault, today=TODAY)

    assert result["matches"][0]["last_interaction"] == ""
    assert result["matches"][0]["open_items"] == [
        "Send the operating memo",
        "Review the engine drawings",
    ]
    assert "Tuesday standup" not in "".join(result["lines"])


def test_today_people_ignore_open_items_on_unnamed_pages(tmp_path: Path) -> None:
    vault = _write_today_open_items_vault(tmp_path / "dex")

    result = people_named_in_today_plan(vault, today=TODAY)
    joined_items = [item for row in result["matches"] for item in row["open_items"]]

    assert "Invent the difference engine" not in joined_items
    assert "Charles Babbage" not in [row["name"] for row in result["matches"]]


def test_today_people_ignore_checked_items_and_prose_bullets(tmp_path: Path) -> None:
    vault = _write_today_open_items_vault(tmp_path / "dex")

    result = people_named_in_today_plan(vault, today=TODAY)

    assert result["matches"][0]["open_items"] == [
        "Send the operating memo",
        "Review the engine drawings",
    ]
    assert "Already filed the notes" not in result["matches"][0]["open_items"]
    assert "Prose bullet that is not a to-do" not in result["matches"][0]["open_items"]


def test_today_people_honest_sentences_stay_byte_identical(tmp_path: Path) -> None:
    vault = _write_today_open_items_vault(tmp_path / "dex")
    (vault / "00-Inbox" / "Daily_Plans" / "2026-08-29.md").write_text(
        "# Saturday, August 29, 2026\n\n- Ship the notes panel\n",
        encoding="utf-8",
    )
    nobody = people_named_in_today_plan(vault, today=TODAY)
    (vault / "00-Inbox" / "Daily_Plans" / "2026-08-29.md").unlink()
    missing = people_named_in_today_plan(vault, today=TODAY)

    assert nobody["empty"] == NOBODY_NAMED
    assert nobody["empty"] == "Today's plan does not name anyone in your files."
    assert nobody["matches"] == []
    assert nobody["lines"] == []
    assert missing["empty"] == NO_PLAN
    assert missing["empty"] == "There is no plan for today in your files."
    assert missing["matches"] == []
    assert missing["lines"] == []


def test_typed_ask_payload_stays_byte_identical_with_open_items_on_the_page(
    tmp_path: Path,
) -> None:
    vault = _write_people_vault(tmp_path / "dex")

    result = ask_who_they_are(vault, "Ada Lovelace")

    assert result == {
        "matches": [
            {
                "name": "Ada Lovelace",
                "role": "Founder",
                "company": "Analytical Engines",
                "note": "Ada_Lovelace",
            }
        ],
        "empty": None,
        "lines": [ADA_LINE],
    }
    assert "last_interaction" not in result["matches"][0]
    assert "open_items" not in result["matches"][0]


def test_founder_card_grows_step_six_and_keeps_the_leave_line() -> None:
    card = (REPO_ROOT / "docs" / "founder-test-cards" / "obsidian.md").read_text(
        encoding="utf-8"
    )
    adapter = (
        REPO_ROOT / "core" / "harnesses" / "adapters" / "obsidian.json"
    ).read_text(encoding="utf-8")

    assert STEP6_PROMISE in card
    assert STEP6_PROMISE in adapter
    assert LEAVE_LINE in card
    assert "### Step 6" in card
    assert "### Step 10" not in card
    assert (
        "Today's brief, then who today's plan names, then Decided lately, "
        "then a topic ask, then a person name."
    ) in card


def test_panel_javascript_nests_open_items_under_the_today_person_row() -> None:
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
function node(tag) {
  const children = [];
  const el = {
    tag,
    children,
    text: "",
    cls: "",
    addClass(name) { el.cls = [el.cls, name].filter(Boolean).join(" "); },
    createEl(childTag, opts = {}) {
      const child = node(childTag);
      if (opts.text) child.text = opts.text;
      if (opts.cls) child.cls = opts.cls;
      children.push(child);
      return child;
    },
    empty() { children.length = 0; el.text = ""; },
  };
  return el;
}
const adaText = "---\nname: Ada Lovelace\nrole: Founder\ncompany: Analytical Engines\nlast_interaction: Tuesday standup\n---\n# Ada Lovelace\n\n- [ ] Send the operating memo\n- [x] Already filed the notes\n- Prose bullet that is not a to-do\n- [ ] Review the **engine** drawings\n";
const joseText = "---\nname: \"José García\"\nrole: \"VP, Product\"\ncompany: \"Acme & Sons\"\n---\n# José García\n\nMet at ProductConf.\n";
const charlesText = "---\nname: Charles Babbage\nlast interaction: last summer\n---\n# Charles Babbage\n\n- [ ] Invent the difference engine\n";
const files = {
  "00-Inbox/Daily_Plans/2026-08-29.md": "- Prep with Ada Lovelace\n- Catch up with José García\n",
  "05-Areas/People/Internal/Ada_Lovelace.md": adaText,
  "05-Areas/People/External/José_García.md": joseText,
  "05-Areas/People/Internal/Charles_Babbage.md": charlesText,
};
const app = {
  vault: {
    getMarkdownFiles() {
      return Object.keys(files).map((path) => ({ path, extension: "md" }));
    },
    getAbstractFileByPath(path) {
      return files[path] ? { path, extension: "md" } : null;
    },
    async cachedRead(file) {
      return files[file.path] || "";
    },
  },
};
const ada = panel.collectPersonRecord(adaText, "05-Areas/People/Internal/Ada_Lovelace.md");
const jose = panel.collectPersonRecord(joseText, "05-Areas/People/External/José_García.md");
const charles = panel.collectPersonRecord(charlesText, "05-Areas/People/Internal/Charles_Babbage.md");
const blank = panel.collectPersonRecord(
  adaText.replace("last_interaction: Tuesday standup", "last_interaction: ~"),
  "05-Areas/People/Internal/Ada_Lovelace.md",
);
const checked = panel.collectPersonRecord(
  adaText.replace("- [ ] Send the operating memo", "- [x] Send the operating memo"),
  "05-Areas/People/Internal/Ada_Lovelace.md",
);
const root = node("div");
panel.renderTodayPeople(root, app, new Date(2026, 7, 29)).then(() => {
  const walk = (el) => ({
    tag: el.tag,
    text: el.text,
    cls: el.cls,
    children: el.children.map(walk),
  });
  process.stdout.write(JSON.stringify({
    tree: walk(root),
    ada,
    jose,
    charles,
    blankLast: blank.last_interaction,
    checkedItems: checked.open_items,
    nobody: panel.NOBODY_NAMED,
    noPlan: panel.NO_PLAN,
    personEmpty: panel.PERSON_EMPTY,
  }));
});
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
    heading, people_list = payload["tree"]["children"]
    ada_row, jose_row = people_list["children"]
    nest = ada_row["children"][0]
    nest_lines = [child["text"] for child in nest["children"]]

    assert heading["text"] == "Who today's plan names"
    assert people_list["tag"] == "ul"
    assert people_list["cls"] == "dex-readonly-today-people"
    assert ada_row["text"] == ADA_LINE
    assert nest["tag"] == "ul"
    assert nest_lines == [
        "Last interaction: Tuesday standup",
        "Still open: Send the operating memo",
        "Still open: Review the engine drawings",
    ]
    assert jose_row["text"] == JOSE_LINE
    assert jose_row["children"] == []
    assert payload["ada"]["last_interaction"] == "Tuesday standup"
    assert payload["ada"]["open_items"] == [
        "Send the operating memo",
        "Review the engine drawings",
    ]
    assert payload["jose"]["last_interaction"] == ""
    assert payload["jose"]["open_items"] == []
    assert payload["charles"]["last_interaction"] == "last summer"
    assert payload["charles"]["open_items"] == ["Invent the difference engine"]
    assert payload["blankLast"] == ""
    assert payload["checkedItems"] == ["Review the engine drawings"]
    assert payload["nobody"] == NOBODY_NAMED
    assert payload["noPlan"] == NO_PLAN
    assert payload["personEmpty"] == EMPTY_SENTENCE
