"""Render the interactive, server-backed Dashboard settings section."""

from __future__ import annotations

import html
import json
import re
from typing import Any

SAFE_INTEGRATION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_MEETING_LABELS = {
    "extract_customer_intel": "Customer intelligence",
    "extract_competitive_intel": "Competitive intelligence",
    "extract_action_items": "Action items",
    "extract_decisions": "Decisions",
    "extract_stakeholder_dynamics": "Stakeholder dynamics",
    "extract_budget_timeline": "Budget and timeline",
    "extract_technical_decisions": "Technical decisions",
}
_MEETING_EXPLANATIONS = {
    "extract_customer_intel": "Bring customer pain points and themes into view.",
    "extract_competitive_intel": "Spot competitor mentions and comparisons.",
    "extract_action_items": "Turn clear meeting commitments into action items.",
    "extract_decisions": "Keep the decisions a meeting actually settled.",
    "extract_stakeholder_dynamics": "Remember relationships, influence and concerns.",
    "extract_budget_timeline": "Surface budget signals and important timing.",
    "extract_technical_decisions": "Record architecture choices and their context.",
}


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _inline_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _switch(
    setting_id: str,
    label: str,
    explanation: str,
    *,
    value: Any = None,
    value_kind: str = "bool",
    interactive: bool = True,
) -> str:
    checked_values = ""
    if value_kind == "health":
        checked_values = ' data-checked-value="opted-in" data-unchecked-value="opted-out"'
    checked = value is True or (value_kind == "health" and value == "opted-in")
    checked_attr = " checked" if checked else ""
    status = "" if interactive else "Read-only"
    return f"""
      <div class="setting-row" data-setting-row>
        <div class="setting-copy">
          <label for="setting-{_escape(setting_id)}">{_escape(label)}</label>
          <p>{_escape(explanation)}</p>
        </div>
        <div class="setting-action">
          <input
            id="setting-{_escape(setting_id)}"
            type="checkbox"
            role="switch"
            data-setting-id="{_escape(setting_id)}"
            data-value-kind="{_escape(value_kind)}"
            {checked_values}{checked_attr}
            disabled
          >
          <span class="setting-status" data-setting-status aria-live="polite">{status}</span>
        </div>
      </div>"""


def _select(
    setting_id: str,
    label: str,
    explanation: str,
    options: tuple[tuple[str, str], ...],
    *,
    value: Any = None,
    interactive: bool = True,
) -> str:
    option_html = "".join(
        (
            f'<option value="{_escape(option_value)}"'
            f'{" selected" if option_value == value else ""}>'
            f"{_escape(option_label)}</option>"
        )
        for option_value, option_label in options
    )
    status = "" if interactive else "Read-only"
    return f"""
      <div class="setting-row" data-setting-row>
        <div class="setting-copy">
          <label for="setting-{_escape(setting_id)}">{_escape(label)}</label>
          <p>{_escape(explanation)}</p>
        </div>
        <div class="setting-action">
          <select
            id="setting-{_escape(setting_id)}"
            data-setting-id="{_escape(setting_id)}"
            data-value-kind="enum"
            disabled
          >{option_html}</select>
          <span class="setting-status" data-setting-status aria-live="polite">{status}</span>
        </div>
      </div>"""


def _integration_rows(data: dict[str, Any], *, interactive: bool) -> str:
    apps = _mapping(_mapping(data.get("integrations")).get("apps"))
    rows = []
    for raw_name in sorted(apps, key=lambda item: str(item).casefold()):
        name = str(raw_name)
        if SAFE_INTEGRATION_NAME.fullmatch(name):
            setting_id = f"integration:{name}.enabled"
            rows.append(
                _switch(
                    setting_id,
                    name.replace("_", " ").replace("-", " ").title(),
                    "Let this existing connection contribute context to Dex.",
                    value=_mapping(apps[raw_name]).get("enabled"),
                    interactive=interactive,
                )
            )
        else:
            rows.append(
                f"""
      <div class="setting-row setting-row-readonly">
        <div class="setting-copy">
          <span class="setting-label">{_escape(name)}</span>
          <p>Manage this connection with Dex in conversation.</p>
        </div>
      </div>"""
            )
    if not rows:
        return '<p class="quiet">No existing integrations are available to switch here.</p>'
    return "".join(rows)


def _meeting_label(name: str) -> str:
    return _MEETING_LABELS.get(
        name,
        name.removeprefix("extract_").replace("_", " ").replace("-", " ").title(),
    )


def _meeting_explanation(name: str) -> str:
    return _MEETING_EXPLANATIONS.get(
        name,
        f"Capture {_meeting_label(name).lower()} when Dex processes a meeting.",
    )


def _meeting_rows(profile: dict[str, Any], *, interactive: bool) -> str:
    meeting_intelligence = _mapping(profile.get("meeting_intelligence"))
    rows = []
    for raw_name, value in sorted(
        meeting_intelligence.items(),
        key=lambda item: str(item[0]).casefold(),
    ):
        name = str(raw_name)
        if not isinstance(value, bool) or SAFE_INTEGRATION_NAME.fullmatch(name) is None:
            continue
        rows.append(
            _switch(
                f"meeting_intel:{name}",
                _meeting_label(name),
                _meeting_explanation(name),
                value=value,
                interactive=interactive,
            )
        )
    return "".join(rows)


def _capability_value(profile: dict[str, Any], room: str) -> bool | None:
    value = _mapping(_mapping(profile.get("capabilities")).get(room)).get("enabled")
    if isinstance(value, bool):
        return value
    if room == "quarter_goals":
        legacy = _mapping(profile.get("quarterly_planning")).get("enabled")
        if isinstance(legacy, bool):
            return legacy
    return None


def render(
    data: dict[str, Any],
    server_ctx: dict[str, Any] | None,
) -> tuple[str, str]:
    """Return the full settings inventory, live when a server context is present."""
    context = _mapping(server_ctx)
    token = str(context.get("token") or "")
    interactive = bool(server_ctx)
    profile = _mapping(data.get("profile"))
    communication = _mapping(profile.get("communication"))
    analytics = _mapping(profile.get("analytics"))
    entity_creation = _mapping(profile.get("entity_creation"))
    entity_gardener = _mapping(profile.get("entity_gardener"))
    journaling = _mapping(profile.get("journaling"))
    analytics_switch = _switch(
        "analytics_enabled",
        "Anonymous product analytics",
        "Share feature-use counts, never names, notes, or file contents.",
        value=analytics.get("enabled"),
        interactive=interactive,
    )
    entity_select = _select(
        "entity_creation",
        "New people and companies",
        "Choose whether new people and company pages appear automatically, as suggestions, or not at all.",
        (("auto", "Create automatically"), ("suggest", "Suggest first"), ("off", "Off")),
        value=entity_creation.get("mode"),
        interactive=interactive,
    )
    formality_select = _select(
        "formality",
        "Formality",
        "Set how polished or conversational Dex sounds.",
        (
            ("formal", "Formal"),
            ("professional_casual", "Professional, relaxed"),
            ("casual", "Casual"),
        ),
        value=communication.get("formality"),
        interactive=interactive,
    )
    directness_select = _select(
        "directness",
        "Directness",
        "Set how directly Dex gives advice and feedback.",
        (
            ("very_direct", "Very direct"),
            ("balanced", "Balanced"),
            ("supportive", "Supportive"),
        ),
        value=communication.get("directness"),
        interactive=interactive,
    )
    detail_select = _select(
        "detail_level",
        "Detail level",
        "Choose between quick answers, balanced context, or the full picture.",
        (
            ("concise", "Concise"),
            ("balanced", "Balanced"),
            ("comprehensive", "Comprehensive"),
        ),
        value=communication.get("detail_level"),
        interactive=interactive,
    )
    coaching_select = _select(
        "coaching_style",
        "Coaching style",
        "Choose whether Dex encourages, works alongside you, or pushes harder.",
        (
            ("encouraging", "Encouraging"),
            ("collaborative", "Collaborative"),
            ("challenging", "Challenging"),
        ),
        value=communication.get("coaching_style"),
        interactive=interactive,
    )
    health_switch = _switch(
        "health_telemetry",
        "Anonymous health telemetry",
        "Share nightly pass/fail counts only; this is separate from analytics.",
        value=profile.get("health_telemetry"),
        value_kind="health",
        interactive=interactive,
    )
    capability_rows = "".join(
        (
            _switch(
                "capability:career",
                "Career",
                "Career coaching, evidence capture and resume tools — unlocks a set of skills.",
                value=_capability_value(profile, "career"),
                interactive=interactive,
            ),
            _switch(
                "capability:companies",
                "Companies",
                "Richer company pages and commercial context — unlocks a set of skills.",
                value=_capability_value(profile, "companies"),
                interactive=interactive,
            ),
            _switch(
                "capability:quarter_goals",
                "Quarter goals",
                "Quarter planning, reviews and goal tracking — unlocks a set of skills.",
                value=_capability_value(profile, "quarter_goals"),
                interactive=interactive,
            ),
        )
    )
    meeting_rows = _meeting_rows(profile, interactive=interactive)
    meeting_foundations = "".join(
        (
            entity_select,
            _switch(
                "entity_gardener",
                "Keep people pages fresh",
                "Refresh useful person summaries as new meetings add context.",
                value=entity_gardener.get("enabled"),
                interactive=interactive,
            ),
        )
    )
    journaling_rows = "".join(
        (
            _switch(
                "journaling_morning",
                "Morning journal",
                "Start the day by setting an intention and focus.",
                value=journaling.get("morning"),
                interactive=interactive,
            ),
            _switch(
                "journaling_evening",
                "Evening journal",
                "Close the day with a short reflection.",
                value=journaling.get("evening"),
                interactive=interactive,
            ),
            _switch(
                "journaling_weekly",
                "Weekly journal",
                "Notice patterns and lessons across the week.",
                value=journaling.get("weekly"),
                interactive=interactive,
            ),
        )
    )
    integration_rows = _integration_rows(data, interactive=interactive)
    heading = "Tune Dex from here" if interactive else "See the full shape of your Dex"
    note = (
        "These changes stay in your local Dex files."
        if interactive
        else "Read-only — open with 'let me change my settings' to make these live."
    )
    handoff_disabled = "" if interactive else " disabled"
    fragment = f"""
    <section id="settings" aria-labelledby="settings-heading">
      <div class="section-heading">
        <p class="kicker">Settings</p>
        <h2 id="settings-heading">{heading}</h2>
        <p class="quiet">{note}</p>
      </div>
      <div class="settings-group" data-settings-group="privacy">
        <h3 class="settings-group-label">Privacy</h3>
        <div class="settings-list">{analytics_switch}{health_switch}</div>
      </div>
      <div class="settings-group" data-settings-group="communication">
        <h3 class="settings-group-label">Communication</h3>
        <div class="settings-list">
          {formality_select}{directness_select}{detail_select}{coaching_select}
        </div>
      </div>
      <div class="settings-group" data-settings-group="capabilities">
        <h3 class="settings-group-label">Capabilities</h3>
        <div class="settings-list">{capability_rows}</div>
      </div>
      <div class="settings-group" data-settings-group="meetings">
        <h3 class="settings-group-label">Meetings</h3>
        <div class="settings-list" data-meeting-intel-list>{meeting_rows}</div>
        <div class="settings-list">{meeting_foundations}</div>
      </div>
      <div class="settings-group" data-settings-group="journaling">
        <h3 class="settings-group-label">Journaling</h3>
        <div class="settings-list">{journaling_rows}</div>
      </div>
      <div class="settings-group" data-settings-group="connections">
        <h3 class="settings-group-label">Connections</h3>
        <div class="settings-subsection">
          <h4>Existing integrations</h4>
          <div class="settings-list">{integration_rows}</div>
        </div>
        <div class="settings-subsection">
          <h4>Set up something new</h4>
          <button type="button" class="handoff-button" data-command="/todoist-setup"{handoff_disabled}>
            Set up Todoist
            <span>Dex walks you through it (run /todoist-setup)</span>
          </button>
          <span class="handoff-status" data-handoff-status aria-live="polite"></span>
        </div>
      </div>
    </section>"""

    if not interactive:
        return fragment, ""

    script = f"""
(() => {{
  const dashboardToken = {_inline_json(token)};
  const meetingLabels = {_inline_json(_MEETING_LABELS)};
  const meetingExplanations = {_inline_json(_MEETING_EXPLANATIONS)};
  const settingsRoot = document.getElementById('settings');
  const currentValues = new Map();

  function controls() {{
    return Array.from(settingsRoot.querySelectorAll('[data-setting-id]'));
  }}

  function apiUrl(path) {{
    const url = new URL(path, window.location.href);
    url.searchParams.set('t', dashboardToken);
    return url.toString();
  }}

  function statusFor(control) {{
    return control.closest('[data-setting-row]').querySelector('[data-setting-status]');
  }}

  function valueFrom(control) {{
    if (control.dataset.valueKind === 'bool') return control.checked;
    if (control.dataset.valueKind === 'health') {{
      return control.checked ? control.dataset.checkedValue : control.dataset.uncheckedValue;
    }}
    return control.value;
  }}

  function meetingLabel(name) {{
    if (meetingLabels[name]) return meetingLabels[name];
    const words = name.replace(/^extract_/, '').replace(/[_-]+/g, ' ');
    return words.replace(/\\b\\w/g, (letter) => letter.toUpperCase());
  }}

  function addMeetingControls(settings, unavailable) {{
    const list = settingsRoot.querySelector('[data-meeting-intel-list]');
    if (!list) return;
    const existing = new Set(controls().map((control) => control.dataset.settingId));
    const settingIds = new Set([
      ...Object.keys(settings || {{}}),
      ...Object.keys(unavailable || {{}})
    ]);
    Array.from(settingIds)
      .filter((settingId) => settingId.startsWith('meeting_intel:'))
      .sort()
      .forEach((settingId) => {{
        if (existing.has(settingId)) return;
        const name = settingId.slice('meeting_intel:'.length);
        const row = document.createElement('div');
        row.className = 'setting-row';
        row.dataset.settingRow = '';

        const copy = document.createElement('div');
        copy.className = 'setting-copy';
        const label = document.createElement('label');
        label.htmlFor = 'setting-' + settingId;
        label.textContent = meetingLabel(name);
        const explanation = document.createElement('p');
        explanation.textContent = meetingExplanations[name]
          || 'Capture ' + meetingLabel(name).toLowerCase() + ' when Dex processes a meeting.';
        copy.append(label, explanation);

        const action = document.createElement('div');
        action.className = 'setting-action';
        const control = document.createElement('input');
        control.id = 'setting-' + settingId;
        control.type = 'checkbox';
        control.setAttribute('role', 'switch');
        control.dataset.settingId = settingId;
        control.dataset.valueKind = 'bool';
        control.disabled = true;
        const status = document.createElement('span');
        status.className = 'setting-status';
        status.dataset.settingStatus = '';
        status.setAttribute('aria-live', 'polite');
        action.append(control, status);
        row.append(copy, action);
        list.append(row);
      }});
  }}

  function applyValue(control, value) {{
    if (control.dataset.valueKind === 'bool') control.checked = value === true;
    else if (control.dataset.valueKind === 'health') control.checked = value === 'opted-in';
    else control.value = value;
  }}

  async function readJson(response) {{
    const payload = await response.json().catch(() => ({{ error: 'Dex could not read the response.' }}));
    if (!response.ok) throw new Error(payload.error || 'Dex could not save that change.');
    return payload;
  }}

  async function loadState() {{
    try {{
      const response = await fetch(apiUrl('/api/state'), {{
        headers: {{ Accept: 'application/json' }},
        cache: 'no-store'
      }});
      const payload = await readJson(response);
      const unavailable = payload.unavailable || {{}};
      addMeetingControls(payload.settings, unavailable);
      controls().forEach((control) => {{
        const settingId = control.dataset.settingId;
        if (Object.prototype.hasOwnProperty.call(payload.settings, settingId)) {{
          currentValues.set(settingId, payload.settings[settingId]);
          applyValue(control, payload.settings[settingId]);
          control.disabled = false;
          statusFor(control).textContent = '';
        }} else if (Object.prototype.hasOwnProperty.call(unavailable, settingId)) {{
          control.disabled = true;
          statusFor(control).textContent = unavailable[settingId];
        }} else {{
          control.disabled = true;
          statusFor(control).textContent = 'Not set up in this vault yet.';
        }}
      }});
    }} catch (error) {{
      controls().forEach((control) => {{
        control.disabled = true;
        statusFor(control).textContent = 'Not live right now — reopen from Dex to change this.';
      }});
    }}
  }}

  async function saveValue(control, nextValue, previousValue) {{
    const settingId = control.dataset.settingId;
    const status = statusFor(control);
    control.disabled = true;
    status.textContent = 'Saving…';
    try {{
      const response = await fetch(apiUrl('/api/toggle'), {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json', Accept: 'application/json' }},
        body: JSON.stringify({{ setting_id: settingId, value: nextValue }})
      }});
      const payload = await readJson(response);
      currentValues.set(settingId, payload.new);
      applyValue(control, payload.new);
      status.replaceChildren(document.createTextNode('Changed just now — '));
      const undo = document.createElement('button');
      undo.type = 'button';
      undo.className = 'undo-button';
      undo.textContent = 'undo';
      undo.addEventListener('click', () => {{
        const valueBeforeUndo = currentValues.get(settingId);
        applyValue(control, payload.old);
        currentValues.set(settingId, payload.old);
        saveValue(control, payload.old, valueBeforeUndo);
      }}, {{ once: true }});
      status.appendChild(undo);
    }} catch (error) {{
      currentValues.set(settingId, previousValue);
      applyValue(control, previousValue);
      status.textContent = error.message;
    }} finally {{
      control.disabled = false;
    }}
  }}

  settingsRoot.addEventListener('change', (event) => {{
    const control = event.target.closest
      ? event.target.closest('[data-setting-id]')
      : null;
    if (!control) return;
    const settingId = control.dataset.settingId;
    const previousValue = currentValues.get(settingId);
    const nextValue = valueFrom(control);
    currentValues.set(settingId, nextValue);
    saveValue(control, nextValue, previousValue);
  }});

  document.querySelectorAll('[data-command]').forEach((button) => {{
    button.addEventListener('click', async () => {{
      const command = button.dataset.command;
      const status = document.querySelector('[data-handoff-status]');
      try {{
        await navigator.clipboard.writeText(command);
        status.textContent = command + ' copied — paste it into Dex.';
      }} catch (_error) {{
        status.textContent = 'Run ' + command + ' in Dex.';
      }}
    }});
  }});

  let closeSent = false;
  function closeServer() {{
    if (closeSent) return;
    closeSent = true;
    const url = apiUrl('/api/close');
    if (navigator.sendBeacon) {{
      navigator.sendBeacon(url, new Blob(['{{}}'], {{ type: 'application/json' }}));
    }} else {{
      fetch(url, {{ method: 'POST', body: '{{}}', keepalive: true }}).catch(() => {{}});
    }}
  }}

  window.addEventListener('pagehide', closeServer);
  window.addEventListener('beforeunload', closeServer);
  loadState();
}})();
"""
    return fragment, script
