#!/usr/bin/env python3
"""
Test the updated Granola MCP server (API-first with cache fallback)
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core', 'mcp'))

# Import the functions directly
from granola_server import (
    get_recent_meetings,
    get_meeting_details,
    search_meetings,
    get_api_access_token,
    read_granola_cache
)

print("=" * 70)
print("TESTING UPDATED GRANOLA MCP (API-first with cache fallback)")
print("=" * 70)

# Test 1: Check API token
print("\n1. Checking API token...")
token = get_api_access_token()
if token:
    print(f"   ✓ API token available: {token[:50]}...")
else:
    print("   ✗ API token not available")

# Test 2: Check cache
print("\n2. Checking cache...")
cache = read_granola_cache()
if cache:
    print(f"   ✓ Cache available with {len(cache.get('documents', {}))} documents")
else:
    print("   ✗ Cache not available")

# Test 3: Get recent meetings (should use API first)
print("\n3. Getting recent meetings (last 7 days, limit 5)...")
try:
    meetings = get_recent_meetings(days_back=7, limit=5)
    print(f"   ✓ Retrieved {len(meetings)} meetings")
    if meetings:
        first = meetings[0]
        print(f"   → First meeting: {first.get('title', 'Untitled')}")
        print(f"   → Date: {first.get('date', 'N/A')}")
        print(f"   → Data source: {first.get('source', 'unknown')}")
        print(f"   → Has notes: {'Yes' if first.get('notes') else 'No'}")
except Exception as e:
    print(f"   ✗ Error: {e}")

# Test 4: Search meetings
print("\n4. Searching for 'Dave' meetings...")
try:
    results = search_meetings(query="Dave", days_back=30, limit=3)
    print(f"   ✓ Found {len(results)} meetings")
    if results:
        for idx, meeting in enumerate(results, 1):
            print(f"   {idx}. {meeting.get('title', 'Untitled')} ({meeting.get('date', 'N/A')})")
            print(f"      Source: {meeting.get('source', 'unknown')}")
except Exception as e:
    print(f"   ✗ Error: {e}")

# Test 5: Get specific meeting details
print("\n5. Getting meeting details...")
try:
    if meetings:
        meeting_id = meetings[0]['id']
        details = get_meeting_details(meeting_id)
        if details:
            print(f"   ✓ Retrieved details for: {details.get('title', 'Untitled')}")
            print(f"   → Data source: {details.get('source', 'unknown')}")
            print(f"   → Notes length: {len(details.get('notes', ''))} chars")
            print(f"   → Action items: {len(details.get('action_items', []))}")
        else:
            print(f"   ✗ Meeting not found")
except Exception as e:
    print(f"   ✗ Error: {e}")

print("\n" + "=" * 70)
print("TEST COMPLETE")
print("=" * 70)
