---
created: 2026-04-09
type: reference
---

# Wisory Score — Origin Story

## How the Scoring Framework Came to Be

### The Players

- **Jason Wadler** — Founder, The Wisory. Provided the strategic framework.
- **Matt Panucci** — Advisor/consultant. Provided the PE operational lens.
- **Regis Hadiaris** — Designed the index architecture, scoring mechanics, and AI implementation.

---

## Timeline

### December 23, 2025 — The Foundational Meeting (1hr 21min)

Jason, Matt, and Regis. This is where the index concept was born.

- **Jason Wadler** proposed the "outside in" and "inside out" assessment framework — combining brand, product, pricing, and distribution (market-facing) with culture, leadership, and team (internal). This became the structural DNA for the indices: top 3 market-facing, bottom 3 operational/internal.
- **Matt Panucci** highlighted common PE operational challenges — revenue optimism, capability gaps — that shaped what the indices needed to detect. His experience operating inside PE portfolio companies informed the failure modes each index targets.
- **Regis** captured the concepts and began translating them into a buildable system.

The team agreed to create a proprietary score algorithm to quantify diligence and post-close execution, leveraging AI and advisor expertise.

### December 31, 2025 — Productization Jam Session Part II (31min)

Matt and Regis refined the concept into product form:

- First named the **Clarity Score Index (CSI)** and drafted diagnostic questions
- Discussed using diagnostics for organizational health and commercial maturity
- Identified need for historical deal data to train AI models
- Proposed a 60-day phase for building and selling the product
- Discussed compensation model ($10K/month retainer + equity + % of deals)

### January 2, 2026 — Strategy Session

Matt pushed for a **case study as the spine** — "what data do we need? What are the frameworks? Which advisors should we validate with?" The case study would inform the MVP and accelerate sales.

### January 5, 2026 — Index Architecture Takes Shape

- **Matt's key insight:** The diagnostic questions were right, but the system needed to evolve from client-generated answers to **inference models**. He mapped four levels of insight:
  1. Industry/Category — publicly available data only
  2. + CAST advisor input — closer to industry, may know key actors
  3. Pre-LOI — above + pre-LOI diligence data
  4. Diligence — above + management team access for "real" answers

- **Regis** delivered: Revised Strategy Clarity deck, Clarity Score Diagnostic (Airtable form), Comp slide, 90-day product roadmap, and the concept of building a custom GPT with "Industry Packs."

### January 7, 2026 — Regis Formalizes the Scoring System

Two emails from Regis to Matt defined the technical architecture:

**Email 1 — Scoring Mechanics:**
- Adopted Matt's 4-level insight evolution concept with rescoring at each level
- Defined the **canonical 0-10 scale** (the only scale written to Airtable)
- Created the **0-4 rubric** (absent/weak/partial/strong/exceptional) for internal reasoning
- Defined **rubric-to-score translation**: `score = (rubric / 4) × 10`
- Wrote: "I'd expect we create similar for the **other 4 indices**, and then incrementally improve them over time."

**Email 2 — AI Implementation:**
- Defined the `/csi-extract` command
- Steps: review analysis → infer 13 diagnostic answers (Q1-Q13) → score each on 0-10
- This became the operational bridge between the framework and Dot Connector AI

### January 6, 2026 — Shipped to Jason

Strategy Clarity deck, 90-day roadmap, and engagement economics sent to Jason Wadler with three options. Recommended Option A (greenlight roadmap).

### January 21, 2026 — Matt Steps Back

Jason paused the engagement: "Let's pause the work beyond what has been built for Deerpath." Matt's active involvement ended, but the scoring architecture was fully established.

### January–March 2026 — Regis Builds the System

Regis continued independently, expanding from CSI to the full 6-index Wisory Score:
1. **CSI** — Clarity Score Index (strategic clarity)
2. **RQI** — Revenue Quality Index
3. **ADI** — Acquisition Dynamics Index
4. **OHI** — Operational Health Index
5. **CDI** — Cultural Dynamics Index
6. **TRI** — Technology Readiness Index

Each index got its own diagnostic questions, scoring rubrics, and AI extraction commands. The 66 vector definition/exemplar pairs were segmented as individual skills. The system was deployed as IntelliQ on LangGraph.

---

## Attribution Summary

| Contribution | Who |
|---|---|
| "Outside in / inside out" strategic framework | Jason Wadler |
| PE operational failure patterns (what indices need to detect) | Matt Panucci |
| 4-level insight evolution model (public → advisor → pre-LOI → diligence) | Matt Panucci |
| Index architecture, naming, and structure (6 indices) | Regis Hadiaris |
| Scoring mechanics (0-10 canonical scale, rubric, translation) | Regis Hadiaris |
| Diagnostic questions for each index | Regis Hadiaris |
| AI implementation (Dot Connector AI, `/csi-extract`, LangGraph) | Regis Hadiaris |
| 66 vector definition/exemplar pairs | Regis Hadiaris |
| IntelliQ production deployment | Regis Hadiaris |
| Case study / MVP framing | Matt Panucci |
| 90-day product roadmap | Regis Hadiaris |

---

## Source Materials

- Otter.ai recording: "Regis's Meeting Notes" — Dec 23, 2025 (1hr 21min) — Jason, Matt, Regis
- Otter.ai recording: "Productization Jam Session, Part II" — Dec 31, 2025 (31min) — Matt, Regis
- Email thread: "Next Steps" — Jan 5-7, 2026 — Regis ↔ Matt
- Email thread: "The Wisory Updated Strategy + Roadmap + Draft Engagement Economics" — Jan 6-21, 2026 — Jason, Matt, Regis

---

*Compiled: April 9, 2026*
