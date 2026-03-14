#!/usr/bin/env python3
"""
Direct Office 365 calendar queries via Microsoft Graph.

Usage:
    calendar_office365.py list
    calendar_office365.py events <calendar_name> <start_offset> <end_offset>
    calendar_office365.py search <calendar_name> <query> <days_back> <days_forward>
    calendar_office365.py next <calendar_name>
    calendar_office365.py attendees <calendar_name> <start_offset> <end_offset>
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml


def _load_dotenv_into_env(vault_path: Path) -> None:
    """Load .env values into process env if missing."""
    env_path = vault_path / ".env"
    if not env_path.exists():
        return

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _read_profile(vault_path: Path) -> dict:
    profile_path = vault_path / "System" / "user-profile.yaml"
    if not profile_path.exists():
        return {}
    try:
        return yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _parse_graph_datetime(date_time: str, tz_name: str) -> datetime:
    """
    Parse Graph event datetime into timezone-aware datetime.
    Graph often returns local dateTime without offset + separate timeZone.
    """
    dt_str = (date_time or "").strip()
    if dt_str.endswith("Z"):
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))

    # Has offset already
    if "+" in dt_str[10:] or "-" in dt_str[10:]:
        return datetime.fromisoformat(dt_str)

    tz = ZoneInfo(tz_name) if tz_name else timezone.utc
    naive = datetime.fromisoformat(dt_str)
    return naive.replace(tzinfo=tz)


def _format_dt_for_dex(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S %z")


class GraphCalendarClient:
    def __init__(self):
        vault_path = Path(os.environ.get("VAULT_PATH", Path.cwd()))
        _load_dotenv_into_env(vault_path)
        self.profile = _read_profile(vault_path)
        self.timezone = self.profile.get("timezone", "UTC")

        self.tenant_id = os.environ.get("MS_TENANT_ID", "").strip()
        self.client_id = os.environ.get("MS_CLIENT_ID", "").strip()
        self.client_secret = os.environ.get("MS_CLIENT_SECRET", "").strip()
        self.refresh_token = os.environ.get("MS_REFRESH_TOKEN", "").strip()
        self.user_email = (
            os.environ.get("MS_USER_EMAIL", "").strip()
            or self.profile.get("calendar", {}).get("office365_user", "")
            or self.profile.get("work_email", "")
        )
        self._mode = "unknown"

    def _token_endpoint(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"

    def _require_base_creds(self):
        missing = []
        if not self.tenant_id:
            missing.append("MS_TENANT_ID")
        if not self.client_id:
            missing.append("MS_CLIENT_ID")
        if not self.client_secret:
            missing.append("MS_CLIENT_SECRET")
        if missing:
            raise RuntimeError(f"Missing Office 365 credentials: {', '.join(missing)}")

    def get_access_token(self) -> str:
        self._require_base_creds()

        # Prefer delegated token flow if refresh token exists
        if self.refresh_token:
            base_payload = {
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "refresh_token": self.refresh_token,
                "scope": "openid profile offline_access email User.Read Calendars.Read",
            }
            attempts = []
            # Confidential client flow
            attempts.append({**base_payload, "client_secret": self.client_secret})
            # Public client flow
            attempts.append(base_payload)

            for payload in attempts:
                response = requests.post(self._token_endpoint(), data=payload, timeout=20)
                if response.ok:
                    token = response.json().get("access_token")
                    if token:
                        self._mode = "delegated"
                        return token
                # If invalid_client, try next variant; otherwise keep current behavior and continue.

        # Fallback to app-only flow
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
        }
        response = requests.post(self._token_endpoint(), data=payload, timeout=20)
        if not response.ok:
            raise RuntimeError(f"Token request failed: {response.status_code} {response.text[:400]}")
        token = response.json().get("access_token")
        if not token:
            raise RuntimeError("Token response missing access_token")
        self._mode = "application"
        return token

    def _principal_path(self) -> str:
        # Ensure auth mode is known before deciding /me vs /users/{email}
        if self._mode == "unknown":
            self.get_access_token()
        if self._mode == "application":
            if not self.user_email:
                raise RuntimeError(
                    "App-only token requires mailbox target. Set MS_USER_EMAIL or "
                    "System/user-profile.yaml -> calendar.office365_user"
                )
            return f"/users/{self.user_email}"
        return "/me"

    def _request(self, path: str, params: dict | None = None) -> dict:
        token = self.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Prefer": f'outlook.timezone="{self.timezone}"',
        }
        url = f"https://graph.microsoft.com/v1.0{path}"
        response = requests.get(url, headers=headers, params=params or {}, timeout=20)
        if not response.ok:
            raise RuntimeError(f"Graph request failed: {response.status_code} {response.text[:500]}")
        return response.json()

    def list_calendars(self) -> list[dict]:
        base = self._principal_path()
        data = self._request(f"{base}/calendars", params={"$top": 200})
        items = data.get("value", [])
        return [
            {
                "title": cal.get("name", ""),
                "type": "office365",
                "color": cal.get("hexColor"),
                "identifier": cal.get("id"),
            }
            for cal in items
        ]

    def _resolve_calendar_id(self, calendar_name: str) -> str | None:
        if not calendar_name or calendar_name.lower() == "work":
            return None
        if calendar_name.lower() == "all":
            return "all"
        calendars = self.list_calendars()
        for cal in calendars:
            if cal["identifier"] == calendar_name or cal["title"].lower() == calendar_name.lower():
                return cal["identifier"]
        return None

    def _calendar_view(self, calendar_name: str, start_dt: datetime, end_dt: datetime) -> list[dict]:
        base = self._principal_path()
        cal_id = self._resolve_calendar_id(calendar_name)
        params = {
            "startDateTime": start_dt.isoformat(),
            "endDateTime": end_dt.isoformat(),
            "$top": 200,
            "$orderby": "start/dateTime",
        }

        # all calendars requested: aggregate each explicit calendar
        if cal_id == "all":
            events = []
            for cal in self.list_calendars():
                cid = cal.get("identifier")
                if not cid:
                    continue
                data = self._request(f"{base}/calendars/{cid}/calendarView", params=params)
                events.extend(data.get("value", []))
            return events

        if cal_id:
            path = f"{base}/calendars/{cal_id}/calendarView"
        else:
            path = f"{base}/calendarView"
        data = self._request(path, params=params)
        return data.get("value", [])

    @staticmethod
    def _format_attendee(att: dict) -> dict:
        status_raw = ((att.get("status") or {}).get("response") or "unknown").lower()
        status_map = {
            "accepted": "Accepted",
            "declined": "Declined",
            "tentativelyaccepted": "Tentative",
            "notresponded": "Pending",
            "organizer": "Accepted",
        }
        email = ((att.get("emailAddress") or {}).get("address") or "").lower()
        return {
            "name": ((att.get("emailAddress") or {}).get("name") or "").strip(),
            "email": email,
            "status": status_map.get(status_raw, "Unknown"),
            "type": "Person",
            "is_organizer": bool(att.get("isOrganizer", False)),
        }

    def _to_dex_event(self, ev: dict, include_attendees: bool = False) -> dict:
        start = ev.get("start") or {}
        end = ev.get("end") or {}
        start_dt = _parse_graph_datetime(start.get("dateTime", ""), start.get("timeZone", self.timezone))
        end_dt = _parse_graph_datetime(end.get("dateTime", ""), end.get("timeZone", self.timezone))
        item = {
            "title": ev.get("subject") or "",
            "start": _format_dt_for_dex(start_dt),
            "end": _format_dt_for_dex(end_dt),
            "location": (ev.get("location") or {}).get("displayName", "") or "",
            "url": ev.get("webLink") or "",
            "notes": ev.get("bodyPreview") or "",
            "all_day": bool(ev.get("isAllDay", False)),
        }
        if include_attendees:
            item["attendees"] = [self._format_attendee(a) for a in (ev.get("attendees") or [])]
        return item

    def get_events(self, calendar_name: str, start_offset: int, end_offset: int, include_attendees: bool = False) -> list[dict]:
        today = datetime.now(ZoneInfo(self.timezone)).replace(hour=0, minute=0, second=0, microsecond=0)
        start_dt = today + timedelta(days=start_offset)
        end_dt = today + timedelta(days=end_offset)
        events = self._calendar_view(calendar_name, start_dt, end_dt)
        return [self._to_dex_event(ev, include_attendees=include_attendees) for ev in events]

    def search_events(self, calendar_name: str, query: str, days_back: int, days_forward: int) -> list[dict]:
        now = datetime.now(ZoneInfo(self.timezone))
        start_dt = now - timedelta(days=days_back)
        end_dt = now + timedelta(days=days_forward)
        events = self._calendar_view(calendar_name, start_dt, end_dt)
        q = query.lower()
        filtered = [ev for ev in events if q in (ev.get("subject") or "").lower()]
        return [self._to_dex_event(ev, include_attendees=False) for ev in filtered]

    def next_event(self, calendar_name: str) -> dict | None:
        now = datetime.now(ZoneInfo(self.timezone))
        end_dt = now + timedelta(days=90)
        events = self._calendar_view(calendar_name, now, end_dt)
        if not events:
            return None
        events.sort(key=lambda e: (e.get("start") or {}).get("dateTime", ""))
        return self._to_dex_event(events[0], include_attendees=False)


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  calendar_office365.py list")
        print("  calendar_office365.py events <calendar> <start_offset> <end_offset>")
        print("  calendar_office365.py search <calendar> <query> <days_back> <days_forward>")
        print("  calendar_office365.py next <calendar>")
        print("  calendar_office365.py attendees <calendar> <start_offset> <end_offset>")
        sys.exit(1)

    command = sys.argv[1]
    client = GraphCalendarClient()

    try:
        if command == "list":
            print(json.dumps(client.list_calendars(), indent=2))
            return

        if command == "events":
            if len(sys.argv) != 5:
                raise RuntimeError("Usage: calendar_office365.py events <calendar> <start_offset> <end_offset>")
            calendar_name = sys.argv[2]
            start_offset = int(sys.argv[3])
            end_offset = int(sys.argv[4])
            print(json.dumps(client.get_events(calendar_name, start_offset, end_offset, include_attendees=False), indent=2))
            return

        if command == "attendees":
            if len(sys.argv) != 5:
                raise RuntimeError("Usage: calendar_office365.py attendees <calendar> <start_offset> <end_offset>")
            calendar_name = sys.argv[2]
            start_offset = int(sys.argv[3])
            end_offset = int(sys.argv[4])
            print(json.dumps(client.get_events(calendar_name, start_offset, end_offset, include_attendees=True), indent=2))
            return

        if command == "search":
            if len(sys.argv) != 6:
                raise RuntimeError("Usage: calendar_office365.py search <calendar> <query> <days_back> <days_forward>")
            calendar_name = sys.argv[2]
            query = sys.argv[3]
            days_back = int(sys.argv[4])
            days_forward = int(sys.argv[5])
            print(json.dumps(client.search_events(calendar_name, query, days_back, days_forward), indent=2))
            return

        if command == "next":
            if len(sys.argv) != 3:
                raise RuntimeError("Usage: calendar_office365.py next <calendar>")
            calendar_name = sys.argv[2]
            event = client.next_event(calendar_name)
            if event is None:
                print(json.dumps({"message": "No upcoming events found"}))
            else:
                print(json.dumps(event, indent=2))
            return

        raise RuntimeError(f"Unknown command: {command}")

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
