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
    "sf_update_opportunity_notes": tool_sf_update_opportunity_notes,
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
