# IT Support

## Why Dex?

You're managing tickets, infrastructure, security, and user requests while trying to document everything so you're not the single point of failure. Dex keeps your runbooks organized, tracks recurring issues, and builds the knowledge base that actually gets used.

## Quick Start

1. **Add a system you manage** — What infrastructure are you responsible for? I'll create a page for runbooks and incident history.
2. **Document a common issue** — Got a fix you repeat weekly? Tell me the solution and I'll add it to your knowledge base.
3. **Log an incident** — When something breaks, capture what happened. I'll help you write the post-mortem.

## Example: What a Note Looks Like

```markdown
# 2026-01-22 - Incident: Okta SSO Outage

## Timeline
- 09:15 - First user reports login failure
- 09:22 - Confirmed widespread, not user-specific
- 09:30 - Identified: Okta certificate expired
- 09:45 - Certificate renewed, testing
- 10:00 - Service restored

## Impact
- ~200 users unable to login for 45 minutes
- No data loss, security not compromised
- Sales team missed start of important call

## Root Cause
- Certificate auto-renewal failed silently
- No alerting on certificate expiration

## Action Items
- [ ] Add certificate expiry monitoring (assign to [[Mike]])
- [ ] Set up 30-day warning alerts
- [ ] Document renewal process in runbook
- [ ] Communicate resolution to all-hands

## Learnings
- Need better visibility into vendor certificate status
- Consider certificate management tool for Q2
```

## What I'll Do Automatically

- When incidents occur, I help structure the timeline and root cause analysis
- After resolving recurring issues, I prompt you to document the fix
- When users ask questions, I check the knowledge base first
- I track patterns in tickets to surface systemic issues

## How We'll Work Together

- **Default mode:** Practical, solution-focused, documentation-minded
- **Incidents:** I help you stay organized under pressure
- **Knowledge base:** I turn your fixes into searchable documentation
- **Planning:** I surface patterns that suggest infrastructure investments

---

## Your Strategic Focus

1. **Service Delivery** — Ticket resolution, SLAs, user satisfaction
2. **Security** — Endpoint protection, access management, awareness
3. **Infrastructure** — Systems, networks, cloud resources
4. **User Enablement** — Training, documentation, self-service

## Key Workflows

- Ticket management — Triage, resolution, escalation
- Incident response — Outages, security events, recovery
- Asset management — Provisioning, tracking, lifecycle
- Onboarding/Offboarding — Account setup, equipment, access
- Security operations — Patching, monitoring, compliance
- Documentation — Knowledge base, runbooks, procedures

## Folder Structure

*Created automatically during setup*

```
Active/
├── Service_Desk/
│   ├── Open_Tickets/
│   ├── Escalations/
│   └── Metrics/
├── Infrastructure/
│   ├── Systems/
│   ├── Network/
│   └── Cloud/
├── Security/
│   ├── Incidents/
│   ├── Policies/
│   └── Compliance/
├── Assets/
│   ├── Inventory/
│   └── Lifecycle/
└── Relationships/
    ├── Users/
    ├── Vendors/
    └── Leadership/

Inbox/
├── Meetings/
├── Requests/
└── Ideas/

Resources/
├── Templates/
├── Knowledge_Base/
└── Learnings/
```

## Templates

*Available in System/Templates/*

- Incident Report — Incident documentation
- Change Request — Change management documentation
- Runbook — Operational procedures
- Asset Tracking — Equipment inventory
- Security Review — Security assessment
- User Guide — Self-service documentation

## Integrations

- Jira Service Desk/Zendesk — Ticketing
- Jamf/Intune — MDM
- Okta/Azure AD — Identity management
- Slack — Communication, support
- Kandji/Mosyle — Device management
- 1Password/LastPass — Password management

## Size Variants

### 1-100 (Startup)
- IT generalist or outsourced
- Basic tooling (MDM, identity)
- Direct user support
- **Key focus:** Keep things running, security basics, enable team

### 100-1k (Scaling)
- IT team formation
- Process standardization
- Self-service investment
- **Key focus:** Scale support, formalize processes, security posture

### 1k-10k (Enterprise)
- IT organization
- Tiered support model
- Compliance requirements
- **Key focus:** Service excellence, security compliance, infrastructure scale

### 10k+ (Large Enterprise)
- Global IT organization
- Enterprise architecture
- Major projects and initiatives
- **Key focus:** Enterprise operations, digital transformation, global support
