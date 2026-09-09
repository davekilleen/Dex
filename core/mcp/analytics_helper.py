#!/usr/bin/env python3
"""
Dex Analytics Helper

Shared utilities for analytics across Dex skills and MCPs.
Handles consent checking, journey metadata calculation, and event firing.

Privacy Principles:
- Only tracks Dex built-in features, not user customizations
- Tracks THAT features were used, not WHAT users did with them
- Never sends content, names, notes, or conversations

Usage in skills:
    from analytics_helper import fire_event, check_consent, mark_feature_used
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.analytics_events import (
    REDACTED_ANALYTICS_EVENT_NAME,
    is_safe_analytics_event_name,
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


# One definition of where the adoption log lives, so the reader and the writer
# below can never disagree about the file they are talking about.
USAGE_LOG_RELATIVE_PARTS = ('System', 'usage_log.md')

# A feature line looks like "- [ ] Daily planning (`/daily-plan`)". Group 2 is the
# only character this module ever rewrites.
_CHECKBOX_RE = re.compile(r'^(\s*-\s+\[)([ xX])(\]\s+)(\S.*?)\s*$')

# The slash-command inside a label, e.g. "(`/daily-plan`)" -> "daily-plan".
_COMMAND_RE = re.compile(r'`/([a-z0-9][a-z0-9-]*)`', re.IGNORECASE)


def get_usage_log_path() -> Path:
    """Absolute path to the adoption log."""
    return get_vault_path().joinpath(*USAGE_LOG_RELATIVE_PARTS)


def load_usage_log() -> Dict[str, Any]:
    """Parse usage_log.md into structured data."""
    usage_path = get_usage_log_path()
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


def _rewrite_usage_log_safely(transform):
    """Route every adoption-log write through the lifecycle transaction core.

    Dex's vault-mutation contract requires vault writes to go through
    `core/lifecycle/service.py`. Writing this file directly is unsafe against a
    symlinked `System` directory, silently loosens a tightened file mode, and
    lets a feature tick race a consent update. Imported lazily so the MCP
    helper keeps starting on installs that do not carry the lifecycle package.
    """
    from core.lifecycle.service import rewrite_usage_log

    return rewrite_usage_log(get_vault_path(), transform)


def _match_feature_lines(lines: List[str], feature: str) -> List[int]:
    """Line indexes whose checkbox label identifies `feature`.

    Matching is deliberately narrow and ordered, so a caller either gets one
    obvious line or an honest report that it could not tell them apart:

    1. the slash-command in the label ("/daily-plan" matches "(`/daily-plan`)")
    2. the whole label, case-insensitively
    3. the label with its command stripped, case-insensitively

    A broader fuzzy fallback is deliberately absent: silently marking the wrong
    milestone is worse than reporting that the name was ambiguous.
    """
    wanted = feature.strip().lstrip('/').strip()
    if not wanted:
        return []
    wanted_lower = wanted.lower()

    by_command: List[int] = []
    by_label: List[int] = []
    for index, line in enumerate(lines):
        match = _CHECKBOX_RE.match(line)
        if not match:
            continue
        label = match.group(4).strip()
        commands = [c.lower() for c in _COMMAND_RE.findall(label)]
        if wanted_lower in commands:
            by_command.append(index)
            continue
        bare = _COMMAND_RE.sub('', label).strip(' ()').strip()
        if label.lower() == wanted_lower or bare.lower() == wanted_lower:
            by_label.append(index)

    return by_command or by_label


def mark_feature_used(feature: str) -> Dict[str, Any]:
    """Tick one adoption checkbox in usage_log.md.

    Local bookkeeping only. This never sends anything, and it is deliberately
    NOT gated on analytics consent: the log records which Dex features this
    vault has used so `/dex-level-up` can recommend the ones it has not, which
    is useful whether or not the user shares anything.

    Returns a status rather than raising, so a caller can record the outcome
    without a failure interrupting the work the user actually asked for:

      marked          - a box was unticked and is now ticked
      already_marked  - the box was already ticked, nothing written
      ambiguous       - several boxes match; candidates returned, nothing written
      not_found       - no box matches that feature
      unavailable     - the log is missing or could not be read
    """
    usage_path = get_usage_log_path()
    try:
        content = usage_path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return {'status': 'unavailable', 'feature': feature, 'reason': 'usage log not found'}
    except OSError as exc:
        return {'status': 'unavailable', 'feature': feature, 'reason': str(exc)}

    # Decide the outcome from a plain read first, so the caller gets the same
    # statuses as before without opening a transaction for a no-op.
    lines = content.splitlines(keepends=True)
    matches = _match_feature_lines(lines, feature)

    if not matches:
        return {'status': 'not_found', 'feature': feature}

    if len(matches) > 1:
        candidates = [_CHECKBOX_RE.match(lines[i]).group(4).strip() for i in matches]
        return {'status': 'ambiguous', 'feature': feature, 'candidates': candidates}

    label = _CHECKBOX_RE.match(lines[matches[0]]).group(4).strip()
    if _CHECKBOX_RE.match(lines[matches[0]]).group(2).lower() == 'x':
        return {'status': 'already_marked', 'feature': feature, 'label': label}

    def _tick(current: str) -> Optional[str]:
        """Re-match against the text the transaction actually read.

        This runs again on a stale retry, so it must not close over the
        content read above: another writer may have ticked this very box.
        """
        rows = current.splitlines(keepends=True)
        found = _match_feature_lines(rows, feature)
        if len(found) != 1:
            return None
        index = found[0]
        body = rows[index]
        ending = ''
        while body.endswith(('\n', '\r')):
            ending = body[-1] + ending
            body = body[:-1]
        match = _CHECKBOX_RE.match(body)
        if match is None or match.group(2).lower() == 'x':
            return None
        rows[index] = f"{match.group(1)}x{match.group(3)}{match.group(4)}{ending}"
        return ''.join(rows)

    try:
        outcome = _rewrite_usage_log_safely(_tick)
    except Exception as exc:  # the service refuses rather than writes unsafely
        return {'status': 'unavailable', 'feature': feature, 'reason': str(exc)}

    if outcome.get('status') == 'unchanged':
        return {'status': 'already_marked', 'feature': feature, 'label': label}
    return {'status': 'marked', 'feature': feature, 'label': label}


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
    """
    Check if analytics is active and able to send.

    Requires both recorded opt-in consent and a configured transport.
    A shipped proxy with a blank relay address is not active.
    """
    if check_consent() != 'opted-in':
        return False
    return bool(get_analytics_transport().get('configured'))


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
    """Get visitor ID and account ID from user-profile.yaml.
    
    Priority for visitor_id:
    1. analytics.visitor_id from user-profile.yaml (explicit config)
    2. Deterministic hash of user's name (stable across restarts)
    3. 'anonymous' fallback (never random)
    """
    profile = load_user_profile()
    analytics = profile.get('analytics', {})
    
    # Priority 1: Explicit visitor_id in analytics config
    visitor_id = analytics.get('visitor_id')
    
    if not visitor_id:
        # Priority 2: Deterministic hash of name
        name = profile.get('name', '')
        if name:
            visitor_id = hashlib.sha256(name.encode()).hexdigest()[:16]
        else:
            # Priority 3: Fallback
            visitor_id = 'anonymous'
    
    # Account ID from email domain or default
    account_id = analytics.get('account_id') or profile.get('email_domain', 'dex-users')
    
    return {
        'visitor_id': visitor_id,
        'account_id': account_id
    }


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
    Fire an analytics event to Pendo.
    
    Only fires if user has opted in. Automatically includes journey metadata.
    
    Args:
        event_name: Name of the event (e.g., 'daily_plan_completed')
        properties: Additional event properties (counts, categories only - no content!)
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

        if _connection_test:
            # A connection check must prove only that the transport works. It
            # must never read or send a person's identity, profile, journey
            # metadata, or caller-supplied properties.
            visitor_info = {
                'visitor_id': _CONNECTION_TEST_VISITOR_ID,
                'account_id': _CONNECTION_TEST_ACCOUNT_ID,
            }
            event_props = {'connection_test': True}
        else:
            visitor_info = get_visitor_info()
            journey = calculate_journey_metadata()
            profile = load_user_profile()

            # Build properties with journey context.
            event_props = {
                'journey_stage': journey['journey_stage'],
                'days_since_setup': journey['days_since_setup'],
                'feature_adoption_score': journey['feature_adoption_score'],
                'most_active_area': journey['most_active_area'],
                'role': profile.get('role_group', 'unknown'),
                'company_size': profile.get('company_size', 'unknown'),
                **(properties or {})
            }

        payload = {
            'type': 'track',
            'event': event_name,
            'visitorId': visitor_info['visitor_id'],
            'accountId': visitor_info['account_id'],
            'timestamp': int(datetime.now(timezone.utc).timestamp() * 1000),
            'properties': event_props
        }

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
    """Record a consent decision in usage_log.md.

    Goes through the same lifecycle operation as a feature tick. That is what
    makes the concurrency guarantee real: two direct writers to one file can
    each read, modify and write a whole file and silently lose the other's
    change, and consent is the half you least want to lose.

    Args:
        decision: 'opted-in' or 'opted-out'
    """
    today = datetime.now().strftime('%Y-%m-%d')

    def _apply(current: str) -> Optional[str]:
        updated = re.sub(
            r'\*\*Consent asked:\*\* \w+',
            '**Consent asked:** true',
            current,
        )
        updated = re.sub(
            r'\*\*Consent decision:\*\* [\w-]+',
            f'**Consent decision:** {decision}',
            updated,
        )
        updated = re.sub(
            r'\*\*Consent date:\*\* .+',
            f'**Consent date:** {today}',
            updated,
        )
        return updated

    try:
        _rewrite_usage_log_safely(_apply)
    except Exception:
        # Preserve the prior contract: this returned silently when the log was
        # missing or unwritable, and callers do not check a result.
        return


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
