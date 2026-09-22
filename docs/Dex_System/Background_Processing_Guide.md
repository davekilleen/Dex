# Background Processing Guide

Dex can do work during a conversation or through a separately installed job. The app you use determines whether a conversational workflow can continue in the background.

## Conversation work

Claude Code supports background agents; use them only when the workflow and permissions permit it. In other apps, ask for progress in the current conversation unless background execution has been verified. A skill file does not create that execution capability.

The portable package distributed in v1.97.13 has read-only context tools and limited hook adapters. It does not install a meeting processor, task writer, session-end recorder or background service. Complete new-app journeys remain unverified; see [app capabilities](../../docs/HARNESS-PORTABILITY.md).

## Scheduled work

Existing macOS jobs, such as meeting sync and optional Obsidian sync, run through the operating system after separate setup. They are independent of whether a chat is open. Installing or removing an app plugin does not start or stop those jobs. Check their configured schedule and health before expecting automatic results.

## What to expect

- **Automatic:** a configured schedule or trusted app event runs the action. Identify which one.
- **On demand:** request a workflow using its available skill and tools.
- **Guided:** follow explicit steps where the app cannot complete the operation.
- **Unavailable:** the current app or runtime cannot perform it; retain the existing working route.

Syncing a meeting into the vault and processing its follow-ups are separate steps. A notification that meetings are waiting is not proof that tasks or person pages were updated. Ask for the saved result and check which sources were used.

See [the hook inventory](../../docs/architecture/HOOK-INVENTORY.md) for the exact separation between schedules, in-chat events and file writers.
