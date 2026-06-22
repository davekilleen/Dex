#!/usr/bin/env python3
"""Salesforce MCP server for Dex — contacts, opportunities, accounts, activities."""

import base64
import hashlib
import json
import os
import secrets
import sys
import threading
import webbrowser
from datetime import datetime, date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

VAULT_PATH = os.environ.get("VAULT_PATH", "")

# ── Config ────────────────────────────────────────────────────────────────────

CLIENT_ID = os.environ.get("SF_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SF_CLIENT_SECRET", "")
REDIRECT_URI = "http://localhost:8080/callback"
LOGIN_URL = "https://login.salesforce.com"
TOKEN_FILE = Path.home() / ".claude" / "sf_tokens.json"
OWNER_ID = os.environ.get("SF_OWNER_ID", "")


# ── Token storage ─────────────────────────────────────────────────────────────

def load_tokens():
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return None


def save_tokens(tokens):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))


def refresh_access_token(refresh_token):
    data = urlencode({
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token,
    }).encode()
    req = Request(f"{LOGIN_URL}/services/oauth2/token", data=data, method="POST")
    with urlopen(req) as resp:
        result = json.loads(resp.read())
    return result


def get_valid_tokens():
    tokens = load_tokens()
    if not tokens:
        return None
    try:
        refreshed = refresh_access_token(tokens["refresh_token"])
        tokens["access_token"] = refreshed["access_token"]
        if "instance_url" in refreshed:
            tokens["instance_url"] = refreshed["instance_url"]
        save_tokens(tokens)
        return tokens
    except Exception:
        return tokens  # return as-is and let the caller fail


# ── OAuth flow ────────────────────────────────────────────────────────────────

_auth_code = None
_auth_event = threading.Event()
_code_verifier = None


def generate_pkce():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if "code" in params:
            _auth_code = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Salesforce connected! You can close this tab.</h2></body></html>")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Auth failed - no code received.</h2></body></html>")
        _auth_event.set()

    def log_message(self, *args):
        pass  # suppress server logs


def do_oauth():
    global _auth_code, _auth_event, _code_verifier
    _auth_code = None
    _auth_event = threading.Event()
    _code_verifier, code_challenge = generate_pkce()

    auth_url = (
        f"{LOGIN_URL}/services/oauth2/authorize?"
        + urlencode({
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "scope": "api refresh_token",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        })
    )

    server = HTTPServer(("localhost", 8080), CallbackHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.daemon = True
    thread.start()

    webbrowser.open(auth_url)

    _auth_event.wait(timeout=120)
    server.server_close()

    if not _auth_code:
        raise Exception("OAuth timed out or was cancelled")

    data = urlencode({
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": _auth_code,
        "code_verifier": _code_verifier,
    }).encode()
    req = Request(f"{LOGIN_URL}/services/oauth2/token", data=data, method="POST")
    with urlopen(req) as resp:
        tokens = json.loads(resp.read())

    save_tokens(tokens)
    return tokens


# ── Salesforce REST API ───────────────────────────────────────────────────────

def sf_query(tokens, soql):
    instance_url = tokens["instance_url"]
    access_token = tokens["access_token"]
    encoded = urlencode({"q": soql})
    req = Request(
        f"{instance_url}/services/data/v59.0/query?{encoded}",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
    )
    with urlopen(req) as resp:
        return json.loads(resp.read())


def sf_post(tokens, path, payload):
    instance_url = tokens["instance_url"]
    access_token = tokens["access_token"]
    data = json.dumps(payload).encode()
    req = Request(
        f"{instance_url}/services/data/v59.0/{path}",
        data=data,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req) as resp:
        return json.loads(resp.read())


def sf_patch(tokens, path, payload):
    instance_url = tokens["instance_url"]
    access_token = tokens["access_token"]
    data = json.dumps(payload).encode()
    req = Request(
        f"{instance_url}/services/data/v59.0/{path}",
        data=data,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        method="PATCH",
    )
    with urlopen(req) as resp:
        body = resp.read()
        return json.loads(body) if body else {"success": True}


def sf_search(tokens, query):
    instance_url = tokens["instance_url"]
    access_token = tokens["access_token"]
    encoded = urlencode({"q": query})
    req = Request(
        f"{instance_url}/services/data/v59.0/search?{encoded}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urlopen(req) as resp:
        return json.loads(resp.read())


# ── Tools ─────────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "sf_authenticate",
        "description": "Authenticate with Salesforce via OAuth. Opens a browser window — log in and approve. Only needed once; tokens are saved locally.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "sf_get_pipeline",
        "description": "Get open opportunities (sales pipeline). Returns name, stage, amount, close date, account, and owner.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stage": {"type": "string", "description": "Filter by stage name (partial match, optional)"},
                "limit": {"type": "integer", "description": "Max results (default 100)"},
            },
        },
    },
    {
        "name": "sf_search_contacts",
        "description": "Search Salesforce contacts by name, email, or company.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name, email, or company to search for"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "sf_get_account",
        "description": "Get details for a Salesforce account (company) including contacts and open opportunities.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Account/company name (partial match)"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "sf_get_recent_activity",
        "description": "Get recent tasks and events logged in Salesforce.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days_back": {"type": "integer", "description": "How many days back to look (default 7)"},
                "limit": {"type": "integer", "description": "Max results (default 20)"},
            },
        },
    },
    {
        "name": "sf_get_contact",
        "description": "Get a specific contact's details including their account, recent activity, and open opportunities.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Contact name (partial match)"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "sf_get_quotes",
        "description": "Get quotes for an opportunity, including attached document metadata (ContentDocumentId, title, file type).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "opportunity_name": {"type": "string", "description": "Opportunity name (partial match)"},
                "opportunity_id": {"type": "string", "description": "Opportunity Id (exact, preferred over name)"},
            },
        },
    },
    {
        "name": "sf_download_quote_file",
        "description": "Download a quote document from Salesforce by ContentVersionId and save it to a local path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content_version_id": {"type": "string", "description": "ContentVersion Id to download"},
                "save_path": {"type": "string", "description": "Local file path to save to (relative to vault or absolute)"},
            },
            "required": ["content_version_id", "save_path"],
        },
    },
    {
        "name": "sf_get_opportunity",
        "description": "Get full details for a single opportunity including contacts, quotes, and recent activity. Pass either 'name' (partial match) or 'id' (exact Salesforce Id).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Opportunity name (partial match)"},
                "id": {"type": "string", "description": "Exact Salesforce Opportunity Id (18-char, e.g. 006Nu00000...)"},
            },
        },
    },
    {
        "name": "sf_create_task",
        "description": "Log an activity (task) to Salesforce. Use to record meetings, calls, notes, or completed tasks against an opportunity or contact. Returns the new Task Id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Task subject line (e.g. 'Meeting: Pricing Discussion', 'Call: Follow-up on quote')"},
                "description": {"type": "string", "description": "Full task description or meeting notes"},
                "activity_date": {"type": "string", "description": "Date of the activity in YYYY-MM-DD format (defaults to today)"},
                "status": {"type": "string", "description": "Task status: Completed (default), In Progress, Not Started"},
                "what_id": {"type": "string", "description": "Salesforce Opportunity or Account Id to link this task to (WhatId)"},
                "who_id": {"type": "string", "description": "Salesforce Contact Id to link this task to (WhoId)"},
                "type": {"type": "string", "description": "Activity type: Call, Email, Meeting, Note (optional)"},
            },
            "required": ["subject"],
        },
    },
    {
        "name": "sf_get_open_tasks",
        "description": "Get open (not completed) tasks assigned to you in Salesforce. Returns subject, due date, related opportunity/account, and status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max results (default 50)"},
                "due_before": {"type": "string", "description": "Only return tasks due before this date (YYYY-MM-DD, optional)"},
            },
        },
    },
    {
        "name": "sf_get_completed_tasks",
        "description": "Get completed tasks logged in Salesforce within a date range. Returns subject, description/comments, date, contact, and related record. Use to review activity history or analyze note-writing patterns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "Start date (YYYY-MM-DD, default 365 days ago)"},
                "date_to": {"type": "string", "description": "End date (YYYY-MM-DD, default today)"},
                "limit": {"type": "integer", "description": "Max results (default 50)"},
                "has_description": {"type": "boolean", "description": "If true, only return tasks that have a non-empty Description/comment field (default false)"},
            },
        },
    },
    {
        "name": "sf_get_project_management",
        "description": "Get Project Management records (Project_Management__c — closed won orders in delivery). Returns account, machine type/model, ship date, install date, and checkbox milestone status (Deposit_Paid__c, PIM_Sent__c, Intro_Customer_Call__c, Intro_Vendor_Email__c). Auto-computes pending actions based on days until install. Use in daily planning to surface upcoming deliveries and overdue milestones.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max results (default 50)"},
                "days_ahead": {"type": "integer", "description": "Only return records with install date within this many days (optional)"},
            },
        },
    },
    {
        "name": "sf_update_opportunity_notes",
        "description": "Update the Next Steps and/or Description fields on a Salesforce opportunity. Use after decisions are made or next actions are defined.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "opportunity_id": {"type": "string", "description": "Salesforce Opportunity Id (exact)"},
                "next_step": {"type": "string", "description": "Next steps text to set on the opportunity"},
                "description": {"type": "string", "description": "Description/notes to set on the opportunity"},
            },
            "required": ["opportunity_id"],
        },
    },
    # ── Asset / Equipment Intelligence (EDA Data synced to SF) ──────────────────
    {
        "name": "sf_get_account_assets",
        "description": "Get all equipment (assets) on record for a specific account. Returns machine type, model, builder, install date, lease/usage end date, UCC data, and expiry status. Use for customer equipment floor analysis and lease expiration tracking.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "account_name": {"type": "string", "description": "Account name (partial match OK)"},
                "account_id": {"type": "string", "description": "Salesforce Account Id (exact, preferred over name)"},
                "include_competitor": {"type": "boolean", "description": "Include competitor equipment (default true)"},
            },
        },
    },
    {
        "name": "sf_get_assets_expiring_soon",
        "description": "Get all assets across every account whose UsageEndDate (lease/financing end) falls within the next N months. Returns urgency ratings: CRITICAL (0-90 days), HIGH (90-180 days), MEDIUM (180-365 days). Use for weekly lease expiration alerts and outreach prioritization.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "months": {"type": "integer", "description": "Look-ahead window in months (default 12)"},
            },
        },
    },
    {
        "name": "sf_search_assets",
        "description": "Search assets across all accounts by machine type, builder/manufacturer, sale-or-lease status, or other criteria. Use for territory analysis, lookalike prospecting, and finding all accounts with a specific machine type.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "machine_type": {"type": "string", "description": "Machine type keyword (e.g. 'laser', 'press brake', 'VMC')"},
                "builder": {"type": "string", "description": "Manufacturer/builder name (e.g. 'Trumpf', 'Amada', 'Mazak')"},
                "account_name": {"type": "string", "description": "Filter to specific account (partial match)"},
                "competitor_only": {"type": "boolean", "description": "Return only competitor equipment (IsCompetitorProduct = true)"},
                "sale_or_lease": {"type": "string", "description": "Filter by Sale or Lease picklist value"},
                "status": {"type": "string", "description": "Asset status filter"},
                "limit": {"type": "integer", "description": "Max results (default 100)"},
            },
        },
    },
    {
        "name": "sf_get_competitor_assets",
        "description": "Get all competitor equipment tracked across accounts. Returns a breakdown by competitor brand. Use to understand competitive penetration, identify displacement opportunities, and time conversations around aging competitor equipment.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "account_name": {"type": "string", "description": "Filter to a specific account (optional, partial match)"},
                "machine_type": {"type": "string", "description": "Filter by machine type (optional)"},
            },
        },
    },
    {
        "name": "sf_update_asset",
        "description": "Update fields on a Salesforce Asset record. Use to set follow-up dates, update status, add notes, or correct usage end dates after a customer conversation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "asset_id": {"type": "string", "description": "Salesforce Asset Id (exact)"},
                "follow_up_date": {"type": "string", "description": "Follow-up date in YYYY-MM-DD format"},
                "status": {"type": "string", "description": "New asset status"},
                "description": {"type": "string", "description": "Notes or description to set on the asset"},
                "usage_end_date": {"type": "string", "description": "Corrected usage/lease end date in YYYY-MM-DD format"},
            },
            "required": ["asset_id"],
        },
    },
    {
        "name": "sf_get_new_assets",
        "description": "Get assets added to Salesforce in the last N days. Shows new accounts, new equipment records, and recent UCC filings. Use for monthly 'what's new' reports and pipeline prospecting.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Look-back window in days (default 30)"},
                "include_competitor": {"type": "boolean", "description": "Include competitor equipment (default true)"},
            },
        },
    },
    {
        "name": "sf_get_financed_deals",
        "description": "Get Project Management records (machines you've sold) with close dates to calculate predicted replacement windows. Uses 54/60-month lease terms to identify which customers are entering their buying window. Optionally filter by account name, sales rep, or how many months ahead to look.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "account_name": {"type": "string", "description": "Filter by account name (partial match)"},
                "months_ahead": {"type": "integer", "description": "Only return deals whose 60-month window closes within this many months (default: all)"},
                "include_past_window": {"type": "boolean", "description": "Include deals already past the 60-month mark (default true)"},
                "limit": {"type": "integer", "description": "Max results (default 200)"},
            },
        },
    },
]


def tool_sf_authenticate(_args):
    tokens = do_oauth()
    return {"success": True, "instance_url": tokens.get("instance_url"), "message": "Authenticated successfully. Tokens saved."}


def tool_sf_get_pipeline(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    stage = args.get("stage", "")
    limit = args.get("limit", 100)
    stage_filter = f"AND StageName LIKE '%{stage}%'" if stage else ""
    owner_filter = f"AND OwnerId = '{OWNER_ID}'" if OWNER_ID else ""
    soql = f"""
        SELECT Id, Name, StageName, Amount, CloseDate, Account.Name, Account.Id,
               Owner.Name, OwnerId, Probability, Vendor__c, Vendor__r.Name
        FROM Opportunity
        WHERE IsClosed = false {stage_filter} {owner_filter}
        ORDER BY CloseDate ASC
        LIMIT {limit}
    """
    result = sf_query(tokens, soql)
    opps = []
    for r in result.get("records", []):
        opps.append({
            "id": r["Id"],
            "name": r["Name"],
            "stage": r["StageName"],
            "amount": r.get("Amount"),
            "close_date": r.get("CloseDate"),
            "account": r.get("Account", {}).get("Name") if r.get("Account") else None,
            "account_id": r.get("Account", {}).get("Id") if r.get("Account") else None,
            "owner": r.get("Owner", {}).get("Name") if r.get("Owner") else None,
            "probability": r.get("Probability"),
            "vendor_id": r.get("Vendor__c"),
            "vendor": r.get("Vendor__r", {}).get("Name") if r.get("Vendor__r") else None,
        })
    return {"opportunities": opps, "count": len(opps)}


def tool_sf_search_contacts(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    query = args["query"]
    owner_filter = f"AND OwnerId = '{OWNER_ID}'" if OWNER_ID else ""
    soql = f"""
        SELECT Id, Name, Email, Phone, Title, Account.Name
        FROM Contact
        WHERE (Name LIKE '%{query}%' OR Email LIKE '%{query}%' OR Account.Name LIKE '%{query}%') {owner_filter}
        LIMIT 10
    """
    result = sf_query(tokens, soql)
    contacts = []
    for r in result.get("records", []):
        contacts.append({
            "id": r.get("Id"),
            "name": r.get("Name"),
            "email": r.get("Email"),
            "phone": r.get("Phone"),
            "title": r.get("Title"),
            "account": r.get("Account", {}).get("Name") if r.get("Account") else None,
        })
    return {"contacts": contacts, "count": len(contacts)}


def tool_sf_get_account(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    name = args["name"]
    owner_filter = f"AND OwnerId = '{OWNER_ID}'" if OWNER_ID else ""
    soql = f"SELECT Id, Name, Industry, Phone, Website, AnnualRevenue, NumberOfEmployees FROM Account WHERE Name LIKE '%{name}%' {owner_filter} LIMIT 5"
    accounts = sf_query(tokens, soql).get("records", [])
    if not accounts:
        return {"error": f"No account found matching '{name}'"}
    acct = accounts[0]
    acct_id = acct["Id"]
    contacts = sf_query(tokens, f"SELECT Name, Email, Title FROM Contact WHERE AccountId = '{acct_id}' LIMIT 10").get("records", [])
    opps = sf_query(tokens, f"SELECT Id, Name, StageName, Amount, CloseDate FROM Opportunity WHERE AccountId = '{acct_id}' AND IsClosed = false LIMIT 10").get("records", [])
    return {
        "account": {k: v for k, v in acct.items() if k != "attributes"},
        "contacts": [{k: v for k, v in c.items() if k != "attributes"} for c in contacts],
        "open_opportunities": [{k: v for k, v in o.items() if k != "attributes"} for o in opps],
    }


def tool_sf_get_recent_activity(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    days_back = args.get("days_back", 7)
    limit = args.get("limit", 20)
    owner_filter = f"AND OwnerId = '{OWNER_ID}'" if OWNER_ID else ""
    soql = f"""
        SELECT Subject, Status, ActivityDate, Description, Who.Name, What.Name, Owner.Name
        FROM Task
        WHERE CreatedDate = LAST_N_DAYS:{days_back} {owner_filter}
        ORDER BY CreatedDate DESC
        LIMIT {limit}
    """
    result = sf_query(tokens, soql)
    tasks = []
    for r in result.get("records", []):
        tasks.append({
            "subject": r.get("Subject"),
            "status": r.get("Status"),
            "date": r.get("ActivityDate"),
            "contact": r.get("Who", {}).get("Name") if r.get("Who") else None,
            "related_to": r.get("What", {}).get("Name") if r.get("What") else None,
            "owner": r.get("Owner", {}).get("Name") if r.get("Owner") else None,
        })
    return {"tasks": tasks, "count": len(tasks)}


def tool_sf_get_contact(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    name = args["name"]
    owner_filter = f"AND OwnerId = '{OWNER_ID}'" if OWNER_ID else ""
    soql = f"SELECT Id, Name, Email, Phone, Title, Account.Name, LastActivityDate FROM Contact WHERE Name LIKE '%{name}%' {owner_filter} LIMIT 5"
    contacts = sf_query(tokens, soql).get("records", [])
    if not contacts:
        return {"error": f"No contact found matching '{name}'"}
    c = contacts[0]
    contact_id = c["Id"]
    tasks = sf_query(tokens, f"SELECT Subject, Status, ActivityDate FROM Task WHERE WhoId = '{contact_id}' ORDER BY CreatedDate DESC LIMIT 5").get("records", [])
    opps = sf_query(tokens, f"SELECT Name, StageName, Amount, CloseDate FROM Opportunity WHERE ContactId = '{contact_id}' AND IsClosed = false LIMIT 5").get("records", [])
    return {
        "contact": {
            "name": c.get("Name"),
            "email": c.get("Email"),
            "phone": c.get("Phone"),
            "title": c.get("Title"),
            "account": c.get("Account", {}).get("Name") if c.get("Account") else None,
            "last_activity": c.get("LastActivityDate"),
        },
        "recent_tasks": [{k: v for k, v in t.items() if k != "attributes"} for t in tasks],
        "open_opportunities": [{k: v for k, v in o.items() if k != "attributes"} for o in opps],
    }


def tool_sf_get_quotes(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    opp_id = args.get("opportunity_id")
    opp_name = args.get("opportunity_name")
    if not opp_id and not opp_name:
        return {"error": "Provide opportunity_id or opportunity_name."}
    if not opp_id:
        opp_result = sf_query(tokens, f"SELECT Id FROM Opportunity WHERE Name LIKE '%{opp_name}%' LIMIT 1")
        records = opp_result.get("records", [])
        if not records:
            return {"error": f"No opportunity found matching '{opp_name}'"}
        opp_id = records[0]["Id"]
    soql = f"""
        SELECT Id, QuoteNumber, Name, Status, GrandTotal, ExpirationDate, Description
        FROM Quote
        WHERE OpportunityId = '{opp_id}'
        ORDER BY CreatedDate DESC
        LIMIT 20
    """
    quote_result = sf_query(tokens, soql)
    quotes = []
    for q in quote_result.get("records", []):
        quote_id = q["Id"]
        doc_soql = f"""
            SELECT ContentDocumentId, ContentDocument.Title, ContentDocument.FileType,
                   ContentDocument.ContentSize, ContentDocument.LatestPublishedVersionId
            FROM ContentDocumentLink
            WHERE LinkedEntityId = '{quote_id}'
        """
        doc_result = sf_query(tokens, doc_soql)
        docs = []
        for d in doc_result.get("records", []):
            cd = d.get("ContentDocument", {}) or {}
            docs.append({
                "content_document_id": d.get("ContentDocumentId"),
                "title": cd.get("Title"),
                "file_type": cd.get("FileType"),
                "size_bytes": cd.get("ContentSize"),
                "content_version_id": cd.get("LatestPublishedVersionId"),
            })
        quotes.append({
            "id": quote_id,
            "quote_number": q.get("QuoteNumber"),
            "name": q.get("Name"),
            "status": q.get("Status"),
            "grand_total": q.get("GrandTotal"),
            "expiration_date": q.get("ExpirationDate"),
            "description": q.get("Description"),
            "documents": docs,
        })
    return {"opportunity_id": opp_id, "quotes": quotes, "count": len(quotes)}


def tool_sf_download_quote_file(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    cv_id = args["content_version_id"]
    save_path = args["save_path"]
    if not os.path.isabs(save_path) and VAULT_PATH:
        save_path = os.path.join(VAULT_PATH, save_path)
    instance_url = tokens["instance_url"]
    access_token = tokens["access_token"]
    url = f"{instance_url}/services/data/v59.0/sobjects/ContentVersion/{cv_id}/VersionData"
    req = Request(url, headers={"Authorization": f"Bearer {access_token}"})
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with urlopen(req) as resp:
        with open(save_path, "wb") as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)
    file_size = os.path.getsize(save_path)
    return {"success": True, "path": save_path, "size_bytes": file_size}


def tool_sf_get_opportunity(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    opp_id_arg = args.get("id")
    name = args.get("name")
    if not opp_id_arg and not name:
        return {"error": "Provide either 'name' or 'id' parameter."}
    if opp_id_arg:
        soql = f"""
            SELECT Id, Name, StageName, Amount, CloseDate, Probability,
                   Account.Name, Account.Id, Owner.Name, Description,
                   NextStep, LeadSource, Type, Vendor__c, Vendor__r.Name
            FROM Opportunity
            WHERE Id = '{opp_id_arg}'
        """
    else:
        soql = f"""
            SELECT Id, Name, StageName, Amount, CloseDate, Probability,
                   Account.Name, Account.Id, Owner.Name, Description,
                   NextStep, LeadSource, Type, Vendor__c, Vendor__r.Name
            FROM Opportunity
            WHERE Name LIKE '%{name}%'
            LIMIT 5
        """
    opps = sf_query(tokens, soql).get("records", [])
    if not opps:
        return {"error": f"No opportunity found matching '{opp_id_arg or name}'"}
    opp = opps[0]
    opp_id = opp["Id"]
    contacts_soql = f"""
        SELECT Contact.Name, Contact.Email, Contact.Title, Role, IsPrimary
        FROM OpportunityContactRole
        WHERE OpportunityId = '{opp_id}'
    """
    contacts = sf_query(tokens, contacts_soql).get("records", [])
    quotes_soql = f"""
        SELECT Id, QuoteNumber, Name, Status, GrandTotal, ExpirationDate
        FROM Quote
        WHERE OpportunityId = '{opp_id}'
        ORDER BY CreatedDate DESC
        LIMIT 10
    """
    quotes = sf_query(tokens, quotes_soql).get("records", [])
    tasks_soql = f"""
        SELECT Subject, Status, ActivityDate, Who.Name
        FROM Task
        WHERE WhatId = '{opp_id}'
        ORDER BY CreatedDate DESC
        LIMIT 10
    """
    tasks = sf_query(tokens, tasks_soql).get("records", [])
    clean = lambda recs: [{k: v for k, v in r.items() if k != "attributes"} for r in recs]
    return {
        "opportunity": {k: v for k, v in opp.items() if k != "attributes"},
        "contacts": clean(contacts),
        "quotes": clean(quotes),
        "recent_activity": clean(tasks),
    }


def tool_sf_create_task(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    import datetime
    payload = {
        "Subject": args["subject"],
        "Status": args.get("status", "Completed"),
        "ActivityDate": args.get("activity_date", datetime.date.today().isoformat()),
    }
    if args.get("description"):
        payload["Description"] = args["description"]
    if args.get("what_id"):
        payload["WhatId"] = args["what_id"]
    if args.get("who_id"):
        payload["WhoId"] = args["who_id"]
    if args.get("type"):
        payload["Type"] = args["type"]
    if OWNER_ID:
        payload["OwnerId"] = OWNER_ID
    result = sf_post(tokens, "sobjects/Task", payload)
    return {"success": result.get("success", False), "task_id": result.get("id"), "errors": result.get("errors", [])}


def tool_sf_get_open_tasks(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    limit = args.get("limit", 200)
    due_before = args.get("due_before", "")
    owner_filter = f"AND OwnerId = '{OWNER_ID}'" if OWNER_ID else ""
    due_filter = f"AND ActivityDate <= {due_before}" if due_before else ""
    soql = f"""
        SELECT Subject, Status, ActivityDate, Description, Priority,
               Who.Name, What.Name, What.Id
        FROM Task
        WHERE Status != 'Completed' AND IsClosed = false
        {owner_filter} {due_filter}
        ORDER BY ActivityDate ASC NULLS LAST
        LIMIT {limit}
    """
    result = sf_query(tokens, soql)
    tasks = []
    for r in result.get("records", []):
        tasks.append({
            "subject": r.get("Subject"),
            "status": r.get("Status"),
            "due_date": r.get("ActivityDate"),
            "priority": r.get("Priority"),
            "description": r.get("Description"),
            "contact": r.get("Who", {}).get("Name") if r.get("Who") else None,
            "related_to": r.get("What", {}).get("Name") if r.get("What") else None,
            "related_id": r.get("What", {}).get("Id") if r.get("What") else None,
        })
    return {"tasks": tasks, "count": len(tasks)}


def tool_sf_get_completed_tasks(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    import datetime
    today = datetime.date.today().isoformat()
    default_from = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
    date_from = args.get("date_from", default_from)
    date_to = args.get("date_to", today)
    limit = args.get("limit", 50)
    has_description = args.get("has_description", False)
    owner_filter = f"AND OwnerId = '{OWNER_ID}'" if OWNER_ID else ""
    desc_filter = "AND Description != null" if has_description else ""
    soql = (
        f"SELECT Subject, Status, ActivityDate, Description, Type, Who.Name, What.Name, Owner.Name "
        f"FROM Task "
        f"WHERE Status = 'Completed' "
        f"AND ActivityDate >= {date_from} "
        f"AND ActivityDate <= {date_to} "
        f"{owner_filter} {desc_filter} "
        f"ORDER BY ActivityDate DESC "
        f"LIMIT {limit}"
    )
    try:
        result = sf_query(tokens, soql)
    except Exception as e:
        return {"error": str(e), "soql": soql}
    tasks = []
    for r in result.get("records", []):
        tasks.append({
            "subject": r.get("Subject"),
            "type": r.get("Type"),
            "status": r.get("Status"),
            "date": r.get("ActivityDate"),
            "description": r.get("Description"),
            "contact": r.get("Who", {}).get("Name") if r.get("Who") else None,
            "related_to": r.get("What", {}).get("Name") if r.get("What") else None,
            "owner": r.get("Owner", {}).get("Name") if r.get("Owner") else None,
        })
    return {"tasks": tasks, "count": len(tasks)}


def tool_sf_get_project_management(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    import datetime
    limit = args.get("limit", 50)
    days_ahead = args.get("days_ahead")
    date_filter = ""
    if days_ahead:
        cutoff = (datetime.date.today() + datetime.timedelta(days=days_ahead)).isoformat()
        date_filter = f"AND Install_Date__c <= {cutoff}"
    rep_filter = f"AND Sales_Rep__c = '{OWNER_ID}'" if OWNER_ID else ""
    soql = f"""
        SELECT Id, Name,
               Account_Name__r.Name,
               Opportunity_Name__r.Name,
               OWU_Ship_Date__c, Updated_Ship_Date__c, Install_Date__c,
               Deposit_Paid__c, PIM_Sent__c,
               Intro_Customer_Call__c, Intro_Vendor_Email__c,
               Status__c, Machine_Type__c, Model__c,
               Next_Steps__c, Sale_Close_Date__c, Ship_in_4_weeks__c
        FROM Project_Management__c
        WHERE Install_Date__c != null
        {rep_filter} {date_filter}
        ORDER BY Install_Date__c ASC NULLS LAST
        LIMIT {limit}
    """
    result = sf_query(tokens, soql)
    today = datetime.date.today()
    records = []
    for r in result.get("records", []):
        install_raw = r.get("Install_Date__c")
        ship_raw = r.get("Updated_Ship_Date__c") or r.get("OWU_Ship_Date__c")
        install_date = datetime.date.fromisoformat(install_raw) if install_raw else None
        days_until_install = (install_date - today).days if install_date else None
        pim_sent = r.get("PIM_Sent__c", False)
        deposit_paid = r.get("Deposit_Paid__c", False)

        # Compute all pending milestone actions
        actions = []
        if days_until_install is not None:
            if days_until_install <= 14 and not pim_sent:
                actions.append("⚠️ DELIVERY IMMINENT — PIM not sent yet!")
            elif days_until_install <= 14:
                actions.append("🔴 DELIVERY IMMINENT — confirm pre-install checklist complete")
            if days_until_install <= 30 and not pim_sent:
                actions.append("Send pre-installation manual (PIM) to customer")
            if days_until_install <= 60:
                actions.append("Confirm foundation/site requirements with customer")
            if not r.get("Intro_Customer_Call__c"):
                actions.append("Make intro customer call")
            if not r.get("Intro_Vendor_Email__c"):
                actions.append("Send intro vendor email")
        if not deposit_paid:
            actions.append("💰 Deposit not yet received")

        records.append({
            "name": r.get("Name"),
            "account": r.get("Account_Name__r", {}).get("Name") if r.get("Account_Name__r") else None,
            "opportunity": r.get("Opportunity_Name__r", {}).get("Name") if r.get("Opportunity_Name__r") else None,
            "machine_type": r.get("Machine_Type__c"),
            "model": r.get("Model__c"),
            "status": r.get("Status__c"),
            "ship_date": ship_raw,
            "ships_in_4_weeks": r.get("Ship_in_4_weeks__c", False),
            "install_date": install_raw,
            "days_until_install": days_until_install,
            "deposit_paid": deposit_paid,
            "pim_sent": pim_sent,
            "intro_customer_call": r.get("Intro_Customer_Call__c", False),
            "intro_vendor_email": r.get("Intro_Vendor_Email__c", False),
            "sale_close_date": r.get("Sale_Close_Date__c"),
            "next_steps": r.get("Next_Steps__c"),
            "pending_actions": actions,
        })
    return {"project_management_records": records, "count": len(records)}


def tool_sf_update_opportunity_notes(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    opp_id = args["opportunity_id"]
    payload = {}
    if args.get("next_step"):
        payload["NextStep"] = args["next_step"]
    if args.get("description"):
        payload["Description"] = args["description"]
    if not payload:
        return {"error": "Provide next_step or description to update."}
    sf_patch(tokens, f"sobjects/Opportunity/{opp_id}", payload)
    return {"success": True, "opportunity_id": opp_id, "updated_fields": list(payload.keys())}


def _asset_expiry_status(usage_end_str):
    """Return (days_to_expiry, urgency) for a UsageEndDate string."""
    if not usage_end_str:
        return None, None
    try:
        end_date = datetime.strptime(usage_end_str[:10], "%Y-%m-%d").date()
        days = (end_date - date.today()).days
        if days <= 0:
            urgency = "LAPSED"
        elif days <= 90:
            urgency = "CRITICAL"
        elif days <= 180:
            urgency = "HIGH"
        elif days <= 365:
            urgency = "MEDIUM"
        else:
            urgency = "LOW"
        return days, urgency
    except Exception:
        return None, None


def _parse_asset_record(r):
    days, urgency = _asset_expiry_status(r.get("UsageEndDate"))
    return {
        "id": r["Id"],
        "name": r.get("Name"),
        "machine_type": r.get("Machine_Type_New__c"),
        "model": r.get("ModelName__c"),
        "builder": r.get("Builder__c"),
        "serial_number": r.get("SerialNumber"),
        "ucc_vendor": r.get("UCC_Vendor__c"),
        "ucc_id": r.get("UCCID__c"),
        "ucc_status": r.get("UCC_Status__c"),
        "new_or_used": r.get("UCC_New_or_Used__c"),
        "sale_or_lease": r.get("Sale_or_Lease__c"),
        "install_date": r.get("InstallDate"),
        "purchase_date": r.get("Purchase_Date__c") or r.get("PurchaseDate"),
        "usage_end_date": r.get("UsageEndDate"),
        "days_to_expiry": days,
        "urgency": urgency,
        "status": r.get("Status"),
        "is_competitor": r.get("IsCompetitorProduct", False),
        "price": r.get("Price"),
        "warranty_length": r.get("Warranty_Length__c"),
        "follow_up_date": r.get("FollowUpDate__c"),
        "account": r.get("Account", {}).get("Name") if r.get("Account") else None,
        "account_id": r.get("Account", {}).get("Id") if r.get("Account") else None,
        "contact": r.get("Contact", {}).get("Name") if r.get("Contact") else None,
        "opportunity_id": r.get("Opportunity__c"),
        "description": r.get("Description"),
    }


def tool_sf_get_account_assets(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    account_id = args.get("account_id", "")
    account_name = args.get("account_name", "")
    include_competitor = args.get("include_competitor", True)
    if not account_id and not account_name:
        return {"error": "Provide account_name or account_id."}
    account_filter = f"AccountId = '{account_id}'" if account_id else f"Account.Name LIKE '%{account_name}%'"
    competitor_filter = "" if include_competitor else "AND IsCompetitorProduct = false"
    soql = f"""
        SELECT Id, Name, Machine_Type_New__c, ModelName__c, Builder__c, SerialNumber,
               UCC_Vendor__c, UCCID__c, UCC_Status__c, UCC_New_or_Used__c,
               Sale_or_Lease__c, InstallDate, Purchase_Date__c, PurchaseDate,
               UsageEndDate, Status, IsCompetitorProduct, Price, Warranty_Length__c,
               FollowUpDate__c, Description, Account.Name, Account.Id,
               Contact.Name, Opportunity__c
        FROM Asset
        WHERE {account_filter} {competitor_filter}
        ORDER BY InstallDate DESC NULLS LAST
        LIMIT 200
    """
    result = sf_query(tokens, soql)
    assets = [_parse_asset_record(r) for r in result.get("records", [])]
    our_machines = [a for a in assets if not a["is_competitor"]]
    competitor_machines = [a for a in assets if a["is_competitor"]]
    expiring = [a for a in our_machines if a["urgency"] in ("CRITICAL", "HIGH", "MEDIUM")]
    return {
        "assets": assets,
        "count": len(assets),
        "our_equipment_count": len(our_machines),
        "competitor_equipment_count": len(competitor_machines),
        "expiring_within_12_months": len(expiring),
        "account": assets[0]["account"] if assets else (account_name or account_id),
    }


def tool_sf_get_assets_expiring_soon(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    months = args.get("months", 12)
    owner_filter = f"AND OwnerId = '{OWNER_ID}'" if OWNER_ID else ""
    future_date = (date.today() + timedelta(days=months * 30)).strftime("%Y-%m-%d")
    soql = f"""
        SELECT Id, Name, Machine_Type_New__c, ModelName__c, Builder__c,
               Sale_or_Lease__c, UsageEndDate, Status, IsCompetitorProduct,
               Account.Name, Account.Id, FollowUpDate__c
        FROM Asset
        WHERE UsageEndDate != null
          AND UsageEndDate >= TODAY
          AND UsageEndDate <= {future_date}
          {owner_filter}
        ORDER BY UsageEndDate ASC
        LIMIT 500
    """
    result = sf_query(tokens, soql)
    assets = [_parse_asset_record(r) for r in result.get("records", [])]
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for a in assets:
        if a["urgency"] in counts:
            counts[a["urgency"]] += 1
    return {
        "assets": assets,
        "count": len(assets),
        "summary": {
            "critical_0_90_days": counts["CRITICAL"],
            "high_90_180_days": counts["HIGH"],
            "medium_180_365_days": counts["MEDIUM"],
        },
        "months_ahead": months,
    }


def tool_sf_search_assets(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    filters = []
    if args.get("machine_type"):
        filters.append(f"Machine_Type_New__c LIKE '%{args['machine_type']}%'")
    if args.get("builder"):
        filters.append(f"Builder__c LIKE '%{args['builder']}%'")
    if args.get("account_name"):
        filters.append(f"Account.Name LIKE '%{args['account_name']}%'")
    if args.get("competitor_only"):
        filters.append("IsCompetitorProduct = true")
    if args.get("sale_or_lease"):
        filters.append(f"Sale_or_Lease__c = '{args['sale_or_lease']}'")
    if args.get("status"):
        filters.append(f"Status = '{args['status']}'")
    where_clause = " AND ".join(filters) if filters else "Id != null"
    limit = args.get("limit", 100)
    soql = f"""
        SELECT Id, Name, Machine_Type_New__c, ModelName__c, Builder__c, SerialNumber,
               UCC_Vendor__c, Sale_or_Lease__c, InstallDate, Purchase_Date__c,
               UsageEndDate, Status, IsCompetitorProduct, Price,
               Account.Name, Account.Id
        FROM Asset
        WHERE {where_clause}
        ORDER BY Account.Name ASC, InstallDate DESC NULLS LAST
        LIMIT {limit}
    """
    result = sf_query(tokens, soql)
    assets = [_parse_asset_record(r) for r in result.get("records", [])]
    return {"assets": assets, "count": len(assets)}


def tool_sf_get_competitor_assets(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    filters = ["IsCompetitorProduct = true"]
    if args.get("account_name"):
        filters.append(f"Account.Name LIKE '%{args['account_name']}%'")
    if args.get("machine_type"):
        filters.append(f"Machine_Type_New__c LIKE '%{args['machine_type']}%'")
    soql = f"""
        SELECT Id, Name, Machine_Type_New__c, ModelName__c, Builder__c, SerialNumber,
               UCC_Vendor__c, InstallDate, Purchase_Date__c, UsageEndDate, Status,
               Account.Name, Account.Id, Description
        FROM Asset
        WHERE {" AND ".join(filters)}
        ORDER BY Account.Name ASC, InstallDate DESC NULLS LAST
        LIMIT 200
    """
    result = sf_query(tokens, soql)
    assets = [_parse_asset_record(r) for r in result.get("records", [])]
    by_builder = {}
    for a in assets:
        key = a.get("builder") or a.get("ucc_vendor") or "Unknown"
        by_builder.setdefault(key, []).append(a)
    return {
        "assets": assets,
        "count": len(assets),
        "by_competitor_brand": {k: len(v) for k, v in sorted(by_builder.items(), key=lambda x: -len(x[1]))},
    }


def tool_sf_update_asset(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    asset_id = args.get("asset_id")
    if not asset_id:
        return {"error": "asset_id is required."}
    payload = {}
    if args.get("follow_up_date"):
        payload["FollowUpDate__c"] = args["follow_up_date"]
    if args.get("status"):
        payload["Status"] = args["status"]
    if args.get("description"):
        payload["Description"] = args["description"]
    if args.get("usage_end_date"):
        payload["UsageEndDate"] = args["usage_end_date"]
    if not payload:
        return {"error": "Provide at least one field: follow_up_date, status, description, usage_end_date."}
    sf_patch(tokens, f"sobjects/Asset/{asset_id}", payload)
    return {"success": True, "asset_id": asset_id, "updated_fields": list(payload.keys())}


def tool_sf_get_new_assets(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    days = args.get("days", 30)
    include_competitor = args.get("include_competitor", True)
    competitor_filter = "" if include_competitor else "AND IsCompetitorProduct = false"
    soql = f"""
        SELECT Id, Name, Machine_Type_New__c, ModelName__c, Builder__c, SerialNumber,
               UCC_Vendor__c, UCCID__c, UCC_Status__c, Sale_or_Lease__c,
               InstallDate, Purchase_Date__c, UsageEndDate, Status,
               IsCompetitorProduct, Price, Account.Name, Account.Id, CreatedDate
        FROM Asset
        WHERE CreatedDate >= LAST_N_DAYS:{days}
          {competitor_filter}
        ORDER BY CreatedDate DESC
        LIMIT 500
    """
    result = sf_query(tokens, soql)
    assets = [_parse_asset_record(r) for r in result.get("records", [])]
    for a, r in zip(assets, result.get("records", [])):
        a["created_date"] = r.get("CreatedDate")
    new_accounts = list({a["account_id"]: a["account"] for a in assets if a.get("account_id")}.items())
    our_assets = [a for a in assets if not a["is_competitor"]]
    competitor_assets = [a for a in assets if a["is_competitor"]]
    return {
        "assets": assets,
        "count": len(assets),
        "our_equipment_added": len(our_assets),
        "competitor_equipment_added": len(competitor_assets),
        "new_accounts_with_records": [{"account_id": aid, "account": name} for aid, name in new_accounts],
        "unique_accounts_count": len(new_accounts),
        "days_back": days,
    }


_EARLY_TERM = 54   # months — previous standard lease term
_STD_TERM   = 60   # months — common standard lease term


def _replacement_window(close_date_str):
    """Return window info based on 54/60-month lease terms from close date."""
    if not close_date_str:
        return None
    try:
        close = datetime.strptime(close_date_str[:10], "%Y-%m-%d").date()
        today = date.today()
        months_elapsed = (today.year - close.year) * 12 + (today.month - close.month)

        early_end = close + timedelta(days=_EARLY_TERM * 30)
        std_end   = close + timedelta(days=_STD_TERM  * 30)
        days_to_std = (std_end - today).days

        if months_elapsed >= _STD_TERM:
            status = "PAST_WINDOW"
            urgency = "CRITICAL"
        elif months_elapsed >= _EARLY_TERM:
            status = "IN_WINDOW"   # past 54mo, still within 60mo
            urgency = "CRITICAL"
        elif days_to_std <= 180:
            status = "APPROACHING"
            urgency = "HIGH"
        elif days_to_std <= 365:
            status = "UPCOMING"
            urgency = "MEDIUM"
        else:
            status = "ACTIVE"
            urgency = "LOW"

        return {
            "months_elapsed": months_elapsed,
            "early_end_date": early_end.isoformat(),   # 54mo
            "std_end_date":   std_end.isoformat(),      # 60mo
            "days_to_std_end": days_to_std,
            "status": status,
            "urgency": urgency,
        }
    except Exception:
        return None


def tool_sf_get_financed_deals(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}

    account_name   = args.get("account_name", "")
    months_ahead   = args.get("months_ahead", 0)
    include_past   = args.get("include_past_window", True)
    limit          = args.get("limit", 200)

    filters = ["Sale_Close_Date__c != null"]
    if account_name:
        filters.append(f"Account_Name__r.Name LIKE '%{account_name}%'")
    if months_ahead:
        cutoff = (date.today() + timedelta(days=months_ahead * 30)).strftime("%Y-%m-%d")
        # deals closed within the past (months_ahead + 60) months are relevant
        earliest = (date.today() - timedelta(days=(months_ahead + 60) * 30)).strftime("%Y-%m-%d")
        filters.append(f"Sale_Close_Date__c >= {earliest}")

    soql = f"""
        SELECT Id, Name, Sale_Close_Date__c, Install_Date__c, OWU_Ship_Date__c,
               Updated_Ship_Date__c, Warranty_Length__c, Machine_Type__c, Model__c,
               Serial_Number__c, Status__c,
               Account_Name__r.Name, Account_Name__c,
               Opportunity_Name__r.Name, Opportunity_Name__c,
               Asset__c, Asset__r.Name,
               Sales_Rep__r.Name, Vendor__r.Name
        FROM Project_Management__c
        WHERE {" AND ".join(filters)}
        ORDER BY Sale_Close_Date__c ASC
        LIMIT {limit}
    """

    result = sf_query(tokens, soql)
    deals = []
    for r in result.get("records", []):
        window = _replacement_window(r.get("Sale_Close_Date__c"))
        if not window:
            continue
        if not include_past and window["status"] == "PAST_WINDOW":
            continue
        deals.append({
            "id": r["Id"],
            "name": r.get("Name"),
            "machine_type": r.get("Machine_Type__c"),
            "model": r.get("Model__c"),
            "serial_number": r.get("Serial_Number__c"),
            "status": r.get("Status__c"),
            "close_date": r.get("Sale_Close_Date__c"),
            "install_date": r.get("Install_Date__c"),
            "ship_date": r.get("Updated_Ship_Date__c") or r.get("OWU_Ship_Date__c"),
            "warranty_length": r.get("Warranty_Length__c"),
            "account": (r.get("Account_Name__r") or {}).get("Name"),
            "account_id": r.get("Account_Name__c"),
            "opportunity": (r.get("Opportunity_Name__r") or {}).get("Name"),
            "opportunity_id": r.get("Opportunity_Name__c"),
            "asset_id": r.get("Asset__c"),
            "asset_name": (r.get("Asset__r") or {}).get("Name"),
            "sales_rep": (r.get("Sales_Rep__r") or {}).get("Name"),
            "vendor": (r.get("Vendor__r") or {}).get("Name"),
            "window": window,
        })

    critical = [d for d in deals if d["window"]["urgency"] == "CRITICAL"]
    high     = [d for d in deals if d["window"]["urgency"] == "HIGH"]
    medium   = [d for d in deals if d["window"]["urgency"] == "MEDIUM"]

    return {
        "deals": deals,
        "count": len(deals),
        "summary": {
            "in_window_now_54_60mo": len([d for d in deals if d["window"]["status"] == "IN_WINDOW"]),
            "past_window_60mo_plus": len([d for d in deals if d["window"]["status"] == "PAST_WINDOW"]),
            "approaching_high": len(high),
            "upcoming_medium": len(medium),
            "active": len([d for d in deals if d["window"]["urgency"] == "LOW"]),
        },
        "lease_terms_used": f"{_EARLY_TERM}mo early / {_STD_TERM}mo standard",
    }


TOOL_FNS = {
    "sf_authenticate": tool_sf_authenticate,
    "sf_get_pipeline": tool_sf_get_pipeline,
    "sf_search_contacts": tool_sf_search_contacts,
    "sf_get_account": tool_sf_get_account,
    "sf_get_recent_activity": tool_sf_get_recent_activity,
    "sf_get_contact": tool_sf_get_contact,
    "sf_get_quotes": tool_sf_get_quotes,
    "sf_download_quote_file": tool_sf_download_quote_file,
    "sf_get_opportunity": tool_sf_get_opportunity,
    "sf_create_task": tool_sf_create_task,
    "sf_get_open_tasks": tool_sf_get_open_tasks,
    "sf_get_completed_tasks": tool_sf_get_completed_tasks,
    "sf_get_project_management": tool_sf_get_project_management,
    "sf_update_opportunity_notes": tool_sf_update_opportunity_notes,
    "sf_get_account_assets": tool_sf_get_account_assets,
    "sf_get_assets_expiring_soon": tool_sf_get_assets_expiring_soon,
    "sf_search_assets": tool_sf_search_assets,
    "sf_get_competitor_assets": tool_sf_get_competitor_assets,
    "sf_update_asset": tool_sf_update_asset,
    "sf_get_new_assets": tool_sf_get_new_assets,
    "sf_get_financed_deals": tool_sf_get_financed_deals,
}


# ── MCP stdio protocol ────────────────────────────────────────────────────────

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def handle(msg):
    method = msg.get("method")
    id_ = msg.get("id")

    if method == "initialize":
        send({"jsonrpc": "2.0", "id": id_, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "salesforce-mcp", "version": "1.0.0"},
        }})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": id_, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = msg["params"]["name"]
        args = msg["params"].get("arguments", {})
        if name not in TOOL_FNS:
            send({"jsonrpc": "2.0", "id": id_, "error": {"code": -32601, "message": f"Unknown tool: {name}"}})
            return
        try:
            result = TOOL_FNS[name](args)
            send({"jsonrpc": "2.0", "id": id_, "result": {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}})
        except Exception as e:
            send({"jsonrpc": "2.0", "id": id_, "result": {"content": [{"type": "text", "text": json.dumps({"error": str(e)})}]}})
    elif method == "notifications/initialized":
        pass
    elif id_ is not None:
        send({"jsonrpc": "2.0", "id": id_, "error": {"code": -32601, "message": f"Method not found: {method}"}})


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        handle(msg)


if __name__ == "__main__":
    main()
