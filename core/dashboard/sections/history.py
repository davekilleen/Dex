"""Nightfall HTML fragment for the Dex Dashboard's local history."""

from __future__ import annotations

import html
from typing import Any

from core.dashboard.history import sparkline_svg, weekly_trends


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _entries(history_data: Any) -> list[dict[str, Any]]:
    source = _mapping(history_data)
    entries = source.get("history", source.get("entries", []))
    return [entry for entry in _list(entries) if isinstance(entry, dict)]


def _looking_back(history_data: Any) -> str:
    source = _mapping(history_data)
    value = source.get("looking_back")
    if not isinstance(value, str):
        value = _mapping(source.get("observations")).get("looking_back")
    return value.strip() if isinstance(value, str) else ""


def _trends(history_data: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, list[Any]]:
    supplied = _mapping(history_data.get("trends"))
    if all(isinstance(supplied.get(key), list) for key in ("meetings", "tasks", "snapshots")):
        return supplied
    trend_input = dict(history_data)
    trend_input["history"] = entries
    return weekly_trends(trend_input)


def _milestone(history_data: Any) -> dict[str, Any]:
    source = _mapping(history_data)
    candidates = source.get("milestones", source.get("milestone", []))
    if isinstance(candidates, dict):
        candidates = [candidates]
    for candidate in _list(candidates):
        value = _mapping(candidate)
        label = value.get("label")
        if isinstance(label, str) and label.strip():
            return value
    return {}


def _chart(title: str, values: list[Any]) -> str:
    sparkline = sparkline_svg(values, width=220, height=42).replace(
        'stroke="#62d7d1"',
        'stroke="currentColor"',
    )
    return f"""
        <div class="state-panel history-chart">
          <h3>{title}</h3>
          {sparkline}
        </div>"""


def render_history(history_data: dict[str, Any]) -> str:
    """Render the optional history section; an empty history remains invisible."""
    entries = _entries(history_data)
    if not entries:
        return ""
    source = _mapping(history_data)
    first_snapshot = len(entries) == 1
    trend_cards = ""
    if not first_snapshot:
        trends = _trends(source, entries)
        trend_cards = f"""
        <div class="receipt-grid history-trends">
          {_chart("Meetings / week", _list(trends.get("meetings")))}
          {_chart("Tasks completed / week", _list(trends.get("tasks")))}
          {_chart("Snapshots over time", _list(trends.get("snapshots")))}
        </div>"""
    first_note = '<p class="quiet">This is your first snapshot.</p>' if first_snapshot else ""
    milestone = _milestone(source)
    milestone_card = ""
    if milestone:
        milestone_card = f"""
        <div class="suggestion history-milestone" aria-label="Milestone">
          <p class="kicker">✦ Milestone</p>
          <h3>{html.escape(str(milestone["label"]), quote=True)}</h3>
        </div>"""
    looking_back = _looking_back(source)
    looking_back_card = ""
    if looking_back:
        looking_back_card = f"""
        <div class="state-panel prose history-looking-back">
          <h3>Looking back</h3>
          <p>{html.escape(looking_back, quote=True)}</p>
        </div>"""
    return f"""
    <section id="history" aria-labelledby="history-heading">
      <div class="section-heading">
        <p class="kicker">Looking back</p>
        <h2 id="history-heading">The shape of your Dex</h2>
      </div>
      {first_note}
      {trend_cards}
      {milestone_card}
      {looking_back_card}
    </section>"""
