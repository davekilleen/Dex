#!/usr/bin/env python3
"""
Adobe eSign & PDF MCP Server for Dex

Two capability groups in one server:

1. PDF tools (local, no auth) — built on `pypdf`. Read info, extract text,
   merge/split/extract pages, and read/fill AcroForm fields. Useful for
   prepping a document (e.g. a Salesforce quote) before sending it out.

2. Adobe Acrobat Sign tools (OAuth) — send a PDF out for e-signature, check
   status, list agreements, send reminders, cancel, and download the signed
   result. Talks to the Acrobat Sign REST API v6.

Adobe Sign auth uses a standard OAuth 2.0 authorization-code flow (confidential
client — client secret required, no PKCE). Credentials:
- ADOBE_SIGN_CLIENT_ID / ADOBE_SIGN_CLIENT_SECRET: from an Acrobat Sign
  application registered at https://secure.na1.adobesign.com/public/static/appKeys
  (or the equivalent URL for your shard).
- ADOBE_SIGN_SHARD: the data-center shard your Acrobat Sign account lives on
  (na1, na2, na3, eu1, eu2, au1, jp1, in1, ca1 ...). Defaults to "na1".

Tokens are stored at ~/.claude/adobe_sign_tokens.json (outside the repo, never
committed), matching the pattern used by the Salesforce MCP. Run
`adobe_sign_authenticate` once to connect; every other Adobe Sign tool
refreshes the access token automatically.

PDF tools:
- pdf_get_info: page count, encryption, metadata, form-field presence
- pdf_extract_text: extract text (optionally a page range)
- pdf_merge: merge multiple PDFs into one
- pdf_split: split a PDF into one file per page
- pdf_extract_pages: pull a page range/subset into a new file
- pdf_get_form_fields: list AcroForm fields, types, and current values
- pdf_fill_form: fill AcroForm fields and save (optionally flatten)

Adobe Sign tools:
- adobe_sign_authenticate: run the OAuth flow and store tokens
- adobe_sign_check_connection: verify the connection is alive
- adobe_sign_send_for_signature: upload a PDF and send it for e-signature
- adobe_sign_get_status: get an agreement's status and per-signer progress
- adobe_sign_list_agreements: list recent agreements
- adobe_sign_send_reminder: nudge signers who haven't completed yet
- adobe_sign_cancel_agreement: cancel/void an agreement
- adobe_sign_download_signed_document: download the completed PDF
"""

import json
import logging
import os
import secrets
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

try:
    from pypdf import PdfReader, PdfWriter
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

# ============================================================================
# CONFIGURATION
# ============================================================================

VAULT_PATH = Path(os.environ.get("VAULT_PATH", Path.cwd()))

ADOBE_SIGN_CLIENT_ID = os.environ.get("ADOBE_SIGN_CLIENT_ID", "")
ADOBE_SIGN_CLIENT_SECRET = os.environ.get("ADOBE_SIGN_CLIENT_SECRET", "")
ADOBE_SIGN_SHARD = os.environ.get("ADOBE_SIGN_SHARD", "na1").strip() or "na1"
REDIRECT_URI = "http://localhost:8722/callback"
SCOPES = "user_login:self agreement_read:account agreement_write:account agreement_send:account"

AUTHORIZE_URL = f"https://secure.{ADOBE_SIGN_SHARD}.adobesign.com/public/oauth/v2"
TOKEN_URL = f"https://api.{ADOBE_SIGN_SHARD}.adobesign.com/oauth/v2/token"
REFRESH_URL = f"https://api.{ADOBE_SIGN_SHARD}.adobesign.com/oauth/v2/refresh"

TOKEN_FILE = Path.home() / ".claude" / "adobe_sign_tokens.json"

NOT_CONNECTED_MESSAGE = (
    "Adobe Sign not connected — run /adobe-esign-setup to register an "
    "Acrobat Sign app and authenticate."
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def _resolve_path(path_str: str) -> Path:
    """Resolve a user-supplied path against VAULT_PATH unless it's absolute."""
    p = Path(path_str).expanduser()
    if p.is_absolute():
        return p
    return (VAULT_PATH / p).resolve()


# ============================================================================
# PDF TOOLS (local — pypdf, no auth)
# ============================================================================


def _pdf_not_available_error() -> Dict[str, Any]:
    return {
        "success": False,
        "error": "pypdf is not installed. Run: pip install -r core/mcp/requirements.txt",
    }


def _parse_page_range(spec: Optional[str], num_pages: int) -> List[int]:
    """Parse a page spec like '1-3,5,8-10' (1-indexed, inclusive) into 0-indexed ints."""
    if not spec:
        return list(range(num_pages))
    pages: List[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            start_s, end_s = chunk.split("-", 1)
            start, end = int(start_s), int(end_s)
        else:
            start = end = int(chunk)
        for p in range(start, end + 1):
            if 1 <= p <= num_pages:
                pages.append(p - 1)
    return pages


def pdf_get_info(file_path: str) -> Dict[str, Any]:
    path = _resolve_path(file_path)
    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}
    reader = PdfReader(str(path))
    fields = reader.get_fields() or {}
    meta = reader.metadata or {}
    return {
        "success": True,
        "file": str(path),
        "pages": len(reader.pages),
        "encrypted": reader.is_encrypted,
        "has_form_fields": bool(fields),
        "form_field_count": len(fields),
        "title": meta.get("/Title"),
        "author": meta.get("/Author"),
        "creator": meta.get("/Creator"),
        "size_bytes": path.stat().st_size,
    }


def pdf_extract_text(file_path: str, page_range: Optional[str] = None) -> Dict[str, Any]:
    path = _resolve_path(file_path)
    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}
    reader = PdfReader(str(path))
    indices = _parse_page_range(page_range, len(reader.pages))
    pages_text = []
    for i in indices:
        pages_text.append({"page": i + 1, "text": reader.pages[i].extract_text() or ""})
    return {
        "success": True,
        "file": str(path),
        "pages_extracted": len(pages_text),
        "pages": pages_text,
    }


def pdf_merge(file_paths: List[str], output_path: str) -> Dict[str, Any]:
    resolved = [_resolve_path(p) for p in file_paths]
    missing = [str(p) for p in resolved if not p.exists()]
    if missing:
        return {"success": False, "error": f"File(s) not found: {', '.join(missing)}"}

    writer = PdfWriter()
    for p in resolved:
        writer.append(str(p))

    out_path = _resolve_path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        writer.write(f)

    return {
        "success": True,
        "output_file": str(out_path),
        "source_files": [str(p) for p in resolved],
        "total_pages": len(writer.pages),
    }


def pdf_split(file_path: str, output_dir: str) -> Dict[str, Any]:
    path = _resolve_path(file_path)
    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    reader = PdfReader(str(path))
    out_dir = _resolve_path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = path.stem
    outputs = []
    for i, page in enumerate(reader.pages):
        writer = PdfWriter()
        writer.add_page(page)
        out_file = out_dir / f"{stem}-p{i + 1:03d}.pdf"
        with open(out_file, "wb") as f:
            writer.write(f)
        outputs.append(str(out_file))

    return {
        "success": True,
        "source_file": str(path),
        "output_dir": str(out_dir),
        "files_created": outputs,
        "page_count": len(outputs),
    }


def pdf_extract_pages(file_path: str, pages: str, output_path: str) -> Dict[str, Any]:
    path = _resolve_path(file_path)
    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    reader = PdfReader(str(path))
    indices = _parse_page_range(pages, len(reader.pages))
    if not indices:
        return {"success": False, "error": f"No valid pages matched spec: {pages}"}

    writer = PdfWriter()
    for i in indices:
        writer.add_page(reader.pages[i])

    out_path = _resolve_path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        writer.write(f)

    return {
        "success": True,
        "output_file": str(out_path),
        "pages_extracted": [i + 1 for i in indices],
    }


def pdf_get_form_fields(file_path: str) -> Dict[str, Any]:
    path = _resolve_path(file_path)
    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    reader = PdfReader(str(path))
    fields = reader.get_fields() or {}
    field_list = []
    for name, field in fields.items():
        field_list.append({
            "name": name,
            "type": str(field.get("/FT", "")),
            "value": field.get("/V"),
            "required": bool(int(field.get("/Ff", 0) or 0) & 2),
        })

    return {
        "success": True,
        "file": str(path),
        "field_count": len(field_list),
        "fields": field_list,
    }


def pdf_fill_form(
    file_path: str, fields: Dict[str, Any], output_path: str, flatten: bool = False
) -> Dict[str, Any]:
    path = _resolve_path(file_path)
    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    reader = PdfReader(str(path))
    available = reader.get_fields() or {}
    if not available:
        return {"success": False, "error": "This PDF has no fillable AcroForm fields."}
    unknown = [k for k in fields if k not in available]

    writer = PdfWriter()
    writer.append(reader)
    for page in writer.pages:
        writer.update_page_form_field_values(page, fields, auto_regenerate=False)

    flattened = False
    if flatten and hasattr(writer, "flatten"):
        writer.flatten()
        flattened = True

    out_path = _resolve_path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        writer.write(f)

    result = {
        "success": True,
        "output_file": str(out_path),
        "fields_set": [k for k in fields if k not in unknown],
        "flattened": flattened,
    }
    if flatten and not flattened:
        result["warning"] = "This pypdf version doesn't support flatten(); form fields remain editable."
    if unknown:
        result.setdefault("warning", "")
        result["warning"] = (result["warning"] + " " if result["warning"] else "") + \
            f"Field(s) not found in form, skipped: {', '.join(unknown)}"
    return result


# ============================================================================
# ADOBE SIGN — TOKEN STORAGE & OAUTH
# ============================================================================


def _load_tokens() -> Optional[Dict[str, Any]]:
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text())
        except Exception:
            return None
    return None


def _save_tokens(tokens: Dict[str, Any]) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except Exception:
        pass


def _refresh_access_token(tokens: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        resp = requests.post(
            REFRESH_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": ADOBE_SIGN_CLIENT_ID,
                "client_secret": ADOBE_SIGN_CLIENT_SECRET,
            },
            timeout=15,
        )
        resp.raise_for_status()
        refreshed = resp.json()
        tokens["access_token"] = refreshed["access_token"]
        if refreshed.get("api_access_point"):
            tokens["api_access_point"] = refreshed["api_access_point"]
        _save_tokens(tokens)
        return tokens
    except Exception as e:
        logger.warning(f"Adobe Sign token refresh failed: {e}")
        return None


def _get_valid_tokens() -> Optional[Dict[str, Any]]:
    tokens = _load_tokens()
    if not tokens:
        return None
    return _refresh_access_token(tokens) or tokens


def _is_configured() -> bool:
    return bool(ADOBE_SIGN_CLIENT_ID and ADOBE_SIGN_CLIENT_SECRET)


_auth_code: Optional[str] = None
_auth_event = threading.Event()


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global _auth_code
        params = parse_qs(urlparse(self.path).query)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if "code" in params:
            _auth_code = params["code"][0]
            self.wfile.write(b"<html><body><h2>Adobe Sign connected! You can close this tab.</h2></body></html>")
        else:
            self.wfile.write(b"<html><body><h2>Auth failed - no code received.</h2></body></html>")
        _auth_event.set()

    def log_message(self, *args):
        pass


def _do_oauth() -> Dict[str, Any]:
    global _auth_code, _auth_event
    if not _is_configured():
        raise RuntimeError(
            "ADOBE_SIGN_CLIENT_ID / ADOBE_SIGN_CLIENT_SECRET are not set. "
            "Run /adobe-esign-setup first."
        )

    _auth_code = None
    _auth_event = threading.Event()
    state = secrets.token_urlsafe(16)

    auth_url = AUTHORIZE_URL + "?" + urlencode({
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "client_id": ADOBE_SIGN_CLIENT_ID,
        "scope": SCOPES,
        "state": state,
    })

    server = HTTPServer(("localhost", 8722), _CallbackHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.daemon = True
    thread.start()

    webbrowser.open(auth_url)

    _auth_event.wait(timeout=180)
    server.server_close()

    if not _auth_code:
        raise RuntimeError("OAuth timed out or was cancelled before a code was received.")

    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": _auth_code,
            "client_id": ADOBE_SIGN_CLIENT_ID,
            "client_secret": ADOBE_SIGN_CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=15,
    )
    resp.raise_for_status()
    tokens = resp.json()
    _save_tokens(tokens)
    return tokens


# ============================================================================
# ADOBE SIGN — REST API v6
# ============================================================================


def _api_base(tokens: Dict[str, Any]) -> str:
    access_point = tokens.get("api_access_point") or f"https://api.{ADOBE_SIGN_SHARD}.adobesign.com/"
    return access_point.rstrip("/") + "/api/rest/v6"


def _auth_headers(tokens: Dict[str, Any]) -> Dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _upload_transient_document(tokens: Dict[str, Any], file_path: Path) -> str:
    url = f"{_api_base(tokens)}/transientDocuments"
    with open(file_path, "rb") as f:
        resp = requests.post(
            url,
            headers=_auth_headers(tokens),
            files={"File": (file_path.name, f, "application/pdf")},
            data={"File-Name": file_path.name, "Mime-Type": "application/pdf"},
            timeout=60,
        )
    resp.raise_for_status()
    return resp.json()["transientDocumentId"]


def _create_agreement(
    tokens: Dict[str, Any],
    transient_document_id: str,
    name: str,
    recipients: List[Dict[str, str]],
    message: Optional[str],
    signing_order: str,
) -> str:
    member_infos = [{"email": r["email"]} for r in recipients]
    if signing_order == "SEQUENTIAL":
        participant_sets = [
            {"memberInfos": [mi], "order": i + 1, "role": "SIGNER"}
            for i, mi in enumerate(member_infos)
        ]
    else:
        participant_sets = [
            {"memberInfos": member_infos, "order": 1, "role": "SIGNER"}
        ]

    payload = {
        "fileInfos": [{"transientDocumentId": transient_document_id}],
        "name": name,
        "participantSetsInfo": participant_sets,
        "signatureType": "ESIGN",
        "state": "IN_PROCESS",
    }
    if message:
        payload["message"] = message

    resp = requests.post(
        f"{_api_base(tokens)}/agreements",
        headers={**_auth_headers(tokens), "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _get_agreement(tokens: Dict[str, Any], agreement_id: str) -> Dict[str, Any]:
    resp = requests.get(
        f"{_api_base(tokens)}/agreements/{agreement_id}",
        headers=_auth_headers(tokens),
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def _get_agreement_members(tokens: Dict[str, Any], agreement_id: str) -> Dict[str, Any]:
    resp = requests.get(
        f"{_api_base(tokens)}/agreements/{agreement_id}/members",
        headers=_auth_headers(tokens),
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def _list_agreements(tokens: Dict[str, Any]) -> List[Dict[str, Any]]:
    resp = requests.get(
        f"{_api_base(tokens)}/agreements",
        headers=_auth_headers(tokens),
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json().get("userAgreementList", [])


def _send_reminder(tokens: Dict[str, Any], agreement_id: str, note: Optional[str]) -> None:
    # Only remind participants who haven't completed their part yet.
    members = _get_agreement_members(tokens, agreement_id)
    pending_ids = []
    for participant_set in members.get("participantSets", []):
        for member in participant_set.get("memberInfos", []):
            if member.get("status") not in ("SIGNED", "COMPLETED", "APPROVED"):
                pid = member.get("id") or participant_set.get("id")
                if pid:
                    pending_ids.append(pid)

    payload: Dict[str, Any] = {"status": "ACTIVE"}
    if pending_ids:
        payload["recipientParticipantIds"] = pending_ids
    if note:
        payload["note"] = note

    resp = requests.post(
        f"{_api_base(tokens)}/agreements/{agreement_id}/reminders",
        headers={**_auth_headers(tokens), "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )
    resp.raise_for_status()


def _cancel_agreement(
    tokens: Dict[str, Any], agreement_id: str, comment: Optional[str], notify_signer: bool
) -> None:
    payload = {
        "state": "CANCELLED",
        "agreementCancellationInfo": {
            "comment": comment or "Cancelled via Dex",
            "notifySigner": notify_signer,
        },
    }
    resp = requests.put(
        f"{_api_base(tokens)}/agreements/{agreement_id}/state",
        headers={**_auth_headers(tokens), "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )
    resp.raise_for_status()


def _download_combined_document(tokens: Dict[str, Any], agreement_id: str) -> bytes:
    resp = requests.get(
        f"{_api_base(tokens)}/agreements/{agreement_id}/combinedDocument",
        headers={**_auth_headers(tokens), "Accept": "application/pdf"},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.content


# ============================================================================
# MCP SERVER
# ============================================================================

app = Server("dex-adobe-mcp")

_PDF_TOOLS = {
    "pdf_get_info",
    "pdf_extract_text",
    "pdf_merge",
    "pdf_split",
    "pdf_extract_pages",
    "pdf_get_form_fields",
    "pdf_fill_form",
}

_ADOBE_SIGN_TOOLS = {
    "adobe_sign_authenticate",
    "adobe_sign_check_connection",
    "adobe_sign_send_for_signature",
    "adobe_sign_get_status",
    "adobe_sign_list_agreements",
    "adobe_sign_send_reminder",
    "adobe_sign_cancel_agreement",
    "adobe_sign_download_signed_document",
}


@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="pdf_get_info",
            description="Get page count, encryption status, metadata, and form-field presence for a PDF",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the PDF (absolute, or relative to the vault)"},
                },
                "required": ["file_path"],
            },
        ),
        types.Tool(
            name="pdf_extract_text",
            description="Extract text from a PDF, optionally limited to a page range (e.g. '1-3,5')",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the PDF"},
                    "page_range": {"type": "string", "description": "Optional page spec like '1-3,5,8-10' (1-indexed). Defaults to all pages."},
                },
                "required": ["file_path"],
            },
        ),
        types.Tool(
            name="pdf_merge",
            description="Merge multiple PDFs (in order) into a single output PDF",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_paths": {"type": "array", "items": {"type": "string"}, "description": "PDFs to merge, in order"},
                    "output_path": {"type": "string", "description": "Where to write the merged PDF"},
                },
                "required": ["file_paths", "output_path"],
            },
        ),
        types.Tool(
            name="pdf_split",
            description="Split a PDF into one file per page",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "PDF to split"},
                    "output_dir": {"type": "string", "description": "Directory to write the single-page PDFs into"},
                },
                "required": ["file_path", "output_dir"],
            },
        ),
        types.Tool(
            name="pdf_extract_pages",
            description="Extract a page range/subset from a PDF into a new file",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Source PDF"},
                    "pages": {"type": "string", "description": "Page spec like '1-3,5' (1-indexed)"},
                    "output_path": {"type": "string", "description": "Where to write the extracted PDF"},
                },
                "required": ["file_path", "pages", "output_path"],
            },
        ),
        types.Tool(
            name="pdf_get_form_fields",
            description="List a PDF's AcroForm fields, types, current values, and whether each is required",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the PDF"},
                },
                "required": ["file_path"],
            },
        ),
        types.Tool(
            name="pdf_fill_form",
            description="Fill AcroForm fields on a PDF and save the result",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Source PDF with a fillable form"},
                    "fields": {"type": "object", "description": "Map of field name -> value to set"},
                    "output_path": {"type": "string", "description": "Where to write the filled PDF"},
                    "flatten": {"type": "boolean", "description": "Flatten form fields into static content (default false)", "default": False},
                },
                "required": ["file_path", "fields", "output_path"],
            },
        ),
        types.Tool(
            name="adobe_sign_authenticate",
            description="Run the Adobe Sign OAuth flow (opens a browser) and store tokens for future calls",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="adobe_sign_check_connection",
            description="Check whether Adobe Sign is connected and reachable",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="adobe_sign_send_for_signature",
            description="Upload a PDF and send it out for e-signature via Adobe Sign",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "PDF to send (absolute, or relative to the vault)"},
                    "agreement_name": {"type": "string", "description": "Name shown to signers, e.g. 'Acme Corp - Q3 Quote'"},
                    "recipients": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "email": {"type": "string"},
                                "name": {"type": "string"},
                            },
                            "required": ["email"],
                        },
                        "description": "Signers, in signing order if sequential",
                    },
                    "message": {"type": "string", "description": "Optional message included in the signature request email"},
                    "signing_order": {"type": "string", "enum": ["PARALLEL", "SEQUENTIAL"], "default": "PARALLEL", "description": "PARALLEL = everyone signs at once, SEQUENTIAL = signers go in order"},
                },
                "required": ["file_path", "agreement_name", "recipients"],
            },
        ),
        types.Tool(
            name="adobe_sign_get_status",
            description="Get an agreement's status and per-signer progress",
            inputSchema={
                "type": "object",
                "properties": {
                    "agreement_id": {"type": "string", "description": "Adobe Sign agreement ID"},
                },
                "required": ["agreement_id"],
            },
        ),
        types.Tool(
            name="adobe_sign_list_agreements",
            description="List recent Adobe Sign agreements and their status",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20, "description": "Maximum agreements to return"},
                },
            },
        ),
        types.Tool(
            name="adobe_sign_send_reminder",
            description="Send a reminder email to signers who haven't completed an agreement yet",
            inputSchema={
                "type": "object",
                "properties": {
                    "agreement_id": {"type": "string", "description": "Adobe Sign agreement ID"},
                    "note": {"type": "string", "description": "Optional note included in the reminder"},
                },
                "required": ["agreement_id"],
            },
        ),
        types.Tool(
            name="adobe_sign_cancel_agreement",
            description="Cancel/void an agreement",
            inputSchema={
                "type": "object",
                "properties": {
                    "agreement_id": {"type": "string", "description": "Adobe Sign agreement ID"},
                    "comment": {"type": "string", "description": "Optional cancellation reason"},
                    "notify_signer": {"type": "boolean", "default": True, "description": "Whether to notify signers of the cancellation"},
                },
                "required": ["agreement_id"],
            },
        ),
        types.Tool(
            name="adobe_sign_download_signed_document",
            description="Download the (combined) signed PDF for an agreement",
            inputSchema={
                "type": "object",
                "properties": {
                    "agreement_id": {"type": "string", "description": "Adobe Sign agreement ID"},
                    "output_path": {"type": "string", "description": "Where to save the downloaded PDF"},
                },
                "required": ["agreement_id", "output_path"],
            },
        ),
    ]


def _err(message: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps({"success": False, "error": message}, indent=2))]


def _ok(payload: Dict[str, Any]) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps(payload, indent=2, cls=DateTimeEncoder))]


def _not_connected() -> list[types.TextContent]:
    return _ok({"success": False, "connected": False, "message": NOT_CONNECTED_MESSAGE})


@app.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    arguments = arguments or {}

    if name not in _PDF_TOOLS and name not in _ADOBE_SIGN_TOOLS:
        return _err(f"Unknown tool: {name}")

    if name in _PDF_TOOLS and not HAS_PYPDF:
        return _ok(_pdf_not_available_error())

    try:
        if name == "pdf_get_info":
            return _ok(pdf_get_info(arguments["file_path"]))

        elif name == "pdf_extract_text":
            return _ok(pdf_extract_text(arguments["file_path"], arguments.get("page_range")))

        elif name == "pdf_merge":
            return _ok(pdf_merge(arguments["file_paths"], arguments["output_path"]))

        elif name == "pdf_split":
            return _ok(pdf_split(arguments["file_path"], arguments["output_dir"]))

        elif name == "pdf_extract_pages":
            return _ok(pdf_extract_pages(arguments["file_path"], arguments["pages"], arguments["output_path"]))

        elif name == "pdf_get_form_fields":
            return _ok(pdf_get_form_fields(arguments["file_path"]))

        elif name == "pdf_fill_form":
            return _ok(pdf_fill_form(
                arguments["file_path"],
                arguments["fields"],
                arguments["output_path"],
                arguments.get("flatten", False),
            ))

        elif name == "adobe_sign_authenticate":
            tokens = _do_oauth()
            return _ok({
                "success": True,
                "connected": True,
                "message": "Adobe Sign connected.",
                "api_access_point": tokens.get("api_access_point"),
            })

        elif name == "adobe_sign_check_connection":
            if not _is_configured():
                return _not_connected()
            tokens = _get_valid_tokens()
            if not tokens:
                return _not_connected()
            try:
                _list_agreements(tokens)
                return _ok({"success": True, "connected": True, "message": "Adobe Sign connected and reachable."})
            except requests.HTTPError as e:
                return _ok({"success": False, "connected": False, "error": str(e)})

        # Everything below requires a live connection.
        elif name in _ADOBE_SIGN_TOOLS:
            if not _is_configured():
                return _not_connected()
            tokens = _get_valid_tokens()
            if not tokens:
                return _not_connected()

            if name == "adobe_sign_send_for_signature":
                path = _resolve_path(arguments["file_path"])
                if not path.exists():
                    return _err(f"File not found: {arguments['file_path']}")
                transient_id = _upload_transient_document(tokens, path)
                agreement_id = _create_agreement(
                    tokens,
                    transient_id,
                    arguments["agreement_name"],
                    arguments["recipients"],
                    arguments.get("message"),
                    arguments.get("signing_order", "PARALLEL"),
                )
                return _ok({
                    "success": True,
                    "agreement_id": agreement_id,
                    "agreement_name": arguments["agreement_name"],
                    "recipients": [r["email"] for r in arguments["recipients"]],
                    "signing_order": arguments.get("signing_order", "PARALLEL"),
                })

            elif name == "adobe_sign_get_status":
                agreement = _get_agreement(tokens, arguments["agreement_id"])
                members = _get_agreement_members(tokens, arguments["agreement_id"])
                signers = []
                for participant_set in members.get("participantSets", []):
                    for member in participant_set.get("memberInfos", []):
                        signers.append({"email": member.get("email"), "status": member.get("status")})
                return _ok({
                    "success": True,
                    "agreement_id": agreement.get("id"),
                    "name": agreement.get("name"),
                    "status": agreement.get("status"),
                    "signers": signers,
                })

            elif name == "adobe_sign_list_agreements":
                limit = arguments.get("limit", 20)
                agreements = _list_agreements(tokens)[:limit]
                return _ok({
                    "success": True,
                    "count": len(agreements),
                    "agreements": [
                        {
                            "id": a.get("id"),
                            "name": a.get("name"),
                            "status": a.get("status"),
                        }
                        for a in agreements
                    ],
                })

            elif name == "adobe_sign_send_reminder":
                _send_reminder(tokens, arguments["agreement_id"], arguments.get("note"))
                return _ok({"success": True, "agreement_id": arguments["agreement_id"], "message": "Reminder sent."})

            elif name == "adobe_sign_cancel_agreement":
                _cancel_agreement(
                    tokens,
                    arguments["agreement_id"],
                    arguments.get("comment"),
                    arguments.get("notify_signer", True),
                )
                return _ok({"success": True, "agreement_id": arguments["agreement_id"], "message": "Agreement cancelled."})

            elif name == "adobe_sign_download_signed_document":
                content = _download_combined_document(tokens, arguments["agreement_id"])
                out_path = _resolve_path(arguments["output_path"])
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(content)
                return _ok({
                    "success": True,
                    "agreement_id": arguments["agreement_id"],
                    "output_file": str(out_path),
                    "size_bytes": len(content),
                })

        return _err(f"Unknown tool: {name}")

    except requests.HTTPError as e:
        body = ""
        try:
            body = e.response.text[:300]
        except Exception:
            pass
        logger.warning(f"Adobe Sign API error on {name}: {e} {body}")
        return _err(f"Adobe Sign API error: {e} {body}".strip())
    except KeyError as e:
        return _err(f"Missing required argument: {e}")
    except Exception as e:
        logger.exception(f"Error handling tool {name}")
        return _err(str(e))


async def _main():
    logger.info("Starting Dex Adobe eSign & PDF MCP Server")
    logger.info(f"pypdf available: {HAS_PYPDF}")
    logger.info(f"Adobe Sign configured: {_is_configured()}")

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="dex-adobe-mcp",
                server_version="1.0.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main():
    import asyncio
    asyncio.run(_main())


if __name__ == "__main__":
    main()
