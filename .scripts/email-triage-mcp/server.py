#!/usr/bin/env python3
"""MAM Email Triage MCP — queries the Cloudflare Worker / D1 database."""

import json
import os
import re
import sys
import urllib.request
import urllib.parse
import urllib.error
from datetime import date, datetime, timedelta
from html.parser import HTMLParser


def _load_dotenv():
    """Load .env from cwd or up to 3 parent dirs — fallback when env vars aren't set at the system level."""
    path = os.getcwd()
    for _ in range(4):
        env_file = os.path.join(path, '.env')
        if os.path.isfile(env_file):
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, _, v = line.partition('=')
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k not in os.environ:
                            os.environ[k] = v
            break
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent

_load_dotenv()

WORKER_URL = os.environ.get("EMAIL_TRIAGE_URL", "https://mam-email-triage.cbarsanti.workers.dev")
API_KEY    = os.environ.get("EMAIL_TRIAGE_KEY", "")


# ── HTML stripping ─────────────────────────────────────────────────────────────

class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self):
        return re.sub(r'\s+', ' ', ''.join(self._parts)).strip()


def strip_html(html):
    if not html or '<' not in html:
        return html
    s = _HTMLStripper()
    s.feed(html)
    return s.get_text()


# ── HTTP helper ────────────────────────────────────────────────────────────────

def worker_get(path, params=None):
    url = WORKER_URL + path
    if params:
        url += '?' + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    headers = {"User-Agent": "dex-email-triage-mcp/1.0"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def clean_email(row):
    """Strip HTML from body fields and return a clean dict."""
    row = dict(row)
    if row.get('body_preview'):
        row['body_preview'] = strip_html(row['body_preview'])
    if row.get('full_body'):
        row['full_body'] = strip_html(row['full_body'])[:2000]  # cap at 2k chars
    return row


# ── Business day helper (mirrors .scripts/salesforce-mcp/server.py) ────────────

def _us_federal_holidays(year):
    """Return a set of observed US federal holiday dates for the given year."""
    def nth_weekday(year, month, weekday, n):
        d = date(year, month, 1)
        offset = (weekday - d.weekday()) % 7
        d += timedelta(days=offset + (n - 1) * 7)
        return d

    def last_weekday(year, month, weekday):
        d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
        offset = (d.weekday() - weekday) % 7
        return d - timedelta(days=offset)

    def observed(d):
        if d.weekday() == 5:
            return d - timedelta(days=1)
        if d.weekday() == 6:
            return d + timedelta(days=1)
        return d

    return {
        observed(date(year, 1, 1)),
        nth_weekday(year, 1, 0, 3),
        nth_weekday(year, 2, 0, 3),
        last_weekday(year, 5, 0),
        observed(date(year, 6, 19)),
        observed(date(year, 7, 4)),
        nth_weekday(year, 9, 0, 1),
        nth_weekday(year, 10, 0, 2),
        observed(date(year, 11, 11)),
        nth_weekday(year, 11, 3, 4),
        observed(date(year, 12, 25)),
    }


def business_days_since(iso_timestamp):
    """Count weekday/non-holiday days between an ISO timestamp and now."""
    try:
        sent = datetime.fromisoformat(iso_timestamp.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return 0
    now = datetime.now(sent.tzinfo) if sent.tzinfo else datetime.utcnow()

    d = sent.date()
    end = now.date()
    holidays = _us_federal_holidays(d.year)
    count = 0
    while d < end:
        d += timedelta(days=1)
        if d.year not in {h.year for h in holidays}:
            holidays |= _us_federal_holidays(d.year)
        if d.weekday() < 5 and d not in holidays:
            count += 1
    return count


# ── MCP stdio protocol ─────────────────────────────────────────────────────────

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def error_response(id_, code, message):
    send({"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}})


def ok(id_, result):
    send({"jsonrpc": "2.0", "id": id_, "result": result})


# ── Tool definitions ───────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "search_emails",
        "description": (
            "Search emails by keyword (subject or body preview), sender email/name, "
            "Salesforce account name, or triage label. Returns sender, subject, body preview, "
            "received date, triage label, and Salesforce contact/account match."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to search in subject or body preview",
                },
                "from_email": {
                    "type": "string",
                    "description": "Filter by sender email address or name (partial match)",
                },
                "account": {
                    "type": "string",
                    "description": "Filter by Salesforce account name (partial match)",
                },
                "label": {
                    "type": "string",
                    "description": "Filter by triage label: urgent, follow_up, fyi, ignore, unclassified",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 20, max 50)",
                },
            },
        },
    },
    {
        "name": "get_recent_emails",
        "description": "Get the most recent emails, newest first. Optionally filter by triage label or status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of emails to return (default 15)",
                },
                "label": {
                    "type": "string",
                    "description": "Only return emails with this triage label",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status: new, reviewed, actioned",
                },
            },
        },
    },
    {
        "name": "get_actionable_emails",
        "description": (
            "Get emails that need attention — urgent and follow_up emails that are still 'new' (not yet reviewed or actioned). "
            "Use this during daily planning to surface what needs a response. Returns emails grouped by urgency."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max emails to return per label (default 10)",
                },
            },
        },
    },
    {
        "name": "get_emails_from_contact",
        "description": (
            "Get all emails from a specific person, company, or email domain. "
            "Searches sender email, sender name, and matched Salesforce account name."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "contact": {
                    "type": "string",
                    "description": "Email address, name, domain, or company (e.g. 'prestige', 'claire@trumpf.com', 'trumpf.com')",
                },
            },
            "required": ["contact"],
        },
    },
    {
        "name": "get_sent_emails",
        "description": (
            "Get emails Chris has sent, newest first. Optionally filter to a specific recipient "
            "or to only emails still awaiting a reply. Reply status is only tracked for emails "
            "sent to a matched Salesforce contact."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "recipient": {
                    "type": "string",
                    "description": "Filter by recipient email or name (partial match)",
                },
                "awaiting_reply_only": {
                    "type": "boolean",
                    "description": "Only return sent emails that haven't been replied to yet",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 20, max 50)",
                },
            },
        },
    },
    {
        "name": "get_unreplied_emails",
        "description": (
            "Get sent emails to Salesforce contacts that have gone unanswered for at least "
            "N business days (default 3). Use this to find customer follow-ups that are overdue."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "min_business_days": {
                    "type": "integer",
                    "description": "Minimum business days of silence before flagging (default 3)",
                },
            },
        },
    },
]


# ── Tool implementations ───────────────────────────────────────────────────────

def get_actionable_emails(args):
    limit = min(args.get("limit", 10), 30)

    urgent_data     = worker_get("/emails", {"label": "urgent",     "status": "new", "limit": limit})
    follow_up_data  = worker_get("/emails", {"label": "follow_up",  "status": "new", "limit": limit})

    urgent    = [clean_email(e) for e in urgent_data.get("emails", [])]
    follow_up = [clean_email(e) for e in follow_up_data.get("emails", [])]

    return {
        "urgent":    urgent,
        "follow_up": follow_up,
        "summary":   f"{len(urgent)} urgent, {len(follow_up)} follow-up emails need attention",
    }


def search_emails(args):
    query   = args.get("query", "")
    from_em = args.get("from_email", "")
    account = args.get("account", "")
    label   = args.get("label", "")
    limit   = min(args.get("limit", 20), 50)

    # Fetch a wider set from the worker and filter locally for query/from
    params = {"limit": min(limit * 3, 150), "offset": 0}
    if label:
        params["label"] = label
    if account:
        params["account"] = account

    data   = worker_get("/emails", params)
    emails = data.get("emails", [])

    # Client-side filter for query and from_email (worker doesn't support these yet)
    q_low  = query.lower()
    fr_low = from_em.lower()

    results = []
    for e in emails:
        if q_low and q_low not in (e.get("subject") or "").lower() \
                  and q_low not in (e.get("body_preview") or "").lower():
            continue
        if fr_low and fr_low not in (e.get("sender_email") or "").lower() \
                   and fr_low not in (e.get("sender_name") or "").lower():
            continue
        results.append(clean_email(e))
        if len(results) >= limit:
            break

    return {"emails": results, "count": len(results)}


def get_recent_emails(args):
    limit  = min(args.get("limit", 15), 50)
    label  = args.get("label")
    status = args.get("status")

    params = {"limit": limit, "offset": 0}
    if label:
        params["label"] = label
    if status:
        params["status"] = status

    data = worker_get("/emails", params)
    return {
        "emails": [clean_email(e) for e in data.get("emails", [])],
        "count":  len(data.get("emails", [])),
    }


def get_emails_from_contact(args):
    contact = args["contact"].lower()

    # Pull recent emails and filter by sender or SF account
    data   = worker_get("/emails", {"limit": 200, "offset": 0})
    emails = data.get("emails", [])

    # Also try account filter if it looks like a company name (no @)
    if "@" not in contact and "." not in contact:
        data2  = worker_get("/emails", {"limit": 200, "offset": 0, "account": contact})
        seen   = {e["id"] for e in emails}
        emails += [e for e in data2.get("emails", []) if e["id"] not in seen]

    results = []
    for e in emails:
        if contact in (e.get("sender_email") or "").lower() \
        or contact in (e.get("sender_name") or "").lower() \
        or contact in (e.get("sf_account_name") or "").lower():
            results.append(clean_email(e))

    results.sort(key=lambda x: x.get("received_at", ""), reverse=True)
    return {"emails": results[:50], "count": len(results)}


def get_sent_emails(args):
    recipient   = (args.get("recipient") or "").lower()
    awaiting    = args.get("awaiting_reply_only", False)
    limit       = min(args.get("limit", 20), 50)

    params = {"direction": "sent", "limit": min(limit * 3, 150), "offset": 0}
    if awaiting:
        params["reply_status"] = "awaiting_reply"

    data   = worker_get("/emails", params)
    emails = data.get("emails", [])

    results = []
    for e in emails:
        if recipient and recipient not in (e.get("recipient_email") or "").lower() \
                      and recipient not in (e.get("recipient_name") or "").lower():
            continue
        results.append(clean_email(e))
        if len(results) >= limit:
            break

    return {"emails": results, "count": len(results)}


def get_unreplied_emails(args):
    min_days = args.get("min_business_days", 3)

    data   = worker_get("/emails", {"direction": "sent", "reply_status": "awaiting_reply", "limit": 150, "offset": 0})
    emails = data.get("emails", [])

    overdue = []
    for e in emails:
        days = business_days_since(e.get("received_at"))
        if days >= min_days:
            row = clean_email(e)
            row["business_days_waiting"] = days
            overdue.append(row)

    overdue.sort(key=lambda x: x["business_days_waiting"], reverse=True)
    return {
        "emails": overdue,
        "count":  len(overdue),
        "summary": f"{len(overdue)} sent email(s) awaiting reply for {min_days}+ business days",
    }


TOOL_FNS = {
    "get_actionable_emails":   get_actionable_emails,
    "search_emails":           search_emails,
    "get_recent_emails":       get_recent_emails,
    "get_emails_from_contact": get_emails_from_contact,
    "get_sent_emails":         get_sent_emails,
    "get_unreplied_emails":    get_unreplied_emails,
}


# ── Main loop ──────────────────────────────────────────────────────────────────

def handle(msg):
    method = msg.get("method")
    id_    = msg.get("id")

    if method == "initialize":
        ok(id_, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "email-triage-mcp", "version": "1.0.0"},
        })

    elif method == "tools/list":
        ok(id_, {"tools": TOOLS})

    elif method == "tools/call":
        name = msg["params"]["name"]
        args = msg["params"].get("arguments", {})
        if name not in TOOL_FNS:
            error_response(id_, -32601, f"Unknown tool: {name}")
            return
        try:
            result     = TOOL_FNS[name](args)
            result_str = json.dumps(result, default=str)
            ok(id_, {"content": [{"type": "text", "text": result_str}]})
        except Exception as e:
            error_response(id_, -32603, str(e))

    elif method == "notifications/initialized":
        pass

    else:
        if id_ is not None:
            error_response(id_, -32601, f"Method not found: {method}")


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
