"""Behavioral coverage for the self-contained Dex Dashboard renderer."""

from __future__ import annotations

import importlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RENDER_SCRIPT = REPO_ROOT / "core" / "dashboard" / "render.py"
NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


def _renderer():
    return importlib.import_module("core.dashboard.render")


def _data() -> dict:
    return {
        "meta": {
            "generated_at": "2026-07-27T12:00:00Z",
            "vault_path": "/tmp/private",
            "collector_version": "1",
        },
        "profile": {
            "status": "configured",
            "name": "Alex <Admin>",
            "role": "Product & Strategy",
            "company": "Example Co",
            "communication": {
                "formality": "professional_casual",
                "directness": "very_direct",
                "detail_level": "concise",
            },
        },
        "pillars": [
            {
                "id": "trust",
                "name": "Customer <trust>",
                "description": "Make it dependable.",
            }
        ],
        "integrations": {
            "apps": {
                "Google": {"enabled": False},
                "Slack & Co": {"enabled": True},
            },
            "enabled_count": 1,
        },
        "usage": {"counts": {"available": 4, "used": 2}},
        "analytics": {"total": 7},
        "tasks": {"total": 18, "completed": 12, "completed_last_7_days": 3},
        "people": {"total": 8, "internal": 2, "external": 6},
        "companies": {"total": 0},
        "meetings": {"total": 4, "last_7_days": 2, "last_30_days": 4},
        "projects": {"total": 0},
        "health": {
            "label": "cached dex-doctor check",
            "status": "fresh",
            "generated_at": "2026-07-26T10:00:00Z",
            "mode": "quick",
            "checks": [
                {"id": "vault.configs", "feature": "Vault <configuration>", "verdict": "OK"},
                {"id": "calendar", "feature": "Calendar", "verdict": "OFF"},
                {"id": "search", "feature": "Search", "verdict": "UNKNOWN"},
                {"id": "hooks", "feature": "Hooks", "verdict": "BROKEN"},
            ],
            "summary": {"ok": 1, "off": 1, "unknown": 1, "broken": 1},
        },
        "skills": {
            "available": ["daily-plan", "meeting-prep", "week-plan"],
            "used": ["daily-plan", "meeting-prep"],
            "unused": ["week-plan"],
            "ratings": {},
        },
    }


def _observations() -> dict:
    return {
        "observations": [
            "You completed **3 tasks** with `<care>` [inside Dex](#state).",
            "<script>alert('observation')</script>",
        ],
        "suggestion": {
            "title": "Try <weekly planning>",
            "why": "It connects your pillars & current work.",
            "try_prompt": 'Plan my week around "Customer trust" <today>.',
        },
    }


def _journey_data() -> dict:
    return {
        "counts": {"available": 3, "used": 1},
        "groups": [
            {
                "id": "rituals",
                "name": "Rituals",
                "skills": [
                    {
                        "id": "daily-plan",
                        "name": "Daily plan",
                        "description": "Plan today.",
                        "state": "used",
                    },
                    {
                        "id": "week-review",
                        "name": "Week review",
                        "description": "Look back.",
                        "state": "unused",
                    },
                    {
                        "id": "career-coach",
                        "name": "Career coach",
                        "description": "Available in the Career pack.",
                        "state": "available-in-pack",
                    },
                ],
            }
        ],
    }


def _history_data() -> dict:
    return {
        "history": [
            {
                "ts": "2026-07-20T12:00:00Z",
                "counts": {"tasks_done": 99, "meetings": 49, "people": 49},
            },
            {
                "ts": "2026-07-27T12:00:00Z",
                "counts": {"tasks_done": 100, "meetings": 50, "people": 50},
            },
        ],
        "trends": {
            "meetings": [0, 1],
            "tasks": [0, 1],
            "snapshots": [1, 1],
        },
        "milestones": [{"label": "100 completed tasks"}],
        "looking_back": "A steadier week.",
    }


def test_html_is_self_contained_heydex_styled_and_escapes_user_data() -> None:
    render = _renderer()

    page = render.render_dashboard_html(
        _data(),
        _observations(),
        archive_count=7,
        archived=True,
    )

    assert page.startswith("<!doctype html>")
    assert "--bg:#0D0E12" in page
    assert "--accent:#FF4081" in page
    assert "max-width: 1020px" in page
    assert "'Inter','Geist',system-ui,-apple-system,sans-serif" in page
    assert "6.8rem" not in page
    assert "#62d7d1" not in page
    assert "<script src=" not in page
    assert "<link " not in page
    assert "<img " not in page
    assert re.search(r"""(?:src|href)=["']https?://""", page, re.IGNORECASE) is None
    assert page.index('id="receipt"') < page.index('id="observations"')
    assert page.index('id="observations"') < page.index('id="suggestion"')
    assert page.index('id="suggestion"') < page.index('id="state"')
    assert "Your Dex" in page
    assert "Alex &lt;Admin&gt;" in page
    assert "Monday, July 27, 2026" in page
    assert "2 meetings turned into notes this week" in page
    assert "3 tasks completed this week" in page
    assert "12 completed tasks in Dex" in page
    assert "0 companies" not in page
    assert "<strong>3 tasks</strong>" in page
    assert "<code>&lt;care&gt;</code>" in page
    assert '<a href="#state">inside Dex</a>' in page
    assert "&lt;script&gt;alert(&#x27;observation&#x27;)&lt;/script&gt;" in page
    assert "<script>alert('observation')</script>" not in page
    assert "Try &lt;weekly planning&gt;" in page
    assert "Plan my week around &quot;Customer trust&quot; &lt;today&gt;." in page
    assert "navigator.clipboard" in page
    assert "document.execCommand('copy')" in page
    assert "Slack &amp; Co" in page
    assert "connected" in page
    assert "not set up" in page
    assert "needs attention" in page
    assert "broken" not in page.lower()
    assert "Generated locally by Dex · nothing leaves your machine" in page
    assert "snapshot #7 saved" in page


def test_tab_nav_and_panels_render_in_app_order_with_overview_visible() -> None:
    render = _renderer()

    page = render.render_dashboard_html(
        _data(),
        _observations(),
        journey=_journey_data(),
        history_data=_history_data(),
        server_ctx={
            "token": "__DEX_DASHBOARD_TOKEN__",
            "port": "__DEX_DASHBOARD_PORT__",
        },
    )

    tab_labels = ["Overview", "Journey", "Settings", "History"]
    for tab_name in (label.lower() for label in tab_labels):
        assert (f'<button type="button" role="tab" id="tab-{tab_name}" data-tab-target="{tab_name}"') in page
        assert f'data-tab="{tab_name}"' in page

    positions = [page.index(f">{label}</button>") for label in tab_labels]
    assert positions == sorted(positions)
    assert (
        '<section class="tab-panel" id="panel-overview" data-tab="overview" '
        'role="tabpanel" aria-labelledby="tab-overview">'
    ) in page
    for tab_name in ("journey", "settings", "history"):
        assert (
            f'<section class="tab-panel" id="panel-{tab_name}" data-tab="{tab_name}" '
            f'role="tabpanel" aria-labelledby="tab-{tab_name}" hidden>'
        ) in page
    assert 'id="tab-overview" data-tab-target="overview" aria-selected="true"' in page
    assert 'id="tab-journey" data-tab-target="journey" aria-selected="false"' in page
    assert "window.location.hash" in page
    assert "ArrowRight" in page
    assert "ArrowLeft" in page
    assert "#62d7d1" not in page


def test_static_page_keeps_read_only_settings_without_server_placeholders() -> None:
    render = _renderer()

    page = render.render_dashboard_html(_data(), _observations())

    assert "__DEX_DASHBOARD_TOKEN__" not in page
    assert "__DEX_DASHBOARD_PORT__" not in page
    assert 'data-tab="settings"' in page
    assert 'id="state"' in page
    assert "Open with 'let me change my settings' to make these live." in page
    assert "data-setting-id" not in page
    assert "dashboard-port" not in page


def test_journey_collapses_after_twelve_chips_used_first_and_expands_inline() -> None:
    render = _renderer()
    skills = [
        {
            "id": f"unused-{index}",
            "name": f"Unused {index}",
            "state": "unused",
        }
        for index in range(1, 11)
    ] + [
        {
            "id": f"used-{index}",
            "name": f"Used {index}",
            "state": "used",
        }
        for index in range(1, 6)
    ]
    journey = {
        "counts": {"available": 15, "used": 5},
        "groups": [
            {
                "id": "personal",
                "name": "Personal tools",
                "yours": True,
                "skills": skills,
            }
        ],
    }

    page = render.render_dashboard_html(_data(), journey=journey)

    assert "<h3>Yours</h3>" in page
    assert page.index("Used 1") < page.index("Unused 1")
    assert page.count("data-journey-extra hidden") == 3
    assert ('<button type="button" class="journey-more" data-journey-expand aria-expanded="false"') in page
    assert "+ 3 more" in page
    assert "extra.hidden = false" in page


def test_journey_receives_skill_picks_from_observations() -> None:
    render = _renderer()

    page = render.render_dashboard_html(
        _data(),
        {
            "skill_picks": [
                {
                    "skill": "week-plan",
                    "why": "Your open priorities need a weekly reset.",
                }
            ]
        },
        journey=_journey_data(),
    )

    assert "Picked for you" in page
    assert "week-plan" in page
    assert "Your open priorities need a weekly reset." in page
    assert 'data-skill-copy-target="skill-pick-prompt-0"' in page


def test_history_tab_has_a_quiet_first_snapshot_empty_state() -> None:
    render = _renderer()

    page = render.render_dashboard_html(_data(), history_data=None)

    assert 'id="history"' in page
    assert "Your first snapshot was saved today — this tab fills in as you come back." in page


def test_live_settings_are_grouped_without_changing_wire_placeholders() -> None:
    render = _renderer()
    settings_section = importlib.import_module("core.dashboard.sections.settings")

    page = render.render_dashboard_html(
        _data(),
        server_ctx={
            "token": "__DEX_DASHBOARD_TOKEN__",
            "port": "__DEX_DASHBOARD_PORT__",
        },
    )

    settings = page[page.index('id="settings"') : page.index('id="history"')]
    for label in ("Privacy", "Communication", "Capabilities", "Meetings", "Journaling", "Connections"):
        assert f'<h3 class="settings-group-label">{label}</h3>' in settings
    assert settings.index("Anonymous product analytics") < settings.index("Communication")
    assert settings.index("Formality") < settings.index("Connections")
    assert settings.index("Existing integrations") < settings.index("Set up something new")
    assert settings.index("New people and companies") > settings.index("Meetings")
    assert page.count("__DEX_DASHBOARD_TOKEN__") == 1
    assert page.count("__DEX_DASHBOARD_PORT__") == 1


def test_new_section_fragments_have_css_for_every_emitted_class() -> None:
    render = _renderer()
    journey_section = importlib.import_module("core.dashboard.sections.journey")
    history_section = importlib.import_module("core.dashboard.sections.history")
    settings_section = importlib.import_module("core.dashboard.sections.settings")
    settings_fragment, settings_script = settings_section.render(
        _data(),
        {"token": "__DEX_DASHBOARD_TOKEN__", "port": "__DEX_DASHBOARD_PORT__"},
    )
    fragments = [
        journey_section.render_journey(_journey_data()),
        history_section.render_history(_history_data()),
        settings_fragment,
    ]

    page = render.render_dashboard_html(
        _data(),
        _observations(),
        journey=_journey_data(),
        history_data=_history_data(),
        server_ctx={
            "token": "__DEX_DASHBOARD_TOKEN__",
            "port": "__DEX_DASHBOARD_PORT__",
        },
    )
    style = re.search(r"<style>(?P<style>.*?)</style>", page, re.DOTALL)
    assert style is not None
    emitted_classes = {
        css_class
        for fragment in fragments
        for class_value in re.findall(r'class="([^"]+)"', fragment)
        for css_class in class_value.split()
    }
    emitted_classes.update(re.findall(r"className = '([^']+)'", settings_script))

    missing = sorted(
        css_class
        for css_class in emitted_classes
        if re.search(rf"\.{re.escape(css_class)}(?![\w-])", style.group("style")) is None
    )
    assert missing == []


def test_markdown_links_allow_safe_urls_and_reject_javascript() -> None:
    render = _renderer()
    observations = {"observations": ["[Guide](https://example.test/guide) and [unsafe](javascript:alert(1))"]}

    page = render.render_dashboard_html(_data(), observations, archived=False)

    assert '<a href="https://example.test/guide"' in page
    assert 'href="javascript:' not in page
    assert "unsafe (javascript:alert(1))" in page


def test_missing_observations_and_stale_health_degrade_honestly() -> None:
    render = _renderer()
    data = _data()
    data["health"] = {
        "label": "cached dex-doctor check",
        "status": "stale",
        "guidance": "run /dex-doctor for a fresh checkup",
    }

    page = render.render_dashboard_html(data, {}, archived=False)

    assert "Open this from a Dex session to get Dex&#x27;s observations." in page
    assert 'id="suggestion"' not in page
    assert "Run /dex-doctor for a fresh checkup." in page
    assert "snapshot not saved" in page


def test_render_appends_one_compact_snapshot_and_reports_its_number(tmp_path: Path) -> None:
    render = _renderer()
    vault = tmp_path / "vault"
    vault.mkdir()
    output = tmp_path / "dashboard.html"

    result = render.render_dashboard(
        vault,
        _data(),
        _observations(),
        output,
        archive=True,
        now=NOW,
    )

    history = vault / "System" / ".dex" / "dashboard" / "history.jsonl"
    assert result == {"output": str(output), "archived": True, "archive_count": 1}
    assert output.is_file()
    assert history.is_file()
    lines = history.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    snapshot = json.loads(lines[0])
    assert snapshot == {
        "ts": "2026-07-27T12:00:00Z",
        "counts": {
            "tasks_done": 12,
            "people": 8,
            "meetings": 4,
            "skills_used": 2,
            "integrations_on": 1,
        },
        "observations": [
            "You completed **3 tasks** with `<care>` [inside Dex](#state).",
            "<script>alert('observation')</script>",
        ],
        "suggestion_title": "Try <weekly planning>",
    }
    assert "profile" not in snapshot
    assert "analytics" not in snapshot
    assert "snapshot #1 saved" in output.read_text(encoding="utf-8")


def test_render_builds_journey_and_history_after_appending_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    render = _renderer()
    vault = tmp_path / "vault"
    skill = vault / ".claude" / "skills" / "daily-plan" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: Daily plan\ndescription: Plan today.\ncategory: Rituals\n---\n",
        encoding="utf-8",
    )
    history = vault / "System" / ".dex" / "dashboard" / "history.jsonl"
    history.parent.mkdir(parents=True)
    history.write_text(
        json.dumps(
            {
                "ts": "2026-07-20T12:00:00Z",
                "counts": {
                    "tasks_done": 99,
                    "people": 49,
                    "meetings": 49,
                    "skills_used": 0,
                    "integrations_on": 0,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    data = _data()
    data["tasks"]["completed"] = 100
    data["people"]["total"] = 50
    data["meetings"]["total"] = 50
    data["meta"]["vault_age"] = {"age_days": 180}
    observations = _observations() | {"looking_back": "A steadier week."}
    output = tmp_path / "dashboard.html"
    detected = {}
    real_detect_milestones = render.dashboard_history.detect_milestones

    def record_milestones(prev_counts, new_counts, vault_age):
        detected.update(
            {
                "prev_counts": prev_counts,
                "new_counts": new_counts,
                "vault_age": vault_age,
            }
        )
        return real_detect_milestones(prev_counts, new_counts, vault_age)

    monkeypatch.setattr(
        render.dashboard_history,
        "detect_milestones",
        record_milestones,
    )

    render.render_dashboard(
        vault,
        data,
        observations,
        output,
        archive=True,
        now=NOW,
    )

    page = output.read_text(encoding="utf-8")
    assert history.read_text(encoding="utf-8").count("\n") == 2
    assert detected == {
        "prev_counts": {
            "tasks_done": 99,
            "people": 49,
            "meetings": 49,
            "skills_used": 0,
            "integrations_on": 0,
        },
        "new_counts": {
            "tasks_done": 100,
            "people": 50,
            "meetings": 50,
            "skills_used": 2,
            "integrations_on": 1,
        },
        "vault_age": 180,
    }
    assert 'id="journey"' in page
    assert "Daily plan" in page
    assert 'id="history"' in page
    assert "Six months with Dex" in page
    assert "A steadier week." in page
    assert page.count("<svg") == 3


def test_render_omits_derived_sections_when_their_builders_fail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    render = _renderer()
    vault = tmp_path / "vault"
    vault.mkdir()
    output = tmp_path / "dashboard.html"

    def fail(*_args, **_kwargs):
        raise RuntimeError("simulated optional-section failure")

    monkeypatch.setattr(render.dashboard_journey, "build_journey", fail)
    monkeypatch.setattr(render.dashboard_history, "load_history", fail)

    render.render_dashboard(
        vault,
        _data(),
        _observations(),
        output,
        archive=False,
        now=NOW,
    )

    page = output.read_text(encoding="utf-8")
    assert 'id="journey"' in page
    assert "No capabilities are installed in this Dex yet." in page
    assert 'id="history"' in page
    assert "Your first snapshot was saved today — this tab fills in as you come back." in page


def test_no_archive_writes_only_the_requested_html(tmp_path: Path) -> None:
    render = _renderer()
    vault = tmp_path / "vault"
    vault.mkdir()
    output = tmp_path / "preview.html"

    result = render.render_dashboard(
        vault,
        _data(),
        {},
        output,
        archive=False,
        now=NOW,
    )

    assert result == {"output": str(output), "archived": False, "archive_count": 0}
    assert output.is_file()
    assert not (vault / "System" / ".dex" / "dashboard").exists()
    assert "snapshot not saved" in output.read_text(encoding="utf-8")


def test_render_cli_works_without_observations_and_no_archive(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    data_path = tmp_path / "collected.json"
    data_path.write_text(json.dumps(_data()), encoding="utf-8")
    output = tmp_path / "dashboard.html"

    completed = subprocess.run(
        [
            sys.executable,
            str(RENDER_SCRIPT),
            "--vault",
            str(vault),
            "--data",
            str(data_path),
            "--out",
            str(output),
            "--no-archive",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == str(output)
    assert "Open this from a Dex session" in output.read_text(encoding="utf-8")
    assert not (vault / "System" / ".dex" / "dashboard").exists()


def test_render_cli_with_settings_writes_each_server_placeholder_once(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    data_path = tmp_path / "collected.json"
    data_path.write_text(json.dumps(_data()), encoding="utf-8")
    output = tmp_path / "dashboard.html"

    completed = subprocess.run(
        [
            sys.executable,
            str(RENDER_SCRIPT),
            "--vault",
            str(vault),
            "--data",
            str(data_path),
            "--out",
            str(output),
            "--no-archive",
            "--with-settings",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    page = output.read_text(encoding="utf-8")
    assert 'id="settings"' in page
    assert page.count("__DEX_DASHBOARD_TOKEN__") == 1
    assert page.count("__DEX_DASHBOARD_PORT__") == 1


def test_render_cli_rejects_invalid_json_without_a_traceback(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    data_path = tmp_path / "invalid.json"
    data_path.write_text("{invalid", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(RENDER_SCRIPT),
            "--vault",
            str(vault),
            "--data",
            str(data_path),
            "--out",
            str(tmp_path / "dashboard.html"),
            "--no-archive",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "could not read dashboard input" in completed.stderr.lower()
    assert "traceback" not in completed.stderr.lower()
