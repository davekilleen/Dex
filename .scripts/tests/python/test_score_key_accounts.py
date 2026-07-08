"""Tests for the H2 key-account scoring rubric (.scripts/customer-intel/score-key-accounts.py).

The tier assignment here decides which accounts get weekly attention vs a
quarterly touch — a scoring regression silently reshuffles the territory plan.
"""

import json
from datetime import date, timedelta

from conftest import load_tool_module

ska = load_tool_module("score_key_accounts", "customer-intel/score-key-accounts.py")


def _blank_account(**overrides):
    a = {
        "id": "001A", "name": "Acme Corp", "city": "York", "state": "PA",
        "last_activity": None, "open_weighted": 0.0, "open_amount": 0.0,
        "open_opps": [], "won_count": 0, "last_won": None,
        "total_opp_count": 0, "equipment": [], "expiry": [],
    }
    a.update(overrides)
    return a


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_norm_name_strips_corporate_noise():
    assert ska.norm_name("The ACME Manufacturing Co., Inc.") == "acme"
    assert ska.norm_name("Gwynedd Mfg & Industries, LLC") == "gwynedd"
    assert ska.norm_name(None) == ""
    # Same suffix/punctuation variants join to the same key
    assert ska.norm_name("Acme Corp.") == ska.norm_name("ACME corporation")
    # Dotted initials join their undotted form (single-letter runs merge)
    assert ska.norm_name("J.R. Steel Corp") == "jr steel"
    assert ska.norm_name("J.R. Steel Corp") == ska.norm_name("JR Steel Corp")
    assert ska.norm_name("A. B. C. Welding") == ska.norm_name("ABC Welding")
    # Merging is per-run: letters attached to real words stay separate
    assert ska.norm_name("Steel R Us") == "steel r us"


def test_lifecycle_low_matches_machine_families():
    assert ska.lifecycle_low("Fiber Laser") == 10
    assert ska.lifecycle_low("CO2 Laser cutting system") == 8
    assert ska.lifecycle_low("Press Brake") == 15
    assert ska.lifecycle_low("Mystery Machine") == 12  # generic default
    assert ska.lifecycle_low(None) == 12


def test_scale_clamps_to_weight():
    assert ska.scale(-5, 0, 10, 25) == 0.0
    assert ska.scale(5, 0, 10, 25) == 12.5
    assert ska.scale(50, 0, 10, 25) == 25.0
    assert ska.scale(1, 5, 5, 25) == 0.0  # degenerate range


# ---------------------------------------------------------------------------
# Scoring + tiers
# ---------------------------------------------------------------------------


def test_open_opportunity_forces_tier_1():
    a = _blank_account(
        open_opps=[{"name": "New laser", "stage": "Quoting", "amount": 100000.0,
                    "vendor": None, "next_step": None}],
        open_amount=100000.0,
        open_weighted=55000.0,
    )
    scored = ska.score_account(a)
    assert scored["tier"] == 1
    assert scored["pipe"] > 0
    assert any("open" in r for r in scored["reasons"])


def test_imminent_lease_expiry_without_open_opp_is_tier_2():
    a = _blank_account(expiry=[("TRUMPF laser", 60)])
    scored = ska.score_account(a)
    assert scored["tier"] == 2
    assert scored["urgency"] == 35  # CRITICAL bucket = full replacement weight
    assert scored["replacement_signal"] is True
    assert any("CRITICAL" in r for r in scored["reasons"])


def test_historic_buyer_without_open_opp_is_tier_2():
    a = _blank_account(won_count=3, last_won=date.today() - timedelta(days=400))
    scored = ska.score_account(a)
    assert scored["tier"] == 2
    assert scored["historic"] > 0


def test_no_signal_is_tier_3():
    scored = ska.score_account(_blank_account())
    assert scored["tier"] == 3
    assert scored["score"] == 0.0


def test_aged_equipment_contributes_replacement_urgency():
    # 18-year-old press brake vs 15-year lifecycle low -> 3 yrs past window
    a = _blank_account(equipment=[("Cincinnati Press Brake", 18.0, False)])
    scored = ska.score_account(a)
    assert scored["urgency"] > 0
    assert any("past replacement window" in r for r in scored["reasons"])


def test_competitor_equipment_scores_displacement_not_urgency():
    a = _blank_account(equipment=[("Bystronic laser", 10.0, True)])
    scored = ska.score_account(a)
    assert scored["comp"] > 0
    assert scored["urgency"] == 0.0  # competitor gear never counts as owned aging


def test_next_action_matches_tier():
    t1 = ska.score_account(_blank_account(
        open_opps=[{"name": "x", "stage": "Negotiation", "amount": 1.0, "vendor": None, "next_step": None}],
        open_amount=1.0, open_weighted=1.0))
    assert "Close push" in ska.next_action(t1)

    t2 = ska.score_account(_blank_account(expiry=[("laser", 60)]))
    assert "Replacement discovery" in ska.next_action(t2)

    t3 = ska.score_account(_blank_account())
    assert "relationship touch" in ska.next_action(t3)


# ---------------------------------------------------------------------------
# Source loading + report rendering
# ---------------------------------------------------------------------------


def test_build_joins_sources_and_render_produces_report(tmp_path, monkeypatch):
    sf_dir = tmp_path / "salesforce-data"
    eda_dir = tmp_path / "eda-data"
    sf_dir.mkdir()
    eda_dir.mkdir()

    (sf_dir / "accounts.json").write_text(json.dumps([
        {"Id": "001A", "Name": "Acme Manufacturing Inc", "BillingCity": "York", "BillingState": "PA"},
        {"Id": "001B", "Name": "Globex LLC"},
    ]))
    (sf_dir / "opportunities.json").write_text(json.dumps([
        {"AccountId": "001A", "StageName": "Quoting", "Amount": 150000.0,
         "IsWon": False, "IsClosed": False, "Name": "Laser upgrade"},
        {"AccountId": "001A", "StageName": "Closed Won", "Amount": 90000.0,
         "IsWon": True, "IsClosed": True, "CloseDate": "2024-05-01", "Name": "Old deal"},
        {"AccountId": "IGNORED", "StageName": "Quoting", "Amount": 1.0,
         "IsWon": False, "IsClosed": False, "Name": "Not ours"},
    ]))
    # EDA report joins by normalized name ("Acme Manufacturing Inc" -> "acme")
    (eda_dir / "plasma-eda-report-2026-06-26.json").write_text(json.dumps({
        "assets": [{
            "account": "ACME Mfg, Inc.", "machine_type": "Plasma",
            "builder": "Hypertherm", "model": "XPR300",
            "install_date": "2012-01-15", "is_competitor": True,
            "days_to_expiry": 120,
        }]
    }))

    monkeypatch.setattr(ska, "SF_DIR", sf_dir)
    monkeypatch.setattr(ska, "EDA_DIR", eda_dir)

    acct = ska.build()

    assert set(acct) == {"001A", "001B"}
    acme = acct["001A"]
    assert acme["total_opp_count"] == 2
    assert acme["won_count"] == 1
    assert acme["open_amount"] == 150000.0
    assert acme["expiry"] == [("Hypertherm XPR300 Plasma", 120)]
    assert len(acme["equipment"]) == 1

    scored = [ska.score_account(a) for a in acct.values()]
    report = ska.render(scored, top=10)
    assert "# Key Accounts — H2 2026" in report
    assert "Acme Manufacturing Inc" in report
    assert "Tier 1 — Work Weekly" in report
    # Globex has zero signal and must not be ranked
    assert "Globex" not in report.split("## Score Components")[0]
