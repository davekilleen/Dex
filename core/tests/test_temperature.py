from __future__ import annotations

from datetime import date, datetime, timezone

from core.entity_engine.temperature import classify_temperature

NOW = date(2026, 7, 23)


def touch(
    ts: str,
    *,
    touch_type: str = "meeting",
    direction: str = "none",
    source_id: str | None = None,
) -> dict:
    return {
        "ts": ts,
        "type": touch_type,
        "direction": direction,
        "source": {"id": source_id or f"source-{ts}"},
    }


def test_zero_touches_are_excluded_not_cold():
    result = classify_temperature([], entity_type="person", now=NOW)

    assert result["temperature"] is None
    assert result["touch_count"] == 0
    assert result["engagement_count"] == 0
    assert result["last_touch"] is None
    assert result["last_engagement"] is None


def test_recent_engagement_is_warm():
    result = classify_temperature(
        [touch("2026-07-15")],
        entity_type="person",
        now=NOW,
    )

    assert result["temperature"] == "warm"
    assert result["days_since_engagement"] == 8


def test_aging_engagement_is_cooling():
    result = classify_temperature(
        [touch("2026-06-23")],
        entity_type="person",
        now=NOW,
    )

    assert result["temperature"] == "cooling"
    assert result["days_since_engagement"] == 30


def test_recent_outbound_only_contact_is_cooling():
    result = classify_temperature(
        [
            touch(
                "2026-07-20",
                touch_type="mention",
                direction="out",
            )
        ],
        entity_type="person",
        now=NOW,
    )

    assert result["temperature"] == "cooling"
    assert result["last_engagement"] is None
    assert result["days_since_touch"] == 3


def test_old_engagement_is_cold():
    result = classify_temperature(
        [touch("2026-05-01")],
        entity_type="person",
        now=NOW,
    )

    assert result["temperature"] == "cold"


def test_monthly_cadence_extends_cold_threshold_but_not_indefinitely():
    touches = [
        touch("2026-03-24", source_id="monthly-1"),
        touch("2026-04-23", source_id="monthly-2"),
        touch("2026-05-23", source_id="monthly-3"),
    ]

    at_twenty_days = classify_temperature(
        touches,
        entity_type="person",
        now=date(2026, 6, 12),
    )
    at_one_hundred_days = classify_temperature(
        touches,
        entity_type="person",
        now=date(2026, 8, 31),
    )

    assert at_twenty_days["temperature"] == "cooling"
    assert at_twenty_days["cadence_days"] == 30
    assert at_one_hundred_days["temperature"] == "cold"


def test_company_stays_warm_longer_than_person():
    touches = [touch("2026-07-03")]

    person = classify_temperature(touches, entity_type="person", now=NOW)
    company = classify_temperature(touches, entity_type="company", now=NOW)
    unknown = classify_temperature(touches, entity_type="project", now=NOW)

    assert person["temperature"] == "cooling"
    assert company["temperature"] == "warm"
    assert unknown["temperature"] == person["temperature"]


def test_classification_is_invariant_to_touch_order():
    touches = [
        touch("2026-06-01", source_id="meeting-1"),
        touch(
            "2026-06-20",
            touch_type="mention",
            direction="out",
            source_id="mention-1",
        ),
        touch("2026-05-01", source_id="meeting-0"),
        touch("2026-07-01", source_id="meeting-2"),
    ]
    now = datetime(2026, 7, 23, 15, 30, tzinfo=timezone.utc)

    forward = classify_temperature(touches, entity_type="person", now=now)
    reversed_result = classify_temperature(
        list(reversed(touches)),
        entity_type="person",
        now=now,
    )

    assert reversed_result == forward
