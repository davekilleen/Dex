#!/usr/bin/env python3
"""Rename project folders from TBD vendor to actual vendor names using pipeline data."""

import json
import os
import re
import sys

VAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS = os.path.join(VAULT, "04-Projects")

# Pipeline data passed via stdin
pipeline = json.loads(sys.stdin.read())

# Build lookup: opp name -> vendor name
opp_vendors = {}
for opp in pipeline.get("opportunities", []):
    opp_vendors[opp["name"]] = opp.get("vendor", "TBD")

renamed = 0
skipped = 0
errors = []

for folder in sorted(os.listdir(PROJECTS)):
    folder_path = os.path.join(PROJECTS, folder)
    if not os.path.isdir(folder_path):
        continue
    if not folder.endswith(" - TBD"):
        continue

    # Extract opp name from folder: "{Account} - {Opp Name} - TBD"
    # Match against pipeline opp names
    matched_vendor = None
    matched_opp = None
    for opp_name, vendor in opp_vendors.items():
        if opp_name in folder:
            matched_vendor = vendor
            matched_opp = opp_name
            break

    if not matched_vendor or matched_vendor == "TBD":
        skipped += 1
        continue

    # Build new folder name
    new_folder = folder.rsplit(" - TBD", 1)[0] + f" - {matched_vendor}"
    new_folder_path = os.path.join(PROJECTS, new_folder)

    if os.path.exists(new_folder_path):
        errors.append(f"TARGET EXISTS: {new_folder}")
        continue

    try:
        os.rename(folder_path, new_folder_path)
        # Rename the .md file inside too
        for f in os.listdir(new_folder_path):
            if f.endswith(".md") and f != "README.md":
                old_md = os.path.join(new_folder_path, f)
                new_md_name = f.rsplit(" - TBD", 1)[0] + f" - {matched_vendor}.md" if " - TBD" in f else f
                if new_md_name != f:
                    new_md = os.path.join(new_folder_path, new_md_name)
                    os.rename(old_md, new_md)
        renamed += 1
        print(f"  Renamed: {folder}  ->  {new_folder}")
    except Exception as e:
        errors.append(f"ERROR: {folder} - {e}")

print(f"\nDone: {renamed} renamed, {skipped} skipped (no vendor match), {len(errors)} errors")
for e in errors:
    print(f"  {e}")
