#!/usr/bin/env python3
"""Salesforce MCP server for Dex — contacts, opportunities, accounts, activities."""

import base64
import email as email_lib
import hashlib
import json
import os
import secrets
import sys
import threading
import webbrowser
from datetime import datetime, date, timedelta
from email.header import decode_header as email_decode_header
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

VAULT_PATH = os.environ.get("VAULT_PATH", "")
EMAIL_QUEUE_PATH = os.environ.get("EMAIL_QUEUE_PATH", "")  # overrides vault-based path for email queue

# Fall back to reading env values from the mcpjson config file when env vars aren't set
# (Claude Code's mcpjsonServers loader doesn't always pass the env block to the subprocess)
def _load_mcp_config_env():
    global VAULT_PATH, EMAIL_QUEUE_PATH
    server_dir = Path(__file__).resolve().parent  # .scripts/salesforce-mcp/
    config_path = server_dir.parent.parent / ".claude" / "mcp" / "salesforce.json"
    if not config_path.exists():
        return
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        env = cfg.get("server", {}).get("env", {})
        if not VAULT_PATH:
            VAULT_PATH = env.get("VAULT_PATH", "")
        if not EMAIL_QUEUE_PATH:
            raw = env.get("EMAIL_QUEUE_PATH", "")
            # skip unexpanded template variables
            if raw and not raw.startswith("${"):
                EMAIL_QUEUE_PATH = raw
    except Exception:
        pass

_load_mcp_config_env()

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


def sf_get(tokens, path):
    instance_url = tokens["instance_url"]
    access_token = tokens["access_token"]
    req = Request(
        f"{instance_url}/services/data/v59.0/{path}",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
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
                "what_id": {"type": "string", "description": "Salesforce Opportunity or Account Id to link this task to (WhatId). Alias: opportunity_id"},
                "opportunity_id": {"type": "string", "description": "Alias for what_id — Salesforce Opportunity Id to link this task to"},
                "who_id": {"type": "string", "description": "Salesforce Contact Id to link this task to (WhoId). Alias: contact_id"},
                "contact_id": {"type": "string", "description": "Alias for who_id — Salesforce Contact Id to link this task to"},
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
    # ── Quote Creation ────────────────────────────────────────────────────────────
    {
        "name": "sf_search_opportunities",
        "description": "Search open opportunities by account name, contact name, opportunity name, or machine/application context. Returns ranked matches. Use to find the right opportunity before creating a quote.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "account_name": {"type": "string", "description": "Company/account name (partial match)"},
                "contact_name": {"type": "string", "description": "Contact name (partial match) — searches via OpportunityContactRole"},
                "opportunity_name": {"type": "string", "description": "Opportunity name keywords (partial match)"},
                "machine_type": {"type": "string", "description": "Machine type or context (searches Name and Description)"},
                "limit": {"type": "integer", "description": "Max results per search path (default 10)"},
            },
        },
    },
    {
        "name": "sf_create_quote",
        "description": "Create a new Quote record in Salesforce linked to an Opportunity. Returns quote_id, quote_number, and a Salesforce URL. The quote starts in Draft status. Pass custom_fields to set any org-specific fields (e.g. Vendor__c, Machine_Type__c). Use sf_describe_object with object_name='Quote' to discover available custom fields.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "opportunity_id": {"type": "string", "description": "Salesforce Opportunity Id to link this quote to (required)"},
                "name": {"type": "string", "description": "Quote name (e.g. 'Acme Corp - TruBend 5085 Quote')"},
                "expiration_date": {"type": "string", "description": "Quote expiration date (YYYY-MM-DD)"},
                "status": {"type": "string", "description": "Quote status — Draft (default), Needs Review, Approved, Presented, Accepted, Denied"},
                "pricebook_id": {"type": "string", "description": "Pricebook2 Id. Omit to use the Standard Pricebook."},
                "payment_terms": {"type": "string", "description": "Payment terms text (e.g. 'Net 30')"},
                "shipping_handling": {"type": "number", "description": "Shipping and handling amount"},
                "description": {"type": "string", "description": "Quote description or internal notes"},
                "billing_name": {"type": "string", "description": "Billing contact name"},
                "shipping_name": {"type": "string", "description": "Shipping contact name"},
                "shipping_terms": {"type": "string", "description": "Shipping terms (e.g. 'FOB Destination')"},
                "custom_fields": {"type": "object", "description": "Any org-specific custom fields as a flat dict of Salesforce API field name → value. Example: {\"Vendor__c\": \"001abc\", \"Machine_Type__c\": \"Press Brake\"}"},
            },
            "required": ["opportunity_id", "name"],
        },
    },
    {
        "name": "sf_get_pricebooks",
        "description": "List all active pricebooks in Salesforce. Use to find the correct Pricebook2Id before creating a quote or searching for products.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "sf_get_pricebook_entries",
        "description": "Search for products/machines in a Salesforce pricebook. Returns PricebookEntryId, product name, code, and list price — needed to add line items to a quote.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pricebook_id": {"type": "string", "description": "Pricebook2 Id (use sf_get_pricebooks to find)"},
                "product_name": {"type": "string", "description": "Product or machine name to search (partial match, optional — omit to list all)"},
                "limit": {"type": "integer", "description": "Max results (default 25)"},
            },
            "required": ["pricebook_id"],
        },
    },
    {
        "name": "sf_add_quote_line_item",
        "description": "Add a single product/machine line item to an existing Salesforce Quote. Requires a PricebookEntryId from sf_get_pricebook_entries. Use unit_price to override the catalog price. Pass custom_fields for org-specific QuoteLineItem fields. For multiple line items in one call, use sf_add_quote_line_items instead.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "quote_id": {"type": "string", "description": "Salesforce Quote Id"},
                "pricebook_entry_id": {"type": "string", "description": "PricebookEntry Id (from sf_get_pricebook_entries)"},
                "quantity": {"type": "number", "description": "Quantity"},
                "unit_price": {"type": "number", "description": "Unit price (overrides pricebook list price)"},
                "description": {"type": "string", "description": "Line item description — machine specs, model details, notes"},
                "sort_order": {"type": "integer", "description": "Sort order for line item display"},
                "custom_fields": {"type": "object", "description": "Org-specific custom fields as a flat dict of Salesforce API field name → value. Example: {\"Machine_Type__c\": \"Laser\", \"Model__c\": \"TruLaser 5030\"}"},
            },
            "required": ["quote_id", "pricebook_entry_id", "quantity"],
        },
    },
    {
        "name": "sf_add_quote_line_items",
        "description": "Add multiple line items to a Salesforce Quote in a single call. Each item in the 'line_items' array must have pricebook_entry_id and quantity; unit_price, description, sort_order, and custom_fields are optional per item. Returns per-item success/failure so partial failures don't block the rest. Use this when you have 2+ products to add — saves round-trips vs calling sf_add_quote_line_item repeatedly.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "quote_id": {"type": "string", "description": "Salesforce Quote Id"},
                "line_items": {
                    "type": "array",
                    "description": "List of line items to add",
                    "items": {
                        "type": "object",
                        "properties": {
                            "pricebook_entry_id": {"type": "string", "description": "PricebookEntry Id"},
                            "quantity": {"type": "number", "description": "Quantity"},
                            "unit_price": {"type": "number", "description": "Override unit price"},
                            "description": {"type": "string", "description": "Line item description"},
                            "sort_order": {"type": "integer", "description": "Display sort order"},
                            "custom_fields": {"type": "object", "description": "Custom fields for this line item"},
                        },
                        "required": ["pricebook_entry_id", "quantity"],
                    },
                },
            },
            "required": ["quote_id", "line_items"],
        },
    },
    {
        "name": "sf_describe_object",
        "description": "Return field metadata for any Salesforce object (Quote, QuoteLineItem, Opportunity, Contact, Account, etc.). Shows all field names, labels, types, and whether they are custom fields (__c suffix). Use this before creating records to discover what custom fields are available in this org.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_name": {"type": "string", "description": "Salesforce API object name (e.g. 'Quote', 'QuoteLineItem', 'Opportunity', 'Account')"},
                "custom_only": {"type": "boolean", "description": "If true, return only custom fields (__c). Default false returns all fields."},
            },
            "required": ["object_name"],
        },
    },
    {
        "name": "sf_upload_file",
        "description": "Upload a local file to Salesforce and link it to a record (Quote, Opportunity, Task, etc.). Reads the file from disk, encodes it, and creates a ContentVersion linked via FirstPublishLocationId.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path to the file, or path relative to vault root"},
                "title": {"type": "string", "description": "File title in Salesforce (defaults to filename if omitted)"},
                "linked_record_id": {"type": "string", "description": "Salesforce record Id to attach the file to (Quote Id, Opportunity Id, etc.)"},
            },
            "required": ["file_path", "linked_record_id"],
        },
    },
    {
        "name": "sf_get_opportunity_contacts",
        "description": "Get all contacts linked to a Salesforce opportunity via OpportunityContactRole. Returns contact name, email, phone, title, and their role on the opportunity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "opportunity_id": {"type": "string", "description": "Salesforce Opportunity Id"},
            },
            "required": ["opportunity_id"],
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
    {
        "name": "email_read_pending",
        "description": "Read pending quote-request emails that have been dropped into the vault's Inbox/Emails/pending/ folder (e.g. by a Power Automate flow or by dragging an .eml file there). Returns each file's content, sender, subject, date, and original filename. After processing, call email_archive_pending to move the file out of the queue.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max files to return (default 5, newest first)"},
            },
        },
    },
    {
        "name": "email_archive_pending",
        "description": "Move a processed email file from Inbox/Emails/pending/ to Inbox/Emails/processed/ so it won't be picked up again on the next run. Call after the Salesforce quote has been successfully created.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Filename returned by email_read_pending (not the full path, just the name)"},
            },
            "required": ["filename"],
        },
    },
    {
        "name": "sf_get_vendors",
        "description": "Get all Vendor accounts from Salesforce (Record Type = Vendor). Use to present a vendor picklist when creating opportunities. Returns Id, Name, and a 3-letter prefix derived from the vendor name.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "sf_create_opportunity",
        "description": (
            "Create a new Opportunity in Salesforce. "
            "Opportunity name is auto-generated as '[VEN] - [Machine Model] - [Account Name]' "
            "when vendor_id and machine_model are provided (e.g. 'HEM - HEM Saw VT120 - McGregor Industries Inc.'). "
            "Call sf_get_vendors first to resolve a vendor_id from the vendor name. "
            "Returns the new Opportunity Id and a Salesforce Lightning URL."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string", "description": "Salesforce Account Id (18-char) to link the opportunity to"},
                "machine_model": {"type": "string", "description": "Machine model name used in the auto-generated opportunity name (e.g. 'HEM Saw VT120')"},
                "vendor_id": {"type": "string", "description": "Salesforce Account Id of the Vendor (from sf_get_vendors). Saved to Vendor__c and used to generate the opportunity name prefix."},
                "name": {"type": "string", "description": "Explicit opportunity name. If omitted, auto-generated from vendor, machine_model, and account name."},
                "stage": {"type": "string", "description": "Stage name (e.g. 'Discovery', 'Qualification', 'Proposal/Price Quote'). Defaults to 'Discovery'"},
                "close_date": {"type": "string", "description": "Expected close date in YYYY-MM-DD format. Defaults to 90 days from today"},
                "amount": {"type": "number", "description": "Opportunity amount (optional)"},
                "contact_id": {"type": "string", "description": "Salesforce Contact Id to link as primary contact role (optional)"},
                "description": {"type": "string", "description": "Opportunity description or notes (optional)"},
                "next_step": {"type": "string", "description": "Next steps text (optional)"},
                "type": {"type": "string", "description": "Opportunity type (optional, e.g. 'New Business', 'Existing Business')"},
                "skip_follow_up_task": {"type": "boolean", "description": "Set true to skip auto-creating a Discovery Call follow-up task (default false)"},
                "force_create": {"type": "boolean", "description": "Set true to create even if a duplicate open opportunity with the same name exists (default false)"},
            },
            "required": ["account_id"],
        },
    },
    {
        "name": "sf_new_deal",
        "description": (
            "Full new-deal flow in one call: resolves account and vendor by name, "
            "creates the Opportunity (auto-named '[VEN] - [Model] - [Account]'), "
            "creates a Draft Quote linked to the opportunity with the Sales pricebook, "
            "logs a 'New Deal Created' completed activity, and returns Salesforce Lightning "
            "URLs to both the Opportunity and Quote for immediate review."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "account_name": {"type": "string", "description": "Account/company name (partial match OK)"},
                "vendor_name": {"type": "string", "description": "Vendor name (partial match — e.g. 'HEM', 'Trumpf')"},
                "machine_model": {"type": "string", "description": "Machine model (e.g. 'HEM Saw VT120')"},
                "contact_name": {"type": "string", "description": "Primary contact name (partial match, optional)"},
                "amount": {"type": "number", "description": "Estimated deal amount (optional)"},
                "stage": {"type": "string", "description": "Opportunity stage (defaults to 'Discovery')"},
                "close_date": {"type": "string", "description": "Expected close date YYYY-MM-DD (defaults to 90 days out)"},
                "notes": {"type": "string", "description": "Deal notes — saved to Opportunity Description and the activity log"},
                "quote_expiration_date": {"type": "string", "description": "Quote expiration date YYYY-MM-DD (defaults to 30 days out)"},
            },
            "required": ["account_name", "vendor_name", "machine_model"],
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
    soql = f"SELECT Id, Name, Phone, Website, BillingCity, BillingState, BillingPostalCode, Division__c, Territory__c, CompanyType__c, Account_Status__c, Account_Rating__c, Open_Deal_Amount__c, Open_Deal_Count__c, Closed_Deal_Amount__c, Closed_Deal_Count__c FROM Account WHERE Name LIKE '%{name}%' {owner_filter} LIMIT 5"
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
    if args.get("what_id") or args.get("opportunity_id"):
        payload["WhatId"] = args.get("what_id") or args.get("opportunity_id")
    if args.get("who_id") or args.get("contact_id"):
        payload["WhoId"] = args.get("who_id") or args.get("contact_id")
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


def tool_sf_search_opportunities(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    limit = args.get("limit", 10)
    owner_filter = f"AND OwnerId = '{OWNER_ID}'" if OWNER_ID else ""

    filters = ["IsClosed = false"]
    if args.get("account_name"):
        filters.append(f"Account.Name LIKE '%{args['account_name']}%'")
    if args.get("opportunity_name"):
        filters.append(f"Name LIKE '%{args['opportunity_name']}%'")
    if args.get("machine_type"):
        mt = args["machine_type"].replace("'", "\\'")
        filters.append(f"(Name LIKE '%{mt}%' OR Description LIKE '%{mt}%')")

    where = " AND ".join(filters)
    soql = f"""
        SELECT Id, Name, StageName, Amount, CloseDate, Probability,
               Account.Name, Account.Id, Owner.Name, Description, NextStep
        FROM Opportunity
        WHERE {where} {owner_filter}
        ORDER BY LastModifiedDate DESC
        LIMIT {limit}
    """
    result = sf_query(tokens, soql)
    seen_ids = set()

    def _map_opp(r):
        return {
            "id": r["Id"],
            "name": r["Name"],
            "stage": r.get("StageName"),
            "amount": r.get("Amount"),
            "close_date": r.get("CloseDate"),
            "account": (r.get("Account") or {}).get("Name"),
            "account_id": (r.get("Account") or {}).get("Id"),
            "owner": (r.get("Owner") or {}).get("Name"),
            "probability": r.get("Probability"),
            "description": r.get("Description"),
            "next_step": r.get("NextStep"),
        }

    opps = []
    for r in result.get("records", []):
        seen_ids.add(r["Id"])
        opps.append(_map_opp(r))

    # Contact-based search via OpportunityContactRole
    if args.get("contact_name") and len(opps) < limit:
        cname = args["contact_name"].replace("'", "\\'")
        c_result = sf_query(tokens, f"SELECT Id FROM Contact WHERE Name LIKE '%{cname}%' LIMIT 5")
        for c in c_result.get("records", []):
            role_result = sf_query(tokens, f"SELECT OpportunityId FROM OpportunityContactRole WHERE ContactId = '{c['Id']}' LIMIT 10")
            for role in role_result.get("records", []):
                oid = role["OpportunityId"]
                if oid not in seen_ids:
                    seen_ids.add(oid)
                    opp_result = sf_query(tokens, f"""
                        SELECT Id, Name, StageName, Amount, CloseDate, Probability,
                               Account.Name, Account.Id, Owner.Name, Description, NextStep
                        FROM Opportunity WHERE Id = '{oid}' AND IsClosed = false LIMIT 1
                    """)
                    for r in opp_result.get("records", []):
                        opps.append(_map_opp(r))

    return {"opportunities": opps, "count": len(opps)}


SALES_PRICEBOOK_ID = "01sNu000001OquXIAS"


def tool_sf_create_quote(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}

    # Default name to opportunity name if not provided
    name = args.get("name")
    if not name:
        opp_records = sf_query(tokens, f"SELECT Name FROM Opportunity WHERE Id = '{args['opportunity_id']}' LIMIT 1").get("records", [])
        name = opp_records[0]["Name"] if opp_records else args["opportunity_id"]

    # Default pricebook to Sales pricebook
    payload = {
        "Name": name,
        "OpportunityId": args["opportunity_id"],
        "Status": args.get("status", "Draft"),
        "Pricebook2Id": args.get("pricebook_id", SALES_PRICEBOOK_ID),
    }
    for field, key in [
        ("expiration_date", "ExpirationDate"),
        ("payment_terms", "PaymentTerms"),
        ("description", "Description"),
        ("billing_name", "BillingName"),
        ("shipping_name", "ShippingName"),
        ("shipping_terms", "ShippingTerms"),
    ]:
        if args.get(field):
            payload[key] = args[field]
    if args.get("shipping_handling") is not None:
        payload["ShippingHandling"] = args["shipping_handling"]
    if args.get("custom_fields"):
        payload.update(args["custom_fields"])

    result = sf_post(tokens, "sobjects/Quote", payload)
    if not result.get("success"):
        return {"error": "Failed to create quote", "errors": result.get("errors", [])}

    quote_id = result["id"]
    instance_url = tokens["instance_url"]
    q_data = sf_query(tokens, f"SELECT QuoteNumber FROM Quote WHERE Id = '{quote_id}' LIMIT 1")
    quote_number = (q_data.get("records") or [{}])[0].get("QuoteNumber")

    return {
        "success": True,
        "quote_id": quote_id,
        "quote_number": quote_number,
        "quote_url": f"{instance_url}/lightning/r/Quote/{quote_id}/view",
        "opportunity_url": f"{instance_url}/lightning/r/Opportunity/{args['opportunity_id']}/view",
    }


def tool_sf_get_pricebooks(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    soql = "SELECT Id, Name, IsActive, IsStandard FROM Pricebook2 WHERE IsActive = true ORDER BY IsStandard DESC, Name ASC LIMIT 20"
    result = sf_query(tokens, soql)
    pricebooks = [
        {"id": r["Id"], "name": r["Name"], "is_standard": r.get("IsStandard", False)}
        for r in result.get("records", [])
    ]
    return {"pricebooks": pricebooks, "count": len(pricebooks)}


def tool_sf_get_pricebook_entries(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    pricebook_id = args["pricebook_id"]
    limit = args.get("limit", 25)
    name_filter = f"AND Product2.Name LIKE '%{args['product_name']}%'" if args.get("product_name") else ""
    soql = f"""
        SELECT Id, Product2Id, Product2.Name, Product2.Description,
               Product2.ProductCode, UnitPrice, IsActive
        FROM PricebookEntry
        WHERE Pricebook2Id = '{pricebook_id}' AND IsActive = true
        {name_filter}
        ORDER BY Product2.Name ASC
        LIMIT {limit}
    """
    result = sf_query(tokens, soql)
    entries = []
    for r in result.get("records", []):
        p = r.get("Product2") or {}
        entries.append({
            "pricebook_entry_id": r["Id"],
            "product_id": r.get("Product2Id"),
            "product_name": p.get("Name"),
            "product_code": p.get("ProductCode"),
            "description": p.get("Description"),
            "list_price": r.get("UnitPrice"),
        })
    return {"entries": entries, "count": len(entries)}


def tool_sf_add_quote_line_item(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}

    payload = {
        "QuoteId": args["quote_id"],
        "PricebookEntryId": args["pricebook_entry_id"],
        "Quantity": args["quantity"],
    }
    if args.get("unit_price") is not None:
        payload["UnitPrice"] = args["unit_price"]
    if args.get("description"):
        payload["Description"] = args["description"]
    if args.get("sort_order") is not None:
        payload["SortOrder"] = args["sort_order"]
    if args.get("custom_fields"):
        payload.update(args["custom_fields"])

    result = sf_post(tokens, "sobjects/QuoteLineItem", payload)
    if not result.get("success"):
        return {"error": "Failed to add line item", "errors": result.get("errors", [])}
    return {"success": True, "line_item_id": result.get("id"), "quote_id": args["quote_id"]}


def tool_sf_add_quote_line_items(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}

    quote_id = args["quote_id"]
    results = []
    for idx, item in enumerate(args.get("line_items", [])):
        payload = {
            "QuoteId": quote_id,
            "PricebookEntryId": item["pricebook_entry_id"],
            "Quantity": item["quantity"],
        }
        if item.get("unit_price") is not None:
            payload["UnitPrice"] = item["unit_price"]
        if item.get("description"):
            payload["Description"] = item["description"]
        if item.get("sort_order") is not None:
            payload["SortOrder"] = item["sort_order"]
        if item.get("custom_fields"):
            payload.update(item["custom_fields"])

        r = sf_post(tokens, "sobjects/QuoteLineItem", payload)
        if r.get("success"):
            results.append({"index": idx, "success": True, "line_item_id": r.get("id"), "pricebook_entry_id": item["pricebook_entry_id"]})
        else:
            results.append({"index": idx, "success": False, "errors": r.get("errors", []), "pricebook_entry_id": item["pricebook_entry_id"]})

    succeeded = sum(1 for r in results if r["success"])
    return {
        "quote_id": quote_id,
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }


def tool_sf_describe_object(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}

    object_name = args["object_name"]
    custom_only = args.get("custom_only", False)

    from urllib.parse import quote as url_quote
    url = f"sobjects/{url_quote(object_name)}/describe"
    try:
        data = sf_get(tokens, url)
    except Exception as e:
        return {"error": f"Describe failed: {e}"}

    fields = []
    for f in data.get("fields", []):
        is_custom = f.get("name", "").endswith("__c")
        if custom_only and not is_custom:
            continue
        fields.append({
            "name": f.get("name"),
            "label": f.get("label"),
            "type": f.get("type"),
            "custom": is_custom,
            "updateable": f.get("updateable", True),
            "nillable": f.get("nillable", True),
            "length": f.get("length"),
            "pick_values": [p["value"] for p in f.get("picklistValues", []) if p.get("active")] if f.get("picklistValues") else None,
        })

    return {
        "object": object_name,
        "label": data.get("label"),
        "field_count": len(fields),
        "fields": fields,
    }


def tool_sf_upload_file(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}

    file_path = args["file_path"]
    if not os.path.isabs(file_path) and VAULT_PATH:
        file_path = os.path.join(VAULT_PATH, file_path)
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}

    filename = os.path.basename(file_path)
    title = args.get("title") or filename
    linked_record_id = args["linked_record_id"]

    with open(file_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")

    # FirstPublishLocationId auto-creates the ContentDocumentLink
    cv_payload = {
        "Title": title,
        "PathOnClient": filename,
        "VersionData": encoded,
        "FirstPublishLocationId": linked_record_id,
    }
    result = sf_post(tokens, "sobjects/ContentVersion", cv_payload)
    if not result.get("success"):
        return {"error": "Failed to upload file", "errors": result.get("errors", [])}

    cv_id = result["id"]
    cv_data = sf_query(tokens, f"SELECT ContentDocumentId, ContentSize FROM ContentVersion WHERE Id = '{cv_id}' LIMIT 1")
    rec = (cv_data.get("records") or [{}])[0]

    return {
        "success": True,
        "content_version_id": cv_id,
        "content_document_id": rec.get("ContentDocumentId"),
        "title": title,
        "filename": filename,
        "size_bytes": rec.get("ContentSize"),
        "linked_to": linked_record_id,
    }


def tool_sf_get_opportunity_contacts(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    opp_id = args["opportunity_id"]
    soql = f"""
        SELECT Contact.Id, Contact.Name, Contact.Email, Contact.Phone,
               Contact.Title, Role, IsPrimary
        FROM OpportunityContactRole
        WHERE OpportunityId = '{opp_id}'
    """
    result = sf_query(tokens, soql)
    contacts = []
    for r in result.get("records", []):
        c = r.get("Contact") or {}
        contacts.append({
            "contact_id": c.get("Id"),
            "name": c.get("Name"),
            "email": c.get("Email"),
            "phone": c.get("Phone"),
            "title": c.get("Title"),
            "role": r.get("Role"),
            "is_primary": r.get("IsPrimary"),
        })
    return {"contacts": contacts, "count": len(contacts)}


def _decode_header_value(raw):
    parts = email_decode_header(raw or "")
    out = []
    for fragment, enc in parts:
        if isinstance(fragment, bytes):
            out.append(fragment.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(fragment)
    return "".join(out)


def _parse_eml(file_path):
    """Parse a .eml file and return structured fields."""
    with open(file_path, "rb") as f:
        msg = email_lib.message_from_bytes(f.read())
    subject = _decode_header_value(msg.get("Subject", ""))
    from_ = _decode_header_value(msg.get("From", ""))
    date_ = msg.get("Date", "")
    body_parts = []
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                charset = part.get_content_charset() or "utf-8"
                body_parts.append(part.get_payload(decode=True).decode(charset, errors="replace"))
            elif "attachment" in cd:
                fn = part.get_filename()
                if fn:
                    attachments.append(_decode_header_value(fn))
    else:
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if payload:
            body_parts.append(payload.decode(charset, errors="replace"))
    return {
        "from": from_,
        "subject": subject,
        "date": date_,
        "body": "\n".join(body_parts),
        "attachments": attachments,
    }


def _strip_html(text):
    """Strip HTML tags and decode common entities from an HTML email body."""
    from html.parser import HTMLParser

    class _Stripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self._parts = []
            self._skip = False

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style"):
                self._skip = True
            elif tag in ("br", "p", "div", "tr", "li"):
                self._parts.append("\n")

        def handle_endtag(self, tag):
            if tag in ("script", "style"):
                self._skip = False

        def handle_data(self, data):
            if not self._skip:
                self._parts.append(data)

    s = _Stripper()
    s.feed(text)
    result = "".join(s._parts)
    # Collapse runs of blank lines to at most two
    import re
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def _parse_txt(file_path):
    """Parse a plain-text (or HTML) email file saved by Power Automate."""
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    from_ = subject = date_ = ""
    body_lines = []
    in_headers = True
    for line in content.splitlines():
        if in_headers:
            low = line.lower()
            if low.startswith("from:"):
                from_ = line[5:].strip()
            elif low.startswith("subject:"):
                subject = line[8:].strip()
            elif low.startswith("date:"):
                date_ = line[5:].strip()
            elif line.strip() == "":
                in_headers = False
            else:
                body_lines.append(line)
        else:
            body_lines.append(line)
    body = "\n".join(body_lines)
    # PA may write the raw HTML body when the Html-to-text connector is unavailable.
    if "<html" in body.lower() or "<!doctype" in body.lower():
        body = _strip_html(body)
    return {
        "from": from_,
        "subject": subject,
        "date": date_,
        "body": body,
        "attachments": [],
    }


def _get_email_queue_path():
    """Return EMAIL_QUEUE_PATH, falling back to salesforce.json config if env var not set."""
    if EMAIL_QUEUE_PATH:
        return EMAIL_QUEUE_PATH
    # Re-read config file in case the module-level load ran before env was available
    try:
        config_path = Path(__file__).resolve().parent.parent.parent / ".claude" / "mcp" / "salesforce.json"
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        val = cfg.get("server", {}).get("env", {}).get("EMAIL_QUEUE_PATH", "")
        if val and not val.startswith("${"):
            return val
    except Exception:
        pass
    return ""


def tool_email_read_pending(args):
    limit = min(args.get("limit", 5), 20)
    queue_path = _get_email_queue_path()
    if queue_path:
        pending_dir = os.path.join(queue_path, "pending")
    elif VAULT_PATH:
        pending_dir = os.path.join(VAULT_PATH, "Inbox", "Emails", "pending")
    else:
        pending_dir = None
    if not pending_dir or not os.path.isdir(pending_dir):
        return {
            "emails": [],
            "count": 0,
            "pending_dir": pending_dir,
            "message": (
                "Pending folder not found. "
                "Create Inbox/Emails/pending/ in your vault and have Power Automate "
                "save email files there, or drag .eml files into it manually."
            ),
        }

    files = sorted(
        [f for f in Path(pending_dir).iterdir() if f.suffix in (".eml", ".txt", ".md") and f.is_file()],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )[:limit]

    emails = []
    for f in files:
        try:
            if f.suffix == ".eml":
                parsed = _parse_eml(str(f))
            else:
                parsed = _parse_txt(str(f))
            parsed["filename"] = f.name
            parsed["path"] = str(f)
            parsed["body"] = parsed["body"][:8000]
            parsed["body_truncated"] = len(parsed["body"]) > 8000
            emails.append(parsed)
        except Exception as e:
            emails.append({"filename": f.name, "error": str(e)})

    return {"emails": emails, "count": len(emails), "pending_dir": pending_dir}


def tool_email_archive_pending(args):
    filename = args["filename"]
    queue_path = _get_email_queue_path()
    if queue_path:
        pending_dir = Path(queue_path) / "pending"
        processed_dir = Path(queue_path) / "processed"
    elif VAULT_PATH:
        pending_dir = Path(VAULT_PATH) / "Inbox" / "Emails" / "pending"
        processed_dir = Path(VAULT_PATH) / "Inbox" / "Emails" / "processed"
    else:
        return {"error": "Neither EMAIL_QUEUE_PATH nor VAULT_PATH is set."}
    processed_dir.mkdir(parents=True, exist_ok=True)
    src = pending_dir / filename
    if not src.exists():
        return {"error": f"File not found in pending/: {filename}"}
    dst = processed_dir / filename
    if dst.exists():
        stem, suffix = os.path.splitext(filename)
        dst = processed_dir / f"{stem}_{int(datetime.now().timestamp())}{suffix}"
    src.rename(dst)
    # OneDrive syncs the file move to the cloud automatically — no git needed.
    return {"success": True, "archived_to": str(dst)}


def tool_sf_get_vendors(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}
    soql = "SELECT Id, Name FROM Account WHERE RecordType.Name = 'Vendor' ORDER BY Name ASC LIMIT 200"
    result = sf_query(tokens, soql)
    vendors = [{"id": r["Id"], "name": r["Name"], "prefix": r["Name"][:3].upper()} for r in result.get("records", [])]
    return {"vendors": vendors, "count": len(vendors)}


def tool_sf_create_opportunity(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}

    account_id = args["account_id"]
    vendor_id = args.get("vendor_id")
    machine_model = args.get("machine_model", "")

    opp_name = args.get("name")
    if not opp_name:
        if not vendor_id or not machine_model:
            return {"error": "Provide either 'name', or both 'vendor_id' and 'machine_model' to auto-generate the opportunity name."}
        vendor_records = sf_query(tokens, f"SELECT Name FROM Account WHERE Id = '{vendor_id}' LIMIT 1").get("records", [])
        if not vendor_records:
            return {"error": f"Vendor not found for id '{vendor_id}'. Run sf_get_vendors to get valid vendor IDs."}
        vendor_prefix = vendor_records[0]["Name"][:3].upper()
        acct_records = sf_query(tokens, f"SELECT Name FROM Account WHERE Id = '{account_id}' LIMIT 1").get("records", [])
        if not acct_records:
            return {"error": f"Account not found for id '{account_id}'."}
        account_name = acct_records[0]["Name"]
        opp_name = f"{vendor_prefix} - {machine_model} - {account_name}"

    dup_check = sf_query(tokens, (
        f"SELECT Id, Name, StageName FROM Opportunity "
        f"WHERE AccountId = '{account_id}' AND Name = '{opp_name}' AND IsClosed = false LIMIT 1"
    ))
    dup_records = dup_check.get("records", [])
    if dup_records and not args.get("force_create"):
        dup = dup_records[0]
        instance_url = tokens.get("instance_url", "")
        return {
            "duplicate": True,
            "message": "An open opportunity with this name already exists. Pass force_create=true to create anyway.",
            "existing_opportunity_id": dup["Id"],
            "existing_opportunity_name": dup["Name"],
            "existing_stage": dup["StageName"],
            "salesforce_url": f"{instance_url}/lightning/r/Opportunity/{dup['Id']}/view" if instance_url else None,
        }

    default_close = (date.today() + timedelta(days=90)).isoformat()
    payload = {
        "Name": opp_name,
        "AccountId": account_id,
        "StageName": args.get("stage", "Discovery"),
        "CloseDate": args.get("close_date", default_close),
    }
    if vendor_id:
        payload["Vendor__c"] = vendor_id
    if args.get("amount") is not None:
        payload["Amount"] = args["amount"]
    if args.get("description"):
        payload["Description"] = args["description"]
    if args.get("next_step"):
        payload["NextStep"] = args["next_step"]
    if args.get("type"):
        payload["Type"] = args["type"]
    if OWNER_ID:
        payload["OwnerId"] = OWNER_ID

    result = sf_post(tokens, "sobjects/Opportunity", payload)
    opp_id = result.get("id")
    if not opp_id:
        return {"success": False, "errors": result.get("errors", []), "raw": result}

    instance_url = tokens.get("instance_url", "")
    warnings = []

    if args.get("contact_id"):
        try:
            sf_post(tokens, "sobjects/OpportunityContactRole", {
                "OpportunityId": opp_id,
                "ContactId": args["contact_id"],
                "IsPrimary": True,
            })
        except Exception as e:
            warnings.append(f"Contact role not linked: {e}")

    follow_up_task_id = None
    follow_up_date = None
    if not args.get("skip_follow_up_task"):
        follow_up_date = (date.today() + timedelta(days=3)).isoformat()
        task_payload = {
            "Subject": f"Discovery Call - {opp_name}",
            "Status": "Not Started",
            "ActivityDate": follow_up_date,
            "WhatId": opp_id,
            "Type": "Call",
        }
        if args.get("contact_id"):
            task_payload["WhoId"] = args["contact_id"]
        if OWNER_ID:
            task_payload["OwnerId"] = OWNER_ID
        try:
            task_result = sf_post(tokens, "sobjects/Task", task_payload)
            follow_up_task_id = task_result.get("id")
        except Exception as e:
            warnings.append(f"Follow-up task not created: {e}")

    response = {
        "success": True,
        "opportunity_id": opp_id,
        "opportunity_name": opp_name,
        "follow_up_task_id": follow_up_task_id,
        "follow_up_task_due": follow_up_date,
        "salesforce_url": f"{instance_url}/lightning/r/Opportunity/{opp_id}/view" if instance_url else None,
    }
    if warnings:
        response["warnings"] = warnings
    return response


def tool_sf_new_deal(args):
    tokens = get_valid_tokens()
    if not tokens:
        return {"error": "Not authenticated. Run sf_authenticate first."}

    instance_url = tokens.get("instance_url", "")
    steps = []
    warnings = []

    # 1. Resolve account
    acct_records = sf_query(tokens, f"SELECT Id, Name FROM Account WHERE Name LIKE '%{args['account_name']}%' LIMIT 5").get("records", [])
    if not acct_records:
        return {"error": f"No account found matching '{args['account_name']}'."}
    account = acct_records[0]
    account_id, account_name = account["Id"], account["Name"]
    steps.append(f"✅ Account: {account_name} ({account_id})")

    # 2. Resolve vendor
    vendor_records = sf_query(tokens, f"SELECT Id, Name FROM Account WHERE RecordType.Name = 'Vendor' AND Name LIKE '%{args['vendor_name']}%' ORDER BY Name ASC LIMIT 5").get("records", [])
    if not vendor_records:
        return {"error": f"No vendor found matching '{args['vendor_name']}'. Run sf_get_vendors to see all vendors."}
    vendor = vendor_records[0]
    vendor_id, vendor_name = vendor["Id"], vendor["Name"]
    vendor_prefix = vendor_name[:3].upper()
    steps.append(f"✅ Vendor: {vendor_name} ({vendor_id})")

    # 3. Resolve contact (optional)
    contact_id = None
    if args.get("contact_name"):
        contact_records = sf_query(tokens, f"SELECT Id, Name FROM Contact WHERE Name LIKE '%{args['contact_name']}%' AND AccountId = '{account_id}' LIMIT 5").get("records", [])
        if contact_records:
            contact_id = contact_records[0]["Id"]
            steps.append(f"✅ Contact: {contact_records[0]['Name']} ({contact_id})")
        else:
            warnings.append(f"Contact '{args['contact_name']}' not found on this account — skipping contact link.")

    # 4. Create opportunity
    machine_model = args["machine_model"]
    opp_name = f"{vendor_prefix} - {machine_model} - {account_name}"

    dup_check = sf_query(tokens, f"SELECT Id, Name FROM Opportunity WHERE AccountId = '{account_id}' AND Name = '{opp_name}' AND IsClosed = false LIMIT 1").get("records", [])
    if dup_check:
        dup = dup_check[0]
        return {
            "duplicate": True,
            "message": "An open opportunity with this name already exists.",
            "existing_opportunity_id": dup["Id"],
            "existing_opportunity_name": dup["Name"],
            "salesforce_url": f"{instance_url}/lightning/r/Opportunity/{dup['Id']}/view",
        }

    default_close = (date.today() + timedelta(days=90)).isoformat()
    opp_payload = {
        "Name": opp_name,
        "AccountId": account_id,
        "Vendor__c": vendor_id,
        "StageName": args.get("stage", "Discovery"),
        "CloseDate": args.get("close_date", default_close),
    }
    if args.get("amount") is not None:
        opp_payload["Amount"] = args["amount"]
    if args.get("notes"):
        opp_payload["Description"] = args["notes"]
    if OWNER_ID:
        opp_payload["OwnerId"] = OWNER_ID

    opp_result = sf_post(tokens, "sobjects/Opportunity", opp_payload)
    opp_id = opp_result.get("id")
    if not opp_id:
        return {"success": False, "step_failed": "create_opportunity", "errors": opp_result.get("errors", []), "steps_completed": steps}
    opp_url = f"{instance_url}/lightning/r/Opportunity/{opp_id}/view" if instance_url else None
    steps.append(f"✅ Opportunity created: {opp_name}")

    if contact_id:
        try:
            sf_post(tokens, "sobjects/OpportunityContactRole", {"OpportunityId": opp_id, "ContactId": contact_id, "IsPrimary": True})
            steps.append("✅ Primary contact linked")
        except Exception as e:
            warnings.append(f"Contact role not linked: {e}")

    follow_up_date = (date.today() + timedelta(days=3)).isoformat()
    task_payload = {
        "Subject": f"Discovery Call - {opp_name}",
        "Status": "Not Started",
        "ActivityDate": follow_up_date,
        "WhatId": opp_id,
        "Type": "Call",
    }
    if contact_id:
        task_payload["WhoId"] = contact_id
    if OWNER_ID:
        task_payload["OwnerId"] = OWNER_ID
    try:
        sf_post(tokens, "sobjects/Task", task_payload)
        steps.append(f"✅ Discovery Call task scheduled for {follow_up_date}")
    except Exception as e:
        warnings.append(f"Discovery Call task not created: {e}")

    # 5. Create quote
    default_expiry = (date.today() + timedelta(days=30)).isoformat()
    quote_payload = {
        "OpportunityId": opp_id,
        "Name": opp_name,
        "Status": "Draft",
        "ExpirationDate": args.get("quote_expiration_date", default_expiry),
        "Pricebook2Id": SALES_PRICEBOOK_ID,
    }
    quote_result = sf_post(tokens, "sobjects/Quote", quote_payload)
    quote_id = quote_result.get("id")
    quote_url = None
    quote_number = None
    if quote_id:
        quote_url = f"{instance_url}/lightning/r/Quote/{quote_id}/view" if instance_url else None
        qn_records = sf_query(tokens, f"SELECT QuoteNumber FROM Quote WHERE Id = '{quote_id}' LIMIT 1").get("records", [])
        quote_number = qn_records[0].get("QuoteNumber") if qn_records else None
        steps.append(f"✅ Quote created: {quote_number or quote_id}")
    else:
        warnings.append(f"Quote not created: {quote_result.get('errors', quote_result)}")

    # 6. Log completed activity
    log_payload = {
        "Subject": f"New Deal Created - {opp_name}",
        "Status": "Completed",
        "ActivityDate": date.today().isoformat(),
        "WhatId": opp_id,
        "Type": "Note",
        "Description": args.get("notes") or f"Opportunity and quote created for {machine_model} at {account_name}.",
    }
    if contact_id:
        log_payload["WhoId"] = contact_id
    if OWNER_ID:
        log_payload["OwnerId"] = OWNER_ID
    try:
        sf_post(tokens, "sobjects/Task", log_payload)
        steps.append("✅ Activity logged: New Deal Created")
    except Exception as e:
        warnings.append(f"Activity log not created: {e}")

    response = {
        "success": True,
        "opportunity_id": opp_id,
        "opportunity_name": opp_name,
        "opportunity_url": opp_url,
        "quote_id": quote_id,
        "quote_number": quote_number,
        "quote_url": quote_url,
        "account": account_name,
        "vendor": vendor_name,
        "steps": steps,
    }
    if warnings:
        response["warnings"] = warnings
    return response


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
    "sf_search_opportunities": tool_sf_search_opportunities,
    "sf_create_quote": tool_sf_create_quote,
    "sf_get_pricebooks": tool_sf_get_pricebooks,
    "sf_get_pricebook_entries": tool_sf_get_pricebook_entries,
    "sf_add_quote_line_item": tool_sf_add_quote_line_item,
    "sf_add_quote_line_items": tool_sf_add_quote_line_items,
    "sf_describe_object": tool_sf_describe_object,
    "sf_upload_file": tool_sf_upload_file,
    "sf_get_opportunity_contacts": tool_sf_get_opportunity_contacts,
    "email_read_pending": tool_email_read_pending,
    "email_archive_pending": tool_email_archive_pending,
    "sf_get_vendors": tool_sf_get_vendors,
    "sf_create_opportunity": tool_sf_create_opportunity,
    "sf_new_deal": tool_sf_new_deal,
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
