# Agentic Skill Pattern — Phase Separation & Model Routing

**Origin:** Architecture review 2026-07-06; first proven in `/visit-prep` (v1.19.0 era). This is the default design for every new or refactored Dex skill.

## The principle

> The script does 90% of the work for zero tokens; AI only does judgment.

Split every skill into explicit phases and route each phase to the cheapest executor that can do it correctly:

| Phase | Executor | Cost | Examples |
|---|---|---|---|
| **Gather** | Deterministic script (Python on local SF cache / sflib, PowerShell, Node) | Zero tokens | Query accounts, join cases to emails, compute lease-expiry triggers, build the markdown/xlsx skeleton |
| **Judge** | Claude (session model) | Tokens — but small, focused input | Strategy, framing, prioritization, cross-linking, anything requiring taste |
| **Route/format** | Script again | Zero tokens | auto-link-people.cjs, xlsx export, file placement |

## Rules

1. **Never re-derive in-context what a script already computes.** If the skill needs SF data, the script reads the local cache (`.scripts/sflib`-style) — no MCP round-trips for bulk data.
2. **Script output is the contract.** The script emits a complete, well-structured artifact (markdown dossier, JSON). AI appends a clearly-labeled judgment section and never edits the script's sections.
3. **Handle failure deterministically.** Scripts print sentinel lines (`AMBIGUOUS`, `NOT FOUND`, stale-cache warnings); the SKILL.md tells AI exactly how to respond to each.
4. **Offer a `quick` mode** that stops after the script phase — zero-token path for when judgment isn't needed.
5. **Model routing metadata** (v1.18.0): tag the judgment phase's required tier in the skill frontmatter so cheap models handle gather-orchestration and higher tiers are reserved for strategy.
6. **Compound the output.** Judgment phase cross-links into company/person pages so next run starts warm.

## Reference implementations

- `.scripts/visit-prep.py` + `.claude/skills/visit-prep-custom/SKILL.md` — the canonical example
- `.scripts/customer-intel/generate-report.py` — scheduled, fully scripted gather
- `.scripts/morning-brief.py` — daily brief skeleton

## Refactor backlog (as of 2026-07-07)

Candidates still doing MCP-heavy gathering in-context, best first:
1. `week-itinerary` — opps/tasks/calendar/email pulls + routing + xlsx are all scriptable
2. `pipeline-sync` — scripts exist (`pipeline-sync-batch.py` etc.); rewire skill to call them
3. `daily-plan` / `week-plan` — script the assembly, keep AI scheduling judgment
4. `service-pulse` — email × open-case join is pure data work
