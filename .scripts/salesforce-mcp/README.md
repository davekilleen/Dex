# salesforce-mcp — Deploy Guide

## What this is
A Cloudflare Worker that exposes your Salesforce org as MCP tools.
Dex connects to it over HTTP using a Bearer token you define.

Exposes 6 tools:
- `search_accounts`      – search accounts by name
- `search_contacts`      – search contacts by name/email
- `get_opportunities`    – list open opps (filterable)
- `get_account_contacts` – contacts for an account ID
- `get_account_details`  – full account + last 10 activity notes
- `log_activity`         – log a call/meeting note to SF

---

## Step 1 — Deploy the Worker

From the `salesforce-mcp/` folder:

```bash
npx wrangler deploy
```

Wrangler will print your Worker URL:
  https://salesforce-mcp.cbarsanti.workers.dev

---

## Authentication & Architecture

The Worker utilizes the modern Salesforce OAuth 2.0 Client Credentials flow managed through a Salesforce External Client App (ECA).

Authentication tokens are cached in-memory per Cloudflare isolate for 30 minutes to eliminate redundant network round-trips. In the event that a token is revoked or expires early mid-session, the worker features a self-healing retry mechanism that catches `401` errors, clears the cache, fetches a fresh token, and completes the execution seamlessly.

### Required Environment Secrets (Cloudflare Wrangler)

Configure these secrets on your deployed Worker using `wrangler secret put <NAME>`:

| Secret Key | Description | Example / Value |
| :--- | :--- | :--- |
| `SF_CLIENT_ID` | Consumer Key from the Salesforce External Client App | *Obtained from App Setup* |
| `SF_CLIENT_SECRET` | Consumer Secret from the Salesforce External Client App | *Obtained from App Setup* |
| `SF_MY_DOMAIN` | Your specific Salesforce My Domain URL | `midatlanticmachinery.my.salesforce.com` |
| `MCP_SECRET` | Inbound bearer token to secure the Worker endpoint | *Your custom communication token* |

*Note: The legacy `SF_USERNAME`, `SF_PASSWORD`, and `SF_SECURITY_TOKEN` variables are deprecated and have been removed from the environment.*

---

## Step 2 — Set Secrets

Run each of these (you'll be prompted to paste the value):

```bash
npx wrangler secret put SF_CLIENT_ID
npx wrangler secret put SF_CLIENT_SECRET
npx wrangler secret put SF_MY_DOMAIN
npx wrangler secret put MCP_SECRET
```

---

## Step 3 — Add to Dex .mcp.json

In your Dex vault root, open (or create) `.mcp.json` and add:

```json
{
  "mcpServers": {
    "salesforce": {
      "type": "http",
      "url": "https://salesforce-mcp.cbarsanti.workers.dev/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_SECRET_HERE"
      }
    }
  }
}
```

Replace `YOUR_MCP_SECRET_HERE` with the value you set in Step 2.

---

## Step 4 — Test

Quick smoke test from terminal:

```bash
curl -X POST https://salesforce-mcp.cbarsanti.workers.dev/mcp \
  -H "Authorization: Bearer YOUR_MCP_SECRET_HERE" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Should return a list of 6 tools.

Then try a real query:

```bash
curl -X POST https://salesforce-mcp.cbarsanti.workers.dev/mcp \
  -H "Authorization: Bearer YOUR_MCP_SECRET_HERE" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_opportunities","arguments":{}}}'
```

---

## Notes
- All tool calls now use OAuth 2.0 Client Credentials with cached access tokens.
- The Worker no longer stores or uses `SF_PASSWORD` or `SF_SECURITY_TOKEN`.
- The /health endpoint is public (no auth) for uptime checks.

