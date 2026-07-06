#!/usr/bin/env python3
"""Standalone terminal bridge for publishing DexDiff methodologies.

This script travels with the /diff-generate skill, so it uses Python stdlib
only and does not import from dex-core. It connects a tester's terminal to
heydex.ai, sends the full methodology YAML to a browser review session, and
waits for the tester to publish it there.

Exit codes: 0 ok, 2 link needed or usage, 3 network problem,
            5 bad response/server response, 6 local file problem.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

HEYDEX_API_BASE_URL = "https://api.heydex.ai"
HEYDEX_SITE_BASE_URL = "https://heydex.ai"
AUTH_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000
HTTP_TIMEOUT_SECONDS = 20.0
POLL_SECONDS = 2.0
POLL_TIMEOUT_SECONDS = 35 * 60


# ---------------------------------------------------------------------------
# Errors, user_message is always safe to show a non-technical user
# ---------------------------------------------------------------------------
class PublishError(Exception):
    exit_code = 5

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


class AuthError(PublishError):
    exit_code = 2


class NetworkError(PublishError):
    exit_code = 3


class FileProblem(PublishError):
    exit_code = 6


class BadResponse(PublishError):
    exit_code = 5


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def now_ms() -> int:
    return int(time.time() * 1000)


def get_api_base_url(cli_value: "str | None" = None) -> str:
    return (cli_value or os.environ.get("DEXDIFF_API_BASE") or HEYDEX_API_BASE_URL).rstrip("/")


def get_site_base_url(cli_value: "str | None" = None) -> str:
    return (cli_value or os.environ.get("DEXDIFF_SITE_BASE") or HEYDEX_SITE_BASE_URL).rstrip("/")


def auth_file_path() -> Path:
    return Path.home() / ".dex" / "heydex-auth.json"


def link_instructions(site_base: str | None = None, expired: bool = False) -> str:
    base = get_site_base_url(site_base)
    intro = "Your Heydex connection has expired." if expired else "This terminal is not linked to Heydex yet."
    return (
        f"{intro} Open {base}/connect/?cli=true in a browser, sign in, "
        "create a sign-in code, then run:\n"
        "  python3 .claude/skills/diff-generate/scripts/publish_diff.py link --code ABC123"
    )


def _strip_quotes(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in ("'", '"'):
        return stripped[1:-1]
    return stripped


def _strip_inline_comment(value: str) -> str:
    for marker in (" #", "\t#"):
        index = value.find(marker)
        if index != -1:
            return value[:index].rstrip()
    return value.rstrip()


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return cleaned or "workflow"


def _title_from_stem(stem: str) -> str:
    words = re.split(r"[-_]+", stem.strip())
    return " ".join(word[:1].upper() + word[1:] for word in words if word) or "Workflow"


# ---------------------------------------------------------------------------
# Auth storage
# ---------------------------------------------------------------------------
def save_auth(payload: dict, destination: "Path | None" = None, timestamp_ms: "int | None" = None) -> Path:
    session_token = str(payload.get("sessionToken") or "").strip()
    if not session_token:
        raise BadResponse(
            "Heydex did not return a terminal connection token. Try creating a new sign-in code."
        )

    auth_payload = {
        "handle": payload.get("handle"),
        "email": payload.get("email"),
        "displayName": payload.get("displayName"),
        "sessionToken": session_token,
        "timestamp": timestamp_ms if timestamp_ms is not None else now_ms(),
    }

    target = destination or auth_file_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(auth_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return target


def load_auth(now_ms: "int | None" = None, site_base: "str | None" = None) -> dict:
    path = auth_file_path()
    if not path.is_file():
        raise AuthError(link_instructions(site_base))

    try:
        auth = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise AuthError(link_instructions(site_base))

    timestamp = auth.get("timestamp")
    session_token = str(auth.get("sessionToken") or "").strip()
    if not isinstance(timestamp, (int, float)) or not session_token:
        raise AuthError(link_instructions(site_base))

    reference = now_ms if now_ms is not None else globals()["now_ms"]()
    if reference - int(timestamp) > AUTH_MAX_AGE_MS:
        raise AuthError(link_instructions(site_base, expired=True))

    return auth


# ---------------------------------------------------------------------------
# YAML metadata, deliberately light and forgiving
# ---------------------------------------------------------------------------
def _top_level_entries(text: str) -> list[tuple[int, str, str]]:
    entries = []
    for line_number, raw_line in enumerate(text.splitlines()):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line[:1].isspace():
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$", raw_line)
        if match:
            entries.append((line_number, match.group(1), match.group(2)))
    return entries


def _parse_scalar(value: str) -> "str | None":
    clean = _strip_inline_comment(value).strip()
    if not clean or clean in ("|", ">", "|-", ">-", "|+", ">+"):
        return None
    if clean.startswith("[") or clean.startswith("{"):
        return None
    return _strip_quotes(clean)


def _parse_inline_list(value: str) -> "list[str] | None":
    clean = _strip_inline_comment(value).strip()
    if not clean.startswith("[") or not clean.endswith("]"):
        return None
    inner = clean[1:-1].strip()
    if not inner:
        return []
    items = []
    for raw_item in inner.split(","):
        item = _strip_quotes(_strip_inline_comment(raw_item).strip())
        if item:
            items.append(item)
    return items


def _parse_block_list(lines: list[str], start_line: int) -> "list[str] | None":
    items = []
    saw_list_item = False
    for raw_line in lines[start_line + 1 :]:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if not raw_line[:1].isspace():
            break
        stripped = raw_line.strip()
        if not stripped.startswith("- "):
            return None
        saw_list_item = True
        value = _strip_quotes(_strip_inline_comment(stripped[2:]).strip())
        if not value or re.match(r"^[A-Za-z_][A-Za-z0-9_-]*\s*:", value):
            return None
        items.append(value)
    return items if saw_list_item else None


def _first_comment(text: str) -> str:
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            comment = stripped.lstrip("#").strip()
            if comment:
                return comment
    return ""


def extract_metadata(path: Path, text: str) -> dict:
    lines = text.splitlines()
    entries = _top_level_entries(text)
    scalars: dict[str, str] = {}
    lists: dict[str, list[str]] = {}

    for line_number, key, value in entries:
        if key in ("id", "name", "description"):
            scalar = _parse_scalar(value)
            if scalar is not None:
                scalars[key] = scalar
        elif key in ("tags", "roles", "integrations"):
            parsed = _parse_inline_list(value)
            if parsed is None and not _strip_inline_comment(value).strip():
                parsed = _parse_block_list(lines, line_number)
            if parsed is not None:
                lists[key] = parsed

    stem = path.stem
    diff_id = _slugify(scalars.get("id") or stem)
    return {
        "diffId": diff_id,
        "name": scalars.get("name") or _title_from_stem(stem),
        "description": scalars.get("description") or _first_comment(text),
        "tags": lists.get("tags", []),
        "roles": lists.get("roles", []),
        "integrations": lists.get("integrations", []),
    }


def build_diff_object(path: Path) -> dict:
    try:
        methodology = path.read_text(encoding="utf-8")
    except OSError as error:
        raise FileProblem(f"Could not read {path}: {error}. Nothing was published.")

    metadata = extract_metadata(path, methodology)
    return {
        "diffId": metadata["diffId"],
        "name": metadata["name"],
        "description": metadata["description"],
        "methodology": methodology,
        "tags": metadata["tags"],
        "roles": metadata["roles"],
        "integrations": metadata["integrations"],
    }


def build_review_payload(session_token: str, paths: list[Path]) -> dict:
    return {
        "sessionToken": session_token,
        "diffs": [build_diff_object(path) for path in paths],
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def post_json(api_base: str, path: str, payload: dict, timeout: float = HTTP_TIMEOUT_SECONDS) -> dict:
    url = f"{get_api_base_url(api_base)}{path}"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as error:
        raise _http_error_to_publish_error(error)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise NetworkError(
            f"Could not reach {get_api_base_url(api_base)}. Check your internet connection and try again."
        )

    return _decode_json_response(status, response_body)


def get_json(api_base: str, path: str, timeout: float = HTTP_TIMEOUT_SECONDS) -> dict:
    url = f"{get_api_base_url(api_base)}{path}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as error:
        raise _http_error_to_publish_error(error)
    except (urllib.error.URLError, TimeoutError, OSError):
        raise NetworkError(
            f"Could not reach {get_api_base_url(api_base)}. Check your internet connection and try again."
        )

    return _decode_json_response(status, response_body)


def _http_error_to_publish_error(error: urllib.error.HTTPError) -> PublishError:
    body = error.read().decode("utf-8", errors="replace")
    message = ""
    try:
        decoded = json.loads(body)
        if isinstance(decoded, dict):
            message = str(decoded.get("error") or "").strip()
    except json.JSONDecodeError:
        pass

    if error.code == 401:
        detail = f" ({message})" if message else ""
        return AuthError(
            f"The Heydex connection was not accepted{detail}. Create a new sign-in code and run the link command again."
        )
    if error.code == 429:
        return NetworkError("Heydex is receiving too many sign-in attempts right now. Wait a minute and try again.")
    return BadResponse(
        f"Heydex answered with HTTP {error.code}. This is usually temporary, try again in a minute."
    )


def _decode_json_response(status: int, body: str) -> dict:
    if status != 200:
        raise BadResponse(f"Heydex answered with HTTP {status}. Try again in a minute.")
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError:
        raise BadResponse("Heydex returned something that is not valid JSON. Try again in a minute.")
    if not isinstance(decoded, dict):
        raise BadResponse("Heydex returned an unexpected response. Try again in a minute.")
    return decoded


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def command_link(args: argparse.Namespace) -> int:
    code = args.code.strip()
    if not code:
        print("A sign-in code is required. Create one at %s/connect/?cli=true." % get_site_base_url(args.site_base))
        return 2

    payload = post_json(get_api_base_url(args.api_base), "/api/connect/redeem", {"code": code})
    save_auth(payload)

    email = payload.get("email") or "your Heydex account"
    handle = payload.get("handle")
    handle_text = f"@{handle}" if handle else "no public handle yet"
    print(f"Linked this terminal to Heydex for {email} ({handle_text}).")
    if not handle:
        print(
            "Before publishing, finish registration at %s/connect/ so your public handle is ready."
            % get_site_base_url(args.site_base)
        )
    return 0


def command_publish(args: argparse.Namespace) -> int:
    auth = load_auth(site_base=args.site_base)
    paths = [Path(value) for value in args.files]
    payload = build_review_payload(str(auth["sessionToken"]), paths)
    response = post_json(get_api_base_url(args.api_base), "/api/review/create", payload)

    session_code = str(response.get("sessionCode") or "").strip()
    if not session_code:
        raise BadResponse("Heydex did not return a review session. Nothing was published.")

    site_base = get_site_base_url(args.site_base)
    review_url = f"{site_base}/diff/review/?session={urllib.parse.quote(session_code)}"
    print(f"Review your workflow here: {review_url}")
    try:
        webbrowser.open(review_url)
    except Exception:
        pass

    if args.no_wait:
        print("Nothing is shared until you choose Publish on that review page.")
        return 0

    print("Waiting for you to publish from the browser review page. Press Ctrl-C to stop waiting.")
    return wait_for_publish(
        get_api_base_url(args.api_base),
        site_base,
        session_code,
        poll_seconds=POLL_SECONDS,
        timeout_seconds=POLL_TIMEOUT_SECONDS,
    )


def wait_for_publish(
    api_base: str,
    site_base: str,
    session_code: str,
    poll_seconds: float = POLL_SECONDS,
    timeout_seconds: int = POLL_TIMEOUT_SECONDS,
) -> int:
    deadline = time.monotonic() + timeout_seconds
    status_path = "/api/review/status?%s" % urllib.parse.urlencode({"session": session_code})

    try:
        while time.monotonic() < deadline:
            status = get_json(api_base, status_path)
            if status.get("published") is True:
                handle = str(status.get("handle") or "").strip().lstrip("@")
                if handle:
                    print(f"Published: {site_base}/diff/{handle}/")
                else:
                    print("Published on Heydex.")
                return 0
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        print("\nStopped waiting. The review session is still open in your browser.")
        return 0

    print("The review session is still open in your browser. Publish it there when you are ready.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="publish_diff.py",
        description="Publish a generated DexDiff methodology through Heydex review.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    link = subparsers.add_parser("link", help="link this terminal to Heydex with a sign-in code")
    link.add_argument("--code", required=True, help="six-character sign-in code from Heydex")
    link.add_argument("--api-base", default=None, help="API base, default https://api.heydex.ai")
    link.add_argument("--site-base", default=None, help="site base, default https://heydex.ai")
    link.set_defaults(func=command_link)

    publish = subparsers.add_parser("publish", help="open a browser review for one or more methodology files")
    publish.add_argument("files", nargs="+", help="generated methodology YAML file")
    publish.add_argument("--no-wait", action="store_true", help="open review and return without waiting")
    publish.add_argument("--api-base", default=None, help="API base, default https://api.heydex.ai")
    publish.add_argument("--site-base", default=None, help="site base, default https://heydex.ai")
    publish.set_defaults(func=command_publish)

    return parser


def main(argv: "list[str] | None" = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except AuthError as error:
        print("CONNECTION NEEDED: %s" % error.user_message, flush=True)
        return error.exit_code
    except NetworkError as error:
        print("NETWORK ERROR: %s" % error.user_message, flush=True)
        return error.exit_code
    except FileProblem as error:
        print("FILE PROBLEM: %s" % error.user_message, flush=True)
        return error.exit_code
    except BadResponse as error:
        print("BAD RESPONSE: %s" % error.user_message, flush=True)
        return error.exit_code


if __name__ == "__main__":
    sys.exit(main())
