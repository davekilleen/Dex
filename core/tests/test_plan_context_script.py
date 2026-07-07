import importlib.util
from pathlib import Path


def load_module():
    path = Path(__file__).resolve().parents[1] / ".." / ".scripts" / "plan-context.py"
    spec = importlib.util.spec_from_file_location("plan_context", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_context_collects_local_planning_signals(tmp_path: Path):
    module = load_module()

    (tmp_path / "Planning").mkdir()
    (tmp_path / ".scripts" / "salesforce-data").mkdir(parents=True)

    (tmp_path / "Planning" / "Tasks.md").write_text(
        "# Tasks\n\n## This Week\n- [ ] Follow up on Acme quote\n- [x] Close old task\n",
        encoding="utf-8",
    )
    (tmp_path / "Planning" / "Week_Priorities.md").write_text(
        "# Week Priorities\n\n## Top Priorities\n1. Close Acme deal\n2. Ship proposal\n",
        encoding="utf-8",
    )
    (tmp_path / "Planning" / "Quarter_Goals.md").write_text(
        "# Quarter Goals\n\n- Grow account base\n",
        encoding="utf-8",
    )
    (tmp_path / ".scripts" / "salesforce-data" / "opportunities.json").write_text(
        "[{\"Name\": \"Acme Renewal\", \"StageName\": \"Negotiation\", \"Amount\": 120000, \"CloseDate\": \"2026-07-10\", \"IsClosed\": false}]",
        encoding="utf-8",
    )
    (tmp_path / ".scripts" / "salesforce-data" / "case_snapshot.json").write_text(
        "[{\"CaseNumber\": \"00001234\", \"Subject\": \"Need help\", \"Status\": \"Working\", \"Priority\": \"High\"}]",
        encoding="utf-8",
    )

    context = module.build_context(tmp_path, mode="weekly")

    assert context["mode"] == "weekly"
    assert context["top_priorities"][0] == "Close Acme deal"
    assert context["tasks"][0]["title"] == "Follow up on Acme quote"
    assert context["pipeline"][0]["name"] == "Acme Renewal"
    assert context["service_cases"][0]["case_number"] == "00001234"
