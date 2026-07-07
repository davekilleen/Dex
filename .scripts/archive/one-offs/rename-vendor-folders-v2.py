#!/usr/bin/env python3
"""Rename remaining TBD vendor folders using fuzzy matching against pipeline data."""

import json
import os
import re
import sys

VAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS = os.path.join(VAULT, "04-Projects")

pipeline = json.loads(sys.stdin.read())

def normalize(s):
    """Strip special chars for matching."""
    s = s.replace("/", "").replace("\\", "").replace("'", "").replace("’", "")
    s = s.replace("–", "-").replace("—", "-").replace("‘", "").replace("“", "").replace("”", "")
    s = re.sub(r'[^\w\s-]', '', s)
    return re.sub(r'\s+', ' ', s).strip().lower()

# Build lookup
opp_lookup = {}
for opp in pipeline.get("opportunities", []):
    key = normalize(opp["name"])
    opp_lookup[key] = opp.get("vendor", "TBD")
    # Also index by account + opp name combo
    combo = normalize(opp.get("account", "") + " " + opp["name"])
    opp_lookup[combo] = opp.get("vendor", "TBD")

renamed = 0
still_tbd = []

for folder in sorted(os.listdir(PROJECTS)):
    folder_path = os.path.join(PROJECTS, folder)
    if not os.path.isdir(folder_path) or not folder.endswith(" - TBD"):
        continue

    norm_folder = normalize(folder)
    matched_vendor = None

    # Try each pipeline opp name against the folder name
    for opp in pipeline.get("opportunities", []):
        norm_opp = normalize(opp["name"])
        norm_account = normalize(opp.get("account", ""))
        if norm_opp in norm_folder or (norm_account in norm_folder and len(norm_account) > 5):
            # Check if opp name parts match significantly
            opp_parts = norm_opp.split(" - ")
            if any(p in norm_folder for p in opp_parts if len(p) > 3):
                matched_vendor = opp.get("vendor", "TBD")
                break

    if not matched_vendor or matched_vendor == "TBD":
        still_tbd.append(folder)
        continue

    new_folder = folder.rsplit(" - TBD", 1)[0] + f" - {matched_vendor}"
    new_folder_path = os.path.join(PROJECTS, new_folder)

    if os.path.exists(new_folder_path):
        still_tbd.append(f"TARGET EXISTS: {new_folder}")
        continue

    try:
        os.rename(folder_path, new_folder_path)
        for f in os.listdir(new_folder_path):
            if f.endswith(".md") and f != "README.md" and " - TBD" in f:
                old_md = os.path.join(new_folder_path, f)
                new_md = os.path.join(new_folder_path, f.rsplit(" - TBD", 1)[0] + f" - {matched_vendor}.md")
                os.rename(old_md, new_md)
        renamed += 1
        print(f"  Renamed: {folder}  ->  {new_folder}")
    except Exception as e:
        still_tbd.append(f"ERROR: {folder} - {e}")

print(f"\nDone: {renamed} renamed, {len(still_tbd)} still TBD")
for s in still_tbd:
    print(f"  {s}")
