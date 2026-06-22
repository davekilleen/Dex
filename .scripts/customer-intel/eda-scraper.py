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
    python3 eda-scraper.py --headed            # Show browser window (debug login)

Login uses Playwright (headless Chromium) — Fusable enforces browser integrity
checks (Sec-Fetch-User, consent flow) that block plain HTTP clients.

One-time setup:
    pip install playwright
    python -m playwright install chromium

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
FUSABLE_HOST = "appident.fusable.com"
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


def session_is_authenticated(session):
    try:
        r = session.get(f"{BASE_URL}/", timeout=15, allow_redirects=False)
    except Exception as e:
        print(f"Cached session check failed: {e}", file=sys.stderr)
        return False

    if r.status_code in (301, 302, 303, 307, 308):
        loc = r.headers.get("Location", "")
        if FUSABLE_HOST in loc or "/connect/authorize" in loc:
            return False

    if r.status_code == 200:
        return True

    print(f"Cached session check returned HTTP {r.status_code}; re-login required.", file=sys.stderr)
    return False


# ── Login (Playwright / Fusable OIDC) ─────────────────────────────────────────
#
# Fusable enforces browser integrity checks (Sec-Fetch-User, consent validation)
# that return access_denied for plain HTTP clients. Playwright uses real Chromium
# which satisfies all checks.
#
# Flow:
#   1. Navigate to online.edadata.com → OIDC redirect to appident.fusable.com
#   2. Fill username → click Continue → password field appears
#   3. Fill password → submit → OIDC callback → session cookies on online.edadata.com
#   4. Extract cookies → inject into requests Session for all subsequent calls

def login(session, headed=False, debug=False):
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print("", file=sys.stderr)
        print("ERROR: playwright not installed. Run:", file=sys.stderr)
        print("  pip install playwright", file=sys.stderr)
        print("  python -m playwright install chromium", file=sys.stderr)
        sys.exit(1)

    if not EDA_USERNAME or not EDA_PASSWORD:
        print("ERROR: EDA_USERNAME and EDA_PASSWORD not set.", file=sys.stderr)
        print(f"Add them to: {Path(VAULT_PATH) / '.env'}", file=sys.stderr)
        sys.exit(1)

    print("Launching browser for Fusable OIDC login...", file=sys.stderr)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        )
        page = context.new_page()

        try:
            # ── Navigate to EDA → OIDC redirect to Fusable ────────────────────
            print("  Navigating to EDA Data...", file=sys.stderr)
            page.goto(f"{BASE_URL}/", timeout=30000)
            page.wait_for_url(f"**/{FUSABLE_HOST}/**", timeout=20000)

            if debug:
                print(f"  [debug] Login page: {page.url[:80]}", file=sys.stderr)

            # ── Fill username and click Continue ───────────────────────────────
            print("  Filling username...", file=sys.stderr)
            page.wait_for_selector('input[name="Username"]', timeout=10000)
            page.fill('input[name="Username"]', EDA_USERNAME)

            # Click the Continue / submit button
            _click_submit(page)

            # ── Wait for password field ────────────────────────────────────────
            print("  Waiting for password field...", file=sys.stderr)
            try:
                page.wait_for_selector('input[name="Password"]', timeout=8000)
            except PWTimeout:
                if BASE_URL in page.url:
                    return _extract_cookies(context, session, browser)
                print("  ERROR: Password field did not appear.", file=sys.stderr)
                _debug_screenshot(page)
                browser.close()
                return False

            if debug:
                print(f"  [debug] Password page URL: {page.url[:80]}", file=sys.stderr)

            # ── Fill password and submit ───────────────────────────────────────
            print("  Filling password...", file=sys.stderr)
            page.fill('input[name="Password"]', EDA_PASSWORD)
            _click_submit(page)

            # ── Wait for redirect back to EDA Data ────────────────────────────
            print("  Waiting for EDA Data session...", file=sys.stderr)
            try:
                page.wait_for_url(f"**/online.edadata.com/**", timeout=20000)
            except PWTimeout:
                if debug:
                    print(f"  [debug] Current URL after wait: {page.url[:80]}", file=sys.stderr)
                    _debug_screenshot(page)
                print("  ERROR: Did not land back on EDA Data. Check credentials.", file=sys.stderr)
                browser.close()
                return False

            print(f"  Landed at: {page.url[:80]}", file=sys.stderr)
            return _extract_cookies(context, session, browser)

        except PWTimeout as e:
            print(f"  ERROR: Timeout — {e}", file=sys.stderr)
            print(f"  URL at timeout: {page.url[:80]}", file=sys.stderr)
            _debug_screenshot(page)
            browser.close()
            return False
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            _debug_screenshot(page)
            browser.close()
            return False


def _click_submit(page):
    for selector in [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Continue")',
        'button:has-text("Login")',
        'button:has-text("Sign in")',
    ]:
        btn = page.query_selector(selector)
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
        print("  WARNING: No session cookies captured.", file=sys.stderr)
        return False

    save_session(cookie_dict)
    print(f"  OK: Login successful. {len(cookie_dict)} cookies saved.", file=sys.stderr)
    return True


def _debug_screenshot(page):
    try:
        path = Path.home() / ".claude" / "eda_login_debug.png"
        page.screenshot(path=str(path))
        print(f"  Screenshot saved: {path}", file=sys.stderr)
    except Exception:
        pass


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

    # Probe only the pages we actually need — keep request count low
    pages_to_check = ["/Query", "/Report", "/Analyze"]

    found_pages = []
    for path in pages_to_check:
        try:
            r = session.get(f"{BASE_URL}{path}", timeout=15, allow_redirects=False)
            if r.status_code == 302:
                loc = r.headers.get("Location", "")
                print(f"  -> {path:<20} [302] -> {loc[:60]}")
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
                print(f"  OK {path:<20} [{r.status_code}] '{title_text}' "
                      f"({links} links, {forms} forms, {inputs} inputs)")
                found_pages.append({"path": path, "title": title_text})

                for form in soup.find_all("form"):
                    action = form.get("action", "")
                    fields = [i.get("name") for i in form.find_all("input") if i.get("name")]
                    if fields:
                        print(f"    Form -> action='{action}' fields={fields}")

                for t in soup.find_all("table")[:2]:
                    headers = [th.get_text(strip=True) for th in t.find_all("th")]
                    if headers:
                        print(f"    Table headers: {headers}")

            elif r.status_code not in (200, 404):
                print(f"  ? {path:<20} [{r.status_code}]")
        except Exception as e:
            print(f"  X  {path:<20} Error: {e}")
        time.sleep(1)

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
                    print(f"    {text:<35} -> {href}")
        else:
            print(f"\n  Homepage redirected to: {r.url}")
            print("  Session may not be authenticated - try --no-cache to re-login.")
    except Exception:
        pass

    return found_pages


# ── Search & Query (Playwright) ───────────────────────────────────────────────
#
# Results on /Query are JavaScript-rendered via AJAX — a plain POST returns
# the shell page with no data. We inject the saved session cookies into a
# Playwright context so no re-login is needed, then wait for the results
# table to populate in the DOM before extracting.

def _pw_context_with_cookies(playwright, session, headed=False):
    """Create a Playwright browser context pre-loaded with the saved session cookies."""
    browser = playwright.chromium.launch(headless=not headed)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    )
    # Inject session cookies
    pw_cookies = []
    for cookie in session.cookies:
        pw_cookies.append({
            "name":   cookie.name,
            "value":  cookie.value,
            "domain": cookie.domain.lstrip("."),
            "path":   cookie.path or "/",
        })
    if pw_cookies:
        context.add_cookies(pw_cookies)
    return browser, context


def search_company(session, company_name, headed=False):
    """
    Search /Query for a company name. Uses Playwright because results are AJAX-rendered.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright && python -m playwright install chromium")
        sys.exit(1)

    print(f"\nSearching for: {company_name}", file=sys.stderr)

    with sync_playwright() as p:
        browser, context = _pw_context_with_cookies(p, session, headed)
        page = context.new_page()
        try:
            page.goto(f"{BASE_URL}/Query", timeout=30000)
            page.wait_for_selector('input[name="SearchTextBox"]', timeout=10000)

            page.fill('input[name="SearchTextBox"]', company_name)
            page.keyboard.press("Enter")

            # Wait for results table or "no results" indicator
            print("  Waiting for results...", file=sys.stderr)
            try:
                page.wait_for_selector("table.results, .no-results, #resultsGrid, [class*='result']",
                                       timeout=15000)
            except PWTimeout:
                pass  # Parse whatever loaded

            html = page.content()
            browser.close()
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)
            _debug_screenshot(page)
            browser.close()
            return []

    results = parse_results(html)
    print(f"  Found {len(results)} results.", file=sys.stderr)
    return results


def parse_results(html):
    """Parse results table from a /Query results page."""
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


# ── Saved Query Execution ─────────────────────────────────────────────────────

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


def list_saved_queries(session):
    print("\nSaved EDA queries:")
    for q in KNOWN_SAVED_QUERIES:
        print(f"  {q}")
    print(f"\nRun one: --run-query \"CB Accounts - Press Brakes\"")


def run_saved_query(session, query_name, headed=False):
    """
    Run a named saved query from /Query by clicking its checkbox and submitting.
    Uses Playwright because results are AJAX-rendered.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright && python -m playwright install chromium")
        sys.exit(1)

    print(f"\nRunning saved query: {query_name}", file=sys.stderr)

    with sync_playwright() as p:
        browser, context = _pw_context_with_cookies(p, session, headed)
        page = context.new_page()
        try:
            page.goto(f"{BASE_URL}/Query", timeout=30000)

            # Find the checkbox/button for this saved query by its label text
            # Saved queries appear as checkboxes or named submit buttons on the form
            found = False

            # Try checkbox with matching label
            labels = page.query_selector_all("label")
            for label in labels:
                if query_name.lower() in label.inner_text().lower():
                    label.click()
                    found = True
                    print(f"  Checked query: {query_name}", file=sys.stderr)
                    break

            if not found:
                # Fall back: try input[value] matching
                btn = page.query_selector(f'input[value="{query_name}"], button:has-text("{query_name}")')
                if btn:
                    btn.click()
                    found = True

            if not found:
                print(f"  WARNING: Could not find saved query '{query_name}' on /Query page.", file=sys.stderr)
                browser.close()
                return []

            # Click Search/Submit to run the selected query
            for sel in ['input[type="submit"][value*="Search"]', 'button[type="submit"]', 'input[type="submit"]']:
                submit = page.query_selector(sel)
                if submit:
                    submit.click()
                    break

            # Wait for results
            print("  Waiting for results...", file=sys.stderr)
            try:
                page.wait_for_selector("table.results, .no-results, #resultsGrid, [class*='result']",
                                       timeout=15000)
            except PWTimeout:
                pass  # Parse whatever loaded

            html = page.content()
            browser.close()
        except Exception as e:
            print(f"  Error: {e}", file=sys.stderr)
            _debug_screenshot(page)
            browser.close()
            return []

    results = parse_results(html)
    print(f"  Found {len(results)} results.", file=sys.stderr)
    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="EDA Data scraper for Dex")
    parser.add_argument("--discover",   action="store_true", help="Map site structure after login")
    parser.add_argument("--search",     type=str, default="", help="Search by company name")
    parser.add_argument("--run-query",  type=str, default="", help="Run a saved EDA query by name")
    parser.add_argument("--list-queries", action="store_true", help="List all saved queries")
    parser.add_argument("--sync",       action="store_true", help="Sync new filings to Salesforce")
    parser.add_argument("--no-cache",   action="store_true", help="Force fresh login, ignore saved session")
    parser.add_argument("--headed",     action="store_true", help="Show browser window during login")
    parser.add_argument("--debug",      action="store_true", help="Verbose login output + screenshot on error")
    args = parser.parse_args()

    session = make_session()

    if not args.no_cache and load_session(session):
        print("Using saved session.", file=sys.stderr)
    else:
        if not login(session, headed=args.headed, debug=args.debug):
            sys.exit(1)

    if args.discover:
        discover(session)
    elif args.search:
        results = search_company(session, args.search)
        if results:
            print(json.dumps(results, indent=2))
        else:
            print("No results found.")
    elif args.list_queries:
        list_saved_queries(session)
    elif args.run_query:
        results = run_saved_query(session, args.run_query, headed=args.headed)
        if results:
            print(json.dumps(results, indent=2))
        else:
            print("No results found.")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
