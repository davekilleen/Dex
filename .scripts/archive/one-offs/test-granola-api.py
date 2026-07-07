#!/usr/bin/env python3
"""
Test script to verify Granola API access works
"""
import json
import requests
from pathlib import Path

# Read credentials
creds_path = Path.home() / "Library/Application Support/Granola/supabase.json"
with open(creds_path, 'r') as f:
    data = json.load(f)

# Parse the workos_tokens string into a dict
workos_tokens = json.loads(data['workos_tokens'])
access_token = workos_tokens.get('access_token')

print(f"✓ Found access token: {access_token[:50]}...")

# Test API call
url = "https://api.granola.ai/v2/get-documents"
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json",
    "Accept": "*/*",
    "User-Agent": "Granola/5.354.0",
    "X-Client-Version": "5.354.0"
}
data = {
    "limit": 5,  # Just get 5 meetings to test
    "offset": 0,
    "include_last_viewed_panel": True
}

print(f"\n→ Testing API call to {url}")
response = requests.post(url, headers=headers, json=data)

print(f"✓ Status Code: {response.status_code}")

if response.status_code == 200:
    result = response.json()
    docs = result.get("docs", [])
    print(f"✓ Successfully retrieved {len(docs)} documents")
    
    # Show first meeting details
    if docs:
        first_doc = docs[0]
        print(f"\n✓ First meeting:")
        print(f"  - Title: {first_doc.get('title', 'Untitled')}")
        print(f"  - ID: {first_doc.get('id', 'N/A')}")
        print(f"  - Created: {first_doc.get('created_at', 'N/A')}")
        
        # Check if it has content in last_viewed_panel
        if first_doc.get('last_viewed_panel'):
            panel = first_doc['last_viewed_panel']
            if panel.get('content'):
                print(f"  - Has content: YES")
                content = panel['content']
                if content.get('content'):
                    print(f"  - Content blocks: {len(content.get('content', []))}")
            else:
                print(f"  - Has content: NO")
        else:
            print(f"  - Has last_viewed_panel: NO")
    
    print(f"\n✓ API TEST SUCCESSFUL!")
else:
    print(f"✗ API call failed: {response.status_code}")
    print(f"Response: {response.text}")
