# Internal

Colleagues, teammates, and internal stakeholders.

## Automatic Routing

Person pages are automatically routed here if their email domain matches your company domain (configured in `System/user-profile.yaml` → `email_domain` field).

**Example:** If your domain is `acme.com`, then `sarah@acme.com` automatically routes to Internal/.

This routing happens automatically during meeting processing via `/process-meetings`.

## What Goes Here

- **Manager** — Your direct manager (track 1:1s, feedback, career discussions)
- **Direct reports** — People you manage (track development, 1:1s, feedback given)
- **Teammates** — People on your immediate team
- **Cross-functional partners** — Eng, design, marketing, sales, etc.
- **Executives** — Leadership you interact with

## Key Sections

For each person, track:
- **Role and team** — What they do
- **Relationship** — How you work together
- **Recent meetings** — Auto-linked from `00-Inbox/Meetings/`
- **Key topics** — Ongoing threads and projects
- **Action items** — What you owe them / they owe you
- **Notes** — Important context (communication style, what they care about, etc.)

## Special: Manager Pages

If you have an Area for Career (via `/career-setup`), your manager's page gets enhanced tracking:
- Career development discussions extracted from 1:1s
- Feedback received automatically captured
- Growth goal alignment
- Promotion readiness context

## Usage

- **Before 1:1s** — Review their page to remember context
- **After meetings** — Update with new action items or insights
- **During planning** — Check who you haven't connected with recently
