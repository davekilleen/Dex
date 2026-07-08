#!/usr/bin/env python3
"""
gather-meeting-data.py

Queries Salesforce for company/contact details and vault files to build
meeting attendee lists. Output formatted for create-meeting-invite.ps1.

Usage:
    python gather-meeting-data.py --company "Winholt Equipment" --output winholt-invite.json
"""

import json
import sys
import os
import re
import argparse
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

@dataclass
class Attendee:
    name: str
    email: str
    role: Optional[str] = None
    account: Optional[str] = None
    type: str = "Required"  # Required or Optional

@dataclass
class MeetingData:
    title: str
    company: str
    attendees: List[Attendee]
    suggested_date: Optional[str] = None
    suggested_time: Optional[str] = None
    location: Optional[str] = None
    context: Optional[str] = None
    recent_activity: Optional[str] = None

class MeetingDataGatherer:
    def __init__(self, vault_root: Path = None):
        if vault_root is None:
            vault_root = Path.cwd()
        self.vault_root = vault_root
        self.people_dir = vault_root / "People"
        self.projects_dir = vault_root / "Projects"
        self.inbox_dir = vault_root / "Inbox"

    def search_salesforce_account(self, company_name: str) -> Optional[Dict]:
        """Query Salesforce for account by name."""
        # This would normally use mcp__06a829d1-998d-4b20-b5a3-f277de704474__search_accounts
        # For now, return mock data for Winholt Equipment
        if "winholt" in company_name.lower():
            return {
                "id": "001xx000003DHzAAM",
                "name": "Winholt Equipment",
                "phone": "(610) 555-0123",
                "city": "Bensalem, PA",
                "type": "Customer"
            }
        return None

    def search_salesforce_contacts(self, account_id: str, account_name: str) -> List[Dict]:
        """Query Salesforce for contacts under an account."""
        # This would normally use mcp__06a829d1-998d-4b20-b5a3-f277de704474__get_account_contacts
        # For now, return mock data
        if "winholt" in account_name.lower():
            return [
                {
                    "id": "003xx000004B3ZAAA",
                    "name": "Steve Malaro",
                    "email": "steve.malaro@winholt.com",
                    "title": "Equipment Manager",
                    "phone": "(610) 555-0124"
                },
                {
                    "id": "003xx000004B3ZBAAA",
                    "name": "John Winholt",
                    "email": "john@winholt.com",
                    "title": "Owner",
                    "phone": "(610) 555-0125"
                }
            ]
        return []

    def search_vault_for_company(self, company_name: str) -> Dict:
        """Search vault for company page and recent communications."""
        results = {
            "company_page": None,
            "recent_emails": [],
            "project_pages": [],
            "meeting_notes": []
        }

        # Search People/Companies/
        if self.people_dir.exists():
            companies_dir = self.people_dir / "Companies"
            if companies_dir.exists():
                for company_file in companies_dir.glob("*.md"):
                    if company_name.lower() in company_file.name.lower():
                        results["company_page"] = str(company_file)

        # Search Projects/ for matching projects
        if self.projects_dir.exists():
            for project_dir in self.projects_dir.iterdir():
                if project_dir.is_dir() and company_name.lower() in project_dir.name.lower():
                    results["project_pages"].append(str(project_dir))

        # Search Inbox/Meetings/ for recent meeting notes
        meetings_dir = self.inbox_dir / "Meetings"
        if meetings_dir.exists():
            for meeting_file in sorted(meetings_dir.glob("*.md"), reverse=True)[:5]:
                with open(meeting_file, 'r') as f:
                    content = f.read()
                    if company_name.lower() in content.lower():
                        results["meeting_notes"].append(str(meeting_file))

        return results

    def extract_email_from_person_page(self, person_name: str) -> Optional[str]:
        """Extract email from a person's vault page."""
        # Search Internal and External folders
        for folder in ["Internal", "External"]:
            people_folder = self.people_dir / folder
            if people_folder.exists():
                for person_file in people_folder.glob("*.md"):
                    if person_name.lower().replace(" ", "_") in person_file.name.lower():
                        try:
                            with open(person_file, 'r') as f:
                                content = f.read()
                                # Look for email in frontmatter or content
                                email_match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', content)
                                if email_match:
                                    return email_match.group(0)
                        except:
                            pass
        return None

    def gather_meeting_data(self, company_name: str, title: str = None) -> MeetingData:
        """Gather all meeting data from Salesforce and vault."""
        print(f"Searching for {company_name}...", file=sys.stderr)

        # Search Salesforce
        account = self.search_salesforce_account(company_name)
        contacts = []
        if account:
            contacts = self.search_salesforce_contacts(account["id"], account["name"])

        # Search vault
        vault_info = self.search_vault_for_company(company_name)

        # Build attendee list
        attendees = []
        for contact in contacts:
            attendees.append(Attendee(
                name=contact["name"],
                email=contact["email"],
                role=contact.get("title", ""),
                account=account["name"] if account else company_name,
                type="Required"
            ))

        # Generate title if not provided
        if not title:
            title = f"Meeting with {company_name}"

        # Extract context from recent communications
        context = None
        if vault_info["meeting_notes"]:
            context = f"See recent notes: {', '.join(vault_info['meeting_notes'])}"

        meeting_data = MeetingData(
            title=title,
            company=company_name,
            attendees=attendees,
            location=account.get("city") if account else None,
            context=context,
            recent_activity=json.dumps(vault_info, indent=2)
        )

        return meeting_data

def main():
    parser = argparse.ArgumentParser(description="Gather meeting data from Salesforce and vault")
    parser.add_argument("--company", required=True, help="Company name")
    parser.add_argument("--title", help="Meeting title (optional)")
    parser.add_argument("--output", help="Output JSON file")
    parser.add_argument("--format", default="json", choices=["json", "powershell"], help="Output format")

    args = parser.parse_args()

    gatherer = MeetingDataGatherer()
    meeting_data = gatherer.gather_meeting_data(args.company, args.title)

    # Convert to dict for JSON serialization
    output = {
        "title": meeting_data.title,
        "company": meeting_data.company,
        "attendees": [asdict(a) for a in meeting_data.attendees],
        "location": meeting_data.location,
        "context": meeting_data.context,
    }

    if args.format == "json":
        result = json.dumps(output, indent=2)
    else:
        # PowerShell format
        attendees_ps = ", ".join([f"'{a['email']}'" for a in output["attendees"]])
        result = f"""# Generated meeting invite for {output['company']}
$title = "{output['title']}"
$requiredAttendees = @({attendees_ps})
$optionalAttendees = @()
$location = "{output.get('location', '')}"
$body = "{output.get('context', '')}"
"""

    if args.output:
        with open(args.output, 'w') as f:
            f.write(result)
        print(f"Output written to {args.output}", file=sys.stderr)
    else:
        print(result)

if __name__ == "__main__":
    main()
