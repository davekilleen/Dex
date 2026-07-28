"""Render the dashboard's read-only capability journey map."""

from __future__ import annotations

import html
from typing import Any

_CHIP_CLASS = {
    "used": "lit",
    "unused": "dim",
    "available-in-pack": "outlined",
}
_STATE_ORDER = {
    "used": 0,
    "unused": 1,
    "available-in-pack": 2,
}
_VISIBLE_CHIPS = 12


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _number(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _chip(skill: dict[str, Any], *, hidden: bool = False) -> str:
    state = str(skill.get("state") or "")
    css_class = _CHIP_CLASS.get(state, "dim")
    name = html.escape(
        str(skill.get("name") or skill.get("id") or "Unnamed capability"),
        quote=True,
    )
    description = html.escape(str(skill.get("description") or ""), quote=True)
    label = html.escape(
        f"{skill.get('name') or skill.get('id') or 'Unnamed capability'}: {state.replace('-', ' ') or 'unused'}",
        quote=True,
    )
    title = f' title="{description}"' if description else ""
    extra = " data-journey-extra hidden" if hidden else ""
    return f'<li class="journey-chip {css_class}"{title} aria-label="{label}"{extra}>{name}</li>'


def _territory(group: dict[str, Any], index: int) -> str:
    raw_name = "Yours" if group.get("yours") is True else group.get("name") or "Other"
    if raw_name == raw_name.lower():
        raw_name = raw_name.replace("_", " ").title()
    name = html.escape(str(raw_name), quote=True)
    skills = [skill for skill in _list(group.get("skills")) if isinstance(skill, dict)]
    ordered = [
        skill
        for _, skill in sorted(
            enumerate(skills),
            key=lambda item: (
                _STATE_ORDER.get(str(item[1].get("state") or ""), 1),
                item[0],
            ),
        )
    ]
    chips = "".join(_chip(skill, hidden=skill_index >= _VISIBLE_CHIPS) for skill_index, skill in enumerate(ordered))
    remaining = max(0, len(ordered) - _VISIBLE_CHIPS)
    group_id = f"journey-group-{index}"
    more = ""
    if remaining:
        more = f"""
          <li class="journey-more-item">
            <button type="button" class="journey-more" data-journey-expand aria-expanded="false"
              aria-controls="{group_id}">+ {remaining} more</button>
          </li>"""
    return f"""
      <div class="state-panel territory">
        <h3>{name}</h3>
        <ul class="journey-chips" id="{group_id}">{chips}{more}</ul>
      </div>"""


def _skill_picks(value: Any) -> str:
    picks = [
        pick
        for pick in _list(value)
        if isinstance(pick, dict) and str(pick.get("skill") or "").strip()
    ][:5]
    if not picks:
        return ""

    cards = []
    for index, pick in enumerate(picks):
        skill = str(pick.get("skill") or "").strip()
        why = str(pick.get("why") or "").strip()
        skill_text = html.escape(skill, quote=True)
        why_text = html.escape(why, quote=True)
        prompt = html.escape(f"/{skill}", quote=True)
        cards.append(
            f"""
          <article class="journey-pick-card">
            <span class="journey-pick-skill">{skill_text}</span>
            <p>{why_text}</p>
            <div class="journey-pick-actions">
              <code class="journey-pick-prompt" id="skill-pick-prompt-{index}" hidden>{prompt}</code>
              <button type="button" class="journey-pick-copy" id="copy-skill-pick-{index}"
                data-skill-copy-target="skill-pick-prompt-{index}"
                data-skill-copy-status="skill-pick-status-{index}" aria-label="Copy /{skill_text}">Copy</button>
              <span class="journey-pick-copy-status" id="skill-pick-status-{index}" aria-live="polite"></span>
            </div>
          </article>"""
        )
    return f"""
      <div class="journey-picks" aria-labelledby="journey-picks-heading">
        <h3 id="journey-picks-heading">Picked for you</h3>
        <div class="journey-picks-grid">{"".join(cards)}</div>
      </div>"""


def render_journey(journey: dict, picks: list[dict[str, Any]] | None = None) -> str:
    """Render a Nightfall-styled HTML fragment for one capability journey."""
    source = _mapping(journey)
    counts = _mapping(source.get("counts"))
    available = _number(counts.get("available"))
    used = min(_number(counts.get("used")), available)
    capabilities_word = "capability" if used == 1 else "capabilities"
    groups = [group for group in _list(source.get("groups")) if isinstance(group, dict)]
    body = "".join(_territory(group, index) for index, group in enumerate(groups))
    skill_picks = _skill_picks(picks)
    if not body:
        body = '<p class="quiet">No capabilities are installed in this Dex yet.</p>'
    return f"""
    <section id="journey" aria-labelledby="journey-heading">
      <div class="section-heading">
        <p class="kicker">Your journey</p>
        <h2 id="journey-heading">Your Dex, growing with you</h2>
        <p class="quiet">{used} {capabilities_word} in your rotation · {available} available to explore.</p>
      </div>
      {skill_picks}
      <div class="state-grid journey-grid">{body}</div>
    </section>"""
