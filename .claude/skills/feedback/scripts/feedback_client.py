#!/usr/bin/env python3
"""Send Dex feedback reports to heydex.ai and check on their status.

Standalone by design: this script ships inside the skill folder and must not
import anything from dex-core. Standard library only. It shares the terminal
connection file (~/.dex/heydex-auth.json) with the DexDiff publish flow, so
one sign-in serves both.

Contract of record: docs/feedback-loop-contract.md.

Commands:
  link    --code ABC123          Link this terminal to a heydex account.
  report  --file draft.json      Send an approved report; prints the ticket.
  status                         Show every report this account has filed.
  answer  --ticket DEX-142 --text "..."   Answer a question on a ticket.

Every send attempt (successful or not) is recorded in
System/.dex/feedback-log.jsonl so the user can always see exactly what left
their machine. Claim tickets are stored one file per report under
System/.dex/feedback/.
"""

import argparse
import hashlib
import json
import os
import re
import ssl
import stat
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Same backend the DexDiff publish path uses (HTTP Actions). NOT api.heydex.ai,
# which routes to the separate Dex Desktop backend. Override: DEX_FEEDBACK_API_BASE.
HEYDEX_API_BASE_URL = "https://gallant-reindeer-229.eu-west-1.convex.site"
HEYDEX_SITE_BASE_URL = "https://heydex.ai"
AUTH_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000
HTTP_TIMEOUT_SECONDS = 20

SCHEMA_VERSION = 1

# Contract: docs/feedback-loop-contract.md — any linked Heydex session may
# send. DexDiff beta membership is not a client-side send gate. Tests fail
# if this flag is flipped on.
DEXDIFF_BETA_REQUIRED_TO_SEND = False
BETA_GATE_MARKERS = (
    "beta_access_denied",
    "dexdiff beta",
    "private beta",
    "not in beta",
    "beta membership",
)

# Field caps mirror the server (convex feedback shaping). The server is the
# enforcer; these exist so a too-long report fails here with a helpful
# message instead of an opaque 400.
FIELD_CAPS = {
    "feature": 200,
    "dex_version": 50,
    "summary": 2000,
    "error_trace": 8000,
    "investigation": 4000,
    "user_note": 2000,
    "answer": 4000,
}
MACHINE_STATE_CAP = 8000
REVIEW_MODES = ("always-review", "auto-send")
REQUIRED_FIELDS = ("feature", "summary")
OPTIONAL_FIELDS = ("error_trace", "investigation", "user_note")
TICKET_PATTERN = re.compile(r"^DEX-\d{1,10}$")

STATUS_LABELS = {
    "received": "RECEIVED",
    "investigating": "INVESTIGATING",
    "needs_info": "NEEDS INFO",
    "fixed": "FIXED",
    "wont_fix": "CAN'T FIX",
}


# ---------------------------------------------------------------------------
# Errors, user_message is always safe to show a non-technical user
# ---------------------------------------------------------------------------
class FeedbackError(Exception):
    exit_code = 5

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


class AuthError(FeedbackError):
    exit_code = 2


class NetworkError(FeedbackError):
    exit_code = 3


class CertificateError(FeedbackError):
    exit_code = 3


class BadResponse(FeedbackError):
    exit_code = 5


class FileProblem(FeedbackError):
    exit_code = 6


class DraftProblem(FeedbackError):
    exit_code = 4


def _is_beta_gate_message(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in BETA_GATE_MARKERS)


def session_permits_feedback_send(auth: dict | None) -> bool:
    """A linked Heydex session is enough. DexDiff beta is not a send gate.

    Intentionally ignores dexdiffBeta / isBeta / beta membership fields on
    the auth file. Those fields may exist because the same file is shared
    with the DexDiff publish flow.
    """
    if not isinstance(auth, dict):
        return False
    token = str(auth.get("sessionToken") or "").strip()
    if not token:
        return False
    # dexdiffBeta / isBeta / beta on this shared auth file are ignored.
    return DEXDIFF_BETA_REQUIRED_TO_SEND is False


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def now_ms() -> int:
    return int(time.time() * 1000)


def get_api_base_url(cli_value: "str | None" = None) -> str:
    return (cli_value or os.environ.get("DEX_FEEDBACK_API_BASE") or HEYDEX_API_BASE_URL).rstrip("/")


def get_site_base_url(cli_value: "str | None" = None) -> str:
    return (cli_value or os.environ.get("DEX_FEEDBACK_SITE_BASE") or HEYDEX_SITE_BASE_URL).rstrip("/")


def auth_file_path() -> Path:
    return Path.home() / ".dex" / "heydex-auth.json"


def resolve_vault(cli_value: "str | None" = None) -> Path:
    candidate = cli_value or os.environ.get("VAULT_PATH") or os.getcwd()
    return Path(candidate).expanduser().resolve()


def feedback_dir(vault: Path) -> Path:
    return vault / "System" / ".dex" / "feedback"


def receipts_path(vault: Path) -> Path:
    return vault / "System" / ".dex" / "feedback-log.jsonl"


def link_instructions(site_base: "str | None" = None, expired: bool = False) -> str:
    base = get_site_base_url(site_base)
    intro = "Your Heydex connection has expired." if expired else "This terminal is not linked to Heydex yet."
    return (
        f"{intro} Open {base}/connect/?cli=true in a browser, sign in, "
        "create a sign-in code, then run:\n"
        "  python3 .claude/skills/feedback/scripts/feedback_client.py link --code ABC123"
    )


# ---------------------------------------------------------------------------
# Auth storage (shared with the DexDiff publish flow)
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


def load_auth(reference_ms: "int | None" = None, site_base: "str | None" = None) -> dict:
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

    reference = reference_ms if reference_ms is not None else now_ms()
    if reference - int(timestamp) > AUTH_MAX_AGE_MS:
        raise AuthError(link_instructions(site_base, expired=True))

    # A linked Heydex session is enough to send. DexDiff beta membership on
    # this shared auth file is ignored on purpose.
    if not session_permits_feedback_send(auth):
        raise AuthError(link_instructions(site_base))

    return auth


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _request_json(
    method: str,
    api_base: str,
    path: str,
    payload: "dict | None" = None,
    bearer: "str | None" = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> dict:
    url = f"{get_api_base_url(api_base)}{path}"
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as error:
        raise _http_error_to_feedback_error(error)
    except urllib.error.URLError as error:
        if isinstance(error.reason, ssl.SSLCertVerificationError):
            raise CertificateError(
                f"Could not verify the secure certificate from {get_api_base_url(api_base)}. "
                "This can happen when a corporate network inspects encrypted traffic; "
                "your internet connection may still be working. Ask your IT team to check "
                "the network's certificate setup, then try again."
            ) from error
        raise NetworkError(
            f"Could not reach {get_api_base_url(api_base)}. Check your internet connection and try again."
        ) from error
    except ssl.SSLCertVerificationError as error:
        raise CertificateError(
            f"Could not verify the secure certificate from {get_api_base_url(api_base)}. "
            "This can happen when a corporate network inspects encrypted traffic; "
            "your internet connection may still be working. Ask your IT team to check "
            "the network's certificate setup, then try again."
        ) from error
    except (TimeoutError, OSError) as error:
        raise NetworkError(
            f"Could not reach {get_api_base_url(api_base)}. Check your internet connection and try again."
        ) from error

    return _decode_json_response(status, response_body)


def _http_error_to_feedback_error(error: urllib.error.HTTPError) -> FeedbackError:
    body = error.read().decode("utf-8", errors="replace")
    message = ""
    try:
        decoded = json.loads(body)
        if isinstance(decoded, dict):
            message = str(decoded.get("error") or "").strip()
    except json.JSONDecodeError:
        pass

    if error.code == 401:
        # Never recast a hosted beta-gate as "you need DexDiff beta". Sign-in
        # is the only Dex-side send requirement; a linked session that the
        # host still rejects is a connection problem, not a membership one.
        detail = ""
        if message and not _is_beta_gate_message(message):
            detail = f" ({message})"
        return AuthError(
            f"The Heydex connection was not accepted{detail}. Create a new sign-in code and run the link command again."
        )
    if error.code == 429:
        return NetworkError("Heydex is receiving a lot of requests right now. Wait a minute and try again.")
    if error.code == 400:
        return BadResponse(
            "Heydex could not accept this report. This usually means a field was too long — "
            "trim the report and try again."
        )
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
# Local records: receipts + claim tickets
# ---------------------------------------------------------------------------
def append_receipt(vault: Path, action: str, payload: dict, sent: bool, reason: str) -> None:
    """One line per attempt, sent or not — the user can always audit this."""
    path = receipts_path(vault)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "attempted_at": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "sent": sent,
            "reason": reason,
            "payload": payload,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    except OSError:
        pass


def write_ticket_file(vault: Path, ticket: str, report_payload: dict, received_at: int) -> Path:
    directory = feedback_dir(vault)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{ticket}.json"
    record = {
        "ticket": ticket,
        "sent_at": received_at,
        "status": "received",
        "status_changed_at": received_at,
        "last_notified_status_changed_at": received_at,
        "report": report_payload,
    }
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_ticket_files(vault: Path) -> dict:
    directory = feedback_dir(vault)
    tickets = {}
    if not directory.is_dir():
        return tickets
    for path in sorted(directory.glob("DEX-*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        ticket = record.get("ticket")
        if isinstance(ticket, str) and TICKET_PATTERN.match(ticket):
            tickets[ticket] = record
    return tickets


def update_ticket_file(vault: Path, record: dict) -> None:
    directory = feedback_dir(vault)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{record['ticket']}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Report drafts
# ---------------------------------------------------------------------------
def compute_fingerprint(feature: str, error_trace: str, summary: str) -> str:
    """Stable failure signature: same bug from different users should collide.

    Uses the LAST non-empty line of the error trace — for a Python traceback
    that is the exception message ("IndexError: ..."), which distinguishes
    bugs. The first line would be the generic "Traceback (most recent call
    last):" header and would merge every distinct bug in a feature.
    """
    lines = [line for line in error_trace.strip().splitlines() if line.strip()]
    if lines:
        head = lines[-1]
    else:
        summary_lines = [line for line in summary.strip().splitlines() if line.strip()]
        head = summary_lines[0] if summary_lines else ""
    normalized = re.sub(r"0x[0-9a-fA-F]+", "ADDR", head)
    normalized = re.sub(r"\d+", "#", normalized).strip().lower()
    return hashlib.sha256(f"{feature}\n{normalized}".encode("utf-8")).hexdigest()


def validate_draft(draft: dict) -> dict:
    if not isinstance(draft, dict):
        raise DraftProblem("The report draft must be a JSON object.")

    allowed = set(REQUIRED_FIELDS) | set(OPTIONAL_FIELDS) | {
        "schema_version",
        "captured_at",
        "dex_version",
        "machine_state",
        "review_mode",
        "fingerprint",
    }
    unknown = sorted(set(draft) - allowed)
    if unknown:
        raise DraftProblem(
            "The report draft contains fields that are not part of the allowed list: "
            + ", ".join(unknown)
            + ". Only the contract's ingredients may ever be sent."
        )

    for field in REQUIRED_FIELDS:
        value = draft.get(field)
        if not isinstance(value, str) or not value.strip():
            raise DraftProblem(f"The report draft is missing '{field}'.")

    for field, cap in FIELD_CAPS.items():
        if field == "answer":
            continue
        value = draft.get(field)
        if value is None:
            continue
        if not isinstance(value, str):
            raise DraftProblem(f"'{field}' must be text.")
        if len(value) > cap:
            raise DraftProblem(
                f"'{field}' is too long ({len(value)} characters; the limit is {cap}). Trim it and try again."
            )

    machine_state = draft.get("machine_state")
    if machine_state is not None:
        if not isinstance(machine_state, dict):
            raise DraftProblem("'machine_state' must be an object.")
        if len(json.dumps(machine_state)) > MACHINE_STATE_CAP:
            raise DraftProblem("'machine_state' is too large. Trim it and try again.")

    review_mode = draft.get("review_mode", "always-review")
    if review_mode not in REVIEW_MODES:
        raise DraftProblem("'review_mode' must be 'always-review' or 'auto-send'.")

    dex_version = draft.get("dex_version")
    if not isinstance(dex_version, str) or not dex_version.strip():
        raise DraftProblem("The report draft is missing 'dex_version'.")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": draft.get("captured_at") if isinstance(draft.get("captured_at"), int) else now_ms(),
        "dex_version": dex_version.strip(),
        "feature": draft["feature"].strip(),
        "summary": draft["summary"].strip(),
        "review_mode": review_mode,
    }
    for field in OPTIONAL_FIELDS:
        value = draft.get(field)
        if isinstance(value, str) and value.strip():
            payload[field] = value.strip()
    if isinstance(machine_state, dict):
        payload["machine_state"] = machine_state

    fingerprint = draft.get("fingerprint")
    if isinstance(fingerprint, str) and re.fullmatch(r"[0-9a-f]{16,128}", fingerprint):
        payload["fingerprint"] = fingerprint
    else:
        payload["fingerprint"] = compute_fingerprint(
            payload["feature"], payload.get("error_trace", ""), payload["summary"]
        )

    return payload


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def command_check(args: argparse.Namespace) -> int:
    """Preflight: is this terminal linked and fresh enough to send right now?

    Raises AuthError (exit 2, CONNECTION NEEDED) when it is not, so callers can
    resolve the link before any report is drafted.
    """
    auth = load_auth(site_base=args.site_base)
    if not session_permits_feedback_send(auth):
        raise AuthError(link_instructions(args.site_base))
    identity = auth.get("email") or auth.get("handle") or "your Heydex account"
    print(f"LINKED: this terminal can send feedback as {identity}.")
    return 0


def command_link(args: argparse.Namespace) -> int:
    code = args.code.strip()
    if not code:
        raise FeedbackError(
            "A sign-in code is required. Create one at %s/connect/?cli=true." % get_site_base_url(args.site_base)
        )

    payload = _request_json("POST", get_api_base_url(args.api_base), "/api/connect/redeem", {"code": code})
    save_auth(payload)
    email = payload.get("email") or "your Heydex account"
    print(f"Linked this terminal to Heydex for {email}. Feedback reports are ready to send.")
    return 0


def command_report(args: argparse.Namespace) -> int:
    vault = resolve_vault(args.vault)
    draft_path = Path(args.file)
    if not draft_path.is_file():
        raise FileProblem(f"Could not find the report draft at {draft_path}.")
    try:
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise FileProblem(f"Could not read {draft_path} as JSON.")

    payload = validate_draft(draft)
    try:
        auth = load_auth(site_base=args.site_base)
    except AuthError:
        append_receipt(vault, "report", payload, sent=False, reason="AuthError")
        raise

    try:
        response = _request_json(
            "POST",
            get_api_base_url(args.api_base),
            "/api/feedback/report",
            payload,
            bearer=auth["sessionToken"],
        )
    except FeedbackError as error:
        append_receipt(vault, "report", payload, sent=False, reason=type(error).__name__)
        raise

    ticket = str(response.get("ticket") or "")
    received_at = response.get("receivedAt")
    if not TICKET_PATTERN.match(ticket) or not isinstance(received_at, int):
        append_receipt(vault, "report", payload, sent=False, reason="bad_receipt")
        raise BadResponse("Heydex accepted the report but did not return a valid ticket. Try 'status' in a minute.")

    append_receipt(vault, "report", payload, sent=True, reason="sent")
    try:
        write_ticket_file(vault, ticket, payload, received_at)
    except OSError:
        print(
            f"Sent — reference {ticket}. (The local ticket record could not be saved, "
            "so automatic status updates for this ticket may not appear on this machine.)"
        )
        return 0
    print(f"Sent — reference {ticket}. Dex will tell you when there's news.")
    return 0


def command_status(args: argparse.Namespace) -> int:
    vault = resolve_vault(args.vault)
    auth = load_auth(site_base=args.site_base)
    response = _request_json(
        "GET",
        get_api_base_url(args.api_base),
        "/api/feedback/status",
        bearer=auth["sessionToken"],
    )
    reports = response.get("reports")
    if not isinstance(reports, list):
        raise BadResponse("Heydex returned an unexpected status response. Try again in a minute.")

    local = load_ticket_files(vault)
    if not reports:
        print("No feedback reports on file for this account yet.")
        return 0

    print("Your reports:")
    for report in reports:
        ticket = str(report.get("ticket") or "")
        status = str(report.get("status") or "")
        label = STATUS_LABELS.get(status, status.upper() or "UNKNOWN")
        summary = str(report.get("summary") or "").strip().replace("\n", " ")
        if len(summary) > 60:
            summary = summary[:57] + "..."
        extra = ""
        if status == "fixed" and report.get("fixedInVersion"):
            extra = f" in v{report['fixedInVersion']}"
        if status == "needs_info" and report.get("question"):
            extra = " (1 question waiting — run /feedback to answer)"
        print(f"  {ticket}  {summary}  {label}{extra}")
        comment = report.get("comment")
        if comment:
            print(f"          Dave says: {comment}")

        if ticket in local:
            record = local[ticket]
            record["status"] = status
            if isinstance(report.get("statusChangedAt"), int):
                record["status_changed_at"] = report["statusChangedAt"]
            if report.get("question") is not None:
                record["question"] = report["question"]
            if report.get("comment") is not None:
                record["comment"] = report["comment"]
            if report.get("fixedInVersion") is not None:
                record["fixed_in_version"] = report["fixedInVersion"]
            # Seeing the status in person counts as being notified.
            record["last_notified_status_changed_at"] = record.get("status_changed_at")
            try:
                update_ticket_file(vault, record)
            except OSError:
                pass
    return 0


def command_answer(args: argparse.Namespace) -> int:
    vault = resolve_vault(args.vault)
    ticket = args.ticket.strip()
    if not TICKET_PATTERN.match(ticket):
        raise DraftProblem("That does not look like a Dex ticket (expected something like DEX-142).")

    if args.text is not None:
        answer_text = args.text
    elif args.file:
        answer_path = Path(args.file)
        if not answer_path.is_file():
            raise FileProblem(f"Could not find the answer file at {answer_path}.")
        answer_text = answer_path.read_text(encoding="utf-8")
    else:
        raise DraftProblem("Provide the answer with --text or --file.")

    answer_text = answer_text.strip()
    if not answer_text:
        raise DraftProblem("The answer is empty.")
    if len(answer_text) > FIELD_CAPS["answer"]:
        raise DraftProblem(
            f"The answer is too long ({len(answer_text)} characters; the limit is {FIELD_CAPS['answer']})."
        )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "ticket": ticket,
        "captured_at": now_ms(),
        "answer": answer_text,
    }
    try:
        auth = load_auth(site_base=args.site_base)
    except AuthError:
        append_receipt(vault, "answer", payload, sent=False, reason="AuthError")
        raise
    try:
        _request_json(
            "POST",
            get_api_base_url(args.api_base),
            "/api/feedback/answer",
            payload,
            bearer=auth["sessionToken"],
        )
    except FeedbackError as error:
        append_receipt(vault, "answer", payload, sent=False, reason=type(error).__name__)
        raise

    append_receipt(vault, "answer", payload, sent=True, reason="sent")
    local = load_ticket_files(vault)
    if ticket in local:
        record = local[ticket]
        record["status"] = "investigating"
        record.pop("question", None)
        try:
            update_ticket_file(vault, record)
        except OSError:
            pass
    print(f"Answer sent for {ticket}. Thanks — this goes straight to the investigation.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api-base", default=None, help="API base, default %s" % HEYDEX_API_BASE_URL)
    common.add_argument("--site-base", default=None, help="Site base, default %s" % HEYDEX_SITE_BASE_URL)
    common.add_argument("--vault", default=None, help="Vault root, default $VAULT_PATH or the current directory")

    check = subparsers.add_parser("check", parents=[common], help="Preflight: is this terminal linked and ready to send?")
    check.set_defaults(func=command_check)

    link = subparsers.add_parser("link", parents=[common], help="Link this terminal to a heydex account")
    link.add_argument("--code", required=True)
    link.set_defaults(func=command_link)

    report = subparsers.add_parser("report", parents=[common], help="Send an approved report draft")
    report.add_argument("--file", required=True, help="Path to the approved report draft JSON")
    report.set_defaults(func=command_report)

    status = subparsers.add_parser("status", parents=[common], help="Show filed reports and their status")
    status.set_defaults(func=command_status)

    answer = subparsers.add_parser("answer", parents=[common], help="Answer a question on a ticket")
    answer.add_argument("--ticket", required=True)
    answer.add_argument("--text", default=None)
    answer.add_argument("--file", default=None)
    answer.set_defaults(func=command_answer)

    return parser


def main(argv: "list[str] | None" = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except AuthError as error:
        print(f"CONNECTION NEEDED: {error.user_message}")
        return error.exit_code
    except CertificateError as error:
        print(f"CERTIFICATE ERROR: {error.user_message}")
        return error.exit_code
    except NetworkError as error:
        print(f"NETWORK ERROR: {error.user_message}")
        return error.exit_code
    except DraftProblem as error:
        print(f"REPORT PROBLEM: {error.user_message}")
        return error.exit_code
    except FileProblem as error:
        print(f"FILE PROBLEM: {error.user_message}")
        return error.exit_code
    except BadResponse as error:
        print(f"BAD RESPONSE: {error.user_message}")
        return error.exit_code
    except FeedbackError as error:
        print(f"PROBLEM: {error.user_message}")
        return error.exit_code


if __name__ == "__main__":
    sys.exit(main())
