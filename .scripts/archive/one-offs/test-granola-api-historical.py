#!/usr/bin/env python3
"""
Test script to verify Granola API has full content for historical meetings
"""
import json
import requests
from pathlib import Path
from datetime import datetime

# Read credentials
creds_path = Path.home() / "Library/Application Support/Granola/supabase.json"
with open(creds_path, 'r') as f:
    data = json.load(f)

# Parse the workos_tokens string into a dict
workos_tokens = json.loads(data['workos_tokens'])
access_token = workos_tokens.get('access_token')

# Get more meetings to find old ones
url = "https://api.granola.ai/v2/get-documents"
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json",
    "Accept": "*/*",
    "User-Agent": "Granola/5.354.0",
    "X-Client-Version": "5.354.0"
}
data = {
    "limit": 100,  # Get 100 meetings
    "offset": 0,
    "include_last_viewed_panel": True
}

print(f"→ Fetching 100 meetings from API...")
response = requests.post(url, headers=headers, json=data)

if response.status_code == 200:
    result = response.json()
    docs = result.get("docs", [])
    print(f"✓ Retrieved {len(docs)} documents\n")
    
    # Sort by date to find oldest
    meetings_by_date = []
    for doc in docs:
        created_at = doc.get('created_at', '')
        if created_at:
            meetings_by_date.append((created_at, doc))
    
    meetings_by_date.sort()  # Oldest first
    
    # Check oldest meeting
    if meetings_by_date:
        oldest_date, oldest_doc = meetings_by_date[0]
        print(f"→ OLDEST MEETING:")
        print(f"  - Title: {oldest_doc.get('title', 'Untitled')}")
        print(f"  - Date: {oldest_date}")
        print(f"  - ID: {oldest_doc.get('id', 'N/A')}")
        
        # Check if it has content
        has_content = False
        content_blocks = 0
        if oldest_doc.get('last_viewed_panel'):
            panel = oldest_doc['last_viewed_panel']
            if panel.get('content') and panel['content'].get('content'):
                has_content = True
                content_blocks = len(panel['content']['content'])
        
        if has_content:
            print(f"  - ✓ HAS FULL CONTENT: {content_blocks} blocks")
        else:
            print(f"  - ✗ NO CONTENT AVAILABLE")
        
        # Check a middle one (around 50th)
        if len(meetings_by_date) > 50:
            mid_date, mid_doc = meetings_by_date[50]
            print(f"\n→ MIDDLE MEETING (50th oldest):")
            print(f"  - Title: {mid_doc.get('title', 'Untitled')}")
            print(f"  - Date: {mid_date}")
            
            has_content = False
            content_blocks = 0
            if mid_doc.get('last_viewed_panel'):
                panel = mid_doc['last_viewed_panel']
                if panel.get('content') and panel['content'].get('content'):
                    has_content = True
                    content_blocks = len(panel['content']['content'])
            
            if has_content:
                print(f"  - ✓ HAS FULL CONTENT: {content_blocks} blocks")
            else:
                print(f"  - ✗ NO CONTENT AVAILABLE")
        
        # Check most recent
        newest_date, newest_doc = meetings_by_date[-1]
        print(f"\n→ NEWEST MEETING:")
        print(f"  - Title: {newest_doc.get('title', 'Untitled')}")
        print(f"  - Date: {newest_date}")
        
        has_content = False
        content_blocks = 0
        if newest_doc.get('last_viewed_panel'):
            panel = newest_doc['last_viewed_panel']
            if panel.get('content') and panel['content'].get('content'):
                has_content = True
                content_blocks = len(panel['content']['content'])
        
        if has_content:
            print(f"  - ✓ HAS FULL CONTENT: {content_blocks} blocks")
        else:
            print(f"  - ✗ NO CONTENT AVAILABLE")
        
        # Summary stats
        print(f"\n→ SUMMARY:")
        has_content_count = 0
        no_content_count = 0
        for _, doc in meetings_by_date:
            panel = doc.get('last_viewed_panel')
            if panel and isinstance(panel, dict):
                content = panel.get('content')
                if content and isinstance(content, dict) and content.get('content'):
                    has_content_count += 1
                else:
                    no_content_count += 1
            else:
                no_content_count += 1
        
        print(f"  - Total meetings: {len(meetings_by_date)}")
        print(f"  - With content: {has_content_count}")
        print(f"  - Without content: {no_content_count}")
        print(f"  - Success rate: {(has_content_count/len(meetings_by_date)*100):.1f}%")
        
else:
    print(f"✗ API call failed: {response.status_code}")
    print(f"Response: {response.text}")
