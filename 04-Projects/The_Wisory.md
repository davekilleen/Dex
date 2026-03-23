---
status: active
pillar: wisory_product
created: 2026-03-14
---

# The Wisory

## Status

Active — Building product, refining positioning, early client conversations

## Goal

Launch The Wisory as the go-to AI + advisor diligence platform for PE firms — combining deep advisor expertise with AI-powered scoring to deliver the "last 10%" of insight.

## Next Actions

- [ ] Develop new slides showing how the tool differentiates from off-the-shelf AI ^task-20260311-002
- [ ] Gather PE sector activity data to recommend 3-4 target industries ^task-20260312-001
- [ ] Document industry-vs-company scoring consideration for Wisory Score model ^task-20260311-004

## Key Stakeholders

- [[Jason_Wadler|Jason Wadler]] — Founder
- [[Fred_Ehle|Fred Ehle]] — Advisor
- [[Sean_Naismith|Sean Naismith]] — Special Advisor (Analytics/Modeling)
- [[Harriette_Murtland|Harriette Murtland]] — Team member
- [[Jason_Whitney|Jason Whitney]] — Team member

## Product — Wisory Score 2.0

**Core concept:** AI Plus AI — Advisor Insights + Artificial Intelligence = Actual Intelligence

**Two-stage scoring:**
- **Early Stage Screen:** 3 indices (clarity, revenue quality, AI disruption), qualitative bands, 30-70% confidence
- **Full Diligence:** 6 indices (adds organizational health, operational clarity, cultural compatibility), numeric score, 50-97% confidence

**Technical stack:** Custom GPT proof of concept + deterministic Langchain/Lanegraph system (Supabase backend). 12 frameworks, 66 vectors of analysis, 50+ roles.

**Key design principles:**
- Always advisor-led — never decouple tool from advisor
- Position as "the last 10%" — don't compete with cheap consulting or GLG
- Removed directive language (legal risk) — provide "considerations" not recommendations
- Confidence maps to data source quality (public filings → partial → full data room)

## Emerging Concepts

- **Digital Twin:** Virtual replica of target company for simulation and what-if testing (Sean's idea). Credit score simulator analogy — what levers to pull to improve a 45 to a 70.
- **Advisor Skill Encoding:** Encode advisor expertise as Claude skills (Sean's novel concept)
- **Wellness Checks:** Portfolio company health monitoring as use case

## Target Industries (To Validate)

James (Deerpath) guidance: Business services, healthcare, tech/software — NOT manufacturing/food & bev. AI should be ~80% of focus given current mindshare.

## Pipeline

| Prospect | Stage | Notes |
|----------|-------|-------|
| Deerpath Capital | Feedback received | James gave strong strategic input. "Last 10%" framing. |
| Bondi Capital | Sales call completed | Mar 12 |
| Shore Capital | Meeting next week | Scottsdale — deeper conversation + potential investment |
| Pritzker | Waiting | Loved the approach, no response yet |
| Indiana University Ventures | Proposed | Back-test deals through the model |
| Investment banker (Raymond James) | Interested | Tech Services Group — PE intros, pre-market audits, funding round timing |

## Competitive Landscape

- **GLG:** "Mile wide, inch deep" — best advisors burned out, data shared across clients
- **Row Space:** Raised $50M from Sequoia — potential partner or market signal
- **Off-the-shelf AI:** Answer the "how is this different from ChatGPT?" objection with advisor-led process

## Related Meetings

- [[2026-03-11 - AI Strategy and Collaboration]]
- [[2026-03-11 - Wisory Score 2.0 - Sean Intro]]
- [[2026-03-12 - Deerpath Leader James]]
- [[2026-03-12 - Wisory Digital Twin and Scenario Planning]]

## Key Quotes

- James (Deerpath): "Lots of people can make a list of 12 factors. What matters is someone who can say, of those 12, these are the two that really matter."
- MIT study: Humans + AI together outperform either alone

## GPT Upgrades Backlog

- Incorporate safety evals
- Update Product Clarity Matrix
- Update Marketing Brief
- Build ability to diagnose where strategy will fail
- Add disclaimer to every output via the output delivery protocol
- Expand audit ledger to have at least 10 data sources and encourage more
- Create ability to save to Notion or Airtable every output
- Build context around The Wisory Score

## Notes

- PE firms are not price sensitive — focus on value, not cost
- Equity component being finalized for Regis
- Sean is "mirror version" of Regis per Jason — deep analytics/TransUnion background
- Don't try to tell PE firms they're wrong — provide considerations
