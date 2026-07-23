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
3. For safe `adopt` items, ask `build_and_preview_adoption` for the exact preview and approval token.
4. For conflict items, collect the choices below. Keep mine and Compare are read-only; Take theirs and Keep both go through `build_and_preview_conflict_resolution`.
5. Show every proposed file from each preview. Execution requires an explicit yes to that exact preview.
6. Pass unchanged adoption previews and tokens to `execute_approved_adoption`, and unchanged resolution previews and tokens to `execute_approved_conflict_resolution`.
7. Ask `read_lifecycle_state` for the verified post-update state and retention warning, then render every receipt.

If the service reports UNKNOWN, conflict, changed evidence, an unsafe path, or a rejected transaction, stop. Explain the refusal in ordinary language and leave the vault untouched. A refusal is a safety result, not an invitation to work around the engine.

## Five-group preview

Always show these groups in this order, even when a group is empty:

1. **New and safe to adopt** — items whose plan action is `adopt`.
2. **Needs your review** — conflicts or customized release files. Say which files caused the hold, then offer the four choices below. Dex leaves each file untouched until the user makes and approves a choice.
3. **Held back by you** — items whose plan action is `skip-held-back`.
4. **Could not be proved** — UNKNOWN items or incomplete lifecycle evidence. Say no change will be made to them.
5. **Already yours** — adopted items and their receipt-backed rewind status.

Example register:

> Here’s exactly what this changes for you. Two items are new and safe, one customized item stays untouched, and everything else is already current.

Do not describe an item as safe merely because its name looks familiar. Use only the action and reasons returned by the service.

## Conflict choices

For each conflicted file, explain that the user changed it and the update carries a new release version. Offer:

- **Keep mine** — “Leave your version exactly as it is. Nothing is written.” Make no service call for this choice.
- **Take theirs** — “Put the new release version live. Your current version remains recoverable with rewind.”
- **Keep both** — “Put the new release version live and save your version beside it as `{name}-custom`, where it stays invocable. The whole change remains rewindable.” Offer this only for a modified skill file. A missing file has nothing to preserve.
- **Compare** — “Show the differences first. Nothing is written.” Read the current and verified release byte sources, render a concise inline diff, then offer the same four choices again. For a large file, summarize the changed regions instead of dumping the whole file.

Collect one `take-theirs` or `keep-both` strategy for each item the user wants resolved. Leave Keep mine items out of the request. Pass only those selected strategies to `build_and_preview_conflict_resolution`, one object per item to resolve, each naming that item and its chosen strategy.

The resolution preview is a separate approval boundary. Show every write exactly as returned, including its path, `release` or `preserved` source, SHA-256, and byte size. Explain which canonical file becomes live and which `-custom` sidecar preserves the user's bytes. Ask: “Apply this exact resolution?” Only an explicit yes to that unchanged preview and approval token permits `execute_approved_conflict_resolution`.

If Keep both is refused because a `{name}-custom` already exists, reassure the user that neither file changed and re-offer Keep mine, Take theirs, or Compare. Never overwrite, rename, merge, or number the existing sidecar.

## Approval

Before execution, show:

- item name and version;
- every file in the preview;
- whether the file is being placed for the first time or refreshed by the authorized lifecycle plan;
- that one crash-safe transaction will apply the complete approved set;
- that the receipt is the source for a later rewind.

Ask one direct question: “Apply this exact update?” for an adoption preview, or “Apply this exact resolution?” for a conflict preview. A vague earlier request to “update Dex” is not approval of a later concrete preview. If anything changes between preview and execution, render the service refusal and build a fresh preview only after the user asks to continue.

## Receipt view

After success, render the receipt returned by `execute_approved_adoption` or `execute_approved_conflict_resolution`:

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
- Read-only Compare may render differences, but it must never mutate either byte source.
- Never instruct the user to move files around as part of an update.
- Never bypass a conflict by replacing the customized file.
- Never synthesize, edit, or shorten an approval token or receipt.
- Never treat an update receipt as permission to rewind; rollback has its own exact acknowledgement.
- For a legacy install that cannot activate the service, explain that the compatibility bridge or installer must complete first. Do not recreate that bridge manually.

The user should see choices, consequences, and receipts. The lifecycle service owns every mutation.
