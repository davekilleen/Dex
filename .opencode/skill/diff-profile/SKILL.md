---
name: diff-profile
description: "Package your entire Dex system into a shareable DexDiff profile so others can replicate how you work. Use when the user says 'share my whole setup', 'publish my profile'. Not for a single workflow; use `diff-generate`. Not for adopting a whole profile; use `diff-adopt-profile`."
---

## What This Command Does

**In plain English:** Scans your entire vault, identifies your strongest custom workflows, groups them at the right level of granularity, and generates methodology documents for each one - plus an overview of how you use Dex. The result is a complete profile that lives at `heydex.ai/diff/your-handle/`.

**How to run it:**
```
/diff-profile
```

---

## Status

This command is coming in a future update.

For now, generate individual workflow diffs with:
```
/diff-generate "my meeting prep workflow"
/diff-generate "my deal review process"
/diff-generate "my weekly planning ritual"
```

Each creates a methodology document that others can adopt individually via `/diff-adopt`.

---

## What It Will Do (Preview)

1. Scan your entire vault — all custom skills, hooks, extensions
2. Build candidate workflow clusters based on shared folders, skill references, hook chains, and observed usage sequences
3. Score each candidate for:
   - distinctiveness — does it represent a meaningfully different job to be done?
   - evidence density — is there enough real usage/customisation here to make it credible?
   - transferability — would another Dex user understand why this matters and want to adopt it?
   - novelty — does it show something differentiated rather than generic Dex usage?
   - standalone strength — would this still feel useful if published as its own workflow?
4. Merge, split, or drop candidates using these rules:
   - merge clusters that feel repetitive, thin, or only make sense together
   - split clusters that contain two or more clearly different workflows that would each be valuable alone
   - drop clusters that are too generic, too weakly evidenced, or not compelling enough to share
   - prefer fewer, stronger workflows over many thin ones
   - never force a fixed number of workflows
5. Aim for the smallest set of workflows that fully captures the user's differentiated value:
   - minimum target: 2-3 workflows if the evidence is thin
   - upper bound: 12-15 only if they are genuinely distinct and all clear the quality bar
   - otherwise let the model decide the number based on usefulness, not neatness
6. Propose boundaries with names and descriptions:
   ```
   I found [N] strong workflows in your vault:

   1. Meeting Prep (3 skills, 1 hook)
      Job: "Never walk into a meeting cold"
   2. Deal Intelligence (4 skills)
      Job: "Know which deals need attention and why"
   3. Weekly Rhythm (3 skills)
      Job: "Start every week with clarity, end it with evidence"
   ...

   Adjust these groupings? [Looks good] [Merge some] [Split one]
   ```
7. Before showing the groupings, explain the judgement clearly:
   - say that Dex chose the number of workflows based on strength, not quota
   - call out any important merges, splits, or dropped candidates when useful
   - make it legible why this set is the right shape for publishing
8. Generate a methodology doc for each retained cluster
9. Generate an overview narrative: "How I use Dex as a [role]"
10. Save everything to the DexDiff profile draft area in the user's vault.
   - canonical contract key: `DEXDIFF_PROFILE_DRAFTS_DIR`
   - current default relative path: `04-Projects/DexDiff/beta/profile/`

## Quality Bar

Every published workflow should be:

- useful to an outsider who has never seen the user's vault
- substantial enough to stand on its own
- clearly different from the other workflows in the profile
- backed by real evidence in the user's setup or usage patterns
- interesting enough to make the profile feel sharp, not padded

If a workflow does not clear this bar, merge it or drop it.

## Reviewer Judgement

When reviewing descriptions for implementation leakage:

- keep public or commercially available tool names when they help the reader understand the workflow
  (examples: QMD, Granola, Slack, Salesforce, Notion, Linear)
- abstract only genuinely internal or private implementation details
  (examples: company codenames, private scripts, internal project names, vault-specific paths,
  proprietary dataset names, team-specific naming conventions)
- if a public tool name stays but may confuse a reader, define or clarify it rather than removing it

## Handoff After Generation

After generating and saving the profile draft:

- describe it as a **local DexDiff draft**, not as something already published
- do **not** imply that choosing the online path immediately makes it public
- do **not** default to editing workflows or the profile overview in the terminal
- explain that final editing and publish happen on Heydex

When the user wants to continue, offer this exact shape of next steps:

```text
What would you like to do next?

1. Review draft on Heydex
   Open the hosted draft/review flow. If a local draft already exists in
   `DEXDIFF_PROFILE_DRAFTS_DIR`, reuse that saved draft and the existing machine auth token
   to create a fresh review session instead of regenerating. The user can sign in, claim
   their profile if needed, edit the workflows and overview on the website, and then choose
   when to publish live.

2. Keep local draft for later
   Save locally only. Nothing is published. Remind the user that the draft is stored in the
   DexDiff profile draft area (`DEXDIFF_PROFILE_DRAFTS_DIR`) and can be regenerated or resumed later.

3. Regroup and regenerate
   Rebuild the workflow grouping from scratch using the same underlying evidence.
   Explain that this replaces the current draft only after confirmation.

4. Discard this draft
   Stop here without opening Heydex or publishing anything.
```

Do not offer "edit one workflow" or "edit overview" as top-level terminal options in the normal flow.
If the user explicitly asks to edit locally in the terminal, do that as an exception, not the default.
