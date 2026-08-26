"""Freshness must be a fact about the ledger, never an opinion about the assistant.

The failure these guard against: a long session where a calendar read from four
hours ago and one from a minute ago carry identical authority, so the stale one
gets used and nothing says otherwise.
"""
from __future__ import annotations

import time

import pytest

from core.utils import freshness

CONFIG = """
sources:
  clock: {half_life: 5m}
  calendar: {half_life: 30m}
  email: {half_life: 30m}
  tasks: {half_life: 4h}
  week_priorities: {half_life: 2d}
  user_corrections: {half_life: never}
artefacts:
  daily-plan: {requires_fresh: [clock, calendar, email, tasks, week_priorities]}
"""


def _vault(tmp_path, config: str = CONFIG):
    (tmp_path / "System").mkdir(parents=True, exist_ok=True)
    (tmp_path / "System" / "knowledge-half-life.yaml").write_text(config, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("45s", 45), ("30m", 1800), ("4h", 14400), ("2d", 172800), ("1.5h", 5400)],
)
def test_durations_parse(text, seconds):
    assert freshness.parse_duration(text) == seconds


def test_never_is_not_a_duration_but_a_declaration():
    assert freshness.parse_duration("never") is None


def test_a_typo_in_a_half_life_fails_loudly(tmp_path):
    """Silently becoming "fresh forever" is the worst possible reading of a typo."""
    with pytest.raises(ValueError):
        freshness.parse_duration("30 minutes")

    vault = _vault(tmp_path, "sources:\n  calendar: {half_life: soon}\n")
    with pytest.raises(freshness.HalfLifeUnavailable):
        freshness.load_config(vault)


def test_a_missing_config_is_unavailable_not_all_fresh(tmp_path):
    """Not being able to judge freshness must not read as everything being fine."""
    with pytest.raises(freshness.HalfLifeUnavailable):
        freshness.load_config(tmp_path)


def test_an_artefact_requiring_an_unknown_source_refuses_to_load(tmp_path):
    """Such a contract could never be satisfied, and would fail invisibly."""
    vault = _vault(
        tmp_path,
        "sources:\n  calendar: {half_life: 30m}\nartefacts:\n  x: {requires_fresh: [calendar, ghost]}\n",
    )
    with pytest.raises(freshness.HalfLifeUnavailable, match="ghost"):
        freshness.load_config(vault)


def test_a_source_never_observed_is_not_fresh(tmp_path):
    vault = _vault(tmp_path)
    config = freshness.load_config(vault)

    assert freshness.is_fresh(config, vault, "calendar") is False
    assert freshness.age_seconds(vault, "calendar") is None


def test_observation_makes_a_source_fresh_and_time_takes_it_away(tmp_path):
    vault = _vault(tmp_path)
    config = freshness.load_config(vault)
    now = time.time()

    freshness.observe(vault, "calendar", at=now)
    assert freshness.is_fresh(config, vault, "calendar", now=now + 60) is True

    # 30-minute half-life: 31 minutes later it is not.
    assert freshness.is_fresh(config, vault, "calendar", now=now + 1860) is False


def test_a_source_that_does_not_decay_is_always_fresh(tmp_path):
    """Corrections and decisions are superseded, not aged out."""
    vault = _vault(tmp_path)
    config = freshness.load_config(vault)

    assert freshness.is_fresh(config, vault, "user_corrections", now=time.time() + 10**7) is True


def test_an_unknown_source_gets_the_cautious_answer(tmp_path):
    vault = _vault(tmp_path)
    config = freshness.load_config(vault)

    assert freshness.is_fresh(config, vault, "astrology") is False


def test_missing_for_names_exactly_what_the_artefact_lacks(tmp_path):
    vault = _vault(tmp_path)
    config = freshness.load_config(vault)
    now = time.time()

    freshness.observe(vault, "calendar", at=now)
    freshness.observe(vault, "tasks", at=now)
    freshness.observe(vault, "email", at=now - 4 * 3600)  # stale

    missing = freshness.missing_for(config, vault, "daily-plan", now=now)

    assert set(missing) == {"clock", "email", "week_priorities"}


def test_an_artefact_with_no_contract_requires_nothing(tmp_path):
    """Not every output needs a contract; inventing one is worse than having none."""
    vault = _vault(tmp_path)
    config = freshness.load_config(vault)

    assert freshness.missing_for(config, vault, "some-other-skill") == ()


def test_report_distinguishes_stale_from_never_observed(tmp_path):
    """"Old" and "never looked" call for different responses from a reader."""
    vault = _vault(tmp_path)
    config = freshness.load_config(vault)
    now = time.time()
    freshness.observe(vault, "email", at=now - 4 * 3600)

    rows = {r["source"]: r["state"] for r in freshness.report(config, vault, "daily-plan", now=now)["sources"]}

    assert rows["email"] == "STALE"
    assert rows["calendar"] == "NOT OBSERVED"


def test_a_corrupt_ledger_reads_as_no_observations(tmp_path):
    """A damaged ledger must not make everything look freshly observed."""
    vault = _vault(tmp_path)
    ledger = vault / "System" / ".dex"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "observations.json").write_text("{not json", encoding="utf-8")

    assert freshness.read_ledger(vault) == {}


def test_observing_never_raises_even_when_the_ledger_cannot_be_written(tmp_path):
    """Losing an observation is survivable. Failing a tool call over one is not."""
    vault = _vault(tmp_path)
    (vault / "System" / ".dex").mkdir(parents=True, exist_ok=True)
    (vault / "System" / ".dex" / "observations.json").mkdir()

    freshness.observe(vault, "calendar")  # must not raise
