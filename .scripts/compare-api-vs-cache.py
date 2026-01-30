#!/usr/bin/env python3
"""
Compare API vs Cache to see which has more complete data
"""
import json
import requests
from pathlib import Path

# Read API credentials
creds_path = Path.home() / "Library/Application Support/Granola/supabase.json"
with open(creds_path, 'r') as f:
    data = json.load(f)
workos_tokens = json.loads(data['workos_tokens'])
access_token = workos_tokens.get('access_token')

# Read cache
cache_path = Path.home() / "Library/Application Support/Granola/cache-v3.json"
raw_data = cache_path.read_text()
cache_wrapper = json.loads(raw_data)
cache_data = json.loads(cache_wrapper.get('cache', '{}'))
cache_documents = cache_data.get('state', {}).get('documents', {})

print(f"→ Cache has {len(cache_documents)} documents")

# Get API data
url = "https://api.granola.ai/v2/get-documents"
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json",
    "Accept": "*/*",
    "User-Agent": "Granola/5.354.0",
    "X-Client-Version": "5.354.0"
}
response = requests.post(url, headers=headers, json={"limit": 100, "offset": 0, "include_last_viewed_panel": True})
api_docs = response.json().get("docs", [])

print(f"→ API returned {len(api_docs)} documents\n")

# Compare the same meetings
api_docs_by_id = {doc['id']: doc for doc in api_docs}

# Check 10 random meetings that are in both
count = 0
api_has_content = 0
cache_has_content = 0
api_only = 0
cache_only = 0
both_have = 0
neither_has = 0

for meeting_id in list(api_docs_by_id.keys())[:20]:  # Check first 20
    if meeting_id not in cache_documents:
        continue
    
    count += 1
    api_doc = api_docs_by_id[meeting_id]
    cache_doc = cache_documents[meeting_id]
    
    # Check API content
    api_content = False
    panel = api_doc.get('last_viewed_panel')
    if panel and isinstance(panel, dict):
        content = panel.get('content')
        if content and isinstance(content, dict) and content.get('content'):
            api_content = True
    
    # Check cache content
    cache_content = False
    if cache_doc.get('notes_markdown'):
        cache_content = True
    
    if api_content and cache_content:
        both_have += 1
    elif api_content and not cache_content:
        api_only += 1
        print(f"  - {api_doc.get('title', 'Untitled')[:50]}: API has content, cache doesn't")
    elif not api_content and cache_content:
        cache_only += 1
        print(f"  - {cache_doc.get('title', 'Untitled')[:50]}: Cache has content, API doesn't")
    else:
        neither_has += 1

print(f"\n→ COMPARISON (first {count} meetings):")
print(f"  - Both have content: {both_have}")
print(f"  - Only API has content: {api_only}")
print(f"  - Only Cache has content: {cache_only}")
print(f"  - Neither has content: {neither_has}")

if api_only > 0:
    print(f"\n✓ API provides {api_only} more meetings with content than cache")
elif cache_only > 0:
    print(f"\n✓ Cache provides {cache_only} more meetings with content than API")
else:
    print(f"\n→ API and Cache have equivalent content availability")
