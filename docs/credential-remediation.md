# Credential remediation

Todoist and Trello raw credentials live only in the ignored vault-root `.env`. The tracked
`System/integrations/config.yaml` stores `*_env_var` references. Internal task sync resolves
those references itself and sends values only inside the adapter runner's stdin JSON. Values
are excluded from argv, process environment, state, queues, results, and logs.

Existing `.mcp.json` is scan/report-only and Dex never edits it. Any raw residual keeps local
migration `partial`. Revocation and rotation remain provider actions performed by the user;
Dex may run a read-only replacement health check only in an explicitly requested remediation
flow.

Migration is authorized per installation only when all live same-directory journal, temporary
file, durability, replace, identity recheck, readback, rollback, and no-follow containment
capabilities pass. OS, filesystem, sync, removable/network, or support labels never veto a
pass. Failure refuses only migration; scan and manual guidance remain available.

History cleanup is optional privacy hygiene. It requires an explicit choice, a restrictive
verified local bundle, typed consent, and a preinstalled supported `git-filter-repo`. Dex never
installs that tool, contacts a provider, or pushes rewritten history.
