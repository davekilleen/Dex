# Meeting Sources Early Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start useful meeting-note ingestion during onboarding, resolve Granola credentials through the connection catalog first, and provide a safe catch-all folder importer.

**Architecture:** Keep the Granola MCP server as the official API reader, but add a best-effort adapter for the connection manager's least-privilege request envelope before the legacy environment and vault `.env` fallbacks. Remove the encrypted local-cache path entirely. Add a directory wrapper around the existing manual single-file import, with per-file isolation and explicit imported/skipped/failed counts, then mirror it through the service and CLI.

**Tech Stack:** Python 3.12, pytest, argparse, SQLite, Node connection-manager accessor, Markdown onboarding flow.

---

### Task 1: Granola credential precedence

**Files:**
- Modify: `core/tests/test_granola_server.py`
- Modify: `core/mcp/granola_server.py`

- [ ] Add focused tests proving:
  - a successful connection-manager envelope wins over `GRANOLA_API_KEY` and `.env`;
  - environment wins when the accessor reports no connection;
  - vault `.env` wins when the accessor is absent and the environment is empty;
  - missing accessor plus no legacy key returns `None`.
- [ ] Run the focused tests and confirm they fail because connection-manager resolution is not implemented.
- [ ] Add `_read_key_from_connection_manager()` using:

  ```python
  subprocess.run(
      ["node", str(accessor), "granola"],
      check=False,
      capture_output=True,
      text=True,
      timeout=5,
  )
  ```

  Treat non-zero exit, missing executables/files, timeouts, malformed JSON, or a missing bearer header as an ordinary miss. Parse the default Class-B envelope's `headers` case-insensitively and strip the `Bearer ` prefix.
- [ ] Change `get_api_key()` to connection manager → environment → vault `.env`, preserving first-hit behavior.
- [ ] Update the module authentication docstring and disconnected copy so neither means-tests the user.
- [ ] Re-run the focused Granola tests and confirm they pass.

### Task 2: Safe folder imports and dead cache removal

**Files:**
- Create: `core/tests/test_transcript_ingest.py`
- Modify: `core/ritual_intelligence/transcript_ingest.py`

- [ ] Add failing tests for:
  - importing `.md`, `.txt`, `.vtt`, and `.srt` while ignoring unsupported files;
  - a second run reporting prior imports as skipped without adding rows;
  - unreadable and binary files being skipped while later files still import;
  - a supported-extension symlink pointing outside the root being skipped;
  - an empty directory returning zero counts.
- [ ] Run the focused tests and confirm they fail because the folder function does not exist.
- [ ] Delete `_find_latest_cache`, `granola_cache_path`, `_read_granola_cache`, `_normalize_granola_artifacts`, and `ingest_granola_local`, then remove their unused imports.
- [ ] Add `import_manual_transcript_folder(folder_path: Path) -> dict`:
  - validate a real directory root;
  - use `os.walk(..., followlinks=False)`;
  - prune symlink directories and skip symlink files;
  - select only case-insensitive `.md`, `.txt`, `.vtt`, `.srt`;
  - detect prior `manual` imports by canonical path in the transcript table;
  - preflight UTF-8 text and reject NUL-containing content;
  - call `import_manual_transcript(file_path=path, title=path.stem)` for each accepted file;
  - catch unreadable/binary conditions as skipped and unexpected per-file exceptions as failed;
  - return `{"imported": n, "skipped": n, "failed": n}` plus per-file details.
- [ ] Run the focused folder tests and confirm they pass.
- [ ] Search the repository for every deleted Granola-cache symbol and confirm no references remain.

### Task 3: Service and CLI exposure

**Files:**
- Modify: `core/tests/test_ritual_intelligence_entrypoints.py`
- Modify: `core/ritual_intelligence/service.py`
- Modify: `core/ritual_intelligence/cli.py`

- [ ] Add a failing CLI test for:

  ```text
  import-transcript-folder <folder_path>
  ```

  Assert the folder is converted to `Path`, the service method is called, and its JSON report is printed.
- [ ] Run the entrypoint test and confirm it fails because the subcommand is absent.
- [ ] Remove the dead `ingest_granola_local` service method and `ingest-granola` CLI command.
- [ ] Add `RitualIntelligenceService.import_manual_transcript_folder(folder_path=...)` delegating to the ingestion module.
- [ ] Add the `import-transcript-folder` parser and handler beside `import-transcript`.
- [ ] Re-run entrypoint and folder tests and confirm they pass.

### Task 4: Early onboarding offer

**Files:**
- Modify: `.claude/flows/onboarding.md`

- [ ] Immediately after `Calendar First` and before Step 1, add a short, separate meeting-source offer that:
  - runs `node .claude/hooks/integration-concierge.cjs`;
  - asks only about detected tools;
  - routes Granola, Zoom, and Teams to real Dex readers;
  - routes every other detected meeting tool to `import-transcript-folder`;
  - says background sync continues during remaining setup;
  - allows skip/later with no validation gate or blocking;
  - contains no paid/free eligibility question or unsupported-reader promise.
- [ ] Leave all of Step 9 unchanged, as explicitly required by the lane boundary.
- [ ] Inspect the diff around Calendar First and Step 9 to prove placement and scope.

### Task 5: Verification and handoff

**Files:**
- Read final diff for all files above.

- [ ] Run focused red/green tests during implementation.
- [ ] Run:

  ```bash
  uv run --python 3.12 --with pytest --with pytest-asyncio --with mcp --with pyyaml --with python-dateutil --with requests python -m pytest core/tests/ core/mcp/tests/ -q -m "not fuzz"
  uv run --python 3.12 --with ruff ruff check core/
  bash scripts/check-pii.sh
  python3 scripts/check-instructed-tools.py
  node .claude/hooks/integration-concierge.cjs | head -3
  ```

- [ ] Run `npm run test:scripts`, compare its failures with the documented 11 clean-main failures, and confirm this lane added none.
- [ ] Run `git diff --check`, inspect `git diff`, and confirm forbidden paths are untouched.
- [ ] Leave all changes uncommitted and report exact results and judgement calls.
