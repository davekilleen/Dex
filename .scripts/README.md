# Scripts

This project has scripts in multiple locations, each serving a different purpose:

## `.scripts/` (this directory) — Runtime user-facing scripts
Scripts that run in the user's vault at runtime: meeting sync, semantic search, changelog monitoring, git sync, launch agent automation.

**Subdirectories:**
- `meeting-intel/` — Granola meeting sync and automation
- `semantic-search/` — QMD vector search utilities
- `lib/` — Shared Node.js utilities (e.g. `llm-client.cjs`)

## `scripts/` — CI/build/release tooling
Developer-only scripts for releases, testing, and verification. Not shipped to user vaults.

## `core/scripts/` — System integration scripts
macOS LaunchAgent configs and cleanup scripts for features like ScreenPipe.

## `System/scripts/` — AI model configuration
Scripts for checking, configuring, and testing AI model connections (used by `/ai-setup` and `/ai-status`).
