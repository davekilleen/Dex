# Email Triage Worker — Integration Guide

This guide shows how to integrate the email-triage worker with various email systems and Dex workflows.

---

## Gmail Integration

### Step 1 — Set up Gmail API

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project and enable Gmail API
3. Create OAuth 2.0 credentials (Desktop application)
4. Save the credentials JSON

### Step 2 — Create a Node.js Gmail Listener

```javascript
const { google } = require('googleapis');
const fetch = require('node-fetch');

const gmail = google.gmail('v1');
const TRIAGE_WORKER = process.env.TRIAGE_WORKER_URL;
const MCP_SECRET = process.env.MCP_SECRET;

async function triageGmailMessage(auth, messageId) {
  const message = await gmail.users.messages.get({
    auth,
    userId: 'me',
    id: messageId,
    format: 'full',
  });

  const headers = message.data.payload.headers;
  const from = headers.find(h => h.name === 'From')?.value;
  const to = headers.find(h => h.name === 'To')?.value;
  const subject = headers.find(h => h.name === 'Subject')?.value;
  const date = headers.find(h => h.name === 'Date')?.value;

  const body = message.data.snippet || '';

  const response = await fetch(`${TRIAGE_WORKER}/ingest-email`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${MCP_SECRET}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      email_id: messageId,
      from,
      to,
      subject,
      body,
      date,
    }),
  });

  const result = await response.json();
  return result.classification;
}

// Watch for new emails
async function watchGmail(auth) {
  const watch = await gmail.users.watch({
    auth,
    userId: 'me',
    requestBody: {
      topicName: 'projects/your-project-id/topics/gmail',
    },
  });

  console.log('Gmail watch established:', watch.data.expiration);
}
```

### Step 3 — Process with Labels

```javascript
async function applyGmailLabel(auth, messageId, category) {
  const labelMap = {
    urgent: 'IMPORTANT',
    follow_up: 'INBOX',
    fyi: 'IMPORTANT',  // Or a custom label
    ignore: 'SPAM',
  };

  const labelId = labelMap[category];
  if (!labelId) return;

  await gmail.users.messages.modify({
    auth,
    userId: 'me',
    id: messageId,
    requestBody: {
      addLabelIds: [labelId],
    },
  });
}

// Use together
async function processNewEmail(auth, messageId) {
  const classification = await triageGmailMessage(auth, messageId);
  await applyGmailLabel(auth, messageId, classification.category);
  console.log(`${messageId}: ${classification.category}`);
}
```

---

## Outlook / Microsoft 365 Integration

### Step 1 — Set up Microsoft Graph API

1. Register app in [Azure AD](https://portal.azure.com)
2. Grant Mail.Read and Mail.ReadWrite permissions
3. Save Client ID and Client Secret

### Step 2 — Create an Outlook Listener

```python
import requests
from msgraph.core import GraphClient
from azure.identity import ClientSecretCredential

credential = ClientSecretCredential(
    tenant_id=YOUR_TENANT_ID,
    client_id=YOUR_CLIENT_ID,
    client_secret=YOUR_CLIENT_SECRET
)
graph_client = GraphClient(credential=credential)

TRIAGE_WORKER = os.environ['TRIAGE_WORKER_URL']
MCP_SECRET = os.environ['MCP_SECRET']

async def triage_outlook_message(message_id):
    # Get message
    message = graph_client.get(f'/me/messages/{message_id}')

    email_data = {
        'email_id': message['id'],
        'from': message['from']['emailAddress']['address'],
        'to': message['toRecipients'][0]['emailAddress']['address'],
        'subject': message['subject'],
        'body': message['bodyPreview'] or message.get('body', {}).get('content', ''),
        'date': message['receivedDateTime'],
    }

    response = requests.post(
        f'{TRIAGE_WORKER}/ingest-email',
        headers={
            'Authorization': f'Bearer {MCP_SECRET}',
            'Content-Type': 'application/json',
        },
        json=email_data
    )

    return response.json()['classification']

# Apply category as flag/importance
def apply_outlook_category(message_id, category):
    category_map = {
        'urgent': 'Red category',
        'follow_up': 'Orange category',
        'fyi': 'Green category',
        'ignore': 'Gray category',
    }

    graph_client.patch(
        f'/me/messages/{message_id}',
        {
            'categories': [category_map.get(category, 'Green category')],
            'importance': 'high' if category == 'urgent' else 'normal',
        }
    )
```

---

## Zapier / Automation Integration

### Create a Zapier Zap for Email Triage

**Trigger:** Gmail (or Outlook) → New Email

**Action:** Webhook POST

```json
{
  "url": "https://email-triage.cbarsanti.workers.dev/ingest-email",
  "method": "POST",
  "headers": {
    "Authorization": "Bearer YOUR_MCP_SECRET",
    "Content-Type": "application/json"
  },
  "body": {
    "email_id": "{{message_id}}",
    "from": "{{from}}",
    "to": "{{to}}",
    "subject": "{{subject}}",
    "body": "{{text_plain}}",
    "date": "{{received}}"
  }
}
```

**Filter & Conditional Actions:**

```
If classification.category = "urgent"
  → Add star to email
  → Send Slack notification
  → Create task in your system

If classification.category = "follow_up"
  → Move to Inbox/Requires Response
  → Snooze 1 hour

If classification.category = "fyi"
  → Archive automatically

If classification.category = "ignore"
  → Spam or delete
```

---

## Dex Integration

### Add Email Triage Endpoint to Work MCP

Update `.claude/mcp/work.json` to include email triage:

```json
{
  "name": "email-triage",
  "url": "https://email-triage.cbarsanti.workers.dev/mcp",
  "type": "http",
  "auth": "bearer",
  "secret_name": "EMAIL_TRIAGE_SECRET"
}
```

Then add to your `.claude/settings.json`:

```json
{
  "mcp": {
    "email-triage": {
      "enabled": true,
      "secret": "your-mcp-secret"
    }
  }
}
```

### Create a Skill for Triage Workflow

Create `.claude/skills/email-triage/SKILL.md`:

```markdown
# /email-triage

Classify and organize incoming emails using AI.

## Usage

\`\`\`
/email-triage
\`\`\`

Provides:
- Bulk email classification
- Inbox organization
- Priority filtering
- Workflow automation

## Features

**Quick Triage:**
Classify 5–10 emails at a time and apply Dex task creation

**Bulk Processing:**
Process Gmail/Outlook folders with automatic labeling

**Daily Review:**
Auto-triage overnight emails, surface urgent items at start of day
```

---

## Docker / Self-Hosted Integration

### Local Python Service

If you want to run triage locally instead of via Cloudflare:

```python
# email_triage_service.py
from flask import Flask, request
import anthropic

app = Flask(__name__)
client = anthropic.Anthropic()

CATEGORIES = {
    "urgent": "Requires immediate action",
    "follow_up": "Action needed but not urgent",
    "fyi": "Informational only",
    "ignore": "Can be safely archived",
}

@app.route('/ingest-email', methods=['POST'])
def ingest_email():
    email = request.json
    
    prompt = f"""Classify this email into ONE category:
    {', '.join(CATEGORIES.keys())}

    Subject: {email['subject']}
    Body: {email['body']}

    Respond as JSON: {{"category": "...", "confidence": 0.0-1.0, "reasoning": "..."}}
    """

    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )

    import json
    result = json.loads(response.content[0].text)
    
    return {
        "email_id": email.get("email_id"),
        "subject": email["subject"],
        "classification": result
    }

if __name__ == '__main__':
    app.run(port=5000)
```

Deploy with Docker:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY email_triage_service.py .
CMD ["python", "email_triage_service.py"]
```

---

## Monitoring & Analytics

### Log Triage Decisions

```javascript
async function logTriageDecision(email, classification) {
  // Save to database
  await db.collection('email_triage_log').insertOne({
    timestamp: new Date(),
    email_id: email.email_id,
    from: email.from,
    subject: email.subject,
    category: classification.category,
    confidence: classification.confidence,
    reasoning: classification.reasoning,
  });
}

// Dashboard query: Most commonly triaged categories
async function getCategoryStats(days = 7) {
  return await db.collection('email_triage_log').aggregate([
    {
      $match: {
        timestamp: {
          $gte: new Date(Date.now() - days * 24 * 60 * 60 * 1000)
        }
      }
    },
    {
      $group: {
        _id: "$category",
        count: { $sum: 1 },
        avg_confidence: { $avg: "$confidence" }
      }
    }
  ]).toArray();
}
```

---

## Performance Tips

1. **Batch Processing** — Triage 10–50 emails at once instead of individually
2. **Caching** — Cache results for duplicate senders/subjects
3. **Confidence Thresholds** — Manually review classifications < 0.7 confidence
4. **Category Feedback** — Log corrections to fine-tune future classifications
5. **Scheduled Jobs** — Triage overnight emails on a schedule, not real-time

---

## Troubleshooting

### Worker not responding
- Check `npx wrangler tail` for errors
- Verify secrets are set: `npx wrangler secret list`

### Claude API errors
- Verify API key is valid in [Claude dashboard](https://claude.ai/settings/api-keys)
- Check for rate limits (implement retry logic)

### Integration not working
- Test directly: `curl -X POST https://email-triage.cbarsanti.workers.dev/ingest-email ...`
- Log request/response bodies to debug

### Slow classification
- First request to cold worker is normal (1–2s)
- Consider batch processing for high volume
