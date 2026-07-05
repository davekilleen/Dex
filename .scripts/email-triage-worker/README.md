# email-triage — Deploy Guide

## What this is

A Cloudflare Worker that classifies incoming emails using **rule-based logic**.
Email classification happens instantly on ingest with categories:

- **urgent** — Requires immediate action or response (time-sensitive, critical)
- **follow_up** — Action needed but not urgent (decisions, approvals)
- **fyi** — Informational, no action needed (announcements, updates)
- **ignore** — Can be safely ignored or archived (spam, newsletters)

Each classification includes a confidence score (0.0–1.0) and reasoning.

**Zero cost, instant classification** — No API calls, just pattern matching.

---

## Step 1 — Deploy the Worker

From the `email-triage-worker/` folder:

```bash
npx wrangler deploy
```

Wrangler will print your Worker URL:
```
https://email-triage.cbarsanti.workers.dev
```

---

## Step 2 — Set Secrets

```bash
# Strong random string for Bearer token auth
npx wrangler secret put MCP_SECRET
```

That's it! No API keys needed — classification is rule-based.

---

## Step 3 — Test the Endpoint

### Health Check

```bash
curl https://email-triage.cbarsanti.workers.dev/
```

Response:
```json
{
  "service": "email-triage",
  "status": "ok",
  "categories": {
    "urgent": "Requires immediate action or response",
    "follow_up": "Action needed but not urgent",
    "fyi": "Informational, no action needed",
    "ignore": "Can be safely ignored or archived"
  }
}
```

### Classify an Email

```bash
curl -X POST https://email-triage.cbarsanti.workers.dev/ingest-email \
  -H "Authorization: Bearer YOUR_MCP_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "email_id": "msg-12345",
    "from": "oncall@example.com",
    "to": "you@yourcompany.com",
    "subject": "CRITICAL: System downtime happening now",
    "body": "Our production database is down. Immediate action required.",
    "date": "2026-06-25T15:00:00Z"
  }'
```

Response (instant, <10ms):
```json
{
  "email_id": "msg-12345",
  "subject": "CRITICAL: System downtime happening now",
  "from": "oncall@example.com",
  "to": "you@yourcompany.com",
  "classification": {
    "category": "urgent",
    "confidence": 0.95,
    "reasoning": "Contains urgent keywords",
    "method": "rule-based"
  }
}
```

---

## API Reference

### POST /ingest-email

**Required Headers:**
- `Authorization: Bearer <MCP_SECRET>`
- `Content-Type: application/json`

**Request Body:**

```json
{
  "email_id": "optional-unique-id",
  "from": "sender@example.com",
  "to": "recipient@example.com",
  "subject": "Email subject line",
  "body": "Full email body text",
  "date": "ISO 8601 timestamp (optional)"
}
```

**Required Fields:**
- `subject` — Email subject
- `body` — Email body text

**Optional Fields:**
- `email_id` — Unique email identifier (returned in response)
- `from` — Sender email address
- `to` — Recipient email address(es)
- `date` — Email timestamp

**Response (200):**

```json
{
  "email_id": "optional-unique-id",
  "subject": "Email subject",
  "from": "sender@example.com",
  "to": "recipient@example.com",
  "classification": {
    "category": "urgent|follow_up|fyi|ignore",
    "confidence": 0.0,
    "reasoning": "Brief explanation of classification",
    "method": "rule-based"
  }
}
```

**Response time:** <10ms (instant, rule-based — no API calls)

**Error Responses:**

- `401 Unauthorized` — Invalid or missing Bearer token
- `400 Bad Request` — Missing `subject` or `body`
- `500 Internal Server Error` — Claude API or parsing error

---

## Integration Examples

### Node.js / JavaScript

```javascript
async function triageEmail(emailData) {
  const response = await fetch(
    "https://email-triage.cbarsanti.workers.dev/ingest-email",
    {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${process.env.MCP_SECRET}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        email_id: emailData.messageId,
        from: emailData.from,
        to: emailData.to,
        subject: emailData.subject,
        body: emailData.body,
        date: emailData.date,
      }),
    }
  );

  if (!response.ok) {
    throw new Error(`Triage failed: ${response.status}`);
  }

  const result = await response.json();
  // Result includes: category, confidence, reasoning, method
  return result.classification;
}

// Example usage
const result = await triageEmail({
  messageId: "msg-123",
  from: "oncall@example.com",
  to: "team@example.com",
  subject: "CRITICAL: Production down",
  body: "Database is down. Immediate action required.",
});

console.log(`Category: ${result.category} (${(result.confidence * 100).toFixed(0)}%)`);
```

### Python

```python
import requests
import os

def triage_email(email_data):
    response = requests.post(
        "https://email-triage.cbarsanti.workers.dev/ingest-email",
        headers={
            "Authorization": f"Bearer {os.environ['MCP_SECRET']}",
            "Content-Type": "application/json",
        },
        json={
            "email_id": email_data.get("message_id"),
            "from": email_data.get("from"),
            "to": email_data.get("to"),
            "subject": email_data.get("subject"),
            "body": email_data.get("body"),
            "date": email_data.get("date"),
        },
    )
    response.raise_for_status()
    return response.json()
```

### Bash

```bash
#!/bin/bash

TRIAGE_URL="https://email-triage.cbarsanti.workers.dev/ingest-email"
MCP_SECRET="your-secret-here"

curl -X POST "$TRIAGE_URL" \
  -H "Authorization: Bearer $MCP_SECRET" \
  -H "Content-Type: application/json" \
  -d '{
    "from": "sender@example.com",
    "to": "you@example.com",
    "subject": "Test email",
    "body": "This is a test email body",
    "date": "2026-06-25T15:00:00Z"
  }'
```

---

## Common Patterns

### Bulk Triage

Process multiple emails in sequence or parallel:

```javascript
async function triageBulk(emails) {
  const results = await Promise.all(
    emails.map(email => triageEmail(email))
  );
  return results;
}
```

### Filter by Category

```javascript
async function getUrgentEmails(emails) {
  const classified = await triageBulk(emails);
  return classified.filter(r => r.classification.category === "urgent");
}
```

### Minimum Confidence

```javascript
async function getHighConfidenceTriages(email, minConfidence = 0.8) {
  const result = await triageEmail(email);
  if (result.classification.confidence < minConfidence) {
    return null; // Requires manual review
  }
  return result;
}
```

---

## Customizing Rules

To adjust how emails are classified:

1. Edit `rules.json` to add, remove, or modify rules
2. Each rule has:
   - `patterns` — Regex patterns to match in subject + body
   - `from_patterns` — Patterns to match sender email
   - `subject_patterns` — Patterns to match subject only
   - `body_patterns` — Patterns to match body only
   - `confidence` — Score 0.0–1.0 for this rule match
   - `reason` — Human-readable explanation

3. Test changes locally:
   ```bash
   node test.js
   ```

4. Run `npx wrangler deploy` to publish changes

### Example: Add a new rule

```json
{
  "urgent": [
    {
      "from_patterns": ["ceo@"],
      "patterns": ["needs your attention"],
      "confidence": 0.9,
      "reason": "CEO message with keyword"
    }
  ]
}
```

Rules are evaluated in order (urgent → follow_up → fyi → ignore) and return on the first match.

---

## Monitoring & Logs

View Worker logs:

```bash
npx wrangler tail
```

This shows real-time logs including API errors, classification times, and authentication failures.

---

## Troubleshooting

### 401 Unauthorized
- Verify `MCP_SECRET` is set correctly with `npx wrangler secret list`
- Ensure Bearer token in request matches the secret

### 400 Bad Request
- Ensure at least `subject` or `body` is present in JSON
- Check JSON syntax with a JSON validator

### 500 Internal Server Error
- Check `npx wrangler tail` for error details
- Verify regex patterns in `rules.json` are valid
- Test patterns locally with `node test.js`

### Classifications not matching expected category
- Check `rules.json` patterns — they're case-insensitive regex
- Add custom rules for your workflow
- Run `node test.js` to validate changes before deploying
- Test patterns: `node -e "console.log(/URGENT/.test('urgent email'))"`

---

## Cost & Performance

**Rule-based classification is free and instant:**
- No API calls — pattern matching only
- <10ms per classification
- Unlimited emails/day
- Only cost: Cloudflare Workers (first 100k requests/day free)

**For high volume (millions/day), consider:**
- Caching results to avoid redundant processing
- Batching classifications in Power Automate workflows
- Monitoring via Cloudflare Analytics Engine
