/**
 * salesforce-mcp — Cloudflare Worker
 * Implements MCP Streamable HTTP Transport (protocol version 2024-11-05)
 * Exposes Salesforce as MCP tools for use in Dex / Claude Code
 *
 * Required Worker Secrets (set via `wrangler secret put`):
 *   MCP_SECRET          – Bearer token Dex uses to authenticate
 *   SF_CLIENT_ID        – Salesforce Connected App client ID
 *   SF_CLIENT_SECRET    – Salesforce Connected App client secret
 *   SF_USERNAME         – Only needed if client_credentials grant not enabled
 *   SF_PASSWORD         – Only needed if client_credentials grant not enabled
 *   SF_SECURITY_TOKEN   – Only needed if client_credentials grant not enabled
 */

const OWNER_ID = "0055Y00000GU69oQAD";

// ─── Tool Definitions ────────────────────────────────────────────────────────

const TOOLS = [
  {
    name: "search_accounts",
    description: "Search Salesforce accounts by name or keyword. Returns Id, Name, Phone, city, type.",
    inputSchema: {
      type: "object",
      properties: {
        query:  { type: "string",  description: "Account name or keyword" },
        limit:  { type: "number",  description: "Max results (default 10)" }
      },
      required: ["query"]
    }
  },
  {
    name: "search_contacts",
    description: "Search Salesforce contacts by name or email.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string", description: "Contact name or email" },
        limit: { type: "number", description: "Max results (default 10)" }
      },
      required: ["query"]
    }
  },
  {
    name: "get_opportunities",
    description: "List open opportunities. Optional filters by account name or stage.",
    inputSchema: {
      type: "object",
      properties: {
        account_name: { type: "string", description: "Filter by account name (partial match)" },
        stage:        { type: "string", description: "Filter by stage name (partial match)" },
        limit:        { type: "number", description: "Max results (default 20)" }
      }
    }
  },
  {
    name: "get_account_contacts",
    description: "Get all contacts belonging to a specific account ID.",
    inputSchema: {
      type: "object",
      properties: {
        account_id: { type: "string", description: "Salesforce Account ID (18-char)" }
      },
      required: ["account_id"]
    }
  },
  {
    name: "get_account_details",
    description: "Get full account record plus last 10 activity notes.",
    inputSchema: {
      type: "object",
      properties: {
        account_id: { type: "string", description: "Salesforce Account ID (18-char)" }
      },
      required: ["account_id"]
    }
  },
  {
    name: "update_opportunity_stage",
    description: "Update the stage and optionally close date or amount on an Opportunity.",
    inputSchema: {
      type: "object",
      properties: {
        opportunity_id: { type: "string", description: "Salesforce Opportunity ID (18-char)" },
        stage:          { type: "string", description: "New stage name (e.g. 'Proposal/Price Quote', 'Closed Won')" },
        close_date:     { type: "string", description: "New close date in YYYY-MM-DD format (optional)" },
        amount:         { type: "number", description: "New opportunity amount (optional)" },
        description:    { type: "string", description: "Notes to append to the opportunity description (optional)" }
      },
      required: ["opportunity_id", "stage"]
    }
  },
  {
    name: "create_contact",
    description: "Create a new Contact in Salesforce, optionally linked to an Account.",
    inputSchema: {
      type: "object",
      properties: {
        first_name:  { type: "string", description: "Contact first name" },
        last_name:   { type: "string", description: "Contact last name" },
        email:       { type: "string", description: "Email address" },
        phone:       { type: "string", description: "Phone number (optional)" },
        title:       { type: "string", description: "Job title (optional)" },
        account_id:  { type: "string", description: "Salesforce Account ID to link to (optional)" }
      },
      required: ["first_name", "last_name"]
    }
  },
  {
    name: "log_activity",
    description: "Log a completed call or meeting note to an Account or Opportunity.",
    inputSchema: {
      type: "object",
      properties: {
        what_id:     { type: "string", description: "Account or Opportunity ID to attach to" },
        subject:     { type: "string", description: "Activity subject line" },
        description: { type: "string", description: "Call / meeting notes" },
        type:        { type: "string", enum: ["Call","Meeting","Email","Other"], description: "Activity type (default: Call)" }
      },
      required: ["what_id", "subject", "description"]
    }
  },
  {
    name: "get_opportunity",
    description: "Get full details for a single opportunity including contacts, quotes, and recent activity. Pass name (partial) or id (exact).",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Opportunity name (partial match)" },
        id:   { type: "string", description: "Exact Salesforce Opportunity Id (18-char)" }
      }
    }
  },
  {
    name: "get_quotes",
    description: "Get quotes for an opportunity, including attached document metadata (content_version_id, title, file type).",
    inputSchema: {
      type: "object",
      properties: {
        opportunity_id:   { type: "string", description: "Opportunity Id (exact, preferred)" },
        opportunity_name: { type: "string", description: "Opportunity name (partial match)" }
      }
    }
  },
  {
    name: "download_quote_file",
    description: "Download a quote document from Salesforce by ContentVersionId. Returns base64-encoded file content and metadata.",
    inputSchema: {
      type: "object",
      properties: {
        content_version_id: { type: "string", description: "ContentVersion Id to download" }
      },
      required: ["content_version_id"]
    }
  },
  {
    name: "get_account_assets",
    description: "Get all equipment (assets) on record for a specific account. Returns machine type, model, builder, install date, lease end date, UCC data, and expiry urgency.",
    inputSchema: {
      type: "object",
      properties: {
        account_id:          { type: "string", description: "Salesforce Account Id (exact, preferred)" },
        account_name:        { type: "string", description: "Account name (partial match)" },
        include_competitor:  { type: "boolean", description: "Include competitor equipment (default true)" }
      }
    }
  },
  {
    name: "get_assets_expiring_soon",
    description: "Get all assets whose lease/financing end date falls within the next N months. Returns urgency ratings: CRITICAL (0-90d), HIGH (90-180d), MEDIUM (180-365d).",
    inputSchema: {
      type: "object",
      properties: {
        months: { type: "number", description: "Look-ahead window in months (default 12)" }
      }
    }
  },
  {
    name: "search_assets",
    description: "Search assets across all accounts by machine type, builder, sale/lease status, or other criteria.",
    inputSchema: {
      type: "object",
      properties: {
        machine_type:    { type: "string", description: "Machine type keyword (e.g. 'laser', 'press brake', 'VMC')" },
        builder:         { type: "string", description: "Manufacturer/builder name (e.g. 'Trumpf', 'Amada')" },
        account_name:    { type: "string", description: "Filter to specific account (partial match)" },
        competitor_only: { type: "boolean", description: "Return only competitor equipment" },
        sale_or_lease:   { type: "string", description: "Filter by Sale or Lease picklist value" },
        status:          { type: "string", description: "Asset status filter" },
        limit:           { type: "number", description: "Max results (default 100)" }
      }
    }
  },
  {
    name: "get_competitor_assets",
    description: "Get all competitor equipment tracked across accounts, grouped by brand. Use to find displacement opportunities.",
    inputSchema: {
      type: "object",
      properties: {
        account_name: { type: "string", description: "Filter to specific account (optional)" },
        machine_type: { type: "string", description: "Filter by machine type (optional)" }
      }
    }
  },
  {
    name: "update_asset",
    description: "Update fields on a Salesforce Asset record — follow-up date, status, notes, or corrected usage end date.",
    inputSchema: {
      type: "object",
      properties: {
        asset_id:       { type: "string", description: "Salesforce Asset Id (exact)" },
        follow_up_date: { type: "string", description: "Follow-up date in YYYY-MM-DD format" },
        status:         { type: "string", description: "New asset status" },
        description:    { type: "string", description: "Notes or description to set on the asset" },
        usage_end_date: { type: "string", description: "Corrected usage/lease end date in YYYY-MM-DD" }
      },
      required: ["asset_id"]
    }
  },
  {
    name: "get_new_assets",
    description: "Get assets added to Salesforce in the last N days. Use for monthly new-asset reports and pipeline prospecting.",
    inputSchema: {
      type: "object",
      properties: {
        days:               { type: "number", description: "Look-back window in days (default 30)" },
        include_competitor: { type: "boolean", description: "Include competitor equipment (default true)" }
      }
    }
  },
  {
    name: "get_open_tasks",
    description: "Get open (not completed) tasks assigned to you in Salesforce.",
    inputSchema: {
      type: "object",
      properties: {
        limit:      { type: "number", description: "Max results (default 50)" },
        due_before: { type: "string", description: "Only tasks due before this date (YYYY-MM-DD)" }
      }
    }
  },
  {
    name: "get_completed_tasks",
    description: "Get completed tasks within a date range. Use to review activity history.",
    inputSchema: {
      type: "object",
      properties: {
        date_from:       { type: "string", description: "Start date YYYY-MM-DD (default 365 days ago)" },
        date_to:         { type: "string", description: "End date YYYY-MM-DD (default today)" },
        limit:           { type: "number", description: "Max results (default 50)" },
        has_description: { type: "boolean", description: "Only return tasks with non-empty notes (default false)" }
      }
    }
  },
  {
    name: "get_recent_activity",
    description: "Get recent tasks and events logged in Salesforce.",
    inputSchema: {
      type: "object",
      properties: {
        days_back: { type: "number", description: "How many days back to look (default 7)" },
        limit:     { type: "number", description: "Max results (default 20)" }
      }
    }
  },
  {
    name: "update_opportunity_notes",
    description: "Update the Next Steps and/or Description fields on a Salesforce opportunity.",
    inputSchema: {
      type: "object",
      properties: {
        opportunity_id: { type: "string", description: "Salesforce Opportunity Id (exact)" },
        next_step:      { type: "string", description: "Next steps text to set" },
        description:    { type: "string", description: "Description/notes to set" }
      },
      required: ["opportunity_id"]
    }
  }
];

// ─── Main Fetch Handler ──────────────────────────────────────────────────────

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors() });
    }

    if (url.pathname === "/health") {
      return json({ status: "ok", server: "salesforce-mcp", version: "1.0.0" });
    }

    // All other routes require Bearer auth
    const auth = request.headers.get("Authorization") || "";
    if (!env.MCP_SECRET || auth !== `Bearer ${env.MCP_SECRET}`) {
      return json({ error: "Unauthorized" }, 401);
    }

    if (url.pathname === "/mcp" && request.method === "POST") {
      return handleMCP(request, env);
    }

    return json({ error: "Not found", path: url.pathname }, 404);
  }
};

// ─── MCP Protocol Handler ────────────────────────────────────────────────────

async function handleMCP(request, env) {
  let body;
  try { body = await request.json(); }
  catch { return mcpError(null, -32700, "Parse error"); }

  const { jsonrpc, id, method, params } = body;
  if (jsonrpc !== "2.0") return mcpError(id, -32600, "Invalid Request");

  switch (method) {
    case "initialize":
      return mcpResult(id, {
        protocolVersion: "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: "salesforce-mcp", version: "1.0.0" }
      });

    case "notifications/initialized":
      return new Response(null, { status: 204 });

    case "tools/list":
      return mcpResult(id, { tools: TOOLS });

    case "tools/call": {
      const { name, arguments: args } = params || {};
      try {
        const { token, instance } = await getSFToken(env);
        const result = await callTool(name, args || {}, token, instance);
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

// ─── Salesforce Auth ─────────────────────────────────────────────────────────

async function getSFToken(env) {
  // Try client_credentials first (Connected App OAuth), fall back to SOAP password grant
  if (env.SF_CLIENT_ID && env.SF_CLIENT_SECRET) {
    const params = new URLSearchParams({
      grant_type:    "client_credentials",
      client_id:     env.SF_CLIENT_ID,
      client_secret: env.SF_CLIENT_SECRET
    });
    const res  = await fetch("https://login.salesforce.com/services/oauth2/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body:    params.toString()
    });
    const data = await res.json();
    if (data.access_token) {
      return { token: data.access_token, instance: data.instance_url };
    }
    // Fall through to SOAP if client_credentials not enabled on the Connected App
  }

  if (!env.SF_USERNAME || !env.SF_PASSWORD || !env.SF_SECURITY_TOKEN) {
    throw new Error("Set SF_CLIENT_ID+SF_CLIENT_SECRET (OAuth) or SF_USERNAME+SF_PASSWORD+SF_SECURITY_TOKEN (SOAP) via wrangler secret put.");
  }

  const soapBody = `<?xml version="1.0" encoding="utf-8"?>
<env:Envelope xmlns:xsd="http://www.w3.org/2001/XMLSchema"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xmlns:env="http://schemas.xmlsoap.org/soap/envelope/">
  <env:Body>
    <n1:login xmlns:n1="urn:partner.soap.sforce.com">
      <n1:username>${env.SF_USERNAME}</n1:username>
      <n1:password>${env.SF_PASSWORD}${env.SF_SECURITY_TOKEN}</n1:password>
    </n1:login>
  </env:Body>
</env:Envelope>`;

  const res = await fetch("https://login.salesforce.com/services/Soap/u/57.0", {
    method: "POST",
    headers: { "Content-Type": "text/xml", SOAPAction: "login" },
    body: soapBody
  });

  const xml    = await res.text();
  const fault  = xml.match(/<faultstring>([^<]+)<\/faultstring>/);
  if (fault) throw new Error(`SF Auth: ${fault[1]}`);

  const session = xml.match(/<sessionId>([^<]+)<\/sessionId>/);
  const server  = xml.match(/<serverUrl>([^<]+)<\/serverUrl>/);
  if (!session || !server) throw new Error("Could not parse SF login response");

  const instance = server[1].match(/(https:\/\/[^\/]+)/)[1];
  return { token: session[1], instance };
}

// ─── SOQL Helper ─────────────────────────────────────────────────────────────

// Objects that don't use OwnerId scoping (assets belong to accounts, not users)
const NO_OWNER_FILTER = ["FROM ASSET", "FROM QUOTE", "FROM CONTENTDOCUMENTLINK", "FROM OPPORTUNITYCONTACTROLE"];

async function sfQuery(soql, token, instance) {
  // Inject OwnerId filter so we only see Chris's records (skipped for asset/quote objects)
  const upper = soql.toUpperCase();
  const skipOwner = NO_OWNER_FILTER.some(o => upper.includes(o));
  if (!skipOwner && !upper.includes("OWNERID")) {
    if (upper.includes(" WHERE ")) {
      soql = soql.replace(/( WHERE )/i, ` WHERE OwnerId = '${OWNER_ID}' AND `);
    } else {
      const beforeKws = [" ORDER BY ", " LIMIT ", " GROUP BY "];
      let injected = false;
      for (const kw of beforeKws) {
        const idx = upper.indexOf(kw);
        if (idx !== -1) {
          soql = soql.slice(0, idx) + ` WHERE OwnerId = '${OWNER_ID}'` + soql.slice(idx);
          injected = true;
          break;
        }
      }
      if (!injected) soql += ` WHERE OwnerId = '${OWNER_ID}'`;
    }
  }

  const res  = await fetch(`${instance}/services/data/v57.0/query/?q=${encodeURIComponent(soql)}`, {
    headers: { Authorization: `Bearer ${token}`, Accept: "application/json" }
  });
  const data = await res.json();
  if (data.errorCode) throw new Error(data.message || data.errorCode);
  return data.records || [];
}

// ─── Asset Helper ────────────────────────────────────────────────────────────

function parseAsset(r) {
  let days = null, urgency = null;
  if (r.UsageEndDate) {
    const end = new Date(r.UsageEndDate);
    days = Math.round((end - Date.now()) / 86400000);
    urgency = days <= 0 ? "LAPSED" : days <= 90 ? "CRITICAL" : days <= 180 ? "HIGH" : days <= 365 ? "MEDIUM" : "LOW";
  }
  return {
    id:             r.Id,
    name:           r.Name,
    machine_type:   r.Machine_Type_New__c,
    model:          r.ModelName__c,
    builder:        r.Builder__c,
    serial_number:  r.SerialNumber,
    ucc_vendor:     r.UCC_Vendor__c,
    ucc_id:         r.UCCID__c,
    ucc_status:     r.UCC_Status__c,
    new_or_used:    r.UCC_New_or_Used__c,
    sale_or_lease:  r.Sale_or_Lease__c,
    install_date:   r.InstallDate,
    purchase_date:  r.Purchase_Date__c || r.PurchaseDate,
    usage_end_date: r.UsageEndDate,
    days_to_expiry: days,
    urgency,
    status:         r.Status,
    is_competitor:  r.IsCompetitorProduct || false,
    price:          r.Price,
    follow_up_date: r.FollowUpDate__c,
    account:        r.Account?.Name,
    account_id:     r.Account?.Id,
    contact:        r.Contact?.Name,
    opportunity_id: r.Opportunity__c,
    description:    r.Description,
    created_date:   r.CreatedDate,
  };
}

// ─── Tool Implementations ────────────────────────────────────────────────────

async function callTool(name, args, token, instance) {
  const lim = args.limit || 10;

  if (name === "search_accounts") {
    const q = args.query.replace(/'/g, "\\'");
    return sfQuery(
      `SELECT Id, Name, Phone, BillingCity, BillingState, Type, Industry FROM Account WHERE Name LIKE '%${q}%' ORDER BY Name LIMIT ${lim}`,
      token, instance
    );
  }

  if (name === "search_contacts") {
    const q = args.query.replace(/'/g, "\\'");
    return sfQuery(
      `SELECT Id, FirstName, LastName, Title, Email, Phone, Account.Name FROM Contact WHERE Name LIKE '%${q}%' OR Email LIKE '%${q}%' ORDER BY LastName LIMIT ${lim}`,
      token, instance
    );
  }

  if (name === "get_opportunities") {
    let where = `StageName != 'Closed Won' AND StageName != 'Closed Lost'`;
    if (args.account_name) where += ` AND Account.Name LIKE '%${args.account_name.replace(/'/g, "\\'")}%'`;
    if (args.stage)        where += ` AND StageName LIKE '%${args.stage.replace(/'/g, "\\'")}%'`;
    return sfQuery(
      `SELECT Id, Name, StageName, Amount, CloseDate, Account.Name, Description FROM Opportunity WHERE ${where} ORDER BY CloseDate ASC LIMIT ${args.limit || 20}`,
      token, instance
    );
  }

  if (name === "get_account_contacts") {
    return sfQuery(
      `SELECT Id, FirstName, LastName, Title, Email, Phone FROM Contact WHERE AccountId = '${args.account_id}'`,
      token, instance
    );
  }

  if (name === "get_account_details") {
    const [acctRes, activities] = await Promise.all([
      fetch(`${instance}/services/data/v57.0/sobjects/Account/${args.account_id}`, {
        headers: { Authorization: `Bearer ${token}`, Accept: "application/json" }
      }).then(r => r.json()),
      sfQuery(
        `SELECT Id, Subject, ActivityDate, Description, Type FROM Task WHERE WhatId = '${args.account_id}' ORDER BY ActivityDate DESC LIMIT 10`,
        token, instance
      )
    ]);
    if (acctRes.errorCode) throw new Error(acctRes.message);
    return { account: acctRes, recent_activities: activities };
  }

  if (name === "update_opportunity_stage") {
    const body = { StageName: args.stage };
    if (args.close_date)  body.CloseDate   = args.close_date;
    if (args.amount)      body.Amount      = args.amount;
    if (args.description) body.Description = args.description;
    const res = await fetch(`${instance}/services/data/v57.0/sobjects/Opportunity/${args.opportunity_id}`, {
      method: "PATCH",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        Accept: "application/json"
      },
      body: JSON.stringify(body)
    });
    if (res.status === 204) return { success: true, id: args.opportunity_id };
    const data = await res.json();
    if (Array.isArray(data) && data[0]?.errorCode) throw new Error(data[0].message);
    return { success: true, id: args.opportunity_id };
  }

  if (name === "create_contact") {
    const body = {
      FirstName: args.first_name,
      LastName:  args.last_name,
      OwnerId:   OWNER_ID
    };
    if (args.email)      body.Email     = args.email;
    if (args.phone)      body.Phone     = args.phone;
    if (args.title)      body.Title     = args.title;
    if (args.account_id) body.AccountId = args.account_id;
    const res = await fetch(`${instance}/services/data/v57.0/sobjects/Contact`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        Accept: "application/json"
      },
      body: JSON.stringify(body)
    });
    const data = await res.json();
    if (Array.isArray(data) && data[0]?.errorCode) throw new Error(data[0].message);
    return { success: true, id: data.id };
  }

  if (name === "log_activity") {
    const res = await fetch(`${instance}/services/data/v57.0/sobjects/Task`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        Accept: "application/json"
      },
      body: JSON.stringify({
        Subject:     args.subject,
        Description: args.description,
        WhatId:      args.what_id,
        Type:        args.type || "Call",
        Status:      "Completed",
        OwnerId:     OWNER_ID
      })
    });
    const data = await res.json();
    if (Array.isArray(data) && data[0]?.errorCode) throw new Error(data[0].message);
    return { success: true, id: data.id };
  }

  if (name === "get_opportunity") {
    let soql;
    if (args.id) {
      soql = `SELECT Id, Name, StageName, Amount, CloseDate, Probability, Account.Name, Account.Id, Owner.Name, Description, NextStep, LeadSource, Type FROM Opportunity WHERE Id = '${args.id}'`;
    } else if (args.name) {
      const q = args.name.replace(/'/g, "\\'");
      soql = `SELECT Id, Name, StageName, Amount, CloseDate, Probability, Account.Name, Account.Id, Owner.Name, Description, NextStep, LeadSource, Type FROM Opportunity WHERE Name LIKE '%${q}%' LIMIT 5`;
    } else {
      throw new Error("Provide name or id");
    }
    const opps = await sfQuery(soql, token, instance);
    if (!opps.length) throw new Error("No opportunity found");
    const opp = opps[0];
    const [contacts, quotes, tasks] = await Promise.all([
      sfQuery(`SELECT Contact.Name, Contact.Email, Contact.Title, Role, IsPrimary FROM OpportunityContactRole WHERE OpportunityId = '${opp.Id}'`, token, instance),
      sfQuery(`SELECT Id, QuoteNumber, Name, Status, GrandTotal, ExpirationDate FROM Quote WHERE OpportunityId = '${opp.Id}' ORDER BY CreatedDate DESC LIMIT 10`, token, instance),
      sfQuery(`SELECT Subject, Status, ActivityDate, Who.Name FROM Task WHERE WhatId = '${opp.Id}' ORDER BY CreatedDate DESC LIMIT 10`, token, instance),
    ]);
    return { opportunity: opp, contacts, quotes, recent_activity: tasks };
  }

  if (name === "get_quotes") {
    let oppId = args.opportunity_id;
    if (!oppId && args.opportunity_name) {
      const q = args.opportunity_name.replace(/'/g, "\\'");
      const opps = await sfQuery(`SELECT Id FROM Opportunity WHERE Name LIKE '%${q}%' LIMIT 1`, token, instance);
      if (!opps.length) throw new Error(`No opportunity found matching '${args.opportunity_name}'`);
      oppId = opps[0].Id;
    }
    if (!oppId) throw new Error("Provide opportunity_id or opportunity_name");
    const quotes = await sfQuery(
      `SELECT Id, QuoteNumber, Name, Status, GrandTotal, ExpirationDate, Description FROM Quote WHERE OpportunityId = '${oppId}' ORDER BY CreatedDate DESC LIMIT 20`,
      token, instance
    );
    const quotesWithDocs = await Promise.all(quotes.map(async q => {
      const docs = await sfQuery(
        `SELECT ContentDocumentId, ContentDocument.Title, ContentDocument.FileType, ContentDocument.ContentSize, ContentDocument.LatestPublishedVersionId FROM ContentDocumentLink WHERE LinkedEntityId = '${q.Id}'`,
        token, instance
      );
      return {
        ...q,
        documents: docs.map(d => ({
          content_document_id: d.ContentDocumentId,
          title: d.ContentDocument?.Title,
          file_type: d.ContentDocument?.FileType,
          size_bytes: d.ContentDocument?.ContentSize,
          content_version_id: d.ContentDocument?.LatestPublishedVersionId,
        }))
      };
    }));
    return { opportunity_id: oppId, quotes: quotesWithDocs, count: quotesWithDocs.length };
  }

  if (name === "download_quote_file") {
    const res = await fetch(`${instance}/services/data/v57.0/sobjects/ContentVersion/${args.content_version_id}/VersionData`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) throw new Error(`SF returned ${res.status}`);
    const buffer = await res.arrayBuffer();
    const b64 = btoa(String.fromCharCode(...new Uint8Array(buffer)));
    const contentType = res.headers.get("Content-Type") || "application/octet-stream";
    return { success: true, content_version_id: args.content_version_id, content_type: contentType, size_bytes: buffer.byteLength, base64: b64 };
  }

  if (name === "get_account_assets") {
    if (!args.account_id && !args.account_name) throw new Error("Provide account_id or account_name");
    const acctFilter = args.account_id ? `AccountId = '${args.account_id}'` : `Account.Name LIKE '%${args.account_name.replace(/'/g, "\\'")}%'`;
    const compFilter = args.include_competitor === false ? " AND IsCompetitorProduct = false" : "";
    const assets = await sfQuery(
      `SELECT Id, Name, Machine_Type_New__c, ModelName__c, Builder__c, SerialNumber, UCC_Vendor__c, UCCID__c, UCC_Status__c, UCC_New_or_Used__c, Sale_or_Lease__c, InstallDate, Purchase_Date__c, UsageEndDate, Status, IsCompetitorProduct, Price, Warranty_Length__c, FollowUpDate__c, Description, Account.Name, Account.Id, Contact.Name, Opportunity__c FROM Asset WHERE ${acctFilter}${compFilter} ORDER BY InstallDate DESC NULLS LAST LIMIT 200`,
      token, instance
    );
    const parsed = assets.map(parseAsset);
    return { assets: parsed, count: parsed.length, our_equipment_count: parsed.filter(a => !a.is_competitor).length, competitor_equipment_count: parsed.filter(a => a.is_competitor).length };
  }

  if (name === "get_assets_expiring_soon") {
    const months = args.months || 12;
    const futureDate = new Date(Date.now() + months * 30 * 86400000).toISOString().slice(0, 10);
    const assets = await sfQuery(
      `SELECT Id, Name, Machine_Type_New__c, ModelName__c, Builder__c, Sale_or_Lease__c, UsageEndDate, Status, IsCompetitorProduct, Account.Name, Account.Id, FollowUpDate__c FROM Asset WHERE UsageEndDate != null AND UsageEndDate >= TODAY AND UsageEndDate <= ${futureDate} ORDER BY UsageEndDate ASC LIMIT 500`,
      token, instance
    );
    const parsed = assets.map(parseAsset);
    const counts = { CRITICAL: 0, HIGH: 0, MEDIUM: 0 };
    parsed.forEach(a => { if (counts[a.urgency] !== undefined) counts[a.urgency]++; });
    return { assets: parsed, count: parsed.length, summary: { critical_0_90_days: counts.CRITICAL, high_90_180_days: counts.HIGH, medium_180_365_days: counts.MEDIUM }, months_ahead: months };
  }

  if (name === "search_assets") {
    const filters = [];
    if (args.machine_type)   filters.push(`Machine_Type_New__c LIKE '%${args.machine_type.replace(/'/g, "\\'")}%'`);
    if (args.builder)        filters.push(`Builder__c LIKE '%${args.builder.replace(/'/g, "\\'")}%'`);
    if (args.account_name)   filters.push(`Account.Name LIKE '%${args.account_name.replace(/'/g, "\\'")}%'`);
    if (args.competitor_only) filters.push("IsCompetitorProduct = true");
    if (args.sale_or_lease)  filters.push(`Sale_or_Lease__c = '${args.sale_or_lease}'`);
    if (args.status)         filters.push(`Status = '${args.status}'`);
    const where = filters.length ? filters.join(" AND ") : "Id != null";
    const assets = await sfQuery(
      `SELECT Id, Name, Machine_Type_New__c, ModelName__c, Builder__c, SerialNumber, UCC_Vendor__c, Sale_or_Lease__c, InstallDate, Purchase_Date__c, UsageEndDate, Status, IsCompetitorProduct, Price, Account.Name, Account.Id FROM Asset WHERE ${where} ORDER BY Account.Name ASC, InstallDate DESC NULLS LAST LIMIT ${args.limit || 100}`,
      token, instance
    );
    return { assets: assets.map(parseAsset), count: assets.length };
  }

  if (name === "get_competitor_assets") {
    const filters = ["IsCompetitorProduct = true"];
    if (args.account_name) filters.push(`Account.Name LIKE '%${args.account_name.replace(/'/g, "\\'")}%'`);
    if (args.machine_type) filters.push(`Machine_Type_New__c LIKE '%${args.machine_type.replace(/'/g, "\\'")}%'`);
    const assets = await sfQuery(
      `SELECT Id, Name, Machine_Type_New__c, ModelName__c, Builder__c, SerialNumber, UCC_Vendor__c, InstallDate, Purchase_Date__c, UsageEndDate, Status, Account.Name, Account.Id, Description FROM Asset WHERE ${filters.join(" AND ")} ORDER BY Account.Name ASC, InstallDate DESC NULLS LAST LIMIT 200`,
      token, instance
    );
    const parsed = assets.map(parseAsset);
    const byBrand = {};
    parsed.forEach(a => { const k = a.builder || a.ucc_vendor || "Unknown"; byBrand[k] = (byBrand[k] || 0) + 1; });
    return { assets: parsed, count: parsed.length, by_competitor_brand: byBrand };
  }

  if (name === "update_asset") {
    const body = {};
    if (args.follow_up_date)  body.FollowUpDate__c = args.follow_up_date;
    if (args.status)          body.Status          = args.status;
    if (args.description)     body.Description     = args.description;
    if (args.usage_end_date)  body.UsageEndDate    = args.usage_end_date;
    if (!Object.keys(body).length) throw new Error("Provide at least one field to update");
    const res = await fetch(`${instance}/services/data/v57.0/sobjects/Asset/${args.asset_id}`, {
      method: "PATCH",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    if (res.status !== 204) { const d = await res.json(); throw new Error((Array.isArray(d) ? d[0].message : d.message) || "Update failed"); }
    return { success: true, asset_id: args.asset_id, updated_fields: Object.keys(body) };
  }

  if (name === "get_new_assets") {
    const days = args.days || 30;
    const compFilter = args.include_competitor === false ? " AND IsCompetitorProduct = false" : "";
    const assets = await sfQuery(
      `SELECT Id, Name, Machine_Type_New__c, ModelName__c, Builder__c, SerialNumber, UCC_Vendor__c, UCCID__c, UCC_Status__c, Sale_or_Lease__c, InstallDate, Purchase_Date__c, UsageEndDate, Status, IsCompetitorProduct, Price, Account.Name, Account.Id, CreatedDate FROM Asset WHERE CreatedDate >= LAST_N_DAYS:${days}${compFilter} ORDER BY CreatedDate DESC LIMIT 500`,
      token, instance
    );
    const parsed = assets.map(parseAsset);
    return { assets: parsed, count: parsed.length, our_equipment_added: parsed.filter(a => !a.is_competitor).length, competitor_equipment_added: parsed.filter(a => a.is_competitor).length, days_back: days };
  }

  if (name === "get_open_tasks") {
    const dueFilter = args.due_before ? ` AND ActivityDate <= ${args.due_before}` : "";
    const tasks = await sfQuery(
      `SELECT Subject, Status, ActivityDate, Description, Priority, Who.Name, What.Name, What.Id FROM Task WHERE Status != 'Completed' AND IsClosed = false AND OwnerId = '${OWNER_ID}'${dueFilter} ORDER BY ActivityDate ASC NULLS LAST LIMIT ${args.limit || 50}`,
      token, instance
    );
    return { tasks, count: tasks.length };
  }

  if (name === "get_completed_tasks") {
    const today = new Date().toISOString().slice(0, 10);
    const defaultFrom = new Date(Date.now() - 365 * 86400000).toISOString().slice(0, 10);
    const dateFrom = args.date_from || defaultFrom;
    const dateTo   = args.date_to   || today;
    const descFilter = args.has_description ? " AND Description != null" : "";
    const tasks = await sfQuery(
      `SELECT Subject, Status, ActivityDate, Description, Type, Who.Name, What.Name, Owner.Name FROM Task WHERE Status = 'Completed' AND ActivityDate >= ${dateFrom} AND ActivityDate <= ${dateTo} AND OwnerId = '${OWNER_ID}'${descFilter} ORDER BY ActivityDate DESC LIMIT ${args.limit || 50}`,
      token, instance
    );
    return { tasks, count: tasks.length };
  }

  if (name === "get_recent_activity") {
    const tasks = await sfQuery(
      `SELECT Subject, Status, ActivityDate, Description, Who.Name, What.Name, Owner.Name FROM Task WHERE CreatedDate = LAST_N_DAYS:${args.days_back || 7} AND OwnerId = '${OWNER_ID}' ORDER BY CreatedDate DESC LIMIT ${args.limit || 20}`,
      token, instance
    );
    return { tasks, count: tasks.length };
  }

  if (name === "update_opportunity_notes") {
    const body = {};
    if (args.next_step)   body.NextStep    = args.next_step;
    if (args.description) body.Description = args.description;
    if (!Object.keys(body).length) throw new Error("Provide next_step or description");
    const res = await fetch(`${instance}/services/data/v57.0/sobjects/Opportunity/${args.opportunity_id}`, {
      method: "PATCH",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    if (res.status !== 204) { const d = await res.json(); throw new Error((Array.isArray(d) ? d[0].message : d.message) || "Update failed"); }
    return { success: true, opportunity_id: args.opportunity_id, updated_fields: Object.keys(body) };
  }

  throw new Error(`Unknown tool: ${name}`);
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function mcpResult(id, result) {
  return new Response(JSON.stringify({ jsonrpc: "2.0", id, result }), {
    headers: { "Content-Type": "application/json", ...cors() }
  });
}

function mcpError(id, code, message) {
  return new Response(JSON.stringify({ jsonrpc: "2.0", id, error: { code, message } }), {
    status: 400,
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
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization"
  };
}
