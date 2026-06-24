#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dex EDA Data Scraper — UCC-1 Machine Tool Filing Intelligence

Downloads saved queries from online.edadata.com in bulk, caches locally,
and lets you filter/search without hitting the site again.

Usage:
    python3 eda-scraper.py --download                                    # Download all saved queries
    python3 eda-scraper.py --download --query "CB Accounts - Press Brakes"  # One specific query
    python3 eda-scraper.py --search "Keystone Fab"                       # Search cached data
    python3 eda-scraper.py --search "Keystone" --field buycomp1          # Search specific field
    python3 eda-scraper.py --sync                                         # Sync EDA cache → Salesforce Assets
    python3 eda-scraper.py --sync --account "Keystone Fab"               # Sync one account only
    python3 eda-scraper.py --list-queries                                 # List available queries
    python3 eda-scraper.py --cache-info                                   # Show cache stats
    python3 eda-scraper.py --no-login-cache                               # Force fresh login
    python3 eda-scraper.py --headed                                       # Show browser window

Credentials: stored in .env at vault root
    EDA_USERNAME=your@email.com
    EDA_PASSWORD=yourpassword

Our brands config: .scripts/customer-intel/our-brands.json
    List of manufacturer names we sell — everything else is flagged as competitor.
"""

import csv
import json
import os
import re
import sys
import argparse
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

# Force UTF-8 output on Windows so em-dashes and arrows render correctly
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Config ────────────────────────────────────────────────────────────────────

VAULT_PATH    = os.environ.get("VAULT_PATH", str(Path(__file__).parent.parent.parent))
BASE_URL      = "https://online.edadata.com"
FUSABLE_HOST  = "appident.fusable.com"
LOGIN_SESSION = Path.home() / ".claude" / "eda_session.json"
DATA_CACHE    = Path.home() / ".claude" / "eda_data_cache.json"


def load_env():
    env_path = Path(VAULT_PATH) / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

load_env()

EDA_USERNAME = os.environ.get("EDA_USERNAME", "")
EDA_PASSWORD = os.environ.get("EDA_PASSWORD", "")


# ── HTTP Session ───────────────────────────────────────────────────────────────

def make_session():
    try:
        import requests
    except ImportError:
        print("ERROR: requests not installed. Run: pip install requests")
        sys.exit(1)
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    })
    return s


def save_login_session(cookies):
    LOGIN_SESSION.parent.mkdir(parents=True, exist_ok=True)
    with open(LOGIN_SESSION, "w") as f:
        json.dump({"cookies": cookies, "saved_at": datetime.now().isoformat()}, f)


def load_login_session(session):
    if not LOGIN_SESSION.exists():
        return False
    try:
        data = json.loads(LOGIN_SESSION.read_text())
        saved = datetime.fromisoformat(data["saved_at"])
        if (datetime.now() - saved).total_seconds() > 28800:  # 8 hours
            return False
        for name, value in data["cookies"].items():
            session.cookies.set(name, value)
        return True
    except Exception:
        return False


# ── Login (Playwright / Fusable OIDC) ─────────────────────────────────────────

def login(session, headed=False):
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright && python -m playwright install chromium")
        sys.exit(1)

    if not EDA_USERNAME or not EDA_PASSWORD:
        print(f"ERROR: EDA_USERNAME and EDA_PASSWORD not set in {Path(VAULT_PATH) / '.env'}")
        sys.exit(1)

    print("Logging in to EDA Data...", file=sys.stderr)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        try:
            page.goto(f"{BASE_URL}/", timeout=30000)
            page.wait_for_url(f"**/{FUSABLE_HOST}/**", timeout=20000)

            page.wait_for_selector('input[name="Username"]', timeout=10000)
            page.fill('input[name="Username"]', EDA_USERNAME)
            _click_submit(page)

            try:
                page.wait_for_selector('input[name="Password"]', timeout=8000)
            except PWTimeout:
                if BASE_URL in page.url:
                    return _extract_cookies(context, session, browser)
                print("ERROR: Password field did not appear.", file=sys.stderr)
                browser.close()
                return False

            page.fill('input[name="Password"]', EDA_PASSWORD)
            _click_submit(page)

            try:
                page.wait_for_url("**/online.edadata.com/**", timeout=20000)
            except PWTimeout:
                print("ERROR: Login failed. Check credentials.", file=sys.stderr)
                browser.close()
                return False

            return _extract_cookies(context, session, browser)

        except Exception as e:
            print(f"ERROR during login: {e}", file=sys.stderr)
            browser.close()
            return False


def _click_submit(page):
    for sel in ['button[type="submit"]', 'input[type="submit"]',
                'button:has-text("Continue")', 'button:has-text("Login")', 'button:has-text("Sign in")']:
        btn = page.query_selector(sel)
        if btn:
            btn.click()
            return
    page.keyboard.press("Enter")


def _extract_cookies(context, session, browser):
    cookies = context.cookies()
    browser.close()
    cookie_dict = {}
    for c in cookies:
        domain = c.get("domain", "")
        if "edadata.com" in domain or "fusable.com" in domain:
            session.cookies.set(c["name"], c["value"])
            cookie_dict[c["name"]] = c["value"]
    if not cookie_dict:
        print("WARNING: No session cookies captured.", file=sys.stderr)
        return False
    save_login_session(cookie_dict)
    print("  Login successful.", file=sys.stderr)
    return True


# ── Playwright context with injected cookies ───────────────────────────────────

def _pw_context_with_cookies(playwright, session, headed=False):
    browser = playwright.chromium.launch(headless=not headed)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    )
    pw_cookies = []
    for cookie in session.cookies:
        domain = (cookie.domain or "").lstrip(".")
        if domain:
            pw_cookies.append({"name": cookie.name, "value": cookie.value,
                               "domain": domain, "path": cookie.path or "/"})
        else:
            pw_cookies.append({"name": cookie.name, "value": cookie.value, "url": BASE_URL})
    if pw_cookies:
        context.add_cookies(pw_cookies)
    return browser, context


# ── Saved queries ──────────────────────────────────────────────────────────────

KNOWN_SAVED_QUERIES = [
    "All Data - 10 YR CB", "All Data - 10YR", "All Data - 2025 PA",
    "CB Account - NY", "CB Account Match - CNC Router",
    "CB Accounts - Benders", "CB Accounts - Coil Straightners",
    "CB Accounts - Folder", "CB Accounts - High Probability Buy",
    "CB Accounts - Ironworker", "CB Accounts - Laser",
    "CB Accounts - Med Probability Buy", "CB Accounts - Plasma",
    "CB Accounts - Plasma1", "CB Accounts - Press Brakes",
    "CB Accounts - Punch", "CB Accounts - Roll", "CB Accounts - Saw",
    "CB Accounts - Shear", "CB Accounts - Stamping Press",
    "CB Accounts - VMC/UMC", "CB Accounts - Waterjet",
    "CB Accounts Matched", "CB-PK Accounts - Waterjet",
    "Comp Waterjet Accounts", "Florida-JZ", "LVD Strippit Punch",
    "NY - 1 YR - EQUIPMENT BREAKDOWN", "NY - 1YR - Trumpf",
    "TRUMPF Press Brakes", "Vaski Metal (Rotand) - NA Installations",
    "WA, OR, CA - Copper",
]


# ── Download ───────────────────────────────────────────────────────────────────

def _screenshot(page, label):
    """Save a debug screenshot to ~/.claude/eda_debug_<label>.png."""
    try:
        safe = re.sub(r"[^\w]", "_", label)[:40]
        path = Path.home() / ".claude" / f"eda_debug_{safe}.png"
        page.screenshot(path=str(path))
        print(f"  [screenshot] {path}", file=sys.stderr)
    except Exception:
        pass


def _download_one(page, query_name, debug=False):
    """Run one saved query export using an already-open, authenticated Playwright page."""
    from playwright.sync_api import TimeoutError as PWTimeout

    print(f"  {query_name}...", file=sys.stderr)

    page.goto(f"{BASE_URL}/Query", timeout=30000)

    if FUSABLE_HOST in page.url:
        raise RuntimeError("Session expired — re-run with --no-login-cache")

    page.wait_for_load_state("domcontentloaded", timeout=15000)
    time.sleep(1)

    # ── Step 1: Click the saved query link by its text ────────────────────────
    found = False
    # Try <a> tags first, then buttons/inputs with matching text
    for el in page.query_selector_all("a, button, input[type='button'], input[type='submit']"):
        text = (el.inner_text() if el.evaluate("e => e.tagName !== 'INPUT'") else
                el.get_attribute("value") or "")
        if query_name.lower() in (text or "").lower():
            el.click()
            found = True
            break

    if not found:
        if debug:
            # Log all visible link/button text to help diagnose selector mismatches
            links = [(el.inner_text() or "").strip() for el in page.query_selector_all("a")]
            print(f"  [debug] Links on /Query: {[l for l in links if l][:20]}", file=sys.stderr)
            _screenshot(page, f"no_link_{re.sub(r'[^\\w]','_',query_name)[:20]}")
        print(f"  WARNING: '{query_name}' not found on /Query page.", file=sys.stderr)
        return []

    # ── Step 2: Wait for results page ────────────────────────────────────────
    try:
        page.wait_for_load_state("domcontentloaded", timeout=20000)
    except PWTimeout:
        pass
    time.sleep(1.5)

    if debug:
        _screenshot(page, f"results_{re.sub(r'[^\\w]','_',query_name)[:20]}")

    # ── Step 3: Gear icon → opens action/export panel ─────────────────────────
    clicked_gear = page.evaluate("""() => {
        const byId = document.getElementById('gear-button');
        if (byId) { byId.click(); return 'id:gear-button'; }
        const byCls = document.querySelector('[class*="gear"],[id*="gear"]');
        if (byCls) { byCls.click(); return byCls.id || byCls.className; }
        return null;
    }""")
    if debug:
        print(f"  [debug] gear click: {clicked_gear}", file=sys.stderr)
    time.sleep(1)

    # ── Step 4: Export accordion / section ────────────────────────────────────
    clicked_export = page.evaluate("""() => {
        const byId = document.getElementById('export-accordion-section');
        if (byId) { byId.click(); return 'id:export-accordion-section'; }
        // Any visible link/button whose text is exactly "Export"
        for (const el of document.querySelectorAll('a,button')) {
            if ((el.innerText || '').trim().toLowerCase() === 'export' && el.offsetParent) {
                el.click(); return el.outerHTML.slice(0,80);
            }
        }
        // Broader: anything containing "export"
        for (const el of document.querySelectorAll('a,button,span,div')) {
            if ((el.innerText || '').trim().toLowerCase().includes('export') && el.offsetParent) {
                el.click(); return el.outerHTML.slice(0,80);
            }
        }
        return null;
    }""")
    if debug:
        print(f"  [debug] export click: {clicked_export}", file=sys.stderr)
    time.sleep(0.8)

    # ── Step 5: Go / download button → triggers file download ─────────────────
    rows = []
    try:
        with page.expect_download(timeout=30000) as dl_info:
            clicked_go = page.evaluate("""() => {
                const byId = document.getElementById('export-button');
                if (byId) { byId.click(); return 'id:export-button'; }
                for (const b of document.querySelectorAll('button,input[type="submit"],input[type="button"],a')) {
                    const t = (b.innerText || b.value || '').toLowerCase();
                    if ((t.includes('go') || t.includes('download') || t.includes('export')) && b.offsetParent) {
                        b.click(); return b.outerHTML.slice(0,80);
                    }
                }
                return null;
            }""")
            if debug:
                print(f"  [debug] go/download click: {clicked_go}", file=sys.stderr)

        download = dl_info.value
        fname = download.suggested_filename or "eda_export"
        suffix = Path(fname).suffix or ".xlsx"
        tmp = Path.home() / ".claude" / f"eda_export_{int(time.time())}{suffix}"
        download.save_as(str(tmp))
        print(f"  Downloaded: {fname} ({suffix})", file=sys.stderr)
        rows = _parse_excel_or_csv(tmp)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass

    except Exception as e:
        print(f"  ERROR downloading '{query_name}': {e}", file=sys.stderr)
        if debug:
            _screenshot(page, f"error_{re.sub(r'[^\\w]','_',query_name)[:20]}")

    return rows


def _parse_excel_or_csv(path):
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                return []
            headers = [str(h).lower().strip() if h else f"col{i}" for i, h in enumerate(rows[0])]
            return [dict(zip(headers, [str(c) if c is not None else "" for c in row]))
                    for row in rows[1:] if any(c is not None for c in row)]
        except ImportError:
            print("ERROR: openpyxl not installed — run: pip install openpyxl", file=sys.stderr)
            return []
    else:
        try:
            with open(path, newline="", encoding="utf-8-sig") as f:
                return list(csv.DictReader(f))
        except Exception as e:
            print(f"ERROR parsing CSV: {e}", file=sys.stderr)
            return []


# ── Local cache ────────────────────────────────────────────────────────────────

def load_cache():
    if not DATA_CACHE.exists():
        return {}
    try:
        return json.loads(DATA_CACHE.read_text())
    except Exception:
        return {}


def save_cache(cache):
    DATA_CACHE.parent.mkdir(parents=True, exist_ok=True)
    DATA_CACHE.write_text(json.dumps(cache, indent=2))


def all_records(cache):
    seen = set()
    records = []
    for query_data in cache.get("queries", {}).values():
        for row in query_data.get("rows", []):
            key = json.dumps(row, sort_keys=True)
            if key not in seen:
                seen.add(key)
                records.append(row)
    return records


# ── Salesforce Sync Helpers ────────────────────────────────────────────────────

SF_TOKEN_FILE = Path.home() / ".claude" / "sf_tokens.json"
OUR_BRANDS_FILE = Path(__file__).parent / "our-brands.json"

# Map EDA eqtdesc keywords → SF Machine_Type_New__c picklist values
_MACHINE_TYPE_MAP = [
    ("press brake",            "Press Brake"),
    ("pressbrake",             "Press Brake"),
    ("laser punch",            "Laser Punch Press"),
    ("tube laser",             "Laser (Tube)"),
    ("pipe laser",             "Laser (Tube)"),
    ("laser",                  "Laser"),
    ("shear",                  "Shear"),
    ("punch press",            "Punch"),
    ("turret punch",           "Punch"),
    ("punch",                  "Punch"),
    ("waterjet",               "Waterjet"),
    ("plasma",                 "Plasma (CNC)"),
    ("ironworker",             "Ironworker"),
    ("angle line",             "Angle Line"),
    ("bandsaw",                "Bandsaw"),
    ("band saw",               "Bandsaw"),
    ("cold saw",               "Cold Saw"),
    ("saw",                    "Saw (NEC)"),
    ("panel bender",           "Panel Bender"),
    ("folder",                 "Folder (CNC)"),
    ("roll",                   "Rolls (Plate)"),
    ("leveler",                "Leveler"),
    ("deburr",                 "Deburring Machine"),
    ("notcher",                "Notcher"),
    ("tube bender",            "Tube/Pipe Bender"),
    ("pipe bender",            "Tube/Pipe Bender"),
    ("robot",                  "Robot (Tending)"),
    ("welder",                 "Welder (Manual)"),
    ("machining center",       "Vertical Machining Center (3-4 Axis)"),
    ("vertical machining",     "Vertical Machining Center (3-4 Axis)"),
    ("lathe",                  "Lathe (CNC)"),
    ("stamping",               "Stamping Press"),
    ("nitrogen",               "Nitrogen Generator"),
    ("shot blast",             "Shot Blast Equipment"),
    ("storage",                "Storage System"),
    ("software",               "Software"),
    ("coil feed",              "Coil Feeding"),
    ("cut to length",          "Cut To Length"),
]

# Map EDA eqtman keywords → SF Builder__c picklist values
_BUILDER_MAP = {
    "amada":        "Amada/Marvel",
    "trumpf":       "TRUMPF",
    "mitsubishi":   "Mitsubishi",
    "piranha":      "Piranha",
    "scotchman":    "Scotchman",
    "hyd-mech":     "Hyd-Mech",
    "hydmech":      "Hyd-Mech",
    "flow":         "Flow",
    "aida":         "AIDA",
    "arku":         "Arku",
    "cidan":        "Cidan",
    "ehrt":         "EHRT",
    "faccin":       "Faccin",
    "geka":         "Geka",
    "haco":         "Haco",
    "haeger":       "Haeger",
    "he&m":         "HE&M Saw",
    "baileigh":     "Baileigh",
    "wila":         "WILA",
    "tigerstop":    "TigerStop",
    "virtek":       "Virtek",
    "vectis":       "Vectis",
    "mid atlantic": "Mid Atlantic Machinery Automation",
    "midwest auto": "Midwest Automation",
    "miller":       "Miller Welding",
    "royson":       "Royson",
    "standard ind": "Standard Industrial",
    "accurex":      "Accurex",
    "ercolina":     "Ercolina",
    "transfluid":   "Transfluid",
    "prodevco":     "Prodevco",
    "p/a industr":  "P/A Industries",
    "pat mooney":   "Pat Mooney",
}

# Sale/lease → SF Sale_or_Lease__c values (check real picklist)
_SALE_LEASE_MAP = {
    "SALE":       "Sale",
    "LEASE":      "Lease",
    "RENTAL":     "Lease",
    "REFINANCE":  "Lease",
    "WHOLESALE":  "Sale",
    "TERMINATION": None,
}


def load_sf_tokens():
    if not SF_TOKEN_FILE.exists():
        return None
    try:
        return json.loads(SF_TOKEN_FILE.read_text())
    except Exception:
        return None


def sf_request(tokens, path, data=None, method=None):
    url = tokens["instance_url"] + "/services/data/v59.0" + path
    req = Request(url,
                  data=json.dumps(data).encode() if data else None,
                  headers={"Authorization": f"Bearer {tokens['access_token']}",
                           "Content-Type": "application/json"},
                  method=method or ("POST" if data else "GET"))
    try:
        with urlopen(req) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"SF API {e.code}: {body[:500]}") from e


def sf_query_all(tokens, soql):
    """Paginate through all SOQL records."""
    path = "/query?" + urlencode({"q": soql})
    records = []
    while path:
        result = sf_request(tokens, path)
        records.extend(result.get("records", []))
        next_url = result.get("nextRecordsUrl")
        if next_url:
            # nextRecordsUrl is like /services/data/v59.0/query/...
            path = next_url.replace("/services/data/v59.0", "")
        else:
            path = None
    return records


def load_our_brands():
    """Load list of brand names we sell. Falls back to empty list (all = competitor)."""
    if OUR_BRANDS_FILE.exists():
        try:
            return [b.upper() for b in json.loads(OUR_BRANDS_FILE.read_text())]
        except Exception:
            pass
    return []


def is_competitor(eqtman, our_brands):
    if not our_brands:
        return False
    man_upper = (eqtman or "").upper()
    return not any(brand in man_upper for brand in our_brands)


def map_machine_type(eqtdesc):
    desc_lower = (eqtdesc or "").lower()
    for keyword, sf_val in _MACHINE_TYPE_MAP:
        if keyword in desc_lower:
            return sf_val
    return None


def map_builder(eqtman):
    man_lower = (eqtman or "").lower()
    for keyword, sf_val in _BUILDER_MAP.items():
        if keyword in man_lower:
            return sf_val
    return None


def normalize_name(name):
    name = (name or "").lower().strip()
    for suffix in [" inc.", " inc", " llc.", " llc", " corp.", " corp",
                   " co.", " company", " ltd.", " ltd", " & co"]:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
    name = re.sub(r"[^\w\s]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def build_sf_account_index(tokens):
    """Return dict of normalized_name → {Id, Name}."""
    print("  Loading Salesforce accounts...", end=" ", flush=True)
    records = sf_query_all(tokens, "SELECT Id, Name FROM Account WHERE IsDeleted = false LIMIT 100000")
    index = {}
    for r in records:
        key = normalize_name(r["Name"])
        index[key] = {"Id": r["Id"], "Name": r["Name"]}
    print(f"{len(index)} accounts.")
    return index


def find_sf_account(index, company_name):
    key = normalize_name(company_name)
    if key in index:
        return index[key]
    # Try prefix match on first 2+ words
    words = key.split()
    if len(words) >= 2:
        prefix = " ".join(words[:2])
        for k, v in index.items():
            if k.startswith(prefix):
                return v
    return None


def get_existing_ucc_ids(tokens, account_id):
    """Return set of UCCID__c values already in SF for this account."""
    try:
        records = sf_query_all(
            tokens,
            f"SELECT UCCID__c FROM Asset WHERE AccountId = '{account_id}' AND UCCID__c != null"
        )
        return {r["UCCID__c"] for r in records}
    except Exception:
        return set()


def build_asset_payload(eda_rec, account_id, our_brands):
    """Map one EDA record to a Salesforce Asset create payload."""
    uccid = str(eda_rec.get("uccid") or "").strip()
    uccstatus = (eda_rec.get("uccstatus") or "").upper().strip()
    uccdate_raw = (eda_rec.get("uccdate") or "")[:10]
    eqtman = (eda_rec.get("eqtman") or "").strip()
    eqtmodel = (eda_rec.get("eqtmodel") or "").strip()
    eqtdesc = (eda_rec.get("eqtdesc") or "").strip()

    # Asset name
    parts = [p for p in [eqtman, eqtmodel] if p]
    name = " - ".join(parts) if parts else (eqtdesc or "EDA Record")
    name = name[:255]

    # Sale or Lease
    sale_or_lease = _SALE_LEASE_MAP.get(uccstatus)

    # Estimated lease end: UCC filings lapse after 5 years
    usage_end = None
    if uccdate_raw and ("LEASE" in uccstatus or "RENTAL" in uccstatus or "REFINANCE" in uccstatus):
        try:
            filing = datetime.strptime(uccdate_raw, "%Y-%m-%d").date()
            usage_end = (filing + timedelta(days=5 * 365)).isoformat()
        except Exception:
            pass

    # Builder picklist vs Other
    sf_builder = map_builder(eqtman)
    builder_other = eqtman if (eqtman and not sf_builder) else None

    # Machine type picklist
    sf_machine_type = map_machine_type(eqtdesc)

    # New or Used
    eqtnu = (eda_rec.get("eqtnu") or "").strip().upper()
    new_or_used = "New" if eqtnu == "N" else ("Used" if eqtnu == "U" else None)

    payload = {
        "Name": name,
        "AccountId": account_id,
        "UCCID__c": uccid,
        "UCC_BuyID__c": (eda_rec.get("buyid") or "").strip() or None,
        "UCC_Status__c": uccstatus or None,
        "UCC_Vendor__c": (eda_rec.get("spcomp") or "").strip() or None,
        "UCC_S_N__c": (eda_rec.get("eqtsn") or "").strip() or None,
        "UCC_EQT_Code__c": (eda_rec.get("eqtcode") or "").strip() or None,
        "UCC_New_or_Used__c": new_or_used,
        "ModelName__c": eqtmodel or None,
        "Sale_or_Lease__c": sale_or_lease,
        "InstallDate": uccdate_raw or None,
        "UsageEndDate": usage_end,
        "IsCompetitorProduct": is_competitor(eqtman, our_brands),
        "Status": "Installed",
    }

    if sf_builder:
        payload["Builder__c"] = sf_builder
    if builder_other:
        payload["Builder_Other__c"] = builder_other
    if sf_machine_type:
        payload["Machine_Type_New__c"] = sf_machine_type

    # Strip None values — SF rejects null writes for some fields
    return {k: v for k, v in payload.items() if v is not None}


# ── Commands ───────────────────────────────────────────────────────────────────

def cmd_download(session, query_filter=None, headed=False, debug=False):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright && python -m playwright install chromium")
        sys.exit(1)

    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("ERROR: openpyxl not installed (needed to parse Excel exports). Run: pip install openpyxl")
        sys.exit(1)

    queries = KNOWN_SAVED_QUERIES
    if query_filter:
        queries = [q for q in queries if query_filter.lower() in q.lower()]
        if not queries:
            print(f"No saved queries match '{query_filter}'. Run --list-queries to see options.")
            return

    print(f"Downloading {len(queries)} saved quer{'y' if len(queries)==1 else 'ies'}...", file=sys.stderr)
    if debug:
        print(f"  [debug] Screenshots saved to {Path.home() / '.claude'}/eda_debug_*.png", file=sys.stderr)

    cache = load_cache()
    cache.setdefault("queries", {})
    cache.setdefault("downloaded_at", {})

    total = 0
    # One browser session for all queries — avoids per-query browser launch overhead
    with sync_playwright() as p:
        browser, context = _pw_context_with_cookies(p, session, headed)
        page = context.new_page()

        # Verify session is valid before starting the loop
        page.goto(f"{BASE_URL}/Query", timeout=30000)
        if FUSABLE_HOST in page.url:
            print("Session expired — re-run with --no-login-cache", file=sys.stderr)
            browser.close()
            return

        if debug:
            _screenshot(page, "query_page_initial")

        for q in queries:
            try:
                rows = _download_one(page, q, debug=debug)
            except Exception as e:
                print(f"  ERROR on '{q}': {e}", file=sys.stderr)
                rows = []

            if rows:
                cache["queries"][q] = {"rows": rows, "count": len(rows)}
                cache["downloaded_at"][q] = datetime.now().isoformat()
                total += len(rows)
                print(f"  {q}: {len(rows)} records")
            else:
                print(f"  {q}: 0 records (skipped or empty)")

            time.sleep(1)  # brief pause between queries

        browser.close()

    save_cache(cache)
    unique = len(all_records(cache))
    print(f"\nCache updated: {total} rows downloaded, {unique} unique records total.")
    print(f"Cache: {DATA_CACHE}")


def cmd_search(query, field=None):
    cache = load_cache()
    if not cache:
        print("No local cache found. Run --download first.")
        return

    records = all_records(cache)
    query_lower = query.lower()

    if field:
        matches = [r for r in records if query_lower in str(r.get(field, "")).lower()]
    else:
        matches = [r for r in records if any(query_lower in str(v).lower() for v in r.values())]

    if not matches:
        print(f"No results for '{query}' in {len(records)} cached records.")
        return

    print(f"Found {len(matches)} result(s) for '{query}':\n")
    print(json.dumps(matches, indent=2))


def cmd_cache_info():
    cache = load_cache()
    if not cache:
        print("No cache found. Run --download first.")
        return

    queries = cache.get("queries", {})
    downloaded_at = cache.get("downloaded_at", {})
    total = sum(v.get("count", 0) for v in queries.values())
    unique = len(all_records(cache))

    print(f"Cache: {DATA_CACHE}")
    print(f"Unique records: {unique}  |  Total rows: {total}\n")
    print(f"{'Query':<45} {'Records':>8}  {'Downloaded'}")
    print("-" * 75)
    for q, data in sorted(queries.items()):
        ts = downloaded_at.get(q, "unknown")[:16].replace("T", " ")
        print(f"{q:<45} {data.get('count',0):>8}  {ts}")


def _vault_path():
    """Resolve vault root: VAULT_PATH env, or 2 levels up from this script."""
    vp = os.environ.get("VAULT_PATH", "")
    if vp:
        return Path(vp)
    return Path(__file__).resolve().parent.parent.parent


def _company_page_path(company_name):
    safe = re.sub(r'[<>:"/\\|?*]', '', company_name).strip().replace(" ", "_")
    return _vault_path() / "People" / "Companies" / f"{safe}.md"


def _build_markdown(company_name, buyer, assets_sorted, our_eq, comp_eq, terms,
                    leases, avg_interval_months, season_str, URGENCY_ICON,
                    our_brands, today):
    """Return a markdown string for the company page."""
    lines = []
    addr_parts = [buyer.get("buyadr1",""), buyer.get("buycity",""),
                  buyer.get("buystate",""), buyer.get("buyzip","")]
    addr = ", ".join(p for p in addr_parts if p)
    phone = buyer.get("buyphone","")
    sic = buyer.get("buysicdesc","")

    contacts = []
    for n in ["buyc1first buyc1last buyc1title", "buyc2first buyc2last buyc2title"]:
        fn, ln, tt = [buyer.get(k,"").strip() for k in n.split()]
        if fn or ln:
            contacts.append(f"{fn} {ln}".strip() + (f" ({tt})" if tt else ""))

    lines.append(f"---")
    lines.append(f"name: {company_name}")
    lines.append(f"type: customer")
    lines.append(f"eda_sync: {today.isoformat()}")
    lines.append(f"---")
    lines.append("")
    lines.append(f"# {company_name}")
    lines.append("")

    # Basic info
    lines.append("## Overview")
    lines.append("")
    if addr:
        lines.append(f"- **Address:** {addr}")
    if phone and phone != "0000000000":
        lines.append(f"- **Phone:** {phone}")
    if sic:
        lines.append(f"- **Industry:** {sic}")
    for c in contacts:
        lines.append(f"- **Contact:** {c}")
    lines.append("")

    # EDA Intelligence section (matches what /customer-intel skill expects)
    lines.append("## EDA Intelligence")
    lines.append(f"*Last updated: {today.isoformat()} | Source: EDA/UCC-1 local cache*")
    lines.append("")

    filing_dates = [a["filing_date"] for a in assets_sorted if a["filing_date"]]
    crit = [a for a in leases if a["urgency"] in ("CRITICAL", "HIGH")]

    # Fleet summary
    lines.append("**Fleet Summary**")
    lines.append("")
    active_count = len(our_eq) + len(comp_eq)
    summary_rows = [
        f"| Total EDA records | {len(assets_sorted)} |",
        f"| Active equipment | {active_count} |",
    ]
    if our_brands:
        summary_rows += [
            f"| Our equipment | {len(our_eq)} |",
            f"| Competitor equipment | {len(comp_eq)} |",
        ]
    summary_rows.append(f"| Leases tracked | {len(leases)} |")
    if crit:
        summary_rows.append(f"| **Leases expiring <6 months** | **{len(crit)} — PRIORITY** |")
    if avg_interval_months:
        summary_rows.append(f"| Avg buy interval | ~{avg_interval_months} months |")
    if filing_dates:
        summary_rows.append(f"| First filing | {filing_dates[0]} |")
        summary_rows.append(f"| Most recent filing | {filing_dates[-1]} |")
    summary_rows.append(f"| Buying season | {season_str} |")

    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.extend(summary_rows)
    lines.append("")

    # Our equipment table
    if our_eq and our_brands:
        lines.append("### Our Equipment on Floor")
        lines.append("")
        lines.append("| Machine Type | Model | Builder | Filed | S/L |")
        lines.append("|-------------|-------|---------|-------|-----|")
        for a in our_eq:
            sl = "Lease" if a["is_lease"] else "Sale"
            lines.append(f"| {a['eqtdesc'] or '—'} | {a['eqtmodel'] or '—'} | {a['eqtman'] or '—'} | {a['filing_date'] or '—'} | {sl} |")
        lines.append("")

    # Competitor equipment table
    if comp_eq and our_brands:
        lines.append("### Competitor Equipment on Floor")
        lines.append("")
        lines.append("| Machine Type | Model | Competitor | Filed | S/L |")
        lines.append("|-------------|-------|-----------|-------|-----|")
        for a in comp_eq:
            sl = "Lease" if a["is_lease"] else "Sale"
            lines.append(f"| {a['eqtdesc'] or '—'} | {a['eqtmodel'] or '—'} | {a['eqtman'] or '—'} | {a['filing_date'] or '—'} | {sl} |")
        lines.append("")

    # All equipment (no our-brands config)
    if not our_brands:
        lines.append("### Equipment on Floor")
        lines.append("")
        lines.append("| Machine Type | Model | Manufacturer | Filed | S/L |")
        lines.append("|-------------|-------|-------------|-------|-----|")
        for a in our_eq + comp_eq:
            sl = "Lease" if a["is_lease"] else "Sale"
            lines.append(f"| {a['eqtdesc'] or '—'} | {a['eqtmodel'] or '—'} | {a['eqtman'] or '—'} | {a['filing_date'] or '—'} | {sl} |")
        lines.append("")

    # Lease expiration tracker
    if leases:
        lines.append("### Lease Expiration Tracker")
        lines.append("")
        lines.append("| Status | Machine | Manufacturer | Filed | Est. End |")
        lines.append("|--------|---------|-------------|-------|----------|")
        for a in sorted(leases, key=lambda x: x["est_end"] or date(2099,1,1)):
            icon = URGENCY_ICON.get(a["urgency"] or "", "")
            urg = f"{icon} {a['urgency']}" if a["urgency"] else "—"
            lines.append(f"| {urg} | {a['eqtdesc'] or '—'} | {a['eqtman'] or '—'} | {a['filing_date'] or '—'} | {a['est_end'] or '—'} |")
        lines.append("")

    # Strategic notes
    lines.append("### Strategic Notes")
    lines.append("")
    if crit:
        lines.append(f"- **PRIORITY:** {len(crit)} lease(s) expiring within 6 months — contact now.")
    if comp_eq and our_brands:
        comp_brands = sorted({a["eqtman"] for a in comp_eq if a["eqtman"]})
        old_comp = [a for a in comp_eq if a["filing_date"] and (today - a["filing_date"]).days > 365*7]
        lines.append(f"- Competitor brands on floor: {', '.join(comp_brands)}")
        if old_comp:
            lines.append(f"- {len(old_comp)} competitor machine(s) 7+ years old — displacement opportunity.")
    if avg_interval_months and filing_dates:
        next_pred = filing_dates[-1] + timedelta(days=avg_interval_months * 30)
        if next_pred >= today:
            lines.append(f"- Next predicted buy window: ~{next_pred} (based on {avg_interval_months}-month avg interval)")
        else:
            overdue = (today - next_pred).days // 30
            lines.append(f"- Pattern suggests purchase was due ~{overdue} months ago — may be actively shopping.")
    if not crit and not comp_eq:
        lines.append("- No immediate outreach triggers from EDA data.")
    lines.append("")

    lines.append("---")
    lines.append("*Profile auto-generated by `eda-scraper.py --profile --save`. Run again to refresh.*")

    return "\n".join(lines) + "\n"


def cmd_profile(company_query, our_brands, save=False):
    """Generate a customer intelligence profile from the local EDA cache."""
    cache = load_cache()
    if not cache:
        print("No local cache found. Run --download first.")
        return

    records = all_records(cache)
    query_lower = company_query.lower()
    matches = [r for r in records if query_lower in (r.get("buycomp1") or "").lower()]

    if not matches:
        print(f"No EDA records found for '{company_query}'.")
        # Suggest close matches
        names = sorted({r.get("buycomp1","") for r in records if r.get("buycomp1")})
        close = [n for n in names if any(w in n.lower() for w in query_lower.split())][:5]
        if close:
            print("Did you mean:")
            for n in close:
                print(f"  {n}")
        return

    # Deduplicate on uccid
    seen_ids = set()
    unique = []
    for r in matches:
        uid = str(r.get("uccid",""))
        if uid not in seen_ids:
            seen_ids.add(uid)
            unique.append(r)

    company_name = unique[0].get("buycomp1","")
    buyer = unique[0]

    # ── Parse all records ─────────────────────────────────────────────────────
    today = date.today()

    def parse_date(raw):
        s = (raw or "")[:10]
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except Exception:
            return None

    def urgency(end_date):
        if not end_date:
            return None
        days = (end_date - today).days
        if days < 0:     return "LAPSED"
        if days <= 90:   return "CRITICAL"
        if days <= 180:  return "HIGH"
        if days <= 365:  return "MEDIUM"
        return "LOW"

    URGENCY_ICON = {"CRITICAL": "[!!]", "HIGH": "[! ]", "MEDIUM": "[ ~]", "LOW": "[  ]", "LAPSED": "[--]"}

    assets = []
    for r in unique:
        uccstatus = (r.get("uccstatus") or "").upper()
        filing_date = parse_date(r.get("uccdate"))
        is_lease = uccstatus in ("LEASE", "RENTAL", "REFINANCE")
        est_end = None
        if is_lease and filing_date:
            est_end = filing_date + timedelta(days=5 * 365)
        urg = urgency(est_end) if est_end else ("LAPSED" if uccstatus == "TERMINATION" else None)
        eqtman = (r.get("eqtman") or "").strip()
        comp = is_competitor(eqtman, our_brands) if our_brands else False
        assets.append({
            "uccid":       r.get("uccid",""),
            "uccstatus":   uccstatus,
            "filing_date": filing_date,
            "est_end":     est_end,
            "urgency":     urg,
            "eqtman":      eqtman,
            "eqtmodel":    (r.get("eqtmodel") or "").strip(),
            "eqtdesc":     (r.get("eqtdesc") or "").strip(),
            "eqtsn":       (r.get("eqtsn") or "").strip(),
            "spcomp":      (r.get("spcomp") or "").strip(),
            "is_lease":    is_lease,
            "is_comp":     comp,
            "eqtnu":       (r.get("eqtnu") or "").strip().upper(),
        })

    assets_sorted = sorted(assets, key=lambda a: a["filing_date"] or date(1900,1,1))

    our_eq  = [a for a in assets_sorted if not a["is_comp"] and a["uccstatus"] != "TERMINATION"]
    comp_eq = [a for a in assets_sorted if a["is_comp"] and a["uccstatus"] != "TERMINATION"]
    terms   = [a for a in assets_sorted if a["uccstatus"] == "TERMINATION"]
    leases  = [a for a in assets_sorted if a["is_lease"] and a["uccstatus"] != "TERMINATION"]
    crit    = [a for a in leases if a["urgency"] in ("CRITICAL","HIGH")]

    # ── Buying pattern analysis ───────────────────────────────────────────────
    active = [a for a in assets_sorted if a["uccstatus"] != "TERMINATION" and a["filing_date"]]
    filing_dates = [a["filing_date"] for a in active]
    if len(filing_dates) >= 2:
        intervals = [(filing_dates[i+1] - filing_dates[i]).days for i in range(len(filing_dates)-1)]
        avg_interval_months = round(sum(intervals) / len(intervals) / 30)
    else:
        avg_interval_months = None

    # Buying season from filing month
    from collections import Counter as _Counter
    month_counts = _Counter(d.month for d in filing_dates)
    season_months = month_counts.most_common(3)
    MONTH_NAMES = ["","Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    season_str = ", ".join(MONTH_NAMES[m] for m, _ in season_months) if season_months else "unknown"

    # ── Save to vault ─────────────────────────────────────────────────────────
    if save:
        md = _build_markdown(company_name, buyer, assets_sorted, our_eq, comp_eq,
                             terms, leases, avg_interval_months, season_str,
                             URGENCY_ICON, our_brands, today)
        out_path = _company_page_path(company_name)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        print(f"Saved: {out_path}")
        # Run auto-link if available
        auto_link = _vault_path() / ".scripts" / "auto-link-people.cjs"
        if auto_link.exists():
            import subprocess
            subprocess.run(["node", str(auto_link), str(out_path)],
                           capture_output=True)

    # ── Print profile ─────────────────────────────────────────────────────────
    sep = "-" * 72

    print(sep)
    print(f"  CUSTOMER INTELLIGENCE PROFILE")
    print(f"  {company_name}")
    print(sep)

    # Company info
    addr_parts = [buyer.get("buyadr1",""), buyer.get("buycity",""), buyer.get("buystate",""), buyer.get("buyzip","")]
    addr = ", ".join(p for p in addr_parts if p)
    print(f"  Address:  {addr}")
    phone = buyer.get("buyphone","")
    if phone:
        print(f"  Phone:    {phone}")
    sic = buyer.get("buysicdesc","")
    if sic:
        print(f"  Industry: {sic}")
    contacts = []
    for n in ["buyc1first buyc1last buyc1title", "buyc2first buyc2last buyc2title"]:
        fn, ln, tt = [buyer.get(k,"").strip() for k in n.split()]
        if fn or ln:
            contacts.append(f"{fn} {ln}".strip() + (f" ({tt})" if tt else ""))
    for c in contacts:
        print(f"  Contact:  {c}")
    print()

    # Summary
    print(f"  FLEET SUMMARY")
    print(f"  Total EDA records:   {len(unique)}")
    print(f"  Active (non-term):   {len(our_eq) + len(comp_eq)}")
    if our_brands:
        print(f"  Our equipment:       {len(our_eq)}")
        print(f"  Competitor equip:    {len(comp_eq)}")
    print(f"  Terminated/lapsed:   {len(terms)}")
    print(f"  Leases tracked:      {len(leases)}")
    if crit:
        print(f"  Leases expiring <6m: {len(crit)}  <-- OUTREACH PRIORITY")
    if avg_interval_months:
        print(f"  Avg buy interval:    ~{avg_interval_months} months")
    print(f"  Buying season:       {season_str}")
    if filing_dates:
        print(f"  First filing:        {filing_dates[0]}")
        print(f"  Most recent filing:  {filing_dates[-1]}")
    print()

    # Lease urgency alerts
    if leases:
        print(f"  LEASE EXPIRATION TRACKER")
        print(f"  {'Icon':<6} {'Machine':<30} {'Manufacturer':<18} {'Filed':<12} {'Est. End':<12} {'Status'}")
        print(f"  {'----':<6} {'-------':<30} {'------------':<18} {'------':<12} {'--------':<12} {'------'}")
        for a in sorted(leases, key=lambda x: x["est_end"] or date(2099,1,1)):
            icon = URGENCY_ICON.get(a["urgency"] or "", "    ")
            machine = (a["eqtdesc"] or a["eqtmodel"] or "—")[:29]
            mfr = (a["eqtman"] or "—")[:17]
            filed = str(a["filing_date"]) if a["filing_date"] else "—"
            end = str(a["est_end"]) if a["est_end"] else "—"
            urg_label = a["urgency"] or ""
            print(f"  {icon:<6} {machine:<30} {mfr:<18} {filed:<12} {end:<12} {urg_label}")
        print()

    # Equipment floor — our equipment
    if our_eq and our_brands:
        print(f"  OUR EQUIPMENT ON FLOOR ({len(our_eq)} records)")
        print(f"  {'Machine Type':<30} {'Model':<25} {'Builder':<20} {'Filed':<12} {'S/L'}")
        print(f"  {'------------':<30} {'-----':<25} {'-------':<20} {'------':<12} {'---'}")
        for a in our_eq:
            mtype = (a["eqtdesc"] or "—")[:29]
            model = (a["eqtmodel"] or "—")[:24]
            builder = (a["eqtman"] or "—")[:19]
            filed = str(a["filing_date"]) if a["filing_date"] else "—"
            sl = "Lease" if a["is_lease"] else "Sale"
            print(f"  {mtype:<30} {model:<25} {builder:<20} {filed:<12} {sl}")
        print()

    # Competitor equipment
    if comp_eq and our_brands:
        print(f"  COMPETITOR EQUIPMENT ({len(comp_eq)} records)")
        print(f"  {'Machine Type':<30} {'Model':<25} {'Competitor':<20} {'Filed':<12} {'S/L'}")
        print(f"  {'------------':<30} {'-----':<25} {'----------':<20} {'------':<12} {'---'}")
        for a in comp_eq:
            mtype = (a["eqtdesc"] or "—")[:29]
            model = (a["eqtmodel"] or "—")[:24]
            comp = (a["eqtman"] or "—")[:19]
            filed = str(a["filing_date"]) if a["filing_date"] else "—"
            sl = "Lease" if a["is_lease"] else "Sale"
            print(f"  {mtype:<30} {model:<25} {comp:<20} {filed:<12} {sl}")
        print()

    # All equipment (when no our-brands config)
    if not our_brands:
        print(f"  ALL EQUIPMENT ({len(our_eq) + len(comp_eq)} active records)")
        print(f"  {'Machine Type':<30} {'Model':<25} {'Manufacturer':<20} {'Filed':<12} {'S/L'}")
        print(f"  {'------------':<30} {'-----':<25} {'------------':<20} {'------':<12} {'---'}")
        for a in our_eq + comp_eq:
            mtype = (a["eqtdesc"] or "—")[:29]
            model = (a["eqtmodel"] or "—")[:24]
            mfr = (a["eqtman"] or "—")[:19]
            filed = str(a["filing_date"]) if a["filing_date"] else "—"
            sl = "Lease" if a["is_lease"] else "Sale"
            print(f"  {mtype:<30} {model:<25} {mfr:<20} {filed:<12} {sl}")
        print()

    # Terminated / historical
    if terms:
        print(f"  HISTORICAL (TERMINATED UCC FILINGS) — {len(terms)} records")
        for a in terms[-5:]:  # show last 5
            print(f"  {str(a['filing_date']):<12}  {a['eqtdesc'] or a['eqtmodel'] or '—':<30}  {a['eqtman']:<20}")
        if len(terms) > 5:
            print(f"  ... and {len(terms)-5} more")
        print()

    # Strategic notes
    print(f"  STRATEGIC NOTES")
    if crit:
        print(f"  PRIORITY: {len(crit)} lease(s) expiring within 6 months — contact now.")
    if comp_eq and our_brands:
        comp_brands = sorted({a["eqtman"] for a in comp_eq if a["eqtman"]})
        old_comp = [a for a in comp_eq if a["filing_date"] and (today - a["filing_date"]).days > 365*7]
        print(f"  Competitor brands on floor: {', '.join(comp_brands)}")
        if old_comp:
            print(f"  {len(old_comp)} competitor machine(s) 7+ years old — displacement opportunity.")
    if avg_interval_months and filing_dates:
        next_pred = filing_dates[-1] + timedelta(days=avg_interval_months * 30)
        if next_pred >= today:
            print(f"  Next predicted buy window: ~{next_pred} (based on {avg_interval_months}-month avg interval)")
        else:
            overdue = (today - next_pred).days // 30
            print(f"  Pattern suggests purchase was due ~{overdue} months ago — may be shopping now.")
    print(sep)


def cmd_list_queries():
    print("Saved EDA queries:")
    for q in KNOWN_SAVED_QUERIES:
        print(f"  {q}")
    print(f'\nDownload one: --download --query "CB Accounts - Press Brakes"')
    print(f"Download all: --download")


def cmd_sync(account_filter=None, dry_run=False):
    """Sync EDA local cache → Salesforce Assets for all matching accounts."""
    cache = load_cache()
    if not cache:
        print("No local cache found. Run --download first.")
        sys.exit(1)

    tokens = load_sf_tokens()
    if not tokens:
        print("No Salesforce tokens found at ~/.claude/sf_tokens.json")
        print("Run sf_authenticate from Dex first.")
        sys.exit(1)

    our_brands = load_our_brands()
    records = all_records(cache)

    # Group EDA records by buyer company name
    by_company: dict[str, list] = {}
    for r in records:
        company = (r.get("buycomp1") or "").strip()
        if company:
            by_company.setdefault(company, []).append(r)

    if account_filter:
        filter_lower = account_filter.lower()
        by_company = {k: v for k, v in by_company.items() if filter_lower in k.lower()}
        if not by_company:
            print(f"No EDA records match account filter '{account_filter}'.")
            return

    print(f"EDA cache: {len(records)} records across {len(by_company)} companies")
    if dry_run:
        print("[DRY RUN - no records will be written to Salesforce]")

    # Build SF account index (one batch query)
    sf_index = build_sf_account_index(tokens)

    matched_companies = 0
    skipped_companies = 0
    already_exists = 0
    created = 0
    failed = 0

    for company_name, eda_recs in sorted(by_company.items()):
        sf_acct = find_sf_account(sf_index, company_name)
        if not sf_acct:
            skipped_companies += 1
            continue

        matched_companies += 1
        account_id = sf_acct["Id"]

        # Only fetch existing UCCIDs for this account when not dry-running
        existing_ucc_ids = set() if dry_run else get_existing_ucc_ids(tokens, account_id)

        for eda_rec in eda_recs:
            ucc_id = str(eda_rec.get("uccid") or "").strip()
            if not ucc_id:
                continue

            if ucc_id in existing_ucc_ids:
                already_exists += 1
                continue

            payload = build_asset_payload(eda_rec, account_id, our_brands)

            if dry_run:
                print(f"  [DRY RUN] {company_name} -> {payload.get('Name')} (UCCID {ucc_id})")
                created += 1
                continue

            try:
                sf_request(tokens, "/sobjects/Asset", data=payload, method="POST")
                created += 1
            except Exception as e:
                print(f"  ERROR {company_name}/{ucc_id}: {e}", file=sys.stderr)
                failed += 1

    print(f"\nSync complete:")
    print(f"  Matched SF accounts:  {matched_companies}")
    print(f"  No SF match:          {skipped_companies} companies")
    print(f"  Already in SF:        {already_exists}")
    print(f"  {'Would create' if dry_run else 'Created'}:            {created}")
    if not dry_run:
        print(f"  Failed:               {failed}")
    if not our_brands:
        print("\nTip: create .scripts/customer-intel/our-brands.json to flag competitor equipment.")
        print('  Example: ["AMADA", "TRUMPF", "MITSUBISHI"]')


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="EDA Data scraper — download all, filter locally")
    parser.add_argument("--download",       action="store_true", help="Download saved query results to local cache")
    parser.add_argument("--query",          type=str, default="", help="Filter which saved query to download (partial name match)")
    parser.add_argument("--search",         type=str, default="", help="Search cached data by any field value")
    parser.add_argument("--field",          type=str, default="", help="Restrict --search to a specific field name")
    parser.add_argument("--profile",        type=str, default="", help="Generate customer intelligence profile from local cache")
    parser.add_argument("--save",           action="store_true", help="Save --profile output to People/Companies/ in the vault")
    parser.add_argument("--sync",           action="store_true", help="Sync EDA cache to Salesforce Assets")
    parser.add_argument("--account",        type=str, default="", help="Limit --sync to one account name (partial match)")
    parser.add_argument("--dry-run",        action="store_true", help="Preview --sync without writing to Salesforce")
    parser.add_argument("--list-queries",   action="store_true", help="List available saved queries")
    parser.add_argument("--cache-info",     action="store_true", help="Show cache stats")
    parser.add_argument("--no-login-cache", action="store_true", help="Force fresh browser login")
    parser.add_argument("--headed",         action="store_true", help="Show browser window")
    parser.add_argument("--debug",          action="store_true", help="Verbose output + screenshots at each download step")
    args = parser.parse_args()

    if args.list_queries:
        cmd_list_queries()
        return

    if args.cache_info:
        cmd_cache_info()
        return

    if args.search and not args.download:
        cmd_search(args.search, field=args.field or None)
        return

    if args.profile:
        cmd_profile(args.profile, load_our_brands(), save=args.save)
        return

    if args.sync or args.dry_run:
        cmd_sync(account_filter=args.account or None, dry_run=args.dry_run)
        return

    session = make_session()
    if not args.no_login_cache and load_login_session(session):
        print("Using saved login session.", file=sys.stderr)
    else:
        if not login(session, headed=args.headed):
            sys.exit(1)

    if args.download:
        cmd_download(session, query_filter=args.query or None, headed=args.headed, debug=args.debug)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
