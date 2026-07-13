# Task Sync Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the service-generic Python task-sync orchestrator, Work MCP entry points, adapter runner, and Todoist unified API v1 adapter without enabling background sync or changing setup skills.

**Architecture:** `core/integrations/task_sync.py` owns all local state, mapping, queueing, eligibility, and Dex writes while calling adapters only through a JSON stdin/stdout Node runner. `core/mcp/work_server.py` exposes two thin MCP handlers. The Todoist adapter implements the locked adapter contract against `https://api.todoist.com/api/v1`; lane-2 adapters remain untouched and unshipped.

**Tech Stack:** Python 3, pytest, PyYAML, MCP server types, Node.js 18+ CommonJS, global `fetch`, `node:test`.

---

### Task 1: Python orchestrator contract

**Files:**
- Create: `core/tests/test_task_sync.py`
- Create: `core/integrations/task_sync.py`
- Modify: `core/paths.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write failing orchestrator tests**

Cover a disposable canonical task file and monkeypatched adapter runner for first-run clean start, date-gated push creation, idempotent completion pushes, pulled completion propagation, inbound queue deduplication, dry-run no-write behavior, per-service isolation, mapping recording, and state round trips. Use `core.paths` constants or monkeypatched path accessors rather than embedding production vault layout paths in implementation code.

- [ ] **Step 2: Verify the tests fail for missing behavior**

Run:

```bash
.venv/bin/python -m pytest -q core/tests/test_task_sync.py
```

Expected: collection or assertions fail because `core.integrations.task_sync` and its API are not implemented.

- [ ] **Step 3: Implement the orchestrator and path constants**

Expose these Python entry points:

```python
def sync_external_tasks(
    services: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, dict[str, object]]: ...

def record_external_task_mapping(
    task_id: str,
    service: str,
    external_id: str,
) -> dict[str, object]: ...
```

Implement atomic JSON persistence with same-directory temp files plus `Path.replace`, exact first-run behavior, canonical-task-only push scans, external-ID map lookups, inbound queue writes, service gating, and subprocess isolation. Resolve Node with `shutil.which("node")` followed by the repository's known executable candidates; use a 30-second subprocess timeout and parse only the runner's JSON stdout.

- [ ] **Step 4: Verify focused Python behavior**

Run the focused command again and require zero failures.

### Task 2: Work MCP exposure

**Files:**
- Modify: `core/mcp/work_server.py`
- Test: `core/tests/test_task_sync.py`

- [ ] **Step 1: Add failing tool-schema and handler tests**

Assert `sync_external_tasks` accepts optional `services` and `dry_run`, `record_external_task_mapping` requires `task_id`, `service`, and `external_id`, and both handlers delegate to `core.integrations.task_sync` and return JSON text.

- [ ] **Step 2: Verify the focused tests fail**

Run the focused Python test command and confirm the missing tools/handlers cause the failure.

- [ ] **Step 3: Add thin tools and handlers**

Import the orchestrator module, append both `types.Tool` declarations, add only the sync tool to write-tool indexing if appropriate for its real writes, and delegate in `_handle_call_tool_inner` without duplicating orchestration logic.

- [ ] **Step 4: Verify focused Python behavior**

Run the focused Python test command and require zero failures.

### Task 3: Adapter runner

**Files:**
- Create: `.claude/hooks/adapters/run.cjs`
- Create: `.claude/hooks/tests/adapter-runner.test.cjs`

- [ ] **Step 1: Write failing runner tests**

Use `spawnSync(process.execPath, [runner, service, op])` with JSON stdin. Cover a rejected service name and a fixture adapter operation that throws; in both cases stdout must contain exactly one parseable `{ok:false,error}` JSON value and no diagnostic text.

- [ ] **Step 2: Verify runner tests fail**

Run:

```bash
node --test .claude/hooks/tests/adapter-runner.test.cjs
```

Expected: failure because the runner does not exist.

- [ ] **Step 3: Implement the runner**

Allow only lowercase service names matching the adapter filename contract, validate exported operation names (`create`, `complete`, `get_changes`), map `get_changes` to `getChanges`, read `{config,args}` from stdin, invoke the operation, and emit one JSON line to stdout. Send diagnostics only to stderr and represent all operational failures as `{ok:false,error}`.

- [ ] **Step 4: Verify runner tests pass**

Run the focused Node command and require zero failures.

### Task 4: Todoist unified API v1 adapter

**Files:**
- Replace: `.claude/hooks/adapters/todoist.cjs`
- Create: `.claude/hooks/tests/todoist-adapter.test.cjs`

- [ ] **Step 1: Write failing HTTP-stub tests**

Use a local `node:http` server and inject its `/api/v1` base URL through adapter config solely for tests. Assert POST task payloads include the Dex marker, resolved opaque project ID, locked P0-P3 mapping, and `due_string`; completion calls `/tasks/{opaque-id}/close`; changes use paginated v1 response envelopes, skip Dex markers, filter active tasks by creation time, include completion events since the cursor, and retry one 429 using `Retry-After`.

- [ ] **Step 2: Verify Todoist tests fail**

Run:

```bash
node --test .claude/hooks/tests/todoist-adapter.test.cjs
```

Expected: failure because the prototype still calls retired REST v2 and Sync v9 endpoints and has the old transform contract.

- [ ] **Step 3: Rebuild the adapter**

Use global `fetch`, `AbortSignal.timeout(15_000)` or an equivalent abort controller, at most three 429 retries, cursor-aware page fetching for `/projects` and `/tasks`, and graceful independent degradation for active/completed change queries. Fetch completed tasks from the documented `/tasks/completed/by_completion_date?since=...&until=...` endpoint. Preserve every external ID as a string without numeric parsing. `toDex` must return raw external fields only; pillar inference stays in Python.

- [ ] **Step 4: Verify Todoist and runner tests pass**

Run both focused Node test files and require zero failures, recording any sandbox-only loopback bind failure separately.

### Task 5: Integration and requested verification

**Files:**
- Review all changed files, while excluding untracked `things.cjs`, `trello.cjs`, and `jira.cjs` from edits and all version-control operations.

- [ ] **Step 1: Run focused Python tests**

```bash
.venv/bin/python -m pytest -q core/tests/test_task_sync.py
```

- [ ] **Step 2: Run the full Python suite**

```bash
.venv/bin/python -m pytest -q
```

- [ ] **Step 3: Run all hook tests**

```bash
npm run test:hooks
```

- [ ] **Step 4: Run Ruff using the repository environment**

```bash
.venv/bin/python -m ruff check core/integrations/task_sync.py core/mcp/work_server.py core/tests/test_task_sync.py
```

- [ ] **Step 5: Inspect scope and stat without committing**

```bash
git status --short
git diff --stat
git diff --check
```

Confirm no setup `SKILL.md`, lane-2 adapter, or Jira file changed; report the official Todoist documentation basis for the completed-task endpoint and every verification result honestly.
