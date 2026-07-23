---
name: dex-orient
description: "Orient in the Dex Core codebase: prints the released version, what's merged-but-not-released, and where the architecture map + inventory live. Use at the start of any dex-core development or investigation, or whenever you're unsure what's shipped vs built-locally vs prototype."
---

# Dex Orient

1. Run `python3 scripts/dex_state.py` from the repository root.
2. Read `docs/architecture/DEX-CORE-MAP.md` for the narrative and `docs/architecture/INVENTORY.md` for generated tool and skill lists.
3. Summarize the released version, LOCAL delta, planned work, and the relevant map section for the user.

`docs/architecture/STATE.md` holds the generated delta snapshot and hand-maintained PLANNED block; rerun the command above for live truth.
