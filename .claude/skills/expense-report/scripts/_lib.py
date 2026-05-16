"""Shared helpers for the expense-report skill.

Gmail OAuth via gog, Odoo XML-RPC via .mcp.json, vendor categorisation,
HTML → PDF via WeasyPrint, image → PDF via Pillow, live ECB rates.

Importable from collect.py and finalize.py.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import xmlrpc.client
from datetime import datetime
from pathlib import Path
from typing import Iterable

# ----------------- Paths & secrets -----------------
DEX_MCP_JSON = Path("/Users/davidorban/Dev/Dex/.mcp.json")
GOG_CRED = Path("/Users/davidorban/Library/Application Support/gogcli/credentials-mine.json")
DEFAULT_GMAIL_USER = "david.orban@gmail.com"

# Futuroid Ltd company_id=1, David Orban hr.employee id=2
FUTUROID_COMPANY_ID = 1
DAVID_EMPLOYEE_ID = 2


# ----------------- Vendor → product_id -----------------
# product_id values come from the live Odoo (2=Travel & Accommodation,
# 5=Communication / SaaS, 8=AI Tools).
AI_TOOLS_RE = re.compile(
    r"anthropic|warp|openrouter|eleven\s*labs|agentmail|mainfunc|grok|xai|x\.ai|"
    r"gladia|wispr|openai|cursor",
    re.I,
)
TRAVEL_RE = re.compile(
    r"uber|freenow|trenitalia|italo|ryanair|lufthansa|ita\s*airways|"
    r"booking|airbnb|hotel|taxi|hertz|avis|sixt|easyjet|wizz",
    re.I,
)
SAAS_RE = re.compile(r"odoo|vercel|x\s*developer", re.I)


def categorize(vendor: str | None) -> tuple[int, str]:
    """Return (product_id, label)."""
    v = vendor or ""
    if AI_TOOLS_RE.search(v):
        return 8, "AI Tools"
    if TRAVEL_RE.search(v):
        return 2, "Travel & Accommodation"
    if SAAS_RE.search(v):
        return 5, "Communication"
    return 5, "Communication"  # default


# ----------------- OAuth helpers -----------------
def gmail_token(out_path: str = "/tmp/gog-token-expense.json") -> str:
    """Refresh + return a Gmail access token via the gog CLI."""
    subprocess.run(
        ["gog", "auth", "tokens", "export", DEFAULT_GMAIL_USER,
         "--out", out_path, "--client", "mine", "--overwrite"],
        check=True, capture_output=True,
    )
    cred = json.load(open(GOG_CRED))
    tok = json.load(open(out_path))
    body = urllib.parse.urlencode({
        "client_id": cred["client_id"],
        "client_secret": cred["client_secret"],
        "refresh_token": tok["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())["access_token"]


def odoo_session():
    cfg = json.load(open(DEX_MCP_JSON))
    env = cfg["mcpServers"]["odoo-mcp"]["env"]
    common = xmlrpc.client.ServerProxy(f"{env['ODOO_URL']}/xmlrpc/2/common")
    uid = common.authenticate(env["ODOO_DB"], env["ODOO_USER"], env["ODOO_API_KEY"], {})
    if not uid:
        raise RuntimeError("Odoo auth failed — check .mcp.json odoo-mcp env vars")
    models = xmlrpc.client.ServerProxy(f"{env['ODOO_URL']}/xmlrpc/2/object")
    return env["ODOO_DB"], uid, env["ODOO_API_KEY"], models


# ----------------- Gmail helpers -----------------
def gmail_get(url: str, token: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def list_messages(token: str, query: str) -> list[dict]:
    """List all message stubs matching the Gmail search query."""
    ids: list[dict] = []
    page = ""
    while True:
        params = {"q": query, "maxResults": "100"}
        if page:
            params["pageToken"] = page
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages?" + urllib.parse.urlencode(params)
        try:
            d = gmail_get(url, token)
        except Exception as ex:
            print(f"  ! list_messages failed: {ex}", file=sys.stderr)
            break
        ids.extend(d.get("messages", []))
        page = d.get("nextPageToken", "")
        if not page:
            break
    return ids


def find_pdfs(payload) -> list[tuple[str, str]]:
    """Return [(filename, attachment_id), ...] for PDF parts in a payload tree."""
    out: list[tuple[str, str]] = []

    def walk(part):
        if not part:
            return
        mt = (part.get("mimeType") or "").lower()
        body = part.get("body") or {}
        att_id = body.get("attachmentId")
        if mt == "application/pdf" and att_id:
            out.append((part.get("filename") or "att.pdf", att_id))
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    return out


def find_images(payload, min_size: int = 3000) -> list[tuple[str, str, str]]:
    """Return [(filename, attachment_id, mimetype), ...] for image parts
    larger than min_size bytes (filters out tracking pixels)."""
    out = []

    def walk(part):
        if not part:
            return
        mt = (part.get("mimeType") or "").lower()
        body = part.get("body") or {}
        att_id = body.get("attachmentId")
        size = body.get("size") or 0
        if mt.startswith("image/") and att_id and size >= min_size:
            fname = part.get("filename") or f"att.{mt.split('/')[-1]}"
            out.append((fname, att_id, mt))
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    return out


def extract_html(payload) -> str:
    if not payload:
        return ""
    mt = payload.get("mimeType", "")
    data = payload.get("body", {}).get("data")
    if mt.startswith("text/html") and data:
        try:
            return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
        except Exception:
            return ""
    for sub in payload.get("parts", []) or []:
        h = extract_html(sub)
        if h:
            return h
    return ""


def extract_text(payload) -> str:
    if not payload:
        return ""
    mt = payload.get("mimeType", "")
    data = payload.get("body", {}).get("data")
    if mt.startswith("text/plain") and data:
        try:
            return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
        except Exception:
            return ""
    body = ""
    for sub in payload.get("parts", []) or []:
        body += extract_text(sub) + "\n"
    if not body and mt.startswith("text/html") and data:
        try:
            html = base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
            return re.sub(r"<[^>]+>", " ", html)
        except Exception:
            return ""
    return body


def dl_attachment(msg_id: str, att_id: str, token: str) -> bytes:
    url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}/attachments/{att_id}"
    d = gmail_get(url, token, timeout=60)
    data = d.get("data", "")
    return base64.urlsafe_b64decode(data + "===") if data else b""


def collect_cid_images(payload, msg_id: str, token: str) -> dict[str, str]:
    """Return {Content-ID: data: URI} for inline images, so HTML rendering
    can embed cid: references."""
    out: dict[str, str] = {}

    def walk(part):
        if not part:
            return
        mt = (part.get("mimeType") or "").lower()
        body = part.get("body") or {}
        att_id = body.get("attachmentId")
        if mt.startswith("image/") and att_id:
            cid = None
            for h in part.get("headers", []) or []:
                if h.get("name", "").lower() == "content-id":
                    cid = h["value"].strip("<>")
                    break
            if cid:
                try:
                    raw = dl_attachment(msg_id, att_id, token)
                    if raw:
                        b64 = base64.b64encode(raw).decode()
                        out[cid] = f"data:{mt};base64,{b64}"
                except Exception:
                    pass
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    return out


# ----------------- Receipt parsing -----------------
CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP",
                    "USD": "USD", "EUR": "EUR", "GBP": "GBP",
                    "LEI": "RON", "RON": "RON"}


def parse_amount(text: str) -> tuple[float | None, str | None]:
    """Return (amount, currency) parsed from a receipt body, or (None, None)."""
    patterns = [
        # "Total" / "Amount due" / "Amount paid" lines (most reliable)
        r"(?:amount\s+due|amount\s+paid|total|charged|amount)[\s:]*?([\$€£])\s*([\d,]+\.\d{2})",
        # Bare "$100.00"
        r"([\$€£])\s*([\d,]+\.\d{2})",
        # "100.00 USD" / "100,00 EUR"
        r"([\d,]+[.,]\d{2})\s*(USD|EUR|GBP|LEI|RON)",
        # "EUR 100.00"
        r"(USD|EUR|GBP|LEI|RON)\s*([\d,]+[.,]\d{2})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            g1, g2 = m.group(1), m.group(2)
            if g1 in CURRENCY_SYMBOLS:
                cur = CURRENCY_SYMBOLS[g1]
                amt_str = g2
            elif g2 in CURRENCY_SYMBOLS:
                cur = CURRENCY_SYMBOLS[g2]
                amt_str = g1
            else:
                continue
            # European format may use ","; normalise
            if amt_str.count(",") == 1 and amt_str.count(".") == 0:
                amt_str = amt_str.replace(",", ".")
            else:
                amt_str = amt_str.replace(",", "")
            try:
                return float(amt_str), cur
            except ValueError:
                continue
    return None, None


def parse_vendor(subject: str, sender: str | None = None) -> str | None:
    s = subject or ""
    m = re.search(r"Your\s+(?:receipt|invoice)\s+from\s+(.+?)(?:\s+#|\s*$)", s, re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip(",")
    # Vendor pattern matches
    patterns = [
        (r"trip\s+with\s+Uber|\bUber\b", "Uber"),
        (r"Freenow", "Freenow"),
        (r"Trenitalia|Biglietto", "Trenitalia"),
        (r"Ryanair", "Ryanair"),
        (r"Booking|CHANTTAL", "Booking.com"),
        (r"OpenRouter", "OpenRouter"),
        (r"Gladia", "Gladia"),
        (r"Anthropic|Claude", "Anthropic"),
        (r"Vercel", "Vercel"),
        (r"\bWarp\b", "Warp"),
        (r"OpenAI", "OpenAI"),
        (r"Wispr", "Wispr Flow"),
        (r"Eleven\s*Labs", "Eleven Labs"),
        (r"MainFunc|SuperGrok|\bGrok\b|xAI", "Grok xAI"),
        (r"Italo\b", "Italo"),
        (r"Lufthansa", "Lufthansa"),
        (r"ITA\s+Airways", "ITA Airways"),
        (r"Airbnb", "Airbnb"),
        (r"AgentMail", "AgentMail"),
        (r"\bOdoo\b", "Odoo S.A."),
        (r"X\s+Developer\s+Platform", "X Developer Platform"),
    ]
    for pat, name in patterns:
        if re.search(pat, s, re.IGNORECASE):
            return name
    # Sender domain fallback
    if sender:
        m = re.search(r"@([\w.-]+)", sender)
        if m:
            return m.group(1)
    return None


def receipt_number(subject: str) -> str | None:
    """Pull #XXXX-XXXX style receipt number, used for dedupe."""
    m = re.search(r"#\s*([0-9]{2,5}(?:-[0-9]{2,5})+)", subject or "")
    return m.group(1) if m else None


def parse_email_date(headers) -> str | None:
    for h in headers:
        if h["name"].lower() == "date":
            try:
                dt = datetime.strptime(h["value"][:25].strip(), "%a, %d %b %Y %H:%M:%S")
                return dt.strftime("%Y-%m-%d")
            except Exception:
                pass
    return None


# ----------------- HTML/image → PDF -----------------
def html_to_pdf(html_str: str, cid_map: dict[str, str] | None = None) -> bytes:
    """Render an email HTML body to a PDF byte string. Inlines cid: refs."""
    from weasyprint import HTML, CSS  # imported lazily — slow

    for cid, uri in (cid_map or {}).items():
        html_str = html_str.replace(f"cid:{cid}", uri)

    def _no_fetch(url):
        return {"string": b"", "mime_type": "application/octet-stream"}

    css = CSS(string="@page { size: A4; margin: 1.5cm; } body { font-family: sans-serif; font-size: 11px; }")
    out = io.BytesIO()
    HTML(string=html_str, url_fetcher=_no_fetch).write_pdf(out, stylesheets=[css])
    return out.getvalue()


def image_to_pdf(img_bytes: bytes) -> bytes:
    """Convert a raster image to a single-page PDF byte string."""
    from PIL import Image as PILImage

    img = PILImage.open(io.BytesIO(img_bytes))
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    out = io.BytesIO()
    img.save(out, "PDF", resolution=150.0)
    return out.getvalue()


# ----------------- Odoo helpers -----------------
def get_live_usd_rates() -> tuple[dict[str, float], str]:
    """Return ({currency_code: USD_multiplier}, rate_date_str).
    Reads res.currency.rate for company_id=1 (Futuroid, EUR-based)."""
    db, uid, k, models = odoo_session()
    rows = models.execute_kw(
        db, uid, k, "res.currency.rate", "search_read",
        [[("company_id", "=", FUTUROID_COMPANY_ID)]],
        {"fields": ["name", "rate", "currency_id"], "order": "name desc, id desc"},
    )
    per_cur: dict[str, dict] = {}
    for r in rows:
        cur = r["currency_id"][1] if r["currency_id"] else None
        if cur and cur not in per_cur:
            per_cur[cur] = r
    if "USD" not in per_cur:
        raise RuntimeError("No USD rate — run currency sync in Odoo first.")
    eur_to_usd = per_cur["USD"]["rate"]
    rate_date = per_cur["USD"]["name"]
    to_usd: dict[str, float] = {"USD": 1.0, "EUR": eur_to_usd}
    for c, r in per_cur.items():
        to_usd[c] = eur_to_usd / r["rate"] if r["rate"] else 0
    return to_usd, rate_date


def get_currency_id_map(codes: Iterable[str]) -> dict[str, int]:
    db, uid, k, models = odoo_session()
    rows = models.execute_kw(
        db, uid, k, "res.currency", "search_read",
        [[("name", "in", list(codes))]],
        {"fields": ["id", "name"]},
    )
    return {r["name"]: r["id"] for r in rows}


def get_existing_receipt_numbers() -> set[str]:
    """Pull #NNNN-NNNN receipt numbers from every existing hr.expense
    (David at Futuroid). Used to dedupe before pushing new rows."""
    db, uid, k, models = odoo_session()
    rows = models.execute_kw(
        db, uid, k, "hr.expense", "search_read",
        [[("employee_id", "=", DAVID_EMPLOYEE_ID)]],
        {"fields": ["name", "description"]},
    )
    nums: set[str] = set()
    for r in rows:
        for field in ("name", "description"):
            for n in re.findall(r"#\s*([0-9]{2,5}(?:-[0-9]{2,5})+)", r.get(field) or ""):
                nums.add(n)
    return nums


def get_max_expense_id() -> int:
    """Highest existing hr.expense id for David. Used to cohort future runs
    via `id > N` instead of brittle date filters."""
    db, uid, k, models = odoo_session()
    rows = models.execute_kw(
        db, uid, k, "hr.expense", "search_read",
        [[("employee_id", "=", DAVID_EMPLOYEE_ID)]],
        {"fields": ["id"], "order": "id desc", "limit": 1},
    )
    return rows[0]["id"] if rows else 0


def safe_exit(code: int = 0):
    """Bypass CPython finalisers — WeasyPrint's Pango/HarfBuzz unload
    segfaults during _Py_Finalize on macOS. Output is already on disk."""
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
