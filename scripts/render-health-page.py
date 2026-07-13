#!/usr/bin/env python3
"""Render health.json as one self-contained, truthful HTML page."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

UNKNOWN = "unknown"


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _safe_workflow_link(value: Any) -> str:
    url = str(value)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return f"<code>{_escape(value)}</code>"
    escaped = _escape(url)
    return f'<a href="{escaped}" rel="noreferrer">Open workflow run</a>'


def _summary(data: dict[str, Any]) -> str:
    version = _escape(data.get("release", {}).get("version", UNKNOWN))
    passed = data.get("automated_checks", {}).get("passed", UNKNOWN)
    if isinstance(passed, int):
        return f"Dex v{version} passed {passed} automated checks before this release reached you."
    return f"Automated check counts are unavailable for Dex v{version}; no count is being claimed."


def _status_label(status: Any) -> str:
    labels = {
        "passed": "Passed",
        "skipped": "Skipped",
        "not-applicable": "Not applicable — not run (PR-only)",
        UNKNOWN: "Unknown",
    }
    return labels.get(str(status), str(status).replace("-", " ").title())


def _render_gate_rows(gates: Any) -> str:
    if not isinstance(gates, list):
        gates = []
    rows = []
    for gate in gates:
        if not isinstance(gate, dict):
            continue
        status = str(gate.get("status", UNKNOWN))
        css_status = status if status in {"passed", "skipped", "not-applicable", UNKNOWN} else UNKNOWN
        rows.append(
            "<tr>"
            f'<th scope="row">{_escape(gate.get("name", UNKNOWN))}</th>'
            f'<td><span class="status status-{css_status}">{_escape(_status_label(status))}</span></td>'
            f'<td>{_escape(gate.get("detail", UNKNOWN))}</td>'
            "</tr>"
        )
    return "\n".join(rows) or '<tr><td colspan="3">Gate data is unknown.</td></tr>'


def render_health_html(data: dict[str, Any]) -> str:
    release = data.get("release", {})
    checks = data.get("automated_checks", {})
    coverage = data.get("coverage", {})
    version = release.get("version", UNKNOWN)
    source_sha = release.get("source_sha", UNKNOWN)
    release_sha = release.get("release_sha", UNKNOWN)
    generated_at = release.get("generated_at", UNKNOWN)
    workflow_url = release.get("workflow_run_url", UNKNOWN)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>Dex v{_escape(version)} release health</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #f5f3ee;
      --surface: #fffdf8;
      --text: #18201d;
      --muted: #5e6a65;
      --border: #d8ddd8;
      --accent: #176b52;
      --pass-bg: #dff4e9;
      --pass-text: #155b45;
      --neutral-bg: #ecefe9;
      --neutral-text: #4b5550;
      --unknown-bg: #fff0c7;
      --unknown-text: #6f5011;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #121715;
        --surface: #1a211e;
        --text: #eef3ef;
        --muted: #aeb9b3;
        --border: #35413b;
        --accent: #7ed2b3;
        --pass-bg: #173f32;
        --pass-text: #9be0c5;
        --neutral-bg: #303833;
        --neutral-text: #d0d8d3;
        --unknown-bg: #4c3c18;
        --unknown-text: #f4d681;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 16px/1.55 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ width: min(72rem, calc(100% - 2rem)); margin: 0 auto; padding: 4rem 0; }}
    header, section {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 1rem;
      padding: clamp(1.25rem, 3vw, 2.25rem);
      margin-bottom: 1rem;
    }}
    .eyebrow {{ color: var(--accent); font-size: .8rem; font-weight: 750; letter-spacing: .08em; text-transform: uppercase; }}
    h1 {{ max-width: 22ch; margin: .35rem 0 .75rem; font-size: clamp(2rem, 6vw, 4.5rem); line-height: 1.02; letter-spacing: -.04em; }}
    h2 {{ margin-top: 0; font-size: 1.35rem; }}
    .lede {{ max-width: 68ch; margin: 0; color: var(--muted); font-size: clamp(1.05rem, 2vw, 1.3rem); }}
    .headline {{ margin-top: 1.5rem; font-weight: 650; }}
    .metrics, .provenance {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); gap: .75rem; margin: 1rem 0 0; }}
    .metric, .provenance div {{ padding: 1rem; border: 1px solid var(--border); border-radius: .75rem; min-width: 0; }}
    dt {{ color: var(--muted); font-size: .82rem; font-weight: 700; letter-spacing: .03em; text-transform: uppercase; }}
    dd {{ margin: .35rem 0 0; font-weight: 650; overflow-wrap: anywhere; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 42rem; }}
    th, td {{ padding: .85rem .7rem; border-bottom: 1px solid var(--border); text-align: left; vertical-align: top; }}
    thead th {{ color: var(--muted); font-size: .8rem; letter-spacing: .04em; text-transform: uppercase; }}
    tbody th {{ font-weight: 650; }}
    .status {{ display: inline-block; border-radius: 999px; padding: .2rem .6rem; font-size: .84rem; font-weight: 750; white-space: nowrap; }}
    .status-passed {{ background: var(--pass-bg); color: var(--pass-text); }}
    .status-skipped, .status-not-applicable {{ background: var(--neutral-bg); color: var(--neutral-text); }}
    .status-unknown {{ background: var(--unknown-bg); color: var(--unknown-text); }}
    a {{ color: var(--accent); }}
    code {{ font-size: .85em; }}
    footer {{ color: var(--muted); padding: .5rem .25rem; font-size: .9rem; }}
    @media (max-width: 40rem) {{ main {{ padding: 1rem 0; }} header, section {{ border-radius: .75rem; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <div class="eyebrow">{_escape(data.get("label", "Last successful release build"))}</div>
      <h1>Release health for Dex v{_escape(version)}</h1>
      <p class="lede">{_summary(data)}</p>
      <p class="headline">{_escape(data.get("changelog_headline", UNKNOWN))}</p>
      <dl class="metrics">
        <div class="metric"><dt>Passed checks</dt><dd>{_escape(checks.get("passed", UNKNOWN))}</dd></div>
        <div class="metric"><dt>Skipped checks</dt><dd>{_escape(checks.get("skipped", UNKNOWN))}</dd></div>
        <div class="metric"><dt>Failed checks</dt><dd>{_escape(checks.get("failed", UNKNOWN))}</dd></div>
        <div class="metric"><dt>Total coverage</dt><dd>{_escape(coverage.get("total_percent", UNKNOWN))}%</dd></div>
      </dl>
    </header>

    <section aria-labelledby="gate-heading">
      <h2 id="gate-heading">What this release build ran</h2>
      <p>Each row reports this exact release build. Pull-request-only checks are shown as not run, never passed.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">Gate</th><th scope="col">Status</th><th scope="col">What happened</th></tr></thead>
          <tbody>
            {_render_gate_rows(data.get("gates"))}
          </tbody>
        </table>
      </div>
    </section>

    <section aria-labelledby="provenance-heading">
      <h2 id="provenance-heading">Build provenance</h2>
      <dl class="provenance">
        <div><dt>Source commit</dt><dd><code>{_escape(source_sha)}</code></dd></div>
        <div><dt>Generated release commit</dt><dd><code>{_escape(release_sha)}</code></dd></div>
        <div><dt>Verified at (UTC)</dt><dd>{_escape(generated_at)}</dd></div>
        <div><dt>Workflow run</dt><dd>{_safe_workflow_link(workflow_url)}</dd></div>
      </dl>
    </section>

    <footer>This page remains the record of the last successful release build. A later failed build does not rewrite it or make it a claim about current HEAD.</footer>
  </main>
</body>
</html>
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("health.json"))
    parser.add_argument("--output", type=Path, default=Path("health.html"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_health_html(data), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
