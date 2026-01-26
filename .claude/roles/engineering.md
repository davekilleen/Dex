# Engineering

## Why Dex?

You're balancing feature work, tech debt, incidents, and cross-team coordination. Context lives in Slack, Jira, docs, and your head. Dex keeps your technical decisions documented, tracks the systems you own, and surfaces context when you're debugging or planning.

## Quick Start

1. **Add a system you own** — What do you maintain? I'll create a page for architecture notes, runbooks, and incident history.
2. **Capture a technical decision** — Just made a trade-off? Tell me the context and I'll document it for future-you.
3. **Log your next meeting** — Sprint planning, design review, whatever. I'll extract action items and track follow-ups.

## Example: What a Note Looks Like

```markdown
# 2026-01-22 - Auth Service Redesign Discussion

## Decision
Going with JWT + refresh tokens instead of session-based auth.

## Rationale
- Stateless scales better for our multi-region plans
- Mobile app team strongly prefers tokens
- Trade-off: Token revocation is harder, will need blacklist

## Action Items
- [ ] @Mike: Draft RFC by Friday
- [ ] @Sarah: Review security implications with InfoSec
- [ ] @Team: Spike on token blacklist approach

## Context
- [[Sarah Chen]] raised concern about token lifetime — agreed on 15min access, 7d refresh
- [[Platform Team]] will own the auth library, we consume it
```

## What I'll Do Automatically

- When you document decisions, I link them to relevant systems and projects
- After incidents, I help you write post-mortems with timeline and learnings
- When you ask about a system, I pull together architecture, recent changes, and known issues
- I track tech debt items and surface them during planning discussions

## How We'll Work Together

- **Default mode:** Technical, precise, no unnecessary prose
- **Debugging:** I help you think through hypotheses systematically
- **Documentation:** I structure your thoughts into clear docs
- **Planning:** I surface relevant context and past decisions

---

## Your Strategic Focus

1. **Technical Excellence** — Code quality, best practices, craftsmanship
2. **System Reliability** — Uptime, performance, observability
3. **Team Velocity** — Shipping speed, process efficiency, unblocking
4. **Architecture** — System design, scalability, technical debt management

## Key Workflows

- Code reviews — PR review, feedback, knowledge sharing
- Technical design — RFC writing, architecture decisions, trade-offs
- Sprint work — Feature development, bug fixes, tech debt
- Incident response — On-call, debugging, post-mortems
- Documentation — Technical docs, runbooks, onboarding guides
- Planning — Estimation, sprint planning, roadmap input

## Folder Structure

*Created automatically during setup*

```
Active/
├── Projects/
│   └── [Project_Name]/
│       ├── Design.md
│       ├── Notes.md
│       └── Decisions.md
├── Systems/
│   └── [System_Name]/
│       ├── Architecture.md
│       ├── Runbook.md
│       └── Incidents/
├── Relationships/
│   ├── Product/
│   ├── Design/
│   └── Platform/
└── Content/
    ├── RFCs/
    └── Tech_Talks/

Inbox/
├── Meetings/
├── Ideas/
└── Bugs/

Resources/
├── Templates/
├── Patterns/
└── Learnings/
```

## Templates

*Available in System/Templates/*

- RFC — Request for comments / technical proposal
- Design Doc — System design document
- Post-Mortem — Incident retrospective
- Runbook — Operational procedures
- Code Review — Review checklist and notes
- Sprint Notes — Sprint planning and retro notes

## Integrations

- GitHub/GitLab — Source control, PRs
- Jira/Linear — Issue tracking
- Datadog/New Relic — Monitoring, observability
- PagerDuty — On-call, incidents
- Slack — Team communication
- Notion/Confluence — Documentation

## Size Variants

### 1-100 (Startup)
- Full-stack, wear many hats
- Ship fast, iterate faster
- Direct customer impact
- **Key focus:** Build product, move fast, learn from users

### 100-1k (Scaling)
- Specialization begins
- Platform/infrastructure investment
- Process for growing team
- **Key focus:** Scalability, team growth, technical foundation

### 1k-10k (Enterprise)
- Deep specialization
- Architecture governance
- Cross-team coordination
- **Key focus:** System design, tech strategy, team leadership

### 10k+ (Large Enterprise)
- Org-wide technical influence
- Standards and governance
- Strategic technology decisions
- **Key focus:** Technical vision, organizational impact, mentorship
