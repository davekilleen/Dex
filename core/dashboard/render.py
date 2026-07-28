#!/usr/bin/env python3
"""Render one offline Dex Dashboard page and optionally archive a compact snapshot."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.dashboard import history as dashboard_history
from core.dashboard import journey as dashboard_journey
from core.dashboard.sections.history import render_history
from core.dashboard.sections.journey import render_journey
from core.dashboard.sections.settings import render as render_settings
from core.dashboard.server import PORT_PLACEHOLDER, TOKEN_PLACEHOLDER
from core.paths import DEX_RUNTIME_DIR, VAULT_ROOT

INLINE_MARKDOWN = re.compile(
    r"`(?P<code>[^`\n]+)`"
    r"|\[(?P<label>[^\]\n]+)\]\((?P<url>[^)\n]+)\)"
    r"|\*\*(?P<strong>[^*\n]+)\*\*"
)


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_href(value: str) -> str | None:
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return url
    if parsed.scheme == "mailto" and parsed.path:
        return url
    if not parsed.scheme and url.startswith(("#", "/", "./", "../")):
        return url
    return None


def _inline_markdown(value: str) -> str:
    output = []
    cursor = 0
    for match in INLINE_MARKDOWN.finditer(value):
        output.append(_escape(value[cursor : match.start()]))
        if match.group("code") is not None:
            output.append(f"<code>{_escape(match.group('code'))}</code>")
        elif match.group("strong") is not None:
            output.append(f"<strong>{_escape(match.group('strong'))}</strong>")
        else:
            label = _escape(match.group("label"))
            raw_url = match.group("url")
            href = _safe_href(raw_url)
            if href is None:
                output.append(f"{label} ({_escape(raw_url)})")
            else:
                rel = ' rel="noreferrer"' if urlparse(href).scheme in {"http", "https"} else ""
                output.append(f'<a href="{_escape(href)}"{rel}>{label}</a>')
        cursor = match.end()
    output.append(_escape(value[cursor:]))
    return "".join(output)


def _markdown(value: str) -> str:
    paragraphs = []
    for part in re.split(r"\n\s*\n", value.strip()):
        if not part:
            continue
        paragraphs.append(f"<p>{_inline_markdown(part).replace(chr(10), '<br>')}</p>")
    return "".join(paragraphs)


def _number(section: Any, key: str) -> int:
    value = _mapping(section).get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return singular if count == 1 else (plural or f"{singular}s")


def _receipt_lines(data: dict[str, Any]) -> tuple[list[str], list[str]]:
    meetings_week = _number(data.get("meetings"), "last_7_days")
    tasks_week = _number(data.get("tasks"), "completed_last_7_days")
    meetings_total = _number(data.get("meetings"), "total")
    tasks_done = _number(data.get("tasks"), "completed")
    people = _number(data.get("people"), "total")
    skills_used = len([name for name in _list(_mapping(data.get("skills")).get("used")) if isinstance(name, str)])
    weekly = []
    if meetings_week:
        weekly.append(f"{meetings_week} {_plural(meetings_week, 'meeting')} turned into notes this week")
    if tasks_week:
        weekly.append(f"{tasks_week} {_plural(tasks_week, 'task')} completed this week")
    all_time = []
    if meetings_total:
        all_time.append(f"{meetings_total} {_plural(meetings_total, 'meeting note')} in Dex")
    if tasks_done:
        all_time.append(f"{tasks_done} completed {_plural(tasks_done, 'task')} in Dex")
    if people:
        all_time.append(f"{people} {_plural(people, 'person', 'people')} in Dex")
    if skills_used:
        all_time.append(f"{skills_used} {_plural(skills_used, 'skill')} used")
    return weekly, all_time


def _render_receipt(data: dict[str, Any]) -> str:
    weekly, all_time = _receipt_lines(data)
    groups = []
    if weekly:
        groups.append(
            '<div class="receipt-group"><h3>This week</h3>'
            + "".join(f"<p>{_escape(line)}</p>" for line in weekly)
            + "</div>"
        )
    if all_time:
        groups.append(
            '<div class="receipt-group"><h3>All time</h3>'
            + "".join(f"<p>{_escape(line)}</p>" for line in all_time)
            + "</div>"
        )
    body = "".join(groups)
    if not body:
        body = '<p class="quiet">Your value receipt will grow as you use Dex.</p>'
    return f"""
    <section id="receipt" aria-labelledby="receipt-heading">
      <div class="section-heading">
        <p class="kicker">Value receipt</p>
        <h2 id="receipt-heading">What Dex has held onto for you</h2>
      </div>
      <div class="receipt-grid">{body}</div>
    </section>"""


def _observation_strings(observations: Any) -> list[str]:
    return [
        item for item in _list(_mapping(observations).get("observations")) if isinstance(item, str) and item.strip()
    ]


def _render_observations(observations: Any) -> str:
    items = _observation_strings(observations)
    if items:
        body = "".join(f'<div class="observation">{_markdown(item)}</div>' for item in items)
    else:
        body = '<p class="quiet">Open this from a Dex session to get Dex&#x27;s observations.</p>'
    return f"""
    <section id="observations" aria-labelledby="observations-heading">
      <div class="section-heading">
        <p class="kicker">A view from Dex</p>
        <h2 id="observations-heading">What stands out</h2>
      </div>
      <div class="prose">{body}</div>
    </section>"""


def _suggestion(observations: Any) -> dict[str, str]:
    raw = _mapping(_mapping(observations).get("suggestion"))
    return {key: str(raw.get(key) or "").strip() for key in ("title", "why", "try_prompt")}


def _render_suggestion(observations: Any) -> str:
    suggestion = _suggestion(observations)
    if not any(suggestion.values()):
        return ""
    title = suggestion["title"] or "A useful next step"
    why = f'<p class="suggestion-why">{_escape(suggestion["why"])}</p>' if suggestion["why"] else ""
    prompt = ""
    if suggestion["try_prompt"]:
        prompt = f"""
        <div class="try-block">
          <div class="try-label">Try it</div>
          <pre id="tryPrompt"><code>{_escape(suggestion["try_prompt"])}</code></pre>
          <button type="button" id="copyPrompt">Copy prompt</button>
          <span class="copy-status" id="copyStatus" aria-live="polite"></span>
        </div>"""
    return f"""
    <section id="suggestion" class="suggestion" aria-labelledby="suggestion-heading">
      <p class="kicker">One next step</p>
      <h2 id="suggestion-heading">{_escape(title)}</h2>
      {why}
      {prompt}
    </section>"""


def _pretty_setting(value: Any) -> str:
    return str(value).replace("_", " ").strip()


def _render_profile_state(data: dict[str, Any]) -> str:
    profile = _mapping(data.get("profile"))
    role = str(profile.get("role") or "").strip()
    communication = _mapping(profile.get("communication"))
    communication_parts = [
        _pretty_setting(communication[key])
        for key in ("formality", "directness", "detail_level")
        if communication.get(key) not in (None, "")
    ]
    pillars = [
        str(item.get("name") or "").strip()
        for item in _list(data.get("pillars"))
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    rows = []
    if role:
        rows.append(f"<div><dt>Role</dt><dd>{_escape(role)}</dd></div>")
    if pillars:
        rows.append(f"<div><dt>Pillars</dt><dd>{_escape(', '.join(pillars))}</dd></div>")
    if communication_parts:
        rows.append(f"<div><dt>Communication style</dt><dd>{_escape(', '.join(communication_parts))}</dd></div>")
    if not rows:
        return '<p class="quiet">Your role and preferences are not configured yet.</p>'
    return f'<dl class="state-list">{"".join(rows)}</dl>'


def _render_integrations(data: dict[str, Any]) -> str:
    apps = _mapping(_mapping(data.get("integrations")).get("apps"))
    rows = []
    for name, raw in sorted(apps.items(), key=lambda item: str(item[0]).casefold()):
        enabled = bool(_mapping(raw).get("enabled"))
        state = "connected" if enabled else "not set up"
        css = "on" if enabled else "off"
        rows.append(
            "<li>"
            f'<span class="dot dot-{css}" aria-hidden="true"></span>'
            f'<span class="integration-name">{_escape(name)}</span>'
            f'<span class="integration-state">{state}</span>'
            "</li>"
        )
    if not rows:
        return '<p class="quiet">No integration setup is recorded.</p>'
    return f'<ul class="integration-list">{"".join(rows)}</ul>'


def _health_label(verdict: str) -> tuple[str, str]:
    return {
        "OK": ("good", "looking good"),
        "OFF": ("off", "not set up"),
        "UNKNOWN": ("unknown", "unknown"),
        "BROKEN": ("attention", "needs attention"),
    }.get(verdict.upper(), ("unknown", "unknown"))


def _render_health(data: dict[str, Any]) -> str:
    health = _mapping(data.get("health"))
    status = str(health.get("status") or "unknown")
    if status != "fresh":
        return '<p class="quiet health-guidance">Run /dex-doctor for a fresh checkup.</p>'
    rows = []
    for check in _list(health.get("checks")):
        if not isinstance(check, dict):
            continue
        css, label = _health_label(str(check.get("verdict") or "UNKNOWN"))
        feature = str(check.get("feature") or check.get("id") or "Unknown check")
        rows.append(
            "<li>"
            f'<span class="dot dot-{css}" aria-hidden="true"></span>'
            f'<span class="health-name">{_escape(feature)}</span>'
            f'<span class="health-state">{label}</span>'
            "</li>"
        )
    if not rows:
        return '<p class="quiet">The cached checkup has no individual checks to show.</p>'
    return f'<ul class="health-list">{"".join(rows)}</ul>'


def _render_state(data: dict[str, Any]) -> str:
    return f"""
    <section id="state" aria-labelledby="state-heading">
      <div class="section-heading">
        <p class="kicker">Configuration</p>
        <h2 id="state-heading">State of your Dex</h2>
      </div>
      <div class="state-grid">
        <div class="state-panel">
          <h3>You</h3>
          {_render_profile_state(data)}
        </div>
        <div class="state-panel">
          <h3>Integrations</h3>
          {_render_integrations(data)}
        </div>
      </div>
      <div class="health-panel">
        <div>
          <h3>Latest Dex checkup</h3>
          <p class="health-note">This reflects the last saved /dex-doctor check, not a new scan.</p>
        </div>
        {_render_health(data)}
      </div>
    </section>"""


def _display_date(data: dict[str, Any]) -> str:
    raw = _mapping(data.get("meta")).get("generated_at")
    if not isinstance(raw, str):
        return "Date unavailable"
    try:
        generated = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return "Date unavailable"
    return f"{generated:%A, %B} {generated.day}, {generated.year}"


def _render_empty_history() -> str:
    return """
    <section id="history" aria-labelledby="history-heading">
      <div class="section-heading">
        <p class="kicker">Looking back</p>
        <h2 id="history-heading">The shape of your Dex</h2>
      </div>
      <p class="quiet history-empty">
        Your first snapshot was saved today — this tab fills in as you come back.
      </p>
    </section>"""


def render_dashboard_html(
    data: dict[str, Any],
    observations: dict[str, Any] | None = None,
    *,
    archive_count: int = 0,
    archived: bool = False,
    journey: dict[str, Any] | None = None,
    history_data: dict[str, Any] | None = None,
    server_ctx: dict[str, Any] | None = None,
) -> str:
    """Render escaped data into one self-contained, tabbed Dex app."""
    observations = observations or {}
    profile = _mapping(data.get("profile"))
    name = str(profile.get("name") or "").strip()
    identity = f'<span class="user-name">for {_escape(name)}</span>' if name else ""
    archive_note = f"snapshot #{archive_count} saved" if archived else "snapshot not saved"
    suggestion = _render_suggestion(observations)
    journey_section = render_journey(journey or {}, picks=observations.get("skill_picks"))
    history_section = render_history(history_data or {}) or _render_empty_history()
    server_meta = ""
    settings_script = ""
    if server_ctx:
        settings_section, settings_script = render_settings(data, server_ctx)
        server_meta = f'\n  <meta name="dashboard-port" content="{_escape(server_ctx.get("port", ""))}">'
    else:
        settings_section = f"""
    <section id="settings" aria-labelledby="settings-heading">
      <div class="section-heading">
        <p class="kicker">Settings</p>
        <h2 id="settings-heading">The shape of your Dex</h2>
        <p class="quiet settings-readonly-note">
          Open with 'let me change my settings' to make these live.
        </p>
      </div>
      {_render_state(data)}
    </section>"""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">{server_meta}
  <title>Your Dex</title>
  <style>
    :root{{--bg:#0D0E12;--surface:#15161C;--elevated:#1C1D25;--line:#24262E;
      --line2:#32343F;--fg:#E4E5E7;--fg2:#9B9DA6;--fg3:#787B87;--inv:#111111;
      --accent:#FF4081;--accent-dim:rgba(255,64,129,0.72);
      --accent-bg:rgba(255,64,129,0.12);
      --mono:'Geist Mono','JetBrains Mono',ui-monospace,monospace;
      --sans:'Inter','Geist',system-ui,-apple-system,sans-serif;color-scheme:dark}}
    * {{ box-sizing: border-box; }}
    [hidden] {{ display: none !important; }}
    html {{ min-height: 100%; background: var(--bg); }}
    body {{
      min-height: 100vh;
      margin: 0;
      background: var(--bg);
      color: var(--fg);
      font: 15px/1.6 var(--sans);
      -webkit-font-smoothing: antialiased;
      text-rendering: optimizeLegibility;
    }}
    body::before {{
      content: "";
      position: fixed;
      z-index: 0;
      inset: 0;
      pointer-events: none;
      background: radial-gradient(
        880px 560px at 80% -10%,
        rgba(255,64,129,0.06),
        transparent 60%
      );
    }}
    .topbar {{
      position: sticky;
      z-index: 10;
      top: 0;
      border-bottom: 1px solid var(--line);
      background: rgba(13,14,18,.92);
      backdrop-filter: blur(14px);
    }}
    .nav-shell {{
      display: grid;
      max-width: 1020px;
      min-height: 56px;
      margin: 0 auto;
      padding: 0 20px;
      grid-template-columns: auto 1fr;
      align-items: center;
      gap: 28px;
    }}
    .wordmark {{
      color: var(--fg);
      font-size: 21px;
      font-weight: 600;
      letter-spacing: -.04em;
    }}
    .wordmark-dot {{ color: var(--accent); }}
    .tab-list {{
      display: flex;
      justify-content: flex-end;
      gap: 4px;
      overflow-x: auto;
      scrollbar-width: none;
    }}
    .tab-list::-webkit-scrollbar {{ display: none; }}
    button {{
      border: 1px solid var(--line2);
      border-radius: 3px;
      background: transparent;
      color: var(--fg);
      padding: 8px 12px;
      font: 500 13px/1.25 var(--sans);
      cursor: pointer;
      transition: border-color .15s ease, background .15s ease, color .15s ease;
    }}
    button:hover {{ border-color: var(--accent); }}
    button:focus-visible {{
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }}
    .tab-list button {{
      border-color: transparent;
      color: var(--fg2);
      white-space: nowrap;
    }}
    .tab-list button:hover {{ color: var(--fg); }}
    .tab-list button[aria-selected="true"] {{
      border-color: var(--line2);
      background: var(--elevated);
      color: var(--fg);
    }}
    main {{
      position: relative;
      z-index: 1;
      max-width: 1020px;
      margin: 0 auto;
      padding: 0 20px;
    }}
    .tab-panel {{
      min-height: calc(100vh - 136px);
      padding: 42px 0 48px;
      border: 0;
    }}
    .tab-panel > section:first-child {{ padding-top: 0; border-top: 0; }}
    .overview-intro + section {{ border-top: 0; }}
    .overview-intro {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 24px;
      padding: 0 0 30px;
      border-bottom: 1px solid var(--line);
    }}
    .greeting-line {{
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 8px;
    }}
    h1, h2, h3, h4, p {{ overflow-wrap: anywhere; }}
    h1, h2, h3, h4 {{
      font-weight: 500;
      letter-spacing: -.01em;
    }}
    h1 {{ margin: 0; font-size: clamp(26px,3.2vw,36px); line-height: 1.16; }}
    h2 {{ margin: 0; font-size: clamp(24px,3vw,34px); line-height: 1.18; }}
    h3, h4 {{ margin: 0; }}
    h3 {{ font-size: 14px; }}
    h4 {{ color: var(--fg2); font-size: 13px; }}
    .user-name {{ color: var(--fg2); font-size: 16px; }}
    .generated-date {{ margin: 0; color: var(--fg3); font: 12px/1.5 var(--mono); }}
    section {{
      padding: 42px 0;
      border-top: 1px solid var(--line);
    }}
    .section-heading {{ max-width: 650px; margin-bottom: 22px; }}
    .kicker, .settings-group-label {{
      margin: 0 0 7px;
      color: var(--accent);
      font: 500 11px/1.4 var(--mono);
      letter-spacing: .06em;
      text-transform: uppercase;
    }}
    .quiet, .health-note {{ color: var(--fg2); }}
    .receipt-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .receipt-group, .observation, .state-panel, .health-panel {{
      border: 1px solid var(--line);
      border-radius: 9px;
      background: var(--surface);
      padding: 22px 24px;
    }}
    .receipt-group h3 {{
      margin-bottom: 12px;
      color: var(--fg3);
      font: 500 11px/1.4 var(--mono);
      letter-spacing: .06em;
      text-transform: uppercase;
    }}
    .receipt-group p {{ margin: 4px 0; color: var(--fg); font-size: 15px; }}
    .prose {{ display: grid; max-width: 760px; gap: 10px; }}
    .observation {{ color: var(--fg2); }}
    .observation p {{ margin: 0; }}
    strong {{ color: var(--fg); font-weight: 600; }}
    code {{
      padding: 2px 5px;
      border: 1px solid var(--line2);
      border-radius: 3px;
      background: var(--elevated);
      color: var(--fg);
      font: .9em/1.4 var(--mono);
    }}
    a {{ color: var(--accent); text-underline-offset: 3px; }}
    .suggestion {{
      margin: 0;
      padding: 24px;
      border: 1px solid var(--accent-dim);
      border-radius: 9px;
      background: var(--accent-bg);
    }}
    .suggestion-why {{ max-width: 680px; margin: 8px 0 0; color: var(--fg2); }}
    .try-block {{
      position: relative;
      margin-top: 18px;
      padding: 16px;
      border: 1px solid var(--line2);
      border-radius: 8px;
      background: var(--bg);
    }}
    .try-label {{
      margin-bottom: 6px;
      color: var(--accent);
      font: 500 11px/1.4 var(--mono);
      letter-spacing: .06em;
      text-transform: uppercase;
    }}
    pre {{ margin: 0; padding-right: 112px; white-space: pre-wrap; overflow-wrap: anywhere; }}
    pre code {{ padding: 0; border: 0; background: transparent; color: var(--fg); }}
    #copyPrompt {{
      position: absolute;
      top: 12px;
      right: 12px;
      border-color: transparent;
      background: var(--accent);
      color: var(--inv);
    }}
    #copyPrompt:hover {{ background: #ff6ea2; }}
    .copy-status {{
      position: absolute;
      right: 15px;
      bottom: 5px;
      color: var(--fg3);
      font: 11px/1.4 var(--mono);
    }}
    .state-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .state-panel h3, .health-panel h3 {{
      margin-bottom: 12px;
      color: var(--fg2);
    }}
    .state-list {{ margin: 0; }}
    .state-list div {{
      padding: 9px 0;
      border-bottom: 1px solid var(--line);
    }}
    .state-list div:last-child {{ border-bottom: 0; }}
    dt {{ color: var(--fg3); font: 11px/1.4 var(--mono); }}
    dd {{ margin: 2px 0 0; }}
    .integration-list, .health-list {{
      margin: 0;
      padding: 0;
      list-style: none;
    }}
    .integration-list li, .health-list li {{
      display: grid;
      padding: 5px 0;
      grid-template-columns: auto 1fr auto;
      align-items: center;
      gap: 9px;
    }}
    .integration-state, .health-state {{ color: var(--fg2); font-size: 13px; }}
    .dot {{
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--fg3);
    }}
    .dot-on, .dot-good {{ background: var(--accent); }}
    .dot-attention {{ background: var(--accent-dim); }}
    .dot-off, .dot-unknown {{ background: var(--fg3); }}
    .health-panel {{
      display: grid;
      margin-top: 12px;
      grid-template-columns: minmax(180px,.75fr) minmax(260px,1.25fr);
      gap: 24px;
      background: var(--elevated);
    }}
    .health-note, .health-guidance {{ margin: 0; font-size: 12px; }}
    .journey-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      align-items: start;
      gap: 12px;
    }}
    .journey-picks {{ margin: 0 0 20px; }}
    .journey-picks h3 {{ margin: 0 0 10px; color: var(--fg); }}
    .journey-picks-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 12px;
    }}
    .journey-pick-card {{
      display: flex;
      min-width: 0;
      min-height: 146px;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 9px;
      flex-direction: column;
      align-items: flex-start;
      background: var(--surface);
    }}
    .journey-pick-skill {{
      padding: 4px 7px;
      border: 1px solid var(--accent-dim);
      border-radius: 3px;
      background: var(--accent-bg);
      color: var(--accent);
      font: 12px/1.35 var(--mono);
      overflow-wrap: anywhere;
    }}
    .journey-pick-card p {{ margin: 10px 0 14px; color: var(--fg2); font-size: 13px; }}
    .journey-pick-actions {{
      display: flex;
      width: 100%;
      min-height: 29px;
      margin-top: auto;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }}
    .journey-pick-copy {{
      padding: 5px 9px;
      border-color: var(--line2);
      color: var(--fg2);
      font: 12px/1.2 var(--mono);
    }}
    .journey-pick-copy:hover {{ border-color: var(--accent); color: var(--accent); }}
    .journey-pick-prompt {{ display: none; }}
    .journey-pick-copy-status {{ color: var(--fg3); font: 11px/1.4 var(--mono); }}
    .territory {{ min-width: 0; }}
    .journey-chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin: 0;
      padding: 0;
      list-style: none;
    }}
    .journey-chip, .journey-more {{
      border: 1px solid var(--line);
      border-radius: 3px;
      background: var(--surface);
      padding: 5px 8px;
      font: 12px/1.35 var(--mono);
    }}
    .journey-chip.lit {{
      border-color: var(--accent-dim);
      background: var(--accent-bg);
      color: var(--fg);
    }}
    .journey-chip.dim {{ color: var(--fg3); }}
    .journey-chip.outlined {{
      border-color: var(--line2);
      border-style: dashed;
      color: var(--fg3);
    }}
    .journey-more {{
      color: var(--fg2);
      border-color: var(--line2);
    }}
    .journey-more:hover {{ color: var(--accent); }}
    .history-trends {{ margin-bottom: 12px; gap: 12px; }}
    .history-chart svg {{ display: block; width: 100%; height: auto; color: var(--accent); }}
    .history-chart polyline {{ stroke: var(--accent); }}
    .history-milestone {{ margin: 12px 0; }}
    .history-milestone h3 {{ margin: 0; color: var(--fg); }}
    .history-looking-back {{ margin-top: 12px; }}
    .history-looking-back p, .history-empty {{ margin: 0; }}
    .settings-readonly-note {{ margin: 8px 0 0; }}
    #settings > #state {{
      padding-bottom: 0;
      border-top: 0;
    }}
    #settings > #state > .section-heading {{ display: none; }}
    .settings-group {{ margin-top: 30px; }}
    .section-heading + .settings-group {{ margin-top: 0; }}
    .settings-group-label {{ margin-bottom: 9px; }}
    .settings-list {{
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 9px;
      background: var(--surface);
    }}
    .setting-row {{
      display: grid;
      padding: 15px 17px;
      border-bottom: 1px solid var(--line);
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
      gap: 20px;
    }}
    .setting-row:last-child {{ border-bottom: 0; }}
    .setting-row-readonly {{ grid-template-columns: 1fr; }}
    .setting-copy {{ min-width: 0; }}
    .setting-copy label, .setting-label {{
      display: block;
      color: var(--fg);
      font-size: 14px;
      font-weight: 500;
    }}
    .setting-copy p {{ margin: 2px 0 0; color: var(--fg2); font-size: 12px; }}
    .setting-action {{
      display: flex;
      min-width: 136px;
      flex-direction: column;
      align-items: flex-end;
      gap: 4px;
    }}
    .setting-action input[role="switch"] {{
      appearance: none;
      position: relative;
      width: 38px;
      height: 21px;
      margin: 0;
      border: 1px solid var(--line2);
      border-radius: 11px;
      background: var(--elevated);
      cursor: pointer;
      transition: background .15s ease, border-color .15s ease;
    }}
    .setting-action input[role="switch"]::after {{
      content: "";
      position: absolute;
      top: 3px;
      left: 3px;
      width: 13px;
      height: 13px;
      border-radius: 50%;
      background: var(--fg3);
      transition: transform .15s ease, background .15s ease;
    }}
    .setting-action input[role="switch"]:checked {{
      border-color: var(--accent);
      background: var(--accent);
    }}
    .setting-action input[role="switch"]:checked::after {{
      background: var(--inv);
      transform: translateX(17px);
    }}
    .setting-action input[role="switch"]:focus-visible,
    .setting-action select:focus-visible {{
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }}
    .setting-action input:disabled, .setting-action select:disabled {{
      cursor: not-allowed;
      opacity: .48;
    }}
    .setting-action select {{
      min-width: 168px;
      max-width: 240px;
      border: 1px solid var(--line2);
      border-radius: 3px;
      background: var(--elevated);
      color: var(--fg);
      padding: 7px 28px 7px 9px;
      font: 12px/1.4 var(--mono);
    }}
    .setting-status {{
      min-height: 16px;
      color: var(--fg2);
      font: 10px/1.4 var(--mono);
      text-align: right;
    }}
    .settings-subsection {{ margin-top: 16px; }}
    .settings-subsection h4 {{ margin-bottom: 8px; }}
    .handoff-button {{
      display: flex;
      width: 100%;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      border-color: var(--line2);
      background: transparent;
      padding: 11px 13px;
      text-align: left;
    }}
    .handoff-button span {{ color: var(--fg2); font-size: 11px; font-weight: 400; }}
    .handoff-status {{
      display: block;
      min-height: 18px;
      margin-top: 6px;
      color: var(--fg2);
      font: 11px/1.4 var(--mono);
    }}
    .undo-button {{
      margin-left: 2px;
      border: 0;
      color: var(--accent);
      padding: 0;
      font: inherit;
      text-decoration: underline;
      text-underline-offset: 2px;
    }}
    footer {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 8px 16px;
      padding: 20px 0 28px;
      border-top: 1px solid var(--line);
      color: var(--fg3);
      font: 11px/1.5 var(--mono);
    }}
    @media (max-width: 700px) {{
      .nav-shell {{ padding: 0 14px; gap: 12px; }}
      .tab-list {{ justify-content: flex-start; }}
      main {{ padding-inline: 14px; }}
      .tab-panel {{ padding-top: 30px; }}
      .overview-intro {{ align-items: flex-start; flex-direction: column; gap: 8px; }}
      .receipt-grid, .state-grid, .journey-grid {{ grid-template-columns: 1fr; }}
      .health-panel {{ grid-template-columns: 1fr; }}
      .setting-row {{ grid-template-columns: 1fr; }}
      .setting-action {{ min-width: 0; align-items: flex-start; }}
      .setting-status {{ text-align: left; }}
      .handoff-button {{ align-items: flex-start; flex-direction: column; }}
      pre {{ padding: 42px 0 0; }}
    }}
  </style>
</head>
<body>
  <nav class="topbar" aria-label="Dashboard">
    <div class="nav-shell">
      <span class="wordmark" aria-label="Dex">dex<span class="wordmark-dot">.</span></span>
      <div class="tab-list" role="tablist" aria-label="Dashboard sections">
        <button type="button" role="tab" id="tab-overview" data-tab-target="overview" aria-selected="true" aria-controls="panel-overview">Overview</button>
        <button type="button" role="tab" id="tab-journey" data-tab-target="journey" aria-selected="false" aria-controls="panel-journey" tabindex="-1">Journey</button>
        <button type="button" role="tab" id="tab-settings" data-tab-target="settings" aria-selected="false" aria-controls="panel-settings" tabindex="-1">Settings</button>
        <button type="button" role="tab" id="tab-history" data-tab-target="history" aria-selected="false" aria-controls="panel-history" tabindex="-1">History</button>
      </div>
    </div>
  </nav>
  <main>
    <section class="tab-panel" id="panel-overview" data-tab="overview" role="tabpanel" aria-labelledby="tab-overview">
      <header class="overview-intro">
        <div>
          <p class="kicker">Local overview</p>
          <div class="greeting-line"><h1>Your Dex</h1>{identity}</div>
        </div>
        <p class="generated-date">{_escape(_display_date(data))}</p>
      </header>
      {_render_receipt(data)}
      {_render_observations(observations)}
      {suggestion}
    </section>
    <section class="tab-panel" id="panel-journey" data-tab="journey" role="tabpanel" aria-labelledby="tab-journey" hidden>
      {journey_section}
    </section>
    <section class="tab-panel" id="panel-settings" data-tab="settings" role="tabpanel" aria-labelledby="tab-settings" hidden>
      {settings_section}
    </section>
    <section class="tab-panel" id="panel-history" data-tab="history" role="tabpanel" aria-labelledby="tab-history" hidden>
      {history_section}
    </section>
    <footer>
      <span>Generated locally by Dex · nothing leaves your machine</span>
      <span>{_escape(archive_note)}</span>
    </footer>
  </main>
  <script>
    (() => {{
      const tabs = Array.from(document.querySelectorAll('[role="tab"][data-tab-target]'));
      const panels = Array.from(document.querySelectorAll('.tab-panel[data-tab]'));
      const validTabs = new Set(tabs.map((tab) => tab.dataset.tabTarget));

      function activateTab(name, focusTab = false) {{
        const activeName = validTabs.has(name) ? name : 'overview';
        tabs.forEach((tab) => {{
          const active = tab.dataset.tabTarget === activeName;
          tab.setAttribute('aria-selected', String(active));
          tab.tabIndex = active ? 0 : -1;
          if (active && focusTab) tab.focus();
        }});
        panels.forEach((panel) => {{
          panel.hidden = panel.dataset.tab !== activeName;
        }});
      }}

      tabs.forEach((tab, index) => {{
        tab.addEventListener('click', () => {{
          const name = tab.dataset.tabTarget;
          activateTab(name);
          if (window.location.hash !== '#' + name) window.location.hash = name;
        }});
        tab.addEventListener('keydown', (event) => {{
          let nextIndex = null;
          if (event.key === 'ArrowRight') nextIndex = (index + 1) % tabs.length;
          if (event.key === 'ArrowLeft') nextIndex = (index - 1 + tabs.length) % tabs.length;
          if (event.key === 'Home') nextIndex = 0;
          if (event.key === 'End') nextIndex = tabs.length - 1;
          if (nextIndex === null) return;
          event.preventDefault();
          const nextName = tabs[nextIndex].dataset.tabTarget;
          activateTab(nextName, true);
          if (window.location.hash !== '#' + nextName) window.location.hash = nextName;
        }});
      }});

      window.addEventListener('hashchange', () => {{
        activateTab(window.location.hash.slice(1));
      }});
      activateTab(window.location.hash.slice(1));
    }})();
    (() => {{
      document.querySelectorAll('[data-journey-expand]').forEach((button) => {{
        button.addEventListener('click', () => {{
          const group = button.closest('.journey-chips');
          if (!group) return;
          group.querySelectorAll('[data-journey-extra]').forEach((extra) => {{
            extra.hidden = false;
          }});
          button.setAttribute('aria-expanded', 'true');
          button.closest('.journey-more-item').hidden = true;
        }});
      }});
    }})();
    (() => {{
      const wireCopy = (button, prompt, status) => {{
      if (!button || !prompt) return;
      const markCopied = () => {{
        if (status) status.textContent = 'Copied';
        window.setTimeout(() => {{ if (status) status.textContent = ''; }}, 1600);
      }};
      button.addEventListener('click', async () => {{
        const text = prompt.textContent || '';
        try {{
          if (!navigator.clipboard) throw new Error('clipboard unavailable');
          await navigator.clipboard.writeText(text);
          markCopied();
        }} catch (_) {{
          const range = document.createRange();
          range.selectNodeContents(prompt);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          document.execCommand('copy');
          selection.removeAllRanges();
          markCopied();
        }}
      }});
      }};

      wireCopy(
        document.getElementById('copyPrompt'),
        document.getElementById('tryPrompt'),
        document.getElementById('copyStatus'),
      );
      document.querySelectorAll('[data-skill-copy-target]').forEach((button) => {{
        const prompt = document.getElementById(button.dataset.skillCopyTarget);
        const status = document.getElementById(button.dataset.skillCopyStatus);
        wireCopy(button, prompt, status);
      }});
    }})();
    {settings_script}
  </script>
</body>
</html>
"""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _history_path(vault: Path) -> Path:
    return vault / DEX_RUNTIME_DIR.relative_to(VAULT_ROOT) / "dashboard" / "history.jsonl"


def _history_count(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(bool(line.strip()) for line in path.read_text(encoding="utf-8", errors="replace").splitlines())


def _snapshot(data: dict[str, Any], observations: dict[str, Any], now: datetime) -> dict[str, Any]:
    integrations = _mapping(data.get("integrations"))
    integrations_on = _number(integrations, "enabled_count")
    if not integrations_on:
        integrations_on = sum(bool(_mapping(app).get("enabled")) for app in _mapping(integrations.get("apps")).values())
    return {
        "ts": _timestamp(now),
        "counts": {
            "tasks_done": _number(data.get("tasks"), "completed"),
            "people": _number(data.get("people"), "total"),
            "meetings": _number(data.get("meetings"), "total"),
            "skills_used": len(
                [name for name in _list(_mapping(data.get("skills")).get("used")) if isinstance(name, str)]
            ),
            "integrations_on": integrations_on,
        },
        "observations": _observation_strings(observations),
        "suggestion_title": _suggestion(observations)["title"],
    }


def _history_section_data(
    vault: Path,
    data: dict[str, Any],
    observations: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        entries = dashboard_history.load_history(vault)
        if not entries:
            return None
        previous_counts = _mapping(entries[-2].get("counts")) if len(entries) > 1 else {}
        new_counts = _mapping(entries[-1].get("counts"))
        raw_vault_age = _mapping(_mapping(data.get("meta")).get("vault_age")).get("age_days")
        vault_age = (
            raw_vault_age
            if isinstance(raw_vault_age, int) and not isinstance(raw_vault_age, bool) and raw_vault_age >= 0
            else None
        )
        trend_input = {
            "analytics": _mapping(data.get("analytics")),
            "history": entries,
        }
        return {
            "history": entries,
            "trends": dashboard_history.weekly_trends(trend_input),
            "milestones": dashboard_history.detect_milestones(
                previous_counts,
                new_counts,
                vault_age,
            ),
            "looking_back": observations.get("looking_back"),
        }
    except Exception:
        return None


def render_dashboard(
    vault: Path | str,
    data: dict[str, Any],
    observations: dict[str, Any] | None,
    output: Path | str,
    *,
    archive: bool = True,
    now: datetime | None = None,
    server_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write the page and, unless disabled, one compact local history line."""
    vault_path = Path(vault).expanduser().resolve()
    output_path = Path(output).expanduser()
    observation_data = observations or {}
    generated = now or _utc_now()
    history = _history_path(vault_path)
    archive_count = 0
    if archive:
        archive_count = _history_count(history) + 1
        history.parent.mkdir(parents=True, exist_ok=True)
        with history.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    _snapshot(data, observation_data, generated),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
    try:
        journey_data = dashboard_journey.build_journey(vault_path, data)
    except Exception:
        journey_data = None
    history_data = _history_section_data(vault_path, data, observation_data)
    page = render_dashboard_html(
        data,
        observation_data,
        archive_count=archive_count,
        archived=archive,
        journey=journey_data,
        history_data=history_data,
        server_ctx=server_ctx,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
    return {
        "output": str(output_path),
        "archived": archive,
        "archive_count": archive_count,
    }


def _load_json_object(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return parsed


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, required=True, help="Dex vault root")
    parser.add_argument("--data", type=Path, required=True, help="Collected dashboard JSON")
    parser.add_argument("--observations", type=Path, help="Authored observations JSON")
    parser.add_argument("--out", type=Path, required=True, help="HTML output path")
    parser.add_argument("--no-archive", action="store_true", help="Do not append a history snapshot")
    parser.add_argument(
        "--with-settings",
        action="store_true",
        help="Include server-ready local settings controls",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.vault.expanduser().is_dir():
        print(f"Error: vault is not a directory: {args.vault}", file=sys.stderr)
        return 2
    try:
        data = _load_json_object(args.data)
        observations = _load_json_object(args.observations) if args.observations else {}
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"Error: could not read dashboard input: {str(error).splitlines()[0]}", file=sys.stderr)
        return 2
    try:
        result = render_dashboard(
            args.vault,
            data,
            observations,
            args.out,
            archive=not args.no_archive,
            server_ctx=({"token": TOKEN_PLACEHOLDER, "port": PORT_PLACEHOLDER} if args.with_settings else None),
        )
    except OSError as error:
        print(f"Error: could not write dashboard output: {str(error).splitlines()[0]}", file=sys.stderr)
        return 1
    print(result["output"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
