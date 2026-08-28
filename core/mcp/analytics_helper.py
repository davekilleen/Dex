#!/usr/bin/env python3
"""
Dex Analytics Helper

Shared utilities for analytics across Dex skills and MCPs.
Handles consent checking, journey metadata calculation, and event firing.

Privacy Principles:
- On by default in the beta; Settings flip (analytics.enabled: false) is zero egress
- Only tracks Dex built-in features, not user customizations
- Tracks THAT features were used, not WHAT users did with them
- Never sends content, names, notes, conversations, or Guide/Coach work patterns
- Identity is install-scoped only; career-grade surfaces emit nothing

Usage in skills:
    from analytics_helper import fire_event, check_consent, mark_feature_used
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.analytics_events import (
    REDACTED_ANALYTICS_EVENT_NAME,
    is_safe_analytics_event_name,
)
from core.analytics_walls import (
    ANALYTICS_ACCOUNT_SCOPE,
    WALL_CAREER,
    build_safe_track_payload,
    get_or_create_analytics_install_id,
    inspect_caller_properties,
    is_career_grade_event,
    read_analytics_install_id,
)
from core.lifecycle import service as lifecycle_service

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# Configuration
DEFAULT_PENDO_ENDPOINT = "https://app.pendo.io/data/track"
ANALYTICS_MODE_DIRECT = "direct"
ANALYTICS_MODE_PROXY = "proxy"
_CONNECTION_TEST_EVENT = "dex_analytics_test"
_CONNECTION_TEST_VISITOR_ID = "dex-analytics-test"
_CONNECTION_TEST_ACCOUNT_ID = "dex-analytics-test"
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0


def _bounded_request_timeout_seconds(value: object) -> float:
    """Return a finite delivery-only timeout without affecting receipt writes."""
    if (
        type(value) in (int, float)
        and 0 < value <= _DEFAULT_REQUEST_TIMEOUT_SECONDS
    ):
        return float(value)
    return _DEFAULT_REQUEST_TIMEOUT_SECONDS


def get_vault_path() -> Path:
    """Get vault path from environment or default."""
    vault = os.environ.get('VAULT_PATH', os.path.expanduser('~/Dex'))
    return Path(vault)


def get_pendo_secret() -> Optional[str]:
    """Get Pendo Track Event shared secret from environment."""
    secret = os.environ.get('PENDO_TRACK_SECRET', '').strip()
    return secret or None


def get_analytics_mode() -> str:
    """
    Get analytics transport mode.

    Modes:
    - direct: client sends directly to Pendo (requires PENDO_TRACK_SECRET)
    - proxy:  client sends to a relay endpoint (requires DEX_ANALYTICS_ENDPOINT)
    """
    mode = os.environ.get('DEX_ANALYTICS_MODE', ANALYTICS_MODE_DIRECT).strip().lower()
    if mode in (ANALYTICS_MODE_DIRECT, ANALYTICS_MODE_PROXY):
        return mode
    return ANALYTICS_MODE_DIRECT


def get_analytics_endpoint(mode: Optional[str] = None) -> str:
    """Get analytics endpoint for current mode."""
    resolved_mode = mode or get_analytics_mode()
    endpoint = os.environ.get('DEX_ANALYTICS_ENDPOINT', '').strip()

    if endpoint:
        return endpoint
    if resolved_mode == ANALYTICS_MODE_DIRECT:
        return DEFAULT_PENDO_ENDPOINT
    return ''


def get_proxy_token() -> Optional[str]:
    """Optional bearer token for analytics proxy."""
    token = os.environ.get('DEX_ANALYTICS_PROXY_TOKEN', '').strip()
    return token or None


def get_analytics_transport() -> Dict[str, Any]:
    """
    Resolve analytics transport configuration.

    Returns:
        {
            "configured": bool,
            "mode": "direct" | "proxy",
            "endpoint": str,
            "headers": dict,
            "reason": str (if not configured)
        }
    """
    mode = get_analytics_mode()
    endpoint = get_analytics_endpoint(mode)
    headers = {'Content-Type': 'application/json'}

    if not endpoint:
        return {
            'configured': False,
            'mode': mode,
            'endpoint': '',
            'headers': headers,
            'reason': 'no_analytics_endpoint',
        }

    if mode == ANALYTICS_MODE_DIRECT:
        secret = get_pendo_secret()
        if not secret:
            return {
                'configured': False,
                'mode': mode,
                'endpoint': endpoint,
                'headers': headers,
                'reason': 'no_pendo_secret',
            }
        headers['x-pendo-integration-key'] = secret
    else:
        # Proxy mode intentionally avoids shipping Pendo credentials in clients.
        token = get_proxy_token()
        if token:
            headers['Authorization'] = f'Bearer {token}'
        headers['x-dex-analytics-client'] = 'dex-core'

    return {
        'configured': True,
        'mode': mode,
        'endpoint': endpoint,
        'headers': headers,
        'reason': '',
    }


def load_usage_log() -> Dict[str, Any]:
    """Parse usage_log.md into structured data."""
    usage_path = get_vault_path() / 'System' / 'usage_log.md'
    if not usage_path.exists():
        return {}
    
    with open(usage_path, 'r') as f:
        content = f.read()
    
    data = {
        'features': {},
        'metadata': {},
    }
    
    # Parse checkboxes for feature adoption
    checkbox_pattern = r'- \[([ x])\] (.+)'
    for match in re.finditer(checkbox_pattern, content):
        checked = match.group(1) == 'x'
        feature = match.group(2).strip()
        data['features'][feature] = checked
    
    # Parse metadata section
    metadata_patterns = {
        'consent_asked': r'\*\*Consent asked:\*\* (\w+)',
        'consent_decision': r'\*\*Consent decision:\*\* ([\w-]+)',
        'consent_date': r'\*\*Consent date:\*\* (.+)',
        'setup_date': r'\*\*Setup date:\*\* (.+)',
    }
    
    for key, pattern in metadata_patterns.items():
        match = re.search(pattern, content)
        if match:
            value = match.group(1).strip()
            if value and value not in ['(not yet prompted)', '(not yet run)', '(set during onboarding)', 
                                        '(not yet decided)', '(not yet determined)', '(not yet active)']:
                data['metadata'][key] = value
    
    return data


def check_consent() -> str:
    """
    Check analytics consent status.
    
    Returns:
        'pending' - Not yet asked
        'opted-in' - User agreed
        'opted-out' - User declined
    """
    data = load_usage_log()
    decision = data.get('metadata', {}).get('consent_decision', 'pending')
    return decision


def is_analytics_enabled() -> bool:
    """Return whether anonymous product analytics may leave this install.

    Founder ruling (beta): on by default. The Settings switch is
    ``analytics.enabled`` in user-profile.yaml. Flip to false → zero egress.
    A usage_log opted-out decision is also off. Missing Settings is on.
    Unreadable Settings fails closed (off). Bug reports are a separate path
    and still wait for an explicit yes.
    """
    try:
        profile = load_user_profile()
    except Exception:
        return False
    analytics = profile.get("analytics") if isinstance(profile, dict) else {}
    if isinstance(analytics, dict) and analytics.get("enabled") is False:
        return False
    try:
        if check_consent() == "opted-out":
            return False
    except Exception:
        pass
    return True


def load_user_profile() -> dict:
    """Load user profile from yaml."""
    try:
        import yaml
    except ImportError:
        return {}
    
    profile_path = get_vault_path() / 'System' / 'user-profile.yaml'
    if profile_path.exists():
        with open(profile_path, 'r') as f:
            return yaml.safe_load(f) or {}
    return {}


def calculate_journey_metadata() -> Dict[str, Any]:
    """
    Calculate journey metadata from usage_log.md.
    
    Returns dict with:
        - days_since_setup: int
        - feature_adoption_score: int (out of 55)
        - journey_stage: str (new/exploring/established/power_user)
        - most_active_area: str
    """
    data = load_usage_log()
    features = data.get('features', {})
    
    # Count features by area - matches usage_log.md sections (55 total features)
    areas = {
        'core_workflows': [
            'Daily planning', 'Daily review', 'Weekly planning', 'Weekly review',
            'Quarterly planning', 'Quarterly review', 'Getting started', 'Journaling'
        ],
        'meetings': [
            'Meeting prep', 'Meeting processing', 'Person page created', 
            'Person page updated', 'Company page created', 'Granola connected'
        ],
        'tasks': [
            'Task created', 'Task completed', 'Task updated', 
            'Priority set', 'Goal created', 'Pillar alignment'
        ],
        'organization': [
            'Inbox triage', 'Learning capture', 'Project tracking', 
            'Product brief', 'Project page created'
        ],
        'journaling': [
            'Journaling setup', 'Morning journal', 'Evening journal', 'Weekly journal'
        ],
        'career': [
            'Career setup', 'Career coaching', 'Resume builder', 
            'Career evidence', 'Promotion readiness', 'Skills gap'
        ],
        'discovery': [
            'Feature discovery', 'What\'s new', 'Backlog review', 
            'Improvement workshop', 'Idea captured', 'Dex updated', 'Dex rolled back',
            'Learnings reviewed', 'X-ray transparency'
        ],
        'integrations': [
            'Calendar connected', 'Calendar synced', 'Granola connected',
            'Obsidian enabled', 'MCP added'
        ],
        'advanced': [
            'Prompt improvement', 'Custom MCP', 'MCP integrated',
            'Custom skill created', 'Vault reset', 'Setup re-run'
        ],
    }
    
    area_scores = {}
    total_used = 0
    
    for area, area_features in areas.items():
        count = 0
        for af in area_features:
            for feature_name, checked in features.items():
                if af.lower() in feature_name.lower() and checked:
                    count += 1
                    break
        area_scores[area] = count
        total_used += count
    
    # Determine most active area
    most_active = max(area_scores.items(), key=lambda x: x[1]) if area_scores else ('none', 0)
    
    # Calculate days since setup
    setup_date_str = data.get('metadata', {}).get('setup_date')
    if setup_date_str and setup_date_str not in ['(set during onboarding)', '']:
        try:
            setup_date = datetime.strptime(setup_date_str, '%Y-%m-%d')
            days = (datetime.now() - setup_date).days
        except:
            days = 0
    else:
        days = 0
    
    # Determine journey stage
    if days <= 7:
        stage = 'new'
    elif days <= 30:
        stage = 'exploring'
    elif days <= 90:
        stage = 'established'
    else:
        stage = 'power_user'
    
    return {
        'days_since_setup': days,
        'feature_adoption_score': total_used,
        'journey_stage': stage,
        'most_active_area': most_active[0] if most_active[1] > 0 else 'none',
    }


def get_visitor_info() -> Dict[str, str]:
    """Return the install-scoped analytics identifier only.

    Never vault identity (name, email, profile visitor_id) and never Record
    keys (ledger install_id, health telemetry id). Missing id is empty so a
    status check does not create a file.
    """
    install_id = read_analytics_install_id(get_vault_path()) or ""
    return {
        "visitor_id": install_id,
        "account_id": ANALYTICS_ACCOUNT_SCOPE,
    }


def _read_dex_version() -> str | None:
    """Return the shipped Dex version, or None if it cannot be proved."""
    try:
        package = json.loads((_REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    version = package.get("version")
    if isinstance(version, str) and version:
        return version
    return None


def _with_attempt_receipt(
    result: Dict[str, Any],
    *,
    event_name: str,
    outcome: str,
    reason: str,
) -> Dict[str, Any]:
    """Return the delivery result with its one safe, local receipt outcome.

    Receipt failures are deliberately visible but never include the underlying
    filesystem error: that text can carry a user path or transport detail.
    """
    try:
        lifecycle_service._append_analytics_attempt_receipt(
            get_vault_path(),
            event_name=event_name,
            outcome=outcome,
            reason=reason,
        )
    except Exception:
        return {
            **result,
            'receipt_written': False,
            'receipt_reason': 'receipt_write_failed',
        }
    return {**result, 'receipt_written': True}


def fire_event(
    event_name: str,
    properties: Dict[str, Any] = None,
    *,
    _connection_test: bool = False,
    _request_timeout_seconds: float | None = None,
) -> Dict[str, Any]:
    """
    Fire an analytics event through the existing transport.

    Only fires when Settings is on (default on). Walls refuse content,
    Guide/Coach usage patterns, extra identity, and career-grade surfaces.
    Does not invent a vendor, dashboard, or Dex-held key.

    Args:
        event_name: Name of the event (e.g., 'daily_plan_completed')
        properties: App-level counts or error class only — no content
        _request_timeout_seconds: Private delivery-only timeout for callers
            such as session start. It never interrupts the local receipt.
    
    Returns:
        Result dict with success status
    """
    request_timeout_seconds = _bounded_request_timeout_seconds(
        _request_timeout_seconds
    )
    if not is_safe_analytics_event_name(event_name):
        return _with_attempt_receipt(
            {'fired': False, 'reason': 'invalid_event_name'},
            event_name=REDACTED_ANALYTICS_EVENT_NAME,
            outcome='not_sent',
            reason='invalid_event_name',
        )

    if _connection_test and event_name != _CONNECTION_TEST_EVENT:
        return _with_attempt_receipt(
            {'fired': False, 'reason': 'invalid_event_name'},
            event_name=REDACTED_ANALYTICS_EVENT_NAME,
            outcome='not_sent',
            reason='invalid_event_name',
        )

    try:
        analytics_enabled = is_analytics_enabled()
    except Exception:
        return _with_attempt_receipt(
            {'fired': False, 'reason': 'request_failed'},
            event_name=event_name,
            outcome='not_sent',
            reason='request_failed',
        )

    if not analytics_enabled:
        return _with_attempt_receipt(
            {'fired': False, 'reason': 'analytics_disabled'},
            event_name=event_name,
            outcome='not_sent',
            reason='analytics_disabled',
        )

    if not _connection_test and is_career_grade_event(event_name):
        return _with_attempt_receipt(
            {'fired': False, 'reason': WALL_CAREER},
            event_name=event_name,
            outcome='not_sent',
            reason=WALL_CAREER,
        )

    if not _connection_test:
        property_wall = inspect_caller_properties(properties)
        if property_wall is not None:
            return _with_attempt_receipt(
                {'fired': False, 'reason': property_wall},
                event_name=event_name,
                outcome='not_sent',
                reason=property_wall,
            )

    if not HAS_REQUESTS:
        return _with_attempt_receipt(
            {'fired': False, 'reason': 'requests_not_installed'},
            event_name=event_name,
            outcome='not_sent',
            reason='requests_not_installed',
        )
    
    try:
        transport = get_analytics_transport()
        if not transport.get('configured'):
            transport_reason = transport.get('reason')
            if transport_reason not in {'no_analytics_endpoint', 'no_pendo_secret'}:
                transport_reason = 'no_analytics_endpoint'
            return _with_attempt_receipt(
                {'fired': False, 'reason': transport_reason},
                event_name=event_name,
                outcome='not_sent',
                reason=transport_reason,
            )

        timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if _connection_test:
            # A connection check must prove only that the transport works. It
            # must never read or send a person's identity, profile, journey
            # metadata, or caller-supplied properties.
            payload, wall_reason = build_safe_track_payload(
                event_name=event_name,
                visitor_id=_CONNECTION_TEST_VISITOR_ID,
                timestamp_ms=timestamp_ms,
                properties=None,
                connection_test=True,
            )
        else:
            visitor_id = get_or_create_analytics_install_id(get_vault_path())
            payload, wall_reason = build_safe_track_payload(
                event_name=event_name,
                visitor_id=visitor_id,
                timestamp_ms=timestamp_ms,
                properties=properties,
                dex_version=_read_dex_version(),
            )
        if payload is None or wall_reason is not None:
            blocked = wall_reason or WALL_CAREER
            return _with_attempt_receipt(
                {'fired': False, 'reason': blocked},
                event_name=event_name,
                outcome='not_sent',
                reason=blocked,
            )

        response = requests.post(
            transport['endpoint'],
            json=payload,
            headers=transport['headers'],
            timeout=request_timeout_seconds,
        )
        if response.status_code == 200:
            return _with_attempt_receipt(
                {'fired': True, 'event': event_name, 'mode': transport['mode']},
                event_name=event_name,
                outcome='sent',
                reason='sent',
            )
        return _with_attempt_receipt(
            {
                'fired': False,
                'mode': transport['mode'],
                'reason': 'http_error',
            },
            event_name=event_name,
            outcome='not_sent',
            reason='http_error',
        )
    except Exception:
        return _with_attempt_receipt(
            {'fired': False, 'reason': 'request_failed'},
            event_name=event_name,
            outcome='not_sent',
            reason='request_failed',
        )


def update_consent(decision: str):
    """
    Update usage_log.md with consent decision.
    
    Args:
        decision: 'opted-in' or 'opted-out'
    """
    usage_path = get_vault_path() / 'System' / 'usage_log.md'
    if not usage_path.exists():
        return
    
    with open(usage_path, 'r') as f:
        content = f.read()
    
    today = datetime.now().strftime('%Y-%m-%d')
    
    # Update consent fields
    content = re.sub(
        r'\*\*Consent asked:\*\* \w+',
        '**Consent asked:** true',
        content
    )
    content = re.sub(
        r'\*\*Consent decision:\*\* [\w-]+',
        f'**Consent decision:** {decision}',
        content
    )
    content = re.sub(
        r'\*\*Consent date:\*\* .+',
        f'**Consent date:** {today}',
        content
    )
    
    with open(usage_path, 'w') as f:
        f.write(content)


def mark_feature_used(feature_name: str):
    """Mark a feature as used in usage_log.md."""
    usage_path = get_vault_path() / 'System' / 'usage_log.md'
    if not usage_path.exists():
        return
    
    with open(usage_path, 'r') as f:
        content = f.read()
    
    # Find and check the checkbox for this feature
    # Pattern: - [ ] Feature name... → - [x] Feature name...
    pattern = rf'- \[ \] ([^(\n]*{re.escape(feature_name)}[^(\n]*)'
    
    def replace_checkbox(match):
        return f'- [x] {match.group(1)}'
    
    new_content = re.sub(pattern, replace_checkbox, content, flags=re.IGNORECASE)
    
    if new_content != content:
        with open(usage_path, 'w') as f:
            f.write(new_content)


# Event name constants for consistency
class Events:
    # Lifecycle
    SESSION_STARTED = 'session_started'
    ONBOARDING_COMPLETED = 'onboarding_completed'
    
    # Core Skills
    DAILY_PLAN_COMPLETED = 'daily_plan_completed'
    DAILY_REVIEW_COMPLETED = 'daily_review_completed'
    WEEK_PLAN_COMPLETED = 'week_plan_completed'
    WEEK_REVIEW_COMPLETED = 'week_review_completed'
    QUARTER_PLAN_COMPLETED = 'quarter_plan_completed'
    MEETING_PREP_COMPLETED = 'meeting_prep_completed'
    
    # Tasks
    TASK_CREATED = 'task_created'
    TASK_COMPLETED = 'task_completed'
    
    # People & Meetings
    PERSON_PAGE_CREATED = 'person_page_created'
    MEETING_PROCESSED = 'meeting_processed'
    
    # Career
    CAREER_COACH_SESSION = 'career_coach_session'
    
    # Discovery
    LEVEL_UP_VIEWED = 'level_up_viewed'
    IDEA_CAPTURED = 'idea_captured'


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description="Fire one Dex analytics event safely.")
    parser.add_argument("--event", help="Built-in event name to record")
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        help="Delivery-only limit for a caller that must remain responsive",
    )
    args = parser.parse_args()
    if args.event:
        print(
            json.dumps(
                fire_event(
                    args.event,
                    _request_timeout_seconds=args.request_timeout_seconds,
                ),
                sort_keys=True,
            )
        )
    else:
        print("Consent status:", check_consent())
        print("\nJourney metadata:")
        for k, v in calculate_journey_metadata().items():
            print(f"  {k}: {v}")
