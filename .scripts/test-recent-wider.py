#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core', 'mcp'))

from granola_server import get_recent_meetings

# Test with 30 days to see if we get any meetings
print("Testing get_recent_meetings with 30 days...")
meetings = get_recent_meetings(days_back=30, limit=5)
print(f"Found {len(meetings)} meetings")

for meeting in meetings:
    print(f"\n  - {meeting.get('title', 'Untitled')}")
    print(f"    Date: {meeting.get('date', 'N/A')}")
    print(f"    Source: {meeting.get('source', 'unknown')}")
    print(f"    Has notes: {'Yes' if meeting.get('notes') else 'No'}")
    if meeting.get('notes'):
        print(f"    Notes length: {len(meeting.get('notes'))} chars")
