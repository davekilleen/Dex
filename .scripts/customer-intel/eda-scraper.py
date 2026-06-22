#!/usr/bin/env python3
"""
Dex EDA Data Scraper — UCC-1 Machine Tool Filing Intelligence

Logs into online.edadata.com, searches for UCC filings, and syncs
key dates back to Salesforce Asset records.

Usage:
    python3 eda-scraper.py --discover          # Map site structure after login
    python3 eda-scraper.py --search "Acme"     # Search by company name
    python3 eda-scraper.py --sync              # Sync new filings to Salesforce
    python3 eda-scraper.py --export            # Export all accessible filings

Credentials: stored in .env at vault root (never committed to git)
    EDA_USERNAME=your@email.com
    EDA_PASSWORD=yourpassword
"""

import json
import os
import sys
import argparse
import time
from datetime import datetime, date
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

VAULT_PATH   = os.environ.get("VAULT_PATH", str(Path(__file__).parent.parent.parent))
BASE_URL     = "https://online.edadata.com"
SESSION_FILE = Path.home() / ".claude" / "eda_session.json"

# Load credentials from .env
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
    """Create a requests session with browser-like headers."""
    try:
        import requests
    except ImportError:
        print("ERROR: requests not installed. Run: pip install requests beautifulsoup4")
        sys.exit(1)

    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xhtml+xml,*/*;q=0.9",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    })
    return s


def save_session(cookies):
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SESSION_FILE, "w") as f:
        json.dump({"cookies": cookies, "saved_at": datetime.now().isoformat()}, f)


def load_session(session):
    if not SESSION_FILE.exists():
        return False
    try:
        data = json.loads(SESSION_FILE.read_text())
        # Expire sessions after 8 hours
        saved = datetime.fromisoformat(data["saved_at"])
        if (datetime.now() - saved).total_seconds() > 28800:
            return False
        for name, value in data["cookies"].items():
            session.cookies.set(name, value)
        return True
    except Exception:
        return False


# ── Login ─────────────────────────────────────────────────────────────────────

def login(session):
    """
    Login to EDA Data. Form details will be filled in once we know
    the login page structure (field names, form action, CSRF token).

    TODO: Update LOGIN_URL, USERNAME_FIELD, PASSWORD_FIELD, FORM_ACTION
    once the user inspects the login form.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("ERROR: beautifulsoup4 not installed. Run: pip install requests beautifulsoup4")
        sys.exit(1)

    if not EDA_USERNAME or not EDA_PASSWORD:
        print("ERROR: EDA_USERNAME and EDA_PASSWORD not set.")
        print(f"Add them to: {Path(VAULT_PATH) / '.env'}")
        print("  EDA_USERNAME=your@email.com")
        print("  EDA_PASSWORD=yourpassword")
        sys.exit(1)

    print("Fetching login page...", file=sys.stderr)
    # ── PLACEHOLDER: update these once login form is inspected ────────────────
    LOGIN_URL     = f"{BASE_URL}/"           # URL of the login page
    FORM_ACTION   = f"{BASE_URL}/"           # form action (may differ)
    USERNAME_FIELD = "username"              # name attr of username input
    PASSWORD_FIELD = "password"              # name attr of password input
    # ─────────────────────────────────────────────────────────────────────────

    resp = session.get(LOGIN_URL, timeout=30)
    if resp.status_code != 200:
        print(f"ERROR: Login page returned {resp.status_code}", file=sys.stderr)
        return False

    soup = BeautifulSoup(resp.text, "html.parser")

    # Auto-detect form action
    form = soup.find("form")
    if form and form.get("action"):
        action = form["action"]
        if action.startswith("http"):
            FORM_ACTION = action
        elif action.startswith("/"):
            FORM_ACTION = BASE_URL + action
        else:
            FORM_ACTION = BASE_URL + "/" + action
        print(f"  Form action: {FORM_ACTION}", file=sys.stderr)

    # Collect all hidden fields (CSRF tokens etc.)
    payload = {}
    for hidden in soup.find_all("input", type="hidden"):
        if hidden.get("name") and hidden.get("value"):
            payload[hidden["name"]] = hidden["value"]

    # Auto-detect field names if not matching defaults
    for inp in soup.find_all("input"):
        name = inp.get("name", "").lower()
        typ  = inp.get("type", "").lower()
        if typ in ("text", "email") and any(k in name for k in ("user", "email", "login")):
            USERNAME_FIELD = inp["name"]
            print(f"  Username field: {USERNAME_FIELD}", file=sys.stderr)
        if typ == "password":
            PASSWORD_FIELD = inp["name"]
            print(f"  Password field: {PASSWORD_FIELD}", file=sys.stderr)

    payload[USERNAME_FIELD] = EDA_USERNAME
    payload[PASSWORD_FIELD] = EDA_PASSWORD

    print("Submitting login...", file=sys.stderr)
    resp = session.post(FORM_ACTION, data=payload, timeout=30, allow_redirects=True)

    if resp.status_code in (200, 302):
        # Check if login succeeded by looking for known post-login indicators
        if any(indicator in resp.text.lower() for indicator in
               ("logout", "sign out", "dashboard", "welcome", "search", "log out")):
            print("  Login successful.", file=sys.stderr)
            save_session(dict(session.cookies))
            return True
        elif any(indicator in resp.text.lower() for indicator in
                 ("invalid", "incorrect", "failed", "error", "wrong")):
            print("  Login failed — check credentials.", file=sys.stderr)
            return False
        else:
            # Ambiguous — save session and try to proceed
            print("  Login response ambiguous — proceeding.", file=sys.stderr)
            save_session(dict(session.cookies))
            return True

    print(f"  Login returned {resp.status_code}", file=sys.stderr)
    return False


# ── Discovery ─────────────────────────────────────────────────────────────────

def discover(session):
    """
    Map the site structure after login. Finds search pages, reports,
    export options, and API endpoints. Run this first after getting access.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("ERROR: beautifulsoup4 not installed.")
        sys.exit(1)

    print("\n=== EDA Data Site Discovery ===\n")

    pages_to_check = [
        "/", "/home", "/dashboard", "/search", "/report",
        "/equipment", "/filings", "/ucc", "/data", "/export",
        "/api", "/accounts", "/assets",
    ]

    found_pages = []
    for path in pages_to_check:
        try:
            r = session.get(f"{BASE_URL}{path}", timeout=15)
            if r.status_code == 200 and len(r.text) > 500:
                soup = BeautifulSoup(r.text, "html.parser")
                title = soup.find("title")
                title_text = title.get_text(strip=True) if title else "No title"
                links = len(soup.find_all("a"))
                forms = len(soup.find_all("form"))
                inputs = len(soup.find_all("input"))
                print(f"  ✓ {path:<20} [{r.status_code}] '{title_text}' "
                      f"({links} links, {forms} forms, {inputs} inputs)")
                found_pages.append({
                    "path": path,
                    "title": title_text,
                    "links": links,
                    "forms": forms,
                })

                # Look for search forms
                for form in soup.find_all("form"):
                    action = form.get("action", "")
                    fields = [i.get("name") for i in form.find_all("input") if i.get("name")]
                    if fields:
                        print(f"    Form → action='{action}' fields={fields}")

                # Look for data tables
                tables = soup.find_all("table")
                for t in tables[:2]:
                    headers = [th.get_text(strip=True) for th in t.find_all("th")]
                    if headers:
                        print(f"    Table headers: {headers}")

            elif r.status_code != 404:
                print(f"  ? {path:<20} [{r.status_code}]")
        except Exception as e:
            print(f"  ✗ {path:<20} Error: {e}")
        time.sleep(0.5)

    # Also scan all links on the homepage for navigation structure
    try:
        r = session.get(f"{BASE_URL}/", timeout=15)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            print("\n  Navigation links found on homepage:")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(strip=True)
                if href.startswith("/") and text and len(text) < 50:
                    print(f"    {text:<30} → {href}")
    except Exception:
        pass

    return found_pages


# ── Search ────────────────────────────────────────────────────────────────────

def search_company(session, company_name):
    """
    Search EDA Data for a company's UCC filings.

    TODO: Update SEARCH_URL and field names once site structure is known.
    """
    print(f"\nSearching for: {company_name}", file=sys.stderr)

    # PLACEHOLDER — will be updated after discovery
    SEARCH_URL = f"{BASE_URL}/search"
    payload = {
        "company": company_name,   # update field name after discovery
        "state": "",
        "type": "equipment",
    }

    r = session.get(SEARCH_URL, params=payload, timeout=30)
    if r.status_code != 200:
        print(f"Search returned {r.status_code}", file=sys.stderr)
        return []

    return parse_results(r.text)


def parse_results(html):
    """
    Parse UCC filing results from a search results page.

    TODO: Update selectors once we know the actual HTML structure.
    Key fields to extract:
      - debtor_name (company name)
      - filing_date
      - lapse_date (= filing_date + 5 years, or continuation date)
      - filing_number (UCCID)
      - collateral_description (machine type/model/serial)
      - secured_party (financing company)
      - status (active/lapsed/terminated)
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []

    # Generic table parser — works for most EDA-style result pages
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if not headers:
            continue
        for row in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if cells and len(cells) >= len(headers):
                record = dict(zip(headers, cells))
                results.append(record)

    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="EDA Data scraper for Dex")
    parser.add_argument("--discover",  action="store_true", help="Map site structure after login")
    parser.add_argument("--search",    type=str, default="",  help="Search by company name")
    parser.add_argument("--sync",      action="store_true", help="Sync new filings to Salesforce")
    parser.add_argument("--no-cache",  action="store_true", help="Force fresh login, ignore saved session")
    args = parser.parse_args()

    session = make_session()

    # Try saved session first, then fresh login
    if not args.no_cache and load_session(session):
        print("Using saved session.", file=sys.stderr)
    else:
        if not login(session):
            sys.exit(1)

    if args.discover:
        discover(session)
    elif args.search:
        results = search_company(session, args.search)
        if results:
            print(json.dumps(results, indent=2))
        else:
            print("No results found.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
