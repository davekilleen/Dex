# Memory Ownership Boundaries

Your saved Dex work belongs to the vault. An AI app's native memory, conversation history and model context are separate stores; changing apps does not automatically transfer them.

## App-native memory

Claude Code auto-memory may retain preferences and project knowledge when enabled in that host. Its scope and availability are host-owned. It does not persist across all AI apps by virtue of installing Dex. Keep preferences you want Dex to reuse in your vault profile or an explicitly saved note.

Agent-specific `memory: project` is also a host feature. A copied skill or agent instruction does not establish equivalent memory elsewhere.

## Dex session learnings

Operational decisions, commitments and reusable lessons can be saved in `System/Session_Learnings/` by the configured full-vault workflows. Claude Code has session-related capture hooks; the v1.97.13 portable package does not include a session-end capture adapter. In a new app, ask for a summary and confirm whether saving is available. Do not claim a memory was stored until the saved result is read back.

## Search and context

Vault search indexes existing content when its search service is configured. The portable `boot_today` and `get_person_context` tools read selected vault files; they do not record the current conversation. A missing index, ungranted folder or unavailable tool must be reported as such.

Vault files are local, but an AI app may send the context it reads to its model provider. Folder access, connected-service permissions and feedback consent remain separate decisions. See [app limits](../../docs/HARNESS-PORTABILITY.md) and [the system guide](Dex_System_Guide.md).
