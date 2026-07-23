---
name: dex-rollback
description: "Rewind one receipt-backed Dex adoption through the frozen lifecycle service. Use when the user says 'undo the update', 'go back', 'that broke something after updating'. Not for applying an update; use `dex-update`."
---

# Dex Rollback

Use this skill when someone wants to undo a Dex adoption. Keep the language calm and concrete. This skill selects and renders a receipt; it never restores, copies, deletes, renames, or rewrites vault files itself.

## The one route

Every rewind goes through `core.lifecycle.service` version 1.0.0. The only mutation operation this skill may request is `rewind_adoption_by_receipt`. There is no manual fallback and no file-by-file workaround.

Use the service in this order:

1. Ask `read_lifecycle_state` for the verified ledger and retention state.
2. Render the adopted items that have receipt-backed rewind evidence.
3. Let the user choose exactly one adoption receipt.
4. Show the receipt’s transaction identifier and complete file list.
5. Ask for explicit confirmation of that exact adoption and file list.
6. Pass the unchanged adoption receipt and its exact acknowledgement token to `rewind_adoption_by_receipt`.
7. Ask `read_lifecycle_state` again and render the rewind receipt and resulting state.

If the snapshot has aged out, a file changed after adoption, the ledger cannot be verified, the acknowledgement does not match, or the service refuses for any other reason, stop. Explain that no files were changed. Never guess an older state from release files or version labels.

## Choice view

For each rewindable adoption, show:

- item names and versions;
- when the lifecycle ledger recorded it, if the state provides that time;
- adoption transaction identifier;
- number of receipt-declared files;
- whether the retained snapshot is still available;
- whether any adopted file has drifted since adoption.

Example register:

> I found one update that can still be undone exactly. It changed three Dex-owned files, and none of those files has changed since.

Do not call a receipt rewindable unless the verified state says its receipt and retained snapshot pass preflight.

## Confirmation

Before requesting the rewind, show every affected path and say what the service will do:

- restore the exact pre-adoption bytes for files that existed;
- remove only files that this receipt proves the adoption created;
- leave later user changes untouched by refusing if receipt-owned files drifted;
- perform the rewind as a new crash-safe transaction;
- record a new rewind receipt rather than erasing history.

Ask one direct question: “Rewind this exact adoption?” Confirmation of an item name alone is insufficient if the receipt or file list has changed.

## Result view

After `rewind_adoption_by_receipt` succeeds, render:

- original adoption transaction identifier;
- new rewind transaction identifier;
- every restored or removed receipt path;
- snapshot reference for the rewind transaction;
- verified post-rewind lifecycle state;
- current retention warning, if any.

Use language such as:

> Rollback complete. Dex restored the exact receipt-backed pre-update state in one protected transaction and kept the history visible.

Never claim success unless the service returned a rewind receipt and the refreshed lifecycle state verifies the item is no longer adopted.

## Boundaries

- Never perform or recommend raw vault file operations.
- Never use source-control history as a substitute for a lifecycle receipt.
- Never alter a receipt, acknowledgement token, transaction identifier, or path list.
- Never rewind more than the chosen receipt proves.
- Never overwrite a file that changed after adoption; render the refusal and route the decision back to the user.
- If no receipt is rewindable, say so plainly and stop.

The user chooses the receipt. The skill explains the consequence. The lifecycle service owns the mutation.
