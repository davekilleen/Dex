---
name: diff-adopt-profile
description: "Adopt a full published Heydex profile by handle ('set me up like @davekilleen'). Use when the user says 'set me up like <person>', or names a handle. Not for a single workflow doc; use `diff-adopt`. Not for creating your own profile; use `diff-profile`."
---

## What This Command Does

**In plain English:** Pulls down someone's full published Heydex profile, not just one workflow. You get the profile overview, the ordered workflow set, each methodology document, and the optional Love Letter. Then you walk the user through adopting the whole profile into their own Dex setup.

**How to run it:**
```text
/diff-adopt-profile @davekilleen
/diff-adopt-profile https://heydex.ai/diff/davekilleen/
```

Natural-language triggers count too: when a user says "set me up like Dave" (or like any named person with a Heydex handle), treat it as `/diff-adopt-profile @<their-handle>`.

## Arguments

`$ARGUMENTS` must be either:
- a handle like `@davekilleen`
- a public Heydex profile URL like `https://heydex.ai/diff/davekilleen/`

If missing or invalid:
```text
/diff-adopt-profile expects a Heydex handle or public profile URL.

Examples:
  /diff-adopt-profile @davekilleen
  /diff-adopt-profile https://heydex.ai/diff/davekilleen/
```

## Hosted Contract

Always fetch the bundle from the **API host**:

```text
GET https://api.heydex.ai/api/profile-bundle?handle=<handle>
```

Critical: the API lives on `api.heydex.ai` (Convex HTTP actions). The website host `heydex.ai` serves pages only - it has **no** `/api/*` routes, and fetching the bundle from `https://heydex.ai/api/...` returns a bare 404. Never use the website host for API calls. (Local stubs and rehearsals override the base with the `DEXDIFF_API_BASE` environment variable.)

Expected contract:
- `contractVersion: "2026-04-10"`
- `profile`
- `workflows` — ordered list, each with `diffId`, `name`, `description`, `methodology`, `tags`, `roles`, `integrations`
- `loveLetter` — optional

Do **not** use the normal public profile page payload for this command. The whole point is to pull the dedicated runtime bundle.

## The Deterministic Half Is A Script

This skill ships with `scripts/adopt_profile.py` (stdlib-only Python). Use it for fetch, validation, and saving - do not hand-roll HTTP calls or file writes:

```bash
# Step 1 of the flow (fetch + report, writes nothing):
python3 <skill-dir>/scripts/adopt_profile.py @<handle> --fetch-only --json

# Step 3 of the flow (save bundle + adoption log, after user consent):
python3 <skill-dir>/scripts/adopt_profile.py @<handle> --json
```

Exit codes: `0` success, `2` bad handle, `3` network down, `4` profile not found, `5` malformed payload or server error, `6` not inside a Dex vault. Every non-zero exit prints a plain-language explanation on stdout - relay it to the user verbatim, then stop. Never improvise around a failure, and never fail silently.

If `python3` is not available on the machine, fall back to fetching `https://api.heydex.ai/api/profile-bundle?handle=<handle>` yourself (WebFetch or curl), validate the contract fields listed above, and perform the same writes by hand - but say so explicitly and keep the same stop-on-failure behavior.

## Flow

### 1. Resolve and fetch

1. Resolve the handle from the argument (`@handle` or a profile URL both work - the script parses either).
2. Run the bundled script with `--fetch-only --json`.
3. On failure, relay the script's explanation and stop. Typical cases to recognise:
   - **Profile not found (exit 4):** the handle is wrong or the profile is not public. Tell the user exactly that, suggest checking the spelling and the profile page `https://heydex.ai/diff/<handle>/`.
   - **Network down (exit 3):** tell the user nothing was changed and to retry once they are online.
   - **Malformed bundle (exit 5):** the published profile is broken server-side; the user cannot fix this - tell them to let the author know.
4. If the report includes `warnings` about v1-summary methodologies, tell the user plainly: those workflows were published in an old thin format and cannot be regenerated faithfully; offer to continue with only the full-fidelity workflows.

### 2. Introduce the profile

Lead with what makes the profile useful:

```text
[displayName] — [role], [company]

This profile contains [N] published workflows:
  1. [workflow name]
  2. [workflow name]
  ...

[If loveLetter exists]
WHY THIS PROFILE EXISTS
"[loveLetter.text]"

Want to bring this full profile into your Dex setup? [Yes] [Show me the workflows first]
```

If the user wants to inspect first, walk them through the workflows in order before asking again.

### 3. Save the bundle locally before building

Before generating any local skills or hooks, run the bundled script **without** `--fetch-only`. It saves the raw hosted bundle into the user's DexDiff profile draft area and writes the adoption log in one deterministic step:

- root: `DEXDIFF_PROFILE_DRAFTS_DIR` (default `04-Projects/DexDiff/beta/profile/`)
- profile folder: `DEXDIFF_PROFILE_DRAFTS_DIR/adopted/<handle>/`
- manifest: `profile-bundle.json`
- workflows: `workflows/01-<diff-id>.yaml`, `02-<diff-id>.yaml`, etc.
- optional Love Letter: `love-letter.md`
- adoption log: `System/.dex/adoptions/profiles/<handle>.json`

The log includes:
- `profile_handle`
- `profile_display_name`
- `adopted_at`
- `source`
- `bundle_contract_version`
- `manifest_path`
- `workflow_ids`
- `workflow_paths`
- `love_letter_path`

Relay the script's printed file list to the user so they can see exactly what landed where. If the script exits 6 ("not a Dex vault"), the user is running from the wrong folder - help them locate their Dex vault and re-run from there.

### 4. Discovery pass across the whole profile

Do one shared discovery pass for the whole profile:
- detect the user's role
- scan folders
- check integrations
- note existing skills that overlap

Then reuse that shared context across every workflow instead of restarting discovery from scratch for each one.

### 5. Preview one combined install plan

Show one combined plan covering:
- the full ordered workflow set
- which local skills would be created or enhanced
- folders/templates/hooks that would be added
- any conflicts that need decisions

Keep the workflow order from the hosted bundle.

### 6. Build after one approval gate

Only build after the user approves the combined plan.

For each workflow:
- use the same adoption principles as `/diff-adopt`
- generate local skills fresh from the methodology
- never install foreign code directly
- never overwrite existing files without explicit confirmation

### 7. Finish with first-use guidance

End by explaining:
- what was installed
- the order the workflows are meant to be used in
- where the saved bundle lives locally
- how to inspect installed workflows with `/diff-list`

## Important Rules

- Treat this as a real runtime command, not future-state.
- Always use the dedicated profile bundle contract on `api.heydex.ai` - never the website host.
- Use the bundled `scripts/adopt_profile.py` for fetch and save; do not hand-roll the deterministic steps.
- Every failure gets a plain-language explanation and a clean stop. Never fail silently, never half-complete.
- Keep single-workflow adoption as `/diff-adopt @handle/diffId`.
- Do not introduce multi-select workflow picking into this command.
- Preserve workflow order from the hosted bundle.
- Save the bundle locally before generating anything else.
- Never overwrite existing files without approval.

## Inside Dex Desktop Chat (no shell available)

The Dex desktop app's chat lane cannot run shell commands or scripts. When the
tools `mcp__dex-dexdiff__dexdiff_fetch_bundle` and
`mcp__dex-dexdiff__dexdiff_write_adoption` are available, use THEM for the
deterministic halves instead of `scripts/adopt_profile.py`:

- `dexdiff_fetch_bundle` replaces the hosted fetch + validation step and
  returns the validated bundle.
- `dexdiff_write_adoption` replaces the file-writing + adoption-log step; it
  writes atomically, never overwrites, and records the adoption server-side
  on completion.

The conversational halves — preview against the user's real vault, consent,
adaptation, education — stay with this skill, unchanged. If neither tool is
available (plain terminal), use the bundled script exactly as documented above.
