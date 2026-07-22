---
name: dex-update
description: "Preview and safely adopt a Dex update through the receipt-backed lifecycle (look → back up → apply → verify → rewindable). Use when the user says 'update Dex', 'install the new version', or a release notice appeared. Not for undoing an update; use `dex-rollback`. Not just seeing what changed; use `dex-whats-new`."
---

# Dex Update

Use this skill when someone wants the latest Dex capabilities or asks what an update would change. Keep the conversation plain and reassuring. The skill collects choices and renders lifecycle results; it never edits, copies, renames, deletes, or merges vault files itself.

## The one route

Every lifecycle operation goes through `core.lifecycle.service` version 1.0.0. Treat its response as authoritative. Do not fall back to direct file operations, Git mutation, an update script, or a hand-built repair when the service refuses.

Use the service operations in this order:

1. Ask `build_inventory_and_plan` for the verified inventory and ledger-aware plan.
2. Render the five groups below without changing anything.
3. After the user chooses items, ask `build_and_preview_adoption` for the exact preview and approval token.
4. Show every proposed file from that preview. Execution requires an explicit yes to that exact preview.
5. Pass the unchanged preview and token to `execute_approved_adoption`.
6. Ask `read_lifecycle_state` for the verified post-update state and retention warning, then render the receipt.

If the service reports UNKNOWN, conflict, changed evidence, an unsafe path, or a rejected transaction, stop. Explain the refusal in ordinary language and leave the vault untouched. A refusal is a safety result, not an invitation to work around the engine.

## Five-group preview

Always show these groups in this order, even when a group is empty:

1. **New and safe to adopt** — items whose plan action is `adopt`.
2. **Needs your review** — conflicts or customized release files. Say which files caused the hold and that Dex preserved them.
3. **Held back by you** — items whose plan action is `skip-held-back`.
4. **Could not be proved** — UNKNOWN items or incomplete lifecycle evidence. Say no change will be made to them.
5. **Already yours** — adopted items and their receipt-backed rewind status.

Example register:

> Here’s exactly what this changes for you. Two items are new and safe, one customized item stays untouched, and everything else is already current.

Do not describe an item as safe merely because its name looks familiar. Use only the action and reasons returned by the service.

## Approval

Before execution, show:

- item name and version;
- every file in the preview;
- whether the file is being placed for the first time or refreshed by the authorized lifecycle plan;
- that one crash-safe transaction will apply the complete approved set;
- that the receipt is the source for a later rewind.

Ask one direct question: “Apply this exact update?” A vague earlier request to “update Dex” is not approval of a later concrete preview. If anything changes between preview and execution, render the service refusal and build a fresh preview only after the user asks to continue.

## Receipt view

After success, render the receipt returned by `execute_approved_adoption`:

- adopted items;
- transaction identifier;
- every receipt-declared file;
- snapshot reference;
- rewind acknowledgement availability;
- any retention warning from `read_lifecycle_state`.

Use language such as:

> Update complete. Dex committed one protected transaction and recorded a receipt for every changed file. Your own content was not part of the write set.

Never claim success from a command exit alone. Success means the service returned a committed receipt and the post-update lifecycle state verifies it.

## Boundaries

- Never perform a raw vault write.
- Never instruct the user to move files around as part of an update.
- Never bypass a conflict by replacing the customized file.
- Never synthesize, edit, or shorten an approval token or receipt.
- Never treat an update receipt as permission to rewind; rollback has its own exact acknowledgement.
- For a legacy install that cannot activate the service, explain that the compatibility bridge or installer must complete first. Do not recreate that bridge manually.

The user should see choices, consequences, and receipts. The lifecycle service owns every mutation.
