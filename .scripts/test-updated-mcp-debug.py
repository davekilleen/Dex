#!/usr/bin/env python3
"""
Debug test to find the exact error in search
"""
import sys
import os
import traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core', 'mcp'))

from granola_server import search_meetings

print("Testing search with detailed error tracking...")
try:
    results = search_meetings(query="Dave", days_back=30, limit=3)
    print(f"Success! Found {len(results)} meetings")
    for meeting in results:
        print(f"  - {meeting.get('title')}")
except Exception as e:
    print(f"Error: {e}")
    traceback.print_exc()
