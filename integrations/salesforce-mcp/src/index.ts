import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { z } from "zod";

export interface Env {
  SF_LOGIN_URL: string;
  SF_CLIENT_ID: string;
  SF_CLIENT_SECRET: string;
  SF_USERNAME: string;
  SF_PASSWORD_TOKEN: string; // password + security token concatenated
  MCP_SECRET: string;
}

interface SalesforceToken {
  instanceUrl: string;
  accessToken: string;
}

async function getSalesforceToken(env: Env): Promise<SalesforceToken> {
  const params = new URLSearchParams({
    grant_type: "password",
    client_id: env.SF_CLIENT_ID,
    client_secret: env.SF_CLIENT_SECRET,
    username: env.SF_USERNAME,
    password: env.SF_PASSWORD_TOKEN,
  });

  const res = await fetch(`${env.SF_LOGIN_URL}/services/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: params.toString(),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Salesforce auth failed: ${err}`);
  }

  const data = await res.json() as { instance_url: string; access_token: string };
  return { instanceUrl: data.instance_url, accessToken: data.access_token };
}

async function sfQuery(env: Env, soql: string): Promise<any[]> {
  const { instanceUrl, accessToken } = await getSalesforceToken(env);
  const url = `${instanceUrl}/services/data/v59.0/query?q=${encodeURIComponent(soql)}`;

  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Salesforce query failed: ${err}`);
  }

  const data = await res.json() as { records: any[] };
  return data.records ?? [];
}

async function sfPatch(env: Env, path: string, body: Record<string, unknown>): Promise<void> {
  const { instanceUrl, accessToken } = await getSalesforceToken(env);
  const res = await fetch(`${instanceUrl}/services/data/v59.0/${path}`, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Salesforce update failed: ${err}`);
  }
}

async function sfPost(env: Env, path: string, body: Record<string, unknown>): Promise<string> {
  const { instanceUrl, accessToken } = await getSalesforceToken(env);
  const res = await fetch(`${instanceUrl}/services/data/v59.0/${path}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Salesforce create failed: ${err}`);
  }

  const data = await res.json() as { id: string };
  return data.id;
}

function formatContact(r: any): string {
  return [
    `Name: ${r.Name}`,
    r.Title ? `Title: ${r.Title}` : null,
    r.Email ? `Email: ${r.Email}` : null,
    r.Phone ? `Phone: ${r.Phone}` : null,
    r.Account?.Name ? `Account: ${r.Account.Name}` : null,
  ]
    .filter(Boolean)
    .join("\n");
}

function formatAccount(r: any): string {
  return [
    `Name: ${r.Name}`,
    r.Phone ? `Phone: ${r.Phone}` : null,
    r.BillingCity ? `City: ${r.BillingCity}, ${r.BillingState ?? ""}`.trim() : null,
    r.Website ? `Website: ${r.Website}` : null,
    r.Type ? `Type: ${r.Type}` : null,
    r.OwnerId ? `Owner ID: ${r.OwnerId}` : null,
  ]
    .filter(Boolean)
    .join("\n");
}

function createMcpServer(env: Env): McpServer {
  const server = new McpServer({
    name: "salesforce-mcp",
    version: "1.0.0",
  });

  server.tool(
    "search_contacts",
    "Search Salesforce contacts by name or company name",
    { query: z.string().describe("Name or company to search for") },
    async ({ query }) => {
      const safe = query.replace(/'/g, "\\'");
      const soql = `
        SELECT Id, Name, Title, Email, Phone, Account.Name
        FROM Contact
        WHERE Name LIKE '%${safe}%'
           OR Account.Name LIKE '%${safe}%'
        ORDER BY Name
        LIMIT 10
      `;
      const records = await sfQuery(env, soql);
      if (!records.length) return { content: [{ type: "text", text: `No contacts found for "${query}".` }] };
      const text = records.map(formatContact).join("\n---\n");
      return { content: [{ type: "text", text }] };
    }
  );

  server.tool(
    "search_accounts",
    "Search Salesforce accounts by name",
    { query: z.string().describe("Account/company name to search for") },
    async ({ query }) => {
      const safe = query.replace(/'/g, "\\'");
      const soql = `
        SELECT Id, Name, Phone, BillingCity, BillingState, Website, Type
        FROM Account
        WHERE Name LIKE '%${safe}%'
        ORDER BY Name
        LIMIT 10
      `;
      const records = await sfQuery(env, soql);
      if (!records.length) return { content: [{ type: "text", text: `No accounts found for "${query}".` }] };
      const text = records.map(formatAccount).join("\n---\n");
      return { content: [{ type: "text", text }] };
    }
  );

  server.tool(
    "get_account_contacts",
    "Get all contacts associated with a specific account",
    { account_name: z.string().describe("The account/company name") },
    async ({ account_name }) => {
      const safe = account_name.replace(/'/g, "\\'");
      const soql = `
        SELECT Id, Name, Title, Email, Phone
        FROM Contact
        WHERE Account.Name LIKE '%${safe}%'
        ORDER BY Name
        LIMIT 25
      `;
      const records = await sfQuery(env, soql);
      if (!records.length) return { content: [{ type: "text", text: `No contacts found for account "${account_name}".` }] };
      const text = records.map(formatContact).join("\n---\n");
      return { content: [{ type: "text", text }] };
    }
  );

  server.tool(
    "get_opportunities",
    "Get open opportunities for an account",
    { account_name: z.string().describe("The account/company name") },
    async ({ account_name }) => {
      const safe = account_name.replace(/'/g, "\\'");
      const soql = `
        SELECT Id, Name, StageName, Amount, CloseDate, Probability, OwnerId
        FROM Opportunity
        WHERE Account.Name LIKE '%${safe}%'
          AND IsClosed = false
        ORDER BY CloseDate ASC
        LIMIT 10
      `;
      const records = await sfQuery(env, soql);
      if (!records.length) return { content: [{ type: "text", text: `No open opportunities found for "${account_name}".` }] };
      const text = records.map((r: any) =>
        [
          `Name: ${r.Name}`,
          `Stage: ${r.StageName}`,
          r.Amount ? `Amount: $${Number(r.Amount).toLocaleString()}` : null,
          `Close Date: ${r.CloseDate}`,
          r.Probability ? `Probability: ${r.Probability}%` : null,
        ]
          .filter(Boolean)
          .join("\n")
      ).join("\n---\n");
      return { content: [{ type: "text", text }] };
    }
  );

  server.tool(
    "update_opportunity_stage",
    "Update the stage, amount, or close date of an opportunity",
    {
      opportunity_name: z.string().describe("Opportunity name to search for"),
      stage: z.string().optional().describe("New stage name (e.g. Prospecting, Quoting, Negotiation, Closed Won, Closed Lost)"),
      amount: z.number().optional().describe("New amount in dollars"),
      close_date: z.string().optional().describe("New close date in YYYY-MM-DD format"),
      probability: z.number().optional().describe("New probability percentage (0-100)"),
    },
    async ({ opportunity_name, stage, amount, close_date, probability }) => {
      const safe = opportunity_name.replace(/'/g, "\\'");
      const records = await sfQuery(env, `
        SELECT Id, Name, StageName, Amount, CloseDate
        FROM Opportunity
        WHERE Name LIKE '%${safe}%' AND IsClosed = false
        ORDER BY CreatedDate DESC
        LIMIT 5
      `);

      if (!records.length) return { content: [{ type: "text", text: `No open opportunity found matching "${opportunity_name}".` }] };

      if (records.length > 1) {
        const list = records.map((r: any) => `- ${r.Name} (${r.StageName})`).join("\n");
        return { content: [{ type: "text", text: `Found multiple matches — be more specific:\n${list}` }] };
      }

      const opp = records[0];
      const updates: Record<string, unknown> = {};
      if (stage) updates.StageName = stage;
      if (amount !== undefined) updates.Amount = amount;
      if (close_date) updates.CloseDate = close_date;
      if (probability !== undefined) updates.Probability = probability;

      await sfPatch(env, `sobjects/Opportunity/${opp.Id}`, updates);

      const changed = Object.entries(updates)
        .map(([k, v]) => `${k}: ${v}`)
        .join(", ");
      return { content: [{ type: "text", text: `Updated "${opp.Name}": ${changed}` }] };
    }
  );

  server.tool(
    "log_activity",
    "Log a call, email, or meeting activity against a Salesforce contact or opportunity",
    {
      subject: z.string().describe("Subject of the activity (e.g. 'Call with John Wallo')"),
      description: z.string().describe("Notes or summary of what was discussed"),
      type: z.enum(["Call", "Email", "Meeting"]).describe("Type of activity"),
      contact_name: z.string().optional().describe("Contact name to link the activity to"),
      opportunity_name: z.string().optional().describe("Opportunity name to link the activity to"),
      date: z.string().optional().describe("Date of activity in YYYY-MM-DD format, defaults to today"),
    },
    async ({ subject, description, type, contact_name, opportunity_name, date }) => {
      const today = new Date().toISOString().split("T")[0];
      const body: Record<string, unknown> = {
        Subject: subject,
        Description: description,
        Type: type,
        ActivityDate: date ?? today,
        Status: "Completed",
      };

      if (contact_name) {
        const safe = contact_name.replace(/'/g, "\\'");
        const contacts = await sfQuery(env, `SELECT Id FROM Contact WHERE Name LIKE '%${safe}%' LIMIT 1`);
        if (contacts.length) body.WhoId = contacts[0].Id;
      }

      if (opportunity_name) {
        const safe = opportunity_name.replace(/'/g, "\\'");
        const opps = await sfQuery(env, `SELECT Id FROM Opportunity WHERE Name LIKE '%${safe}%' AND IsClosed = false LIMIT 1`);
        if (opps.length) body.WhatId = opps[0].Id;
      }

      const id = await sfPost(env, "sobjects/Task", body);
      return { content: [{ type: "text", text: `Activity logged (ID: ${id}): "${subject}" on ${body.ActivityDate}` }] };
    }
  );

  server.tool(
    "create_contact",
    "Create a new contact in Salesforce",
    {
      first_name: z.string().describe("First name"),
      last_name: z.string().describe("Last name"),
      account_name: z.string().optional().describe("Account/company name to link to"),
      title: z.string().optional().describe("Job title"),
      email: z.string().optional().describe("Email address"),
      phone: z.string().optional().describe("Phone number"),
    },
    async ({ first_name, last_name, account_name, title, email, phone }) => {
      const body: Record<string, unknown> = {
        FirstName: first_name,
        LastName: last_name,
      };
      if (title) body.Title = title;
      if (email) body.Email = email;
      if (phone) body.Phone = phone;

      if (account_name) {
        const safe = account_name.replace(/'/g, "\\'");
        const accounts = await sfQuery(env, `SELECT Id FROM Account WHERE Name LIKE '%${safe}%' LIMIT 1`);
        if (accounts.length) body.AccountId = accounts[0].Id;
        else return { content: [{ type: "text", text: `Account "${account_name}" not found in Salesforce. Create the account first or check the name.` }] };
      }

      const id = await sfPost(env, "sobjects/Contact", body);
      return { content: [{ type: "text", text: `Contact created: ${first_name} ${last_name} (ID: ${id})${account_name ? ` linked to ${account_name}` : ""}` }] };
    }
  );

  server.tool(
    "create_opportunity",
    "Create a new opportunity in Salesforce",
    {
      name: z.string().describe("Opportunity name"),
      account_name: z.string().describe("Account/company name"),
      stage: z.string().describe("Stage name (e.g. Prospecting, Quoting, Negotiation)"),
      close_date: z.string().describe("Expected close date in YYYY-MM-DD format"),
      amount: z.number().optional().describe("Expected amount in dollars"),
    },
    async ({ name, account_name, stage, close_date, amount }) => {
      const safe = account_name.replace(/'/g, "\\'");
      const accounts = await sfQuery(env, `SELECT Id FROM Account WHERE Name LIKE '%${safe}%' LIMIT 1`);
      if (!accounts.length) return { content: [{ type: "text", text: `Account "${account_name}" not found in Salesforce.` }] };

      const body: Record<string, unknown> = {
        Name: name,
        AccountId: accounts[0].Id,
        StageName: stage,
        CloseDate: close_date,
      };
      if (amount !== undefined) body.Amount = amount;

      const id = await sfPost(env, "sobjects/Opportunity", body);
      return { content: [{ type: "text", text: `Opportunity created: "${name}" for ${account_name} at ${stage} stage (ID: ${id})` }] };
    }
  );

  return server;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    // Auth check
    const auth = request.headers.get("Authorization");
    if (!env.MCP_SECRET || auth !== `Bearer ${env.MCP_SECRET}`) {
      return new Response("Unauthorized", { status: 401 });
    }

    const url = new URL(request.url);

    if (url.pathname === "/mcp" && request.method === "POST") {
      const server = createMcpServer(env);
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: undefined, // stateless mode
      });

      await server.connect(transport);
      return transport.handleRequest(request);
    }

    if (url.pathname === "/health") {
      return new Response(JSON.stringify({ status: "ok", service: "salesforce-mcp" }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    return new Response("Not found", { status: 404 });
  },
};
