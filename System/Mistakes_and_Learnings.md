# Mistakes & Learnings Log

> Running log of errors, corrections, and lessons learned during Dex sessions.
> Updated automatically when mistakes are identified. Referenced in future work to avoid repetition.

---

## 2026-03-14 — Session: Granola Transcript Fetch + Vault Setup

### Mistake 1: Included Non-MedWrite Meetings in Granola Fetch

**What happened:**
When fetching 70 Granola meeting transcripts and saving them to `00-Inbox/Meetings/`, three non-MedWrite meetings slipped through the MedWrite keyword filter:

| File | Why it slipped through | Correct classification |
|------|----------------------|----------------------|
| `2025-05-07 - Homemade Product & Engineering Sync.md` | "Homemade" not in exclusion list | Different company/product — NOT MedWrite |
| `2025-02-17 - Design sync on The Grid's Feedback.md` | "The Grid" not in exclusion list | Different product (The Grid) — NOT MedWrite |
| `2025-03-19 - Tranquil's Feedback.md` | "Tranquil" not in exclusion list; transcript mentioned "dropp" | Dropp/Tranquil product — NOT MedWrite |

**Root cause:**
The exclusion keyword list (`personal_kw`) only covered obvious personal contexts (mortgage, blood work, Dropp, etc.) but didn't include Dropp-adjacent product names like "Homemade", "The Grid", or "Tranquil" which are separate companies/products Bolu was involved with before/outside MedWrite.

**Fix applied:**
All three files deleted from `00-Inbox/Meetings/` on 2026-03-14.

**Rule going forward:**
- Bolu has involvement in at least two non-MedWrite products: **Dropp** (restaurant/inventory app) and a product called **Homemade/The Grid**
- Any future Granola fetch must explicitly exclude: `dropp`, `homemade`, `the grid`, `tranquil`, `restaurant`, `waiter`, `kitchen`, `inventory management` (when in Dropp context)
- When in doubt about a meeting's company context, **check the first 200 chars of transcript** before including — MedWrite meetings mention: hospitals, clinical, GP letters, EHR, patients, Sean, Ahmad, David, or specific hospital names (SVPH, CHI, GleeMed, Beacon)
- Updated exclusion keywords to add: `homemade`, `the grid`, `tranquil` (when not in MedWrite context)

---

### Mistake 2: Gave User Generic Terminal Instructions Instead of Exact Path

**What happened:**
When guiding Bolu through the `./install.sh` step, I wrote `/path/to/your/dex/folder` as a placeholder instead of the actual path, causing confusion and a failed command.

**Root cause:**
I had already identified from the Finder screenshot that the dex folder was at `~/dex`, but gave a generic placeholder anyway.

**Fix applied:**
Corrected immediately to `cd ~/dex && ./install.sh`.

**Rule going forward:**
- Bolu is **not technical**. Never use placeholder paths. Always give the exact, copy-paste-ready command.
- When I can see the file system or a screenshot, always use the real path.

---

## Template for Future Mistakes

```
### Mistake N: [Short title]

**What happened:** [1-2 sentences]
**Root cause:** [Why it happened]
**Fix applied:** [What was done to correct it]
**Rule going forward:** [What to do differently next time]
```

---

## Standing Rules (derived from mistakes)

1. **Never use placeholder paths** — Bolu is non-technical. Always give exact, copy-paste commands.
2. **MedWrite-only filter for Granola** — Exclude Dropp, Homemade, The Grid, Tranquil. Verify transcript content when title is ambiguous.
3. **Bolu's other companies** — She has/had involvement in Dropp (restaurant/F&B app) and possibly other ventures. Keep these strictly separate from MedWrite Dex vault.
4. **Check transcript content** — Don't rely on title alone. Sample first 200 chars of transcript to verify company context.
