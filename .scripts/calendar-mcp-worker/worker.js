/**
 * calendar-mcp — Cloudflare Worker
 * Parses an Outlook ICS URL and exposes calendar data as MCP tools.
 *
 * Required Worker Secrets (set via `wrangler secret put`):
 *   MCP_SECRET        – Bearer token for auth
 *   CALENDAR_ICS_URL  – Full Outlook ICS subscription URL
 */

// ─── Windows → IANA timezone map (Outlook uses Windows names) ────────────────

const WIN_TZ = {
  "Eastern Standard Time":   "America/New_York",
  "Eastern Daylight Time":   "America/New_York",
  "Central Standard Time":   "America/Chicago",
  "Central Daylight Time":   "America/Chicago",
  "Mountain Standard Time":  "America/Denver",
  "Mountain Daylight Time":  "America/Denver",
  "Pacific Standard Time":   "America/Los_Angeles",
  "Pacific Daylight Time":   "America/Los_Angeles",
  "UTC":                     "UTC",
  "GMT Standard Time":       "Europe/London",
  "Greenwich Standard Time": "UTC",
};

// ─── ICS Parser ──────────────────────────────────────────────────────────────

/**
 * Unfold ICS lines (continuation lines start with space or tab per RFC 5545).
 */
function unfoldIcs(text) {
  return text.replace(/\r?\n[ \t]/g, "");
}

/**
 * Parse a property line like:
 *   DTSTART;TZID=Eastern Standard Time:20260624T100000
 *   ATTENDEE;CN=John Smith:mailto:john@example.com
 * Returns { name, params, value }
 */
function parseProp(line) {
  const colonIdx = line.indexOf(":");
  if (colonIdx === -1) return null;
  const head  = line.slice(0, colonIdx);
  const value = line.slice(colonIdx + 1);
  const parts = head.split(";");
  const name  = parts[0].toUpperCase();
  const params = {};
  for (let i = 1; i < parts.length; i++) {
    const eq = parts[i].indexOf("=");
    if (eq !== -1) params[parts[i].slice(0, eq).toUpperCase()] = parts[i].slice(eq + 1);
  }
  return { name, params, value };
}

/**
 * Convert a local datetime string (YYYYMMDDTHHMMSS) + IANA timezone to UTC ms.
 * Uses Intl to get the correct DST-aware offset.
 */
function localToUtcMs(icsLocal, ianaZone) {
  const y  = +icsLocal.slice(0, 4);
  const mo = +icsLocal.slice(4, 6) - 1;
  const d  = +icsLocal.slice(6, 8);
  const h  = icsLocal.length > 8 ? +icsLocal.slice(9, 11) : 0;
  const mi = icsLocal.length > 8 ? +icsLocal.slice(11, 13) : 0;
  const s  = icsLocal.length > 8 ? +icsLocal.slice(13, 15) : 0;

  // Approximate UTC by treating local as UTC first, then apply offset
  const approxMs = Date.UTC(y, mo, d, h, mi, s);
  try {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: ianaZone,
      timeZoneName: "shortOffset"
    }).formatToParts(new Date(approxMs));
    const tzStr = parts.find(p => p.type === "timeZoneName")?.value || "GMT+0";
    const m = tzStr.match(/GMT([+-])(\d+)(?::(\d+))?/);
    if (m) {
      const offsetMin = (m[1] === "+" ? 1 : -1) * (parseInt(m[2]) * 60 + parseInt(m[3] || 0));
      return approxMs - offsetMin * 60000;
    }
  } catch {}
  return approxMs;
}

/**
 * Parse an ICS date/datetime value to a UTC ms timestamp.
 * Handles: DATE (20260624), UTC (20260624T140000Z), local+TZID.
 */
function parseIcsDate(value, tzid) {
  if (!value) return null;
  const v = value.trim();

  // All-day: 20260624
  if (/^\d{8}$/.test(v)) {
    return Date.UTC(+v.slice(0,4), +v.slice(4,6)-1, +v.slice(6,8));
  }

  // UTC: 20260624T140000Z
  if (v.endsWith("Z")) {
    const s = v.replace("Z","");
    return Date.UTC(+s.slice(0,4), +s.slice(4,6)-1, +s.slice(6,8),
                    +s.slice(9,11), +s.slice(11,13), +s.slice(13,15));
  }

  // Local with TZID
  if (tzid) {
    const iana = WIN_TZ[tzid] || tzid;
    return localToUtcMs(v, iana);
  }

  // No TZID — treat as UTC
  return Date.UTC(+v.slice(0,4), +v.slice(4,6)-1, +v.slice(6,8),
                  +v.slice(9,11), +v.slice(11,13), +v.slice(13,15));
}

/** Unescape ICS text values (backslash sequences). */
function unescape(s) {
  return (s || "").replace(/\\n/g, "\n").replace(/\\,/g, ",").replace(/\\;/g, ";").replace(/\\\\/g, "\\");
}

/**
 * Parse all VEVENTs from raw ICS text.
 * Returns array of event objects.
 */
function parseEvents(icsText) {
  const lines = unfoldIcs(icsText).split(/\r?\n/);
  const events = [];
  let current = null;

  for (const line of lines) {
    if (line === "BEGIN:VEVENT") { current = { attendees: [] }; continue; }
    if (line === "END:VEVENT")   { if (current) events.push(current); current = null; continue; }
    if (!current) continue;

    const prop = parseProp(line);
    if (!prop) continue;

    switch (prop.name) {
      case "SUMMARY":
        current.title = unescape(prop.value);
        break;
      case "DTSTART":
        current.startMs = parseIcsDate(prop.value, prop.params.TZID);
        current.allDay  = /^\d{8}$/.test(prop.value.trim());
        break;
      case "DTEND":
        current.endMs = parseIcsDate(prop.value, prop.params.TZID);
        break;
      case "LOCATION":
        current.location = unescape(prop.value);
        break;
      case "DESCRIPTION":
        current.description = unescape(prop.value).slice(0, 500);
        break;
      case "ORGANIZER":
        current.organizer = prop.value.replace(/^mailto:/i, "");
        break;
      case "ATTENDEE": {
        const email = prop.value.replace(/^mailto:/i, "");
        const name  = prop.params.CN || email;
        current.attendees.push({ name, email });
        break;
      }
      case "UID":
        current.uid = prop.value;
        break;
    }
  }

  return events;
}

function eventToOutput(ev) {
  return {
    title:       ev.title       || "No Title",
    start:       ev.startMs != null ? new Date(ev.startMs).toISOString() : null,
    end:         ev.endMs   != null ? new Date(ev.endMs).toISOString()   : null,
    all_day:     ev.allDay  || false,
    location:    ev.location    || "",
    description: ev.description || "",
    organizer:   ev.organizer   || "",
    attendees:   ev.attendees   || [],
  };
}

// ─── Tool Definitions ─────────────────────────────────────────────────────────

const TOOLS = [
  {
    name: "calendar_list_calendars",
    description: "List configured calendars",
    inputSchema: { type: "object", properties: {} }
  },
  {
    name: "calendar_get_today",
    description: "Get today's calendar events",
    inputSchema: {
      type: "object",
      properties: {
        calendar_name: { type: "string", description: "Ignored, for API compatibility" }
      }
    }
  },
  {
    name: "calendar_get_events",
    description: "Get calendar events for a date range",
    inputSchema: {
      type: "object",
      properties: {
        start_date:    { type: "string",  description: "Start date YYYY-MM-DD" },
        end_date:      { type: "string",  description: "End date YYYY-MM-DD" },
        calendar_name: { type: "string",  description: "Ignored, for API compatibility" },
        limit:         { type: "integer", description: "Max events to return (default 50)" }
      }
    }
  },
  {
    name: "calendar_get_next_event",
    description: "Get the next upcoming event",
    inputSchema: {
      type: "object",
      properties: {
        calendar_name: { type: "string", description: "Ignored, for API compatibility" }
      }
    }
  },
  {
    name: "calendar_get_events_with_attendees",
    description: "Get events with full attendee details for a date range",
    inputSchema: {
      type: "object",
      properties: {
        start_date: { type: "string", description: "Start date YYYY-MM-DD" },
        end_date:   { type: "string", description: "End date YYYY-MM-DD" }
      }
    }
  }
];

// ─── Calendar fetch + filter ──────────────────────────────────────────────────

async function fetchEvents(env) {
  const res = await fetch(env.CALENDAR_ICS_URL, {
    headers: { "User-Agent": "calendar-mcp/1.0" }
  });
  if (!res.ok) throw new Error(`ICS fetch failed: ${res.status}`);
  const text = await res.text();
  return parseEvents(text);
}

function eventsInRange(events, startMs, endMs) {
  return events
    .filter(ev => ev.startMs != null && ev.startMs >= startMs && ev.startMs < endMs)
    .sort((a, b) => a.startMs - b.startMs);
}

function dateToMs(dateStr) {
  return new Date(dateStr + "T00:00:00Z").getTime();
}

// ─── Tool dispatch ────────────────────────────────────────────────────────────

async function callTool(name, args, env) {
  const events = await fetchEvents(env);
  const now    = Date.now();

  if (name === "calendar_list_calendars") {
    return { success: true, calendars: ["Work Calendar (Outlook ICS)"], source: "ICS URL" };
  }

  if (name === "calendar_get_today") {
    const todayStart = new Date();
    todayStart.setUTCHours(0, 0, 0, 0);
    const todayEnd = new Date(todayStart.getTime() + 86400000);
    const found = eventsInRange(events, todayStart.getTime(), todayEnd.getTime());
    return {
      success: true,
      date:    new Date().toISOString().slice(0, 10),
      events:  found.map(eventToOutput),
      count:   found.length
    };
  }

  if (name === "calendar_get_events") {
    const start = dateToMs(args.start_date || new Date().toISOString().slice(0, 10));
    const endRaw = args.end_date
      ? dateToMs(args.end_date) + 86400000   // end_date is inclusive
      : start + 86400000;
    const limit  = args.limit || 50;
    const found  = eventsInRange(events, start, endRaw).slice(0, limit);
    return { success: true, events: found.map(eventToOutput), count: found.length };
  }

  if (name === "calendar_get_next_event") {
    const week  = now + 7 * 86400000;
    const found = eventsInRange(events, now, week);
    return { success: true, event: found.length ? eventToOutput(found[0]) : null };
  }

  if (name === "calendar_get_events_with_attendees") {
    const start = dateToMs(args.start_date || new Date().toISOString().slice(0, 10));
    const end   = args.end_date
      ? dateToMs(args.end_date) + 86400000
      : start + 7 * 86400000;
    const found = eventsInRange(events, start, end);
    return { success: true, events: found.map(eventToOutput), count: found.length };
  }

  throw new Error(`Unknown tool: ${name}`);
}

// ─── MCP Protocol Handler ─────────────────────────────────────────────────────

async function handleMCP(request, env) {
  let body;
  try { body = await request.json(); }
  catch { return mcpError(null, -32700, "Parse error"); }

  const { jsonrpc, id, method, params } = body;
  if (jsonrpc !== "2.0") return mcpError(id, -32600, "Invalid Request");

  switch (method) {
    case "initialize":
      return mcpResult(id, {
        protocolVersion: "2025-11-25",
        capabilities: { tools: {} },
        serverInfo: { name: "calendar-mcp", version: "1.0.0" }
      }, { "Mcp-Session-Id": crypto.randomUUID() });

    case "notifications/initialized":
      return new Response(null, { status: 204 });

    case "tools/list":
      return mcpResult(id, { tools: TOOLS });

    case "tools/call": {
      const { name, arguments: args } = params || {};
      try {
        const result = await callTool(name, args || {}, env);
        return mcpResult(id, {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }]
        });
      } catch (e) {
        return mcpResult(id, {
          content: [{ type: "text", text: `Error: ${e.message}` }],
          isError: true
        });
      }
    }

    default:
      return mcpError(id, -32601, `Method not found: ${method}`);
  }
}

// ─── SSE stream for GET /mcp (server-to-client events, stateless keep-alive) ──

function handleMCPStream(sessionId) {
  const { readable, writable } = new TransformStream();
  const writer = writable.getWriter();
  const enc    = new TextEncoder();

  // Send an initial keep-alive comment so the client knows we're alive
  writer.write(enc.encode(": connected\n\n")).then(() => {
    // Leave stream open — CF Worker stays alive until client disconnects
    // For a stateless server we have no server-initiated events to push
  }).catch(() => writer.close());

  return new Response(readable, {
    headers: {
      "Content-Type":                "text/event-stream",
      "Cache-Control":               "no-cache",
      "Connection":                  "keep-alive",
      "Mcp-Session-Id":              sessionId,
      "Access-Control-Expose-Headers": "Mcp-Session-Id",
      ...cors()
    }
  });
}

// ─── Main Fetch Handler ───────────────────────────────────────────────────────

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors() });
    }

    if (url.pathname === "/health") {
      return json({ status: "ok", server: "calendar-mcp", version: "1.0.0" });
    }

    // ── OAuth 2.0 (required for claude.ai web/mobile) ──

    if (url.pathname === "/.well-known/oauth-protected-resource") {
      return json({
        resource:              `https://${url.hostname}`,
        authorization_servers: [`https://${url.hostname}`]
      });
    }

    if (url.pathname === "/.well-known/oauth-authorization-server") {
      return json({
        issuer:                            `https://${url.hostname}`,
        authorization_endpoint:            `https://${url.hostname}/oauth/authorize`,
        token_endpoint:                    `https://${url.hostname}/oauth/token`,
        registration_endpoint:             `https://${url.hostname}/oauth/register`,
        response_types_supported:          ["code"],
        grant_types_supported:             ["authorization_code"],
        code_challenge_methods_supported:  ["S256"]
      });
    }

    if (url.pathname === "/oauth/register" && request.method === "POST") {
      const ct   = request.headers.get("Content-Type") || "";
      const body = ct.includes("application/json")
        ? await request.json()
        : Object.fromEntries(new URLSearchParams(await request.text()));
      return json({
        client_id:                   "mcp-client",
        client_secret:               env.MCP_SECRET,
        redirect_uris:               body.redirect_uris || [],
        grant_types:                 ["authorization_code"],
        response_types:              ["code"],
        token_endpoint_auth_method:  "client_secret_post"
      }, 201);
    }

    if (url.pathname === "/oauth/authorize" && request.method === "GET") {
      const redirectUri = url.searchParams.get("redirect_uri");
      const state       = url.searchParams.get("state");
      if (!redirectUri) return json({ error: "missing redirect_uri" }, 400);
      const dest = new URL(redirectUri);
      dest.searchParams.set("code", env.MCP_SECRET);
      if (state) dest.searchParams.set("state", state);
      return Response.redirect(dest.toString(), 302);
    }

    if (url.pathname === "/oauth/token" && request.method === "POST") {
      const ct   = request.headers.get("Content-Type") || "";
      const body = ct.includes("application/json")
        ? await request.json()
        : Object.fromEntries(new URLSearchParams(await request.text()));
      if (body.grant_type !== "authorization_code") {
        return json({ error: "unsupported_grant_type" }, 400);
      }
      if (!env.MCP_SECRET || body.code !== env.MCP_SECRET) {
        return json({ error: "invalid_grant" }, 400);
      }
      return json({ access_token: env.MCP_SECRET, token_type: "Bearer", expires_in: 31536000 });
    }

    // ── Bearer auth required beyond this point ──

    const auth = request.headers.get("Authorization") || "";
    if (!env.MCP_SECRET || auth !== `Bearer ${env.MCP_SECRET}`) {
      return json({ error: "Unauthorized" }, 401);
    }

    // ── MCP endpoints — root "/" for claude.ai, "/mcp" for Claude Code ──

    if (url.pathname === "/" || url.pathname === "/mcp") {
      if (request.method === "POST") {
        return handleMCP(request, env);
      }
      if (request.method === "GET") {
        const accept = request.headers.get("Accept") || "";
        if (accept.includes("text/event-stream")) {
          return handleMCPStream(crypto.randomUUID());
        }
        return json({ error: "Use POST for MCP requests, or GET with Accept: text/event-stream" }, 405);
      }
    }

    return json({ error: "Not found", path: url.pathname }, 404);
  }
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function mcpResult(id, result, extraHeaders = {}) {
  return new Response(JSON.stringify({ jsonrpc: "2.0", id, result }), {
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Expose-Headers": "Mcp-Session-Id",
      ...cors(),
      ...extraHeaders
    }
  });
}

function mcpError(id, code, message) {
  return new Response(JSON.stringify({ jsonrpc: "2.0", id, error: { code, message } }), {
    status: 200,
    headers: { "Content-Type": "application/json", ...cors() }
  });
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...cors() }
  });
}

function cors() {
  return {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, Mcp-Session-Id"
  };
}
