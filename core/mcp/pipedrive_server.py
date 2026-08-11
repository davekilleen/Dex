#!/usr/bin/env python3
"""
Pipedrive CRM MCP Server for Dex

A thin client over the Pipedrive REST API (v1, personal API token auth).
Dex uses this to get a live view of the user's pipeline and to push
confirmed notes / activities / field updates into the deals they work.

Design:
- Hybrid source of truth: Pipedrive owns the canonical deal NUMBERS
  (stage, value, probability, close date, owner, activities).
  The user's local pipeline tracker note owns STRATEGY + the focus list.
- Reconciliation logic lives in the /pipeline-sync skill, NOT here.
  This server stays a thin, well-behaved API client.
- SAFETY (load-bearing, do not remove): every write tool supports
  dry_run=True so the skill layer can show the exact payload before
  anything hits a shared corporate CRM. The skill layer confirm-gates
  every write on an explicit user yes.
- SAFETY (load-bearing): record creation is opt-in. The create tools
  (pipedrive_create_deal, pipedrive_create_org) are gated behind
  writes.allow_create in System/integrations/pipedrive.yaml and that
  gate defaults to OFF. Many users point Dex at a shared corporate CRM
  where an AI-created deal is a governance problem; enabling creation
  is a deliberate per-user choice. When the gate is off the tools
  return a calm feature-off message, never an error.

Secrets:
- API token resolution order: macOS Keychain (service 'dex-pipedrive',
  account 'api'), then the PIPEDRIVE_API_TOKEN environment variable,
  then a PIPEDRIVE_API_TOKEN=... line in the gitignored vault-root .env
  file. On non-macOS systems the Keychain step is skipped silently.
- Non-secret settings live in System/integrations/pipedrive.yaml
  (template: System/integrations/pipedrive.yaml.example).
- The on/off toggle lives in System/integrations/config.yaml
  (pipedrive.enabled: true; the legacy enabled.pipedrive shape is also
  accepted).
- Nothing secret goes in .mcp.json (it is committed to git).

Graceful degradation: if the integration is not configured or disabled,
tools return the shared Dex feature_status payload ('off' with a
user_message pointing at /pipedrive-setup) rather than crashing.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

_repo_root = str(Path(__file__).parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
from core.utils.feature_status import feature_status

try:
    import yaml
except ImportError:  # pragma: no cover - pyyaml ships with Dex
    yaml = None

try:
    import requests
except ImportError:  # pragma: no cover - requests ships with Dex
    requests = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FEATURE_NAME = "Pipedrive CRM sync"
SERVER_NAME = "dex-pipedrive-mcp"

HTTP_TIMEOUT = 15
NOT_CONNECTED_MESSAGE = (
    "Pipedrive is not connected - run /pipedrive-setup to link your CRM."
)
DISABLED_MESSAGE = (
    "Pipedrive integration is switched off "
    "(System/integrations/config.yaml -> pipedrive.enabled). "
    "Run /pipedrive-setup to enable it."
)
CREATE_DISABLED_MESSAGE = (
    "Deal creation is disabled in your Pipedrive settings; enable "
    "writes.allow_create in System/integrations/pipedrive.yaml if you "
    "want Dex to be able to create records in your CRM."
)

KEYCHAIN_SERVICE = "dex-pipedrive"
KEYCHAIN_ACCOUNT = "api"
TOKEN_ENV_VAR = "PIPEDRIVE_API_TOKEN"

app = Server(SERVER_NAME)


# ---------------------------------------------------------------------------
# Paths (resolved dynamically so tests and long-lived sessions stay correct)
# ---------------------------------------------------------------------------

def _vault_root() -> Path:
    return Path(os.environ.get("VAULT_ROOT") or os.environ.get("VAULT_PATH") or Path.cwd())


def _config_file() -> Path:
    """config.yaml holds the enabled toggle map for all integrations."""
    return _vault_root() / "System" / "integrations" / "config.yaml"


def _settings_file() -> Path:
    """Per-integration non-secret settings (mappings, domain)."""
    return _vault_root() / "System" / "integrations" / "pipedrive.yaml"


def _cache_file() -> Path:
    """Local focus-deal mapping cache (never committed; dotfile)."""
    return _vault_root() / "System" / "integrations" / ".pipedrive-cache.json"


# ---------------------------------------------------------------------------
# Token resolution: Keychain -> environment variable -> vault-root .env
# ---------------------------------------------------------------------------

def _read_keychain() -> Dict[str, Any]:
    """Read the token from the macOS Keychain.

    The stored secret may be either a bare token string or a JSON blob of
    the form {"api_token": "...", "company_domain": "..."}. On systems
    without the `security` binary (anything that is not macOS) this
    returns {} without attempting the call, so the env-var path is used.
    """
    if not shutil.which("security"):
        return {}
    try:
        result = subprocess.run(
            ["security", "find-generic-password",
             "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
            check=False, capture_output=True, text=True, timeout=5,
        )
    except Exception as e:  # noqa: BLE001 - keychain problems must never crash the server
        logger.warning(f"Keychain read failed: {e}")
        return {}
    secret = (result.stdout or "").strip()
    if result.returncode != 0 or not secret:
        return {}
    try:
        parsed = json.loads(secret)
        if isinstance(parsed, dict):
            return parsed
    except ValueError:
        pass
    return {"api_token": secret}


def _read_env_file_token() -> Optional[str]:
    """Parse PIPEDRIVE_API_TOKEN=... from the gitignored vault-root .env."""
    env_path = _vault_root() / ".env"
    if not env_path.exists():
        return None
    try:
        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() != TOKEN_ENV_VAR:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            return value or None
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not read .env file: {e}")
    return None


def _load_token() -> Dict[str, Any]:
    """Resolve credentials in order: Keychain, environment, .env file.

    Returns {} when no source yields a token (the not-configured state).
    """
    keychain = _read_keychain()
    if keychain.get("api_token"):
        return keychain

    env_token = os.environ.get(TOKEN_ENV_VAR)
    if env_token:
        return {"api_token": env_token}

    file_token = _read_env_file_token()
    if file_token:
        return {"api_token": file_token}

    return {}


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _is_enabled() -> bool:
    """Check the integration toggle in System/integrations/config.yaml.

    Canonical shape (matches todoist/trello):  pipedrive: {enabled: true}
    Legacy shape also accepted:                enabled: {pipedrive: true}
    """
    config_file = _config_file()
    if not config_file.exists() or yaml is None:
        return False
    try:
        data = yaml.safe_load(config_file.read_text()) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not read config.yaml: {e}")
        return False
    section = data.get("pipedrive")
    if isinstance(section, dict) and section.get("enabled"):
        return True
    return bool((data.get("enabled", {}) or {}).get("pipedrive", False))


def _load_settings() -> Dict[str, Any]:
    """Read non-secret settings from System/integrations/pipedrive.yaml."""
    settings_file = _settings_file()
    if not settings_file.exists() or yaml is None:
        return {}
    try:
        return yaml.safe_load(settings_file.read_text()) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not read pipedrive.yaml: {e}")
        return {}


def _creates_allowed(config: Dict[str, Any]) -> bool:
    """SAFETY (load-bearing): record creation defaults to OFF.

    Reads writes.allow_create from System/integrations/pipedrive.yaml.
    Anything other than an explicit true keeps creation disabled.
    """
    writes = config.get("writes")
    if isinstance(writes, dict):
        return writes.get("allow_create") is True
    return False


def _resolve() -> Dict[str, Any]:
    """
    Resolve effective Pipedrive settings.

    Returns {"ok": True, api_token, base_url, stage_mapping, owner_mapping,
    config} on success, or {"ok": False, "status": <feature_status payload>}
    when the integration cannot be used.
    """
    if requests is None or yaml is None:
        missing = "requests" if requests is None else "pyyaml"
        return {"ok": False, "status": feature_status(
            FEATURE_NAME, "not_installed",
            f"A required Python package ({missing}) is missing. "
            "Reinstall Dex dependencies: pip install -r requirements.txt",
        )}

    token = _load_token()
    config = _load_settings()

    api_token = token.get("api_token")
    if not api_token:
        # 'off' not 'broken': an unconfigured integration is a healthy state.
        return {"ok": False, "status": feature_status(
            FEATURE_NAME, "off", NOT_CONNECTED_MESSAGE, connected=False,
        )}

    if not _is_enabled():
        return {"ok": False, "status": feature_status(
            FEATURE_NAME, "off", DISABLED_MESSAGE, connected=False,
        )}

    domain = token.get("company_domain") or config.get("company_domain")
    base_url = config.get("base_url")
    if not base_url and domain:
        base_url = f"https://{domain}.pipedrive.com"
    if not base_url:
        return {"ok": False, "status": feature_status(
            FEATURE_NAME, "broken",
            "No base_url / company_domain configured in "
            "System/integrations/pipedrive.yaml. Re-run /pipedrive-setup.",
        )}
    base_url = base_url.rstrip("/")

    return {
        "ok": True,
        "api_token": api_token,
        "base_url": base_url,
        "stage_mapping": config.get("stage_mapping", {}) or {},
        "owner_mapping": config.get("owner_mapping", {}) or {},
        "config": config,
    }


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _request(method: str, path: str, env: Dict[str, Any],
             params: Optional[Dict] = None, body: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Make a Pipedrive API v1 request. Auth via api_token query param
    (the documented method for personal API tokens).
    Returns {"ok": bool, ...} and never raises.
    """
    url = f"{env['base_url']}/api/v1/{path.lstrip('/')}"
    params = dict(params or {})
    params["api_token"] = env["api_token"]
    try:
        resp = requests.request(method, url, params=params, json=body, timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        return {"ok": False, "error": f"Network error calling Pipedrive: {e}"}

    if resp.status_code == 401:
        return {"ok": False, "error": "Pipedrive auth failed (401). Token may be invalid or expired - re-run /pipedrive-setup."}
    if resp.status_code == 403:
        return {"ok": False, "error": "Pipedrive denied the request (403). Your token may lack permission for this action."}
    if resp.status_code == 429:
        return {"ok": False, "error": "Pipedrive rate limit hit (429). Try again in a moment."}

    try:
        payload = resp.json()
    except ValueError:
        return {"ok": False, "error": f"Non-JSON response from Pipedrive (HTTP {resp.status_code})."}

    if not resp.ok or payload.get("success") is False:
        msg = payload.get("error") or payload.get("error_info") or f"HTTP {resp.status_code}"
        return {"ok": False, "error": f"Pipedrive API error: {msg}"}

    return {"ok": True, "data": payload.get("data"), "additional_data": payload.get("additional_data")}


def _text(obj: Any) -> List[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps(obj, indent=2, default=str))]


def _status_response(status_payload: Dict[str, Any]) -> List[types.TextContent]:
    return _text(status_payload)


def _api_error(message: str) -> List[types.TextContent]:
    """A configured integration that fails to reach the API is 'broken'."""
    return _text(feature_status(FEATURE_NAME, "broken", message, error=message))


# ---------------------------------------------------------------------------
# Local mapping cache (focus deal <-> Pipedrive deal id; local file only)
# ---------------------------------------------------------------------------

def _read_cache() -> Dict[str, Any]:
    cache_file = _cache_file()
    if not cache_file.exists():
        return {"deals": {}, "updated_at": None}
    try:
        return json.loads(cache_file.read_text())
    except Exception:  # noqa: BLE001
        return {"deals": {}, "updated_at": None}


def _write_cache(cache: Dict[str, Any]) -> None:
    cache_file = _cache_file()
    cache["updated_at"] = datetime.now().isoformat(timespec="seconds")
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(cache, indent=2))


# ---------------------------------------------------------------------------
# Deal shaping
# ---------------------------------------------------------------------------

def _slim_deal(d: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce a Pipedrive deal object to the fields Dex reconciles on."""
    if not isinstance(d, dict):
        return {}
    org = d.get("org_id")
    org_name = org.get("name") if isinstance(org, dict) else None
    owner = d.get("user_id")
    owner_name = owner.get("name") if isinstance(owner, dict) else None
    return {
        "id": d.get("id"),
        "title": d.get("title"),
        "org_id": org.get("value") if isinstance(org, dict) else org,
        "org_name": org_name,
        "value": d.get("value"),
        "currency": d.get("currency"),
        "stage_id": d.get("stage_id"),
        "status": d.get("status"),
        "probability": d.get("probability"),
        "expected_close_date": d.get("expected_close_date"),
        "owner_id": owner.get("id") if isinstance(owner, dict) else owner,
        "owner_name": owner_name,
        "next_activity_date": d.get("next_activity_date"),
        "last_activity_date": d.get("last_activity_date"),
        "update_time": d.get("update_time"),
    }


# ===========================================================================
# Tool definitions
# ===========================================================================

@app.list_tools()
async def handle_list_tools() -> List[types.Tool]:
    return [
        types.Tool(
            name="pipedrive_status",
            description="Check Pipedrive connectivity and that the API token is valid. Returns the authenticated user on success.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="pipedrive_list_users",
            description="List Pipedrive users (id, name, email). Used to build the owner_mapping during setup.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="pipedrive_list_stages",
            description="List Pipedrive pipelines and their stages (id, name, pipeline). Used to build the stage_mapping during setup.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="pipedrive_find_org",
            description="Search Pipedrive organizations by name. Use to map a Dex company page to a Pipedrive org.",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Organization name to search for"}},
                "required": ["query"],
            },
        ),
        types.Tool(
            name="pipedrive_find_deal",
            description="Search Pipedrive deals by title/term, optionally scoped to an organization. Used for first-run mapping of focus deals.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Deal title or search term"},
                    "org_id": {"type": "integer", "description": "Optional Pipedrive organization id to scope the search"},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="pipedrive_get_deal",
            description="Get full detail for one deal including its notes and open activities.",
            inputSchema={
                "type": "object",
                "properties": {"deal_id": {"type": "integer", "description": "Pipedrive deal id"}},
                "required": ["deal_id"],
            },
        ),
        types.Tool(
            name="pipedrive_list_deals",
            description="List deals for discovery ('what's in Pipedrive I'm not tracking?'). Filter by status/stage/owner.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "open | won | lost | deleted | all_not_deleted (default open)"},
                    "stage_id": {"type": "integer"},
                    "user_id": {"type": "integer", "description": "Filter by owner user id"},
                    "limit": {"type": "integer", "description": "Max deals to return (default 50)"},
                },
            },
        ),
        types.Tool(
            name="pipedrive_get_pipeline_snapshot",
            description="Return slim records for the mapped focus deals (stage/value/probability/close/owner/activity dates). The reconcile workhorse for /pipeline-sync. If deal_ids omitted, uses the saved mapping cache.",
            inputSchema={
                "type": "object",
                "properties": {
                    "deal_ids": {"type": "array", "items": {"type": "integer"}, "description": "Optional explicit list of deal ids. If omitted, reads the saved mapping cache."},
                },
            },
        ),
        types.Tool(
            name="pipedrive_get_mapping",
            description="Read the saved focus-deal mapping cache (Dex key -> Pipedrive deal/org ids).",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="pipedrive_save_mapping",
            description="Persist a confirmed focus-deal mapping to the local cache (does NOT write to Pipedrive). Called by /pipeline-sync after the user confirms a match.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dex_key": {"type": "string", "description": "Stable Dex key for the deal, e.g. 'Acme/Platform Migration' or the company slug"},
                    "deal_id": {"type": "integer"},
                    "org_id": {"type": "integer"},
                    "title": {"type": "string", "description": "Pipedrive deal title (for human reference)"},
                },
                "required": ["dex_key", "deal_id"],
            },
        ),
        types.Tool(
            name="pipedrive_add_deal_note",
            description="Add a note to a deal (e.g. a meeting summary). CONFIRM-GATED: call with dry_run=true first to preview the exact payload, then dry_run=false to send.",
            inputSchema={
                "type": "object",
                "properties": {
                    "deal_id": {"type": "integer"},
                    "content": {"type": "string", "description": "Note content (plain text or simple HTML)"},
                    "dry_run": {"type": "boolean", "description": "If true, return the payload without sending. Default false."},
                },
                "required": ["deal_id", "content"],
            },
        ),
        types.Tool(
            name="pipedrive_add_deal_activity",
            description="Add an activity (task/call/meeting) to a deal - e.g. push a Dex follow-up. CONFIRM-GATED: preview with dry_run=true first. Set done=true when logging a meeting/call that has ALREADY happened (past due_date), otherwise a past-dated activity shows as overdue in the CRM.",
            inputSchema={
                "type": "object",
                "properties": {
                    "deal_id": {"type": "integer"},
                    "subject": {"type": "string"},
                    "due_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "type": {"type": "string", "description": "Activity type key (e.g. task, call, meeting, email). Default 'task'."},
                    "note": {"type": "string", "description": "Optional activity note"},
                    "done": {"type": "boolean", "description": "Mark the activity complete on creation. Use true for already-held meetings/calls (avoids a false 'overdue' on a past due_date); false (default) for a genuinely upcoming/scheduled activity."},
                    "dry_run": {"type": "boolean", "description": "If true, return the payload without sending. Default false."},
                },
                "required": ["deal_id", "subject"],
            },
        ),
        types.Tool(
            name="pipedrive_create_deal",
            description="Create a new deal. OPT-IN + CONFIRM-GATED: only works when writes.allow_create is true in System/integrations/pipedrive.yaml (default off - many CRMs are shared and AI-created deals need a deliberate opt-in). Preview with dry_run=true first, then send. Provide org_id, or org_name to resolve/create the organisation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Deal title"},
                    "org_id": {"type": "integer", "description": "Pipedrive organization id to attach the deal to"},
                    "org_name": {"type": "string", "description": "Organization name (used if org_id is not given; must already exist or be created first with pipedrive_create_org)"},
                    "value": {"type": "number"},
                    "currency": {"type": "string", "description": "e.g. GBP, EUR, USD"},
                    "stage_id": {"type": "integer"},
                    "probability": {"type": "number"},
                    "owner_id": {"type": "integer", "description": "Pipedrive user id to own the deal"},
                    "expected_close_date": {"type": "string", "description": "YYYY-MM-DD"},
                    "dry_run": {"type": "boolean", "description": "If true, return the payload without sending. Default false."},
                },
                "required": ["title"],
            },
        ),
        types.Tool(
            name="pipedrive_create_org",
            description="Create a new organization (deals often need an org that does not exist yet). OPT-IN + CONFIRM-GATED: only works when writes.allow_create is true in System/integrations/pipedrive.yaml (default off). Preview with dry_run=true first.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Organization name"},
                    "dry_run": {"type": "boolean", "description": "If true, return the payload without sending. Default false."},
                },
                "required": ["name"],
            },
        ),
        types.Tool(
            name="pipedrive_update_deal",
            description="Update canonical deal fields (stage_id, value, currency, probability, expected_close_date, user_id). CONFIRM-GATED: preview with dry_run=true first, then send. Only whitelisted fields are accepted.",
            inputSchema={
                "type": "object",
                "properties": {
                    "deal_id": {"type": "integer"},
                    "fields": {
                        "type": "object",
                        "description": "Subset of: stage_id, value, currency, probability, expected_close_date, user_id, status",
                    },
                    "dry_run": {"type": "boolean", "description": "If true, return the payload without sending. Default false."},
                },
                "required": ["deal_id", "fields"],
            },
        ),
    ]


# ===========================================================================
# Tool dispatch
# ===========================================================================

# SAFETY (load-bearing): the only deal fields Dex may ever write. Anything
# outside this whitelist is rejected before a payload is even previewed.
WRITABLE_DEAL_FIELDS = {
    "stage_id", "value", "currency", "probability",
    "expected_close_date", "user_id", "status",
}


@app.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> List[types.TextContent]:
    args = arguments or {}

    # Mapping-cache reads/writes are local files and never need API access.
    if name == "pipedrive_get_mapping":
        return _text(_read_cache())

    if name == "pipedrive_save_mapping":
        cache = _read_cache()
        dex_key = args.get("dex_key")
        if not dex_key or not args.get("deal_id"):
            return _text({"ok": False, "error": "dex_key and deal_id are required"})
        cache.setdefault("deals", {})[dex_key] = {
            "deal_id": args["deal_id"],
            "org_id": args.get("org_id"),
            "title": args.get("title"),
            "mapped_at": datetime.now().isoformat(timespec="seconds"),
        }
        _write_cache(cache)
        return _text({"ok": True, "saved": dex_key, "deals_mapped": len(cache["deals"])})

    # Everything else needs a live, configured connection.
    env = _resolve()
    if not env["ok"]:
        return _status_response(env["status"])

    if name == "pipedrive_status":
        r = _request("GET", "users/me", env)
        if not r["ok"]:
            return _text(feature_status(
                FEATURE_NAME, "broken", r["error"],
                connected=False, error=r["error"],
            ))
        me = r["data"] or {}
        return _text(feature_status(
            FEATURE_NAME, "ok", "Pipedrive connected and reachable.",
            connected=True,
            user={"id": me.get("id"), "name": me.get("name"), "email": me.get("email")},
            company_domain=me.get("company_domain"),
            base_url=env["base_url"],
        ))

    if name == "pipedrive_list_users":
        r = _request("GET", "users", env)
        if not r["ok"]:
            return _api_error(r["error"])
        users = [{"id": u.get("id"), "name": u.get("name"), "email": u.get("email"),
                  "active": u.get("active_flag")} for u in (r["data"] or [])]
        return _text({"ok": True, "users": users})

    if name == "pipedrive_list_stages":
        pipes = _request("GET", "pipelines", env)
        stages = _request("GET", "stages", env)
        if not stages["ok"]:
            return _api_error(stages["error"])
        pipe_names = {p.get("id"): p.get("name") for p in (pipes.get("data") or [])} if pipes["ok"] else {}
        out = [{"id": s.get("id"), "name": s.get("name"),
                "pipeline_id": s.get("pipeline_id"),
                "pipeline_name": pipe_names.get(s.get("pipeline_id")),
                "order_nr": s.get("order_nr")} for s in (stages["data"] or [])]
        return _text({"ok": True, "stages": out})

    if name == "pipedrive_find_org":
        query = args.get("query", "")
        r = _request("GET", "organizations/search", env, params={"term": query, "fields": "name", "limit": 10})
        if not r["ok"]:
            return _api_error(r["error"])
        items = ((r["data"] or {}).get("items") or [])
        orgs = [{"id": i.get("item", {}).get("id"), "name": i.get("item", {}).get("name")} for i in items]
        return _text({"ok": True, "organizations": orgs})

    if name == "pipedrive_find_deal":
        query = args.get("query", "")
        params = {"term": query, "limit": 15}
        if args.get("org_id"):
            params["organization_id"] = args["org_id"]
        r = _request("GET", "deals/search", env, params=params)
        if not r["ok"]:
            return _api_error(r["error"])
        items = ((r["data"] or {}).get("items") or [])
        deals = []
        for i in items:
            it = i.get("item", {})
            deals.append({
                "id": it.get("id"), "title": it.get("title"),
                "status": it.get("status"),
                "value": (it.get("value") or {}).get("amount") if isinstance(it.get("value"), dict) else it.get("value"),
                "org_name": (it.get("organization") or {}).get("name"),
                "stage_name": (it.get("stage") or {}).get("name"),
            })
        return _text({"ok": True, "deals": deals})

    if name == "pipedrive_get_deal":
        deal_id = args.get("deal_id")
        d = _request("GET", f"deals/{deal_id}", env)
        if not d["ok"]:
            return _api_error(d["error"])
        notes = _request("GET", "notes", env, params={"deal_id": deal_id, "limit": 20})
        acts = _request("GET", f"deals/{deal_id}/activities", env, params={"limit": 20})
        deal = _slim_deal(d["data"] or {})
        deal["notes"] = [{"id": n.get("id"), "content": n.get("content"),
                          "add_time": n.get("add_time")} for n in (notes.get("data") or [])] if notes["ok"] else []
        deal["activities"] = [{"id": a.get("id"), "subject": a.get("subject"), "type": a.get("type"),
                               "due_date": a.get("due_date"), "done": a.get("done")}
                              for a in (acts.get("data") or [])] if acts["ok"] else []
        return _text({"ok": True, "deal": deal})

    if name == "pipedrive_list_deals":
        params = {
            "status": args.get("status", "open"),
            "limit": args.get("limit", 50),
        }
        if args.get("stage_id"):
            params["stage_id"] = args["stage_id"]
        if args.get("user_id"):
            params["user_id"] = args["user_id"]
        r = _request("GET", "deals", env, params=params)
        if not r["ok"]:
            return _api_error(r["error"])
        return _text({"ok": True, "deals": [_slim_deal(d) for d in (r["data"] or [])]})

    if name == "pipedrive_get_pipeline_snapshot":
        deal_ids = args.get("deal_ids")
        if not deal_ids:
            cache = _read_cache()
            deal_ids = [v.get("deal_id") for v in cache.get("deals", {}).values() if v.get("deal_id")]
        if not deal_ids:
            return _text({"ok": True, "deals": [], "note": "No mapped focus deals. Run /pipeline-sync to map them first."})
        snapshot, errors = [], []
        for did in deal_ids:
            d = _request("GET", f"deals/{did}", env)
            if d["ok"]:
                snapshot.append(_slim_deal(d["data"] or {}))
            else:
                errors.append({"deal_id": did, "error": d["error"]})
        return _text({"ok": True, "deals": snapshot, "errors": errors,
                      "fetched_at": datetime.now().isoformat(timespec="seconds")})

    if name == "pipedrive_add_deal_note":
        body = {"deal_id": args.get("deal_id"), "content": args.get("content", "")}
        # SAFETY (load-bearing): dry_run returns the exact payload with NO
        # HTTP call, so the skill layer can show it and get an explicit yes.
        if args.get("dry_run"):
            return _text({"dry_run": True, "method": "POST", "endpoint": "notes", "payload": body})
        r = _request("POST", "notes", env, body=body)
        if not r["ok"]:
            return _api_error(r["error"])
        return _text({"ok": True, "note_id": (r["data"] or {}).get("id"), "deal_id": args.get("deal_id")})

    if name == "pipedrive_add_deal_activity":
        body = {
            "deal_id": args.get("deal_id"),
            "subject": args.get("subject"),
            "type": args.get("type", "task"),
            "done": 1 if args.get("done") else 0,
        }
        if args.get("due_date"):
            body["due_date"] = args["due_date"]
        if args.get("note"):
            body["note"] = args["note"]
        # SAFETY (load-bearing): see pipedrive_add_deal_note.
        if args.get("dry_run"):
            return _text({"dry_run": True, "method": "POST", "endpoint": "activities", "payload": body})
        r = _request("POST", "activities", env, body=body)
        if not r["ok"]:
            return _api_error(r["error"])
        return _text({"ok": True, "activity_id": (r["data"] or {}).get("id"), "deal_id": args.get("deal_id")})

    if name == "pipedrive_create_deal":
        # SAFETY (load-bearing): creation is opt-in per user. When the gate
        # is off this is a calm feature-off message, never an error tone.
        if not _creates_allowed(env["config"]):
            return _text(feature_status(FEATURE_NAME, "off", CREATE_DISABLED_MESSAGE))
        body: Dict[str, Any] = {"title": args.get("title")}
        if args.get("org_id"):
            body["org_id"] = args["org_id"]
        elif args.get("org_name"):
            body["org_name"] = args["org_name"]  # resolved below before sending
        for field in ("value", "currency", "stage_id", "probability", "expected_close_date"):
            if args.get(field) is not None:
                body[field] = args[field]
        if args.get("owner_id") is not None:
            body["user_id"] = args["owner_id"]
        # SAFETY (load-bearing): dry_run returns the exact payload with NO
        # HTTP call, so the skill layer can show it and get an explicit yes.
        if args.get("dry_run"):
            return _text({"dry_run": True, "method": "POST", "endpoint": "deals", "payload": body})
        # Resolve org_name -> org_id only at real-send time (search is a read).
        if "org_name" in body and "org_id" not in body:
            org_name = body.pop("org_name")
            found = _request("GET", "organizations/search", env,
                             params={"term": org_name, "fields": "name", "limit": 5})
            items = ((found.get("data") or {}).get("items") or []) if found["ok"] else []
            exact = [i.get("item", {}) for i in items
                     if (i.get("item", {}).get("name") or "").strip().lower() == org_name.strip().lower()]
            if exact:
                body["org_id"] = exact[0].get("id")
            else:
                return _text({"ok": False, "error": (
                    f"No existing organization named '{org_name}'. Create it first "
                    "with pipedrive_create_org (confirm-gated), or pass org_id.")})
        r = _request("POST", "deals", env, body=body)
        if not r["ok"]:
            return _api_error(r["error"])
        return _text({"ok": True, "deal": _slim_deal(r["data"] or {})})

    if name == "pipedrive_create_org":
        # SAFETY (load-bearing): same opt-in gate as pipedrive_create_deal.
        if not _creates_allowed(env["config"]):
            return _text(feature_status(FEATURE_NAME, "off", CREATE_DISABLED_MESSAGE))
        body = {"name": args.get("name")}
        if args.get("dry_run"):
            return _text({"dry_run": True, "method": "POST", "endpoint": "organizations", "payload": body})
        r = _request("POST", "organizations", env, body=body)
        if not r["ok"]:
            return _api_error(r["error"])
        data = r["data"] or {}
        return _text({"ok": True, "org_id": data.get("id"), "name": data.get("name")})

    if name == "pipedrive_update_deal":
        deal_id = args.get("deal_id")
        raw_fields = args.get("fields", {}) or {}
        fields = {k: v for k, v in raw_fields.items() if k in WRITABLE_DEAL_FIELDS}
        rejected = [k for k in raw_fields if k not in WRITABLE_DEAL_FIELDS]
        if not fields:
            return _text({"ok": False, "error": f"No writable fields provided. Allowed: {sorted(WRITABLE_DEAL_FIELDS)}"})
        # SAFETY (load-bearing): see pipedrive_add_deal_note.
        if args.get("dry_run"):
            return _text({"dry_run": True, "method": "PUT", "endpoint": f"deals/{deal_id}",
                          "payload": fields, "rejected_fields": rejected})
        r = _request("PUT", f"deals/{deal_id}", env, body=fields)
        if not r["ok"]:
            return _api_error(r["error"])
        return _text({"ok": True, "deal": _slim_deal(r["data"] or {}), "rejected_fields": rejected})

    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


# ===========================================================================
# Entry point
# ===========================================================================

async def _main():
    logger.info("Starting Pipedrive MCP Server")
    logger.info(f"Vault path: {_vault_root()}")

    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=SERVER_NAME,
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
