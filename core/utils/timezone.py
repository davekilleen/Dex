"""
Timezone utilities for Dex MCP servers.

Provides timezone-aware now() and today() that respect the user's
configured timezone in user-profile.yaml, falling back to system local time.
"""

import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_cached_tz = None
_cache_loaded = False


def _load_user_timezone() -> ZoneInfo | None:
    """Load timezone from user-profile.yaml. Returns None if not configured."""
    try:
        import yaml
    except ImportError:
        return None

    vault_path = Path(os.environ.get('VAULT_PATH', Path.cwd()))
    profile_path = vault_path / "System" / "user-profile.yaml"

    if not profile_path.exists():
        return None

    try:
        with open(profile_path, 'r') as f:
            profile = yaml.safe_load(f)
        tz_str = (profile or {}).get('timezone', '')
        if tz_str:
            return ZoneInfo(tz_str)
    except (ZoneInfoNotFoundError, Exception):
        pass

    return None


def get_user_timezone() -> ZoneInfo | None:
    """Get the user's configured timezone, with caching."""
    global _cached_tz, _cache_loaded
    if not _cache_loaded:
        _cached_tz = _load_user_timezone()
        _cache_loaded = True
    return _cached_tz


def now() -> datetime:
    """Get current datetime in user's timezone, falling back to system local."""
    tz = get_user_timezone()
    if tz:
        return datetime.now(tz)
    return datetime.now().astimezone()


def today() -> date:
    """Get today's date in user's timezone, falling back to system local."""
    return now().date()


def detect_system_timezone() -> str:
    """Detect the system's IANA timezone string. Used during onboarding."""
    try:
        local_now = datetime.now().astimezone()
        tz_name = local_now.tzinfo.tzname(local_now)

        # Try to get IANA name from the system
        # macOS/Linux: read /etc/localtime symlink
        import subprocess
        result = subprocess.run(
            ['readlink', '/etc/localtime'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and 'zoneinfo/' in result.stdout:
            iana = result.stdout.strip().split('zoneinfo/')[-1]
            try:
                ZoneInfo(iana)
                return iana
            except ZoneInfoNotFoundError:
                pass

        # Fallback: try macOS systemsetup
        result = subprocess.run(
            ['systemsetup', '-gettimezone'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and 'Time Zone:' in result.stdout:
            iana = result.stdout.split('Time Zone:')[-1].strip()
            try:
                ZoneInfo(iana)
                return iana
            except ZoneInfoNotFoundError:
                pass

    except Exception:
        pass

    return ""
