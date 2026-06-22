#!/usr/bin/env python3
"""
Dex EDA Data Scraper — UCC-1 Machine Tool Filing Intelligence

Logs into online.edadata.com (Fusable OIDC), searches for UCC filings,
and syncs key dates back to Salesforce Asset records.

Usage:
    python3 eda-scraper.py --discover          # Map site structure after login
    python3 eda-scraper.py --search "Acme"     # Search by company name
    python3 eda-scraper.py --sync              # Sync new filings to Salesforce
    python3 eda-scraper.py --no-cache          # Force fresh login

Login flow (Fusable OIDC/PKCE — server-side two-step):
  1. GET online.edadata.com  →  302 to appident.fusable.com/Account/Login?ReturnUrl=...
  2. POST username           →  200, password form appears
  3. POST username+password  →  302 back through OIDC callback to online.edadata.com
  4. Session cookies saved for 8 hours

No Playwright needed. Only requires: pip install requests beautifulsoup4

Credentials: stored in .env at vault root (never committed to git)
    EDA_USERNAME=your@email.com
    EDA_PASSWORD=yourpassword
"""

import json
import os
import sys
import argparse
import time
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

VAULT_PATH   = os.environ.get("VAULT_PATH", str(Path(__file__).parent.parent.parent))
BASE_URL     = "https://online.edadata.com"
FUSABLE_BASE = "https://appident.fusable.com"
SESSION_FILE = Path.home() / ".claude" / "eda_session.json"


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
        print("ERROR: requests not installed. Run: pip install requests beautifulsoup4")
        sys.exit(1)

    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
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
        saved = datetime.fromisoformat(data["saved_at"])
        if (datetime.now() - saved).total_seconds() > 28800:  # 8 hours
            return False
        for name, value in data["cookies"].items():
            session.cookies.set(name, value)
        return True
    except Exception:
        return False


# ── Login (Fusable OIDC two-step) ──────────────────────────────────────────────
#
# The flow confirmed from network inspection:
#
#   Step 0  GET  online.edadata.com/
#              → 302 to appident.fusable.com/Account/Login?ReturnUrl=<oidc_params>
#              (EDA Data generates PKCE code_challenge here; we follow automatically)
#
#   Step 1  POST appident.fusable.com/Account/Login   (username only)
#              → 200, renders page with Password field
#
#   Step 2  POST appident.fusable.com/Account/Login   (username + password)
#              → 302 to /connect/authorize/callback?...
#              → 302 to online.edadata.com/?code=...
#              → EDA exchanges code for tokens server-side
#              → session cookies set on online.edadata.com

def _collect_hidden(soup):
    hidden = {}
    for inp in soup.find_all("input", type="hidden"):
        if inp.get("name"):
            hidden[inp["name"]] = inp.get("value", "")
    return hidden


def _form_action(soup, fallback_url):
    form = soup.find("form")
    if form and form.get("action"):
        action = form["action"]
        if action.startswith("http"):
            return action
        return FUSABLE_BASE + (action if action.startswith("/") else "/" + action)
    return fallback_url


def login(session, debug=False):
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("ERROR: beautifulsoup4 not installed. Run: pip install beautifulsoup4")
        sys.exit(1)

    if not EDA_USERNAME or not EDA_PASSWORD:
        print("ERROR: EDA_USERNAME and EDA_PASSWORD not set.")
        print(f"Add them to: {Path(VAULT_PATH) / '.env'}")
        sys.exit(1)

    # ── Step 0: GET EDA Data → follows OIDC redirect to Fusable login page ─────
    print("Initiating OIDC login (following EDA → Fusable redirect)...", file=sys.stderr)
    resp0 = session.get(f"{BASE_URL}/", timeout=30, allow_redirects=True)

    if FUSABLE_BASE not in resp0.url:
        # Already logged in, or unexpected redirect
        if BASE_URL in resp0.url and _looks_authenticated(resp0.text):
            print("  Already authenticated.", file=sys.stderr)
            save_session(dict(session.cookies))
            return True
        print(f"  ERROR: Expected Fusable login page, landed at: {resp0.url}", file=sys.stderr)
        return False

    fusable_login_url = resp0.url  # e.g. appident.fusable.com/Account/Login?ReturnUrl=...
    print(f"  Redirected to Fusable: {fusable_login_url[:80]}...", file=sys.stderr)

    soup0 = BeautifulSoup(resp0.text, "html.parser")
    hidden0 = _collect_hidden(soup0)

    # ── Step 1: POST username only ─────────────────────────────────────────────
    # IdentityServer (Fusable) requires a named button value to know which action
    # to execute — "button=login" is the standard IdentityServer pattern.
    print("  Step 1: submitting username...", file=sys.stderr)
    payload1 = {**hidden0, "Username": EDA_USERNAME, "button": "login"}
    resp1 = session.post(
        fusable_login_url,
        data=payload1,
        headers={"Referer": fusable_login_url, "Sec-Fetch-Site": "same-origin"},
        timeout=30,
        allow_redirects=True,
    )

    if resp1.status_code not in (200, 302):
        print(f"  Step 1 returned unexpected status: {resp1.status_code}", file=sys.stderr)
        return False

    soup1 = BeautifulSoup(resp1.text, "html.parser")
    hidden1 = _collect_hidden(soup1)

    if debug:
        print(f"  [debug] Step 1 URL: {resp1.url}", file=sys.stderr)
        print(f"  [debug] Step 1 hidden fields: {list(hidden1.keys())}", file=sys.stderr)
        pw_inp = soup1.find("input", {"name": "Password"})
        print(f"  [debug] Password field present: {pw_inp is not None}", file=sys.stderr)
        # Show first 500 chars of form HTML to help diagnose
        form = soup1.find("form")
        if form:
            print(f"  [debug] Form action: {form.get('action', '(none)')}", file=sys.stderr)
            visible = [i.get("name") for i in form.find_all("input") if i.get("type") != "hidden" and i.get("name")]
            print(f"  [debug] Visible inputs: {visible}", file=sys.stderr)

    # Check password field appeared
    if not soup1.find("input", {"name": "Password"}):
        if _looks_authenticated(resp1.text) and BASE_URL in resp1.url:
            print("  ✓ Single-step login succeeded.", file=sys.stderr)
            save_session(dict(session.cookies))
            return True
        print("  ERROR: Password field not found after username step.", file=sys.stderr)
        print(f"  Current URL: {resp1.url}", file=sys.stderr)
        return False

    step2_url = _form_action(soup1, fusable_login_url)

    # ── Step 2: POST username + password ──────────────────────────────────────
    print("  Step 2: submitting password...", file=sys.stderr)
    payload2 = {**hidden1, "Username": EDA_USERNAME, "Password": EDA_PASSWORD}
    resp2 = session.post(
        step2_url,
        data=payload2,
        headers={"Referer": f"{FUSABLE_BASE}/Account/Login", "Sec-Fetch-Site": "same-origin"},
        timeout=30,
        allow_redirects=True,  # follows OIDC callback chain back to EDA
    )

    # After following all redirects we should land back on online.edadata.com
    final_url = resp2.url
    print(f"  Final URL: {final_url}", file=sys.stderr)

    if BASE_URL in final_url:
        eda_cookies = {n: v for n, v in session.cookies.items()}
        if eda_cookies:
            save_session(eda_cookies)
            print(f"  ✓ Login successful. {len(eda_cookies)} session cookies saved.", file=sys.stderr)
            return True
        # May have landed but without cookies (SPA — verify via content check)
        if _looks_authenticated(resp2.text):
            save_session({})
            print("  ✓ Login successful (no explicit cookies — may use storage).", file=sys.stderr)
            return True

    if "invalid" in resp2.text.lower() or "incorrect" in resp2.text.lower():
        print("  ✗ Credentials rejected. Check EDA_USERNAME / EDA_PASSWORD in .env", file=sys.stderr)
        return False

    print(f"  ERROR: Login did not complete. Final URL: {final_url}", file=sys.stderr)
    print("  Check credentials in .env and try again.", file=sys.stderr)
    return False


def _looks_authenticated(html):
    low = html.lower()
    return any(k in low for k in ("log out", "logout", "sign out", "signout",
                                   "dashboard", "welcome", "my account", "search filings"))


# ── Discovery ─────────────────────────────────────────────────────────────────

def discover(session):
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
            r = session.get(f"{BASE_URL}{path}", timeout=15, allow_redirects=False)
            if r.status_code == 302:
                loc = r.headers.get("Location", "")
                print(f"  → {path:<20} [302] → {loc[:60]}")
                continue
            if r.status_code == 200 and len(r.text) > 500:
                # Follow manually to get final page
                r = session.get(f"{BASE_URL}{path}", timeout=15, allow_redirects=True)
                soup = BeautifulSoup(r.text, "html.parser")
                title = soup.find("title")
                title_text = title.get_text(strip=True) if title else "No title"
                links = len(soup.find_all("a"))
                forms = len(soup.find_all("form"))
                inputs = len(soup.find_all("input"))
                print(f"  ✓ {path:<20} [{r.status_code}] '{title_text}' "
                      f"({links} links, {forms} forms, {inputs} inputs)")
                found_pages.append({"path": path, "title": title_text})

                for form in soup.find_all("form"):
                    action = form.get("action", "")
                    fields = [i.get("name") for i in form.find_all("input") if i.get("name")]
                    if fields:
                        print(f"    Form → action='{action}' fields={fields}")

                for t in soup.find_all("table")[:2]:
                    headers = [th.get_text(strip=True) for th in t.find_all("th")]
                    if headers:
                        print(f"    Table headers: {headers}")

            elif r.status_code not in (200, 404):
                print(f"  ? {path:<20} [{r.status_code}]")
        except Exception as e:
            print(f"  ✗ {path:<20} Error: {e}")
        time.sleep(0.5)

    # Scan homepage nav links
    try:
        r = session.get(f"{BASE_URL}/", timeout=15, allow_redirects=True)
        if r.status_code == 200 and BASE_URL in r.url:
            soup = BeautifulSoup(r.text, "html.parser")
            print("\n  Navigation links on homepage:")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(strip=True)
                if href.startswith("/") and text and len(text) < 60:
                    print(f"    {text:<35} → {href}")
        else:
            print(f"\n  Homepage redirected to: {r.url}")
            print("  Session may not be authenticated — try --no-cache to re-login.")
    except Exception:
        pass

    return found_pages


# ── Search ────────────────────────────────────────────────────────────────────

def search_company(session, company_name):
    """
    Search EDA Data for a company's UCC filings.
    TODO: Update SEARCH_URL and field names after running --discover.
    """
    print(f"\nSearching for: {company_name}", file=sys.stderr)

    SEARCH_URL = f"{BASE_URL}/search"
    payload = {"company": company_name, "state": "", "type": "equipment"}

    r = session.get(SEARCH_URL, params=payload, timeout=30)
    if r.status_code != 200:
        print(f"Search returned {r.status_code}", file=sys.stderr)
        return []

    return parse_results(r.text)


def parse_results(html):
    """
    Parse UCC filing results. Generic table parser — update selectors after discovery.
    Key fields: debtor_name, filing_date, lapse_date, filing_number,
                collateral_description, secured_party, status
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []

    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if not headers:
            continue
        for row in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if cells and len(cells) >= len(headers):
                results.append(dict(zip(headers, cells)))

    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="EDA Data scraper for Dex")
    parser.add_argument("--discover",  action="store_true", help="Map site structure after login")
    parser.add_argument("--search",    type=str, default="",  help="Search by company name")
    parser.add_argument("--sync",      action="store_true", help="Sync new filings to Salesforce")
    parser.add_argument("--no-cache",  action="store_true", help="Force fresh login, ignore saved session")
    parser.add_argument("--debug",     action="store_true", help="Print debug info during login")
    args = parser.parse_args()

    session = make_session()

    if not args.no_cache and load_session(session):
        print("Using saved session.", file=sys.stderr)
    else:
        if not login(session, debug=args.debug):
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
