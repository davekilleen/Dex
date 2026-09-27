# Windows support and security — code-ready specification

**Status:** specification plus the Phase 3 support table below. Written 2026-09-27
against `main`. Full text (areas A–F) lives on
`cursor/windows-support-security-spec-bbc7` at `4773d428` and is also copied by
Phase 1. This file keeps the public status table the README links to.

Tracking: https://github.com/davekilleen/dex-product-gtm-lab/issues/719

## Windows support status

| Area | Status today |
| --- | --- |
| Install (`install.ps1`, Git Bash `install.sh`) | Preview — works on a clean Windows 11 with python.org 3.12/3.13 |
| First setup and daily use (notes, tasks, MCP tools) | Preview |
| `/dex-update` and `/dex-rollback` | Not yet — a fix for how Dex read and wrote its own record files on Windows is in progress |
| Connected-service keys (`.env`) and trusted local MCPs | Not yet — Windows file-permission checks are in progress |
| Older vaults (before v1.80) moving to the current update engine | Not on Windows — start from a fresh install |
| Calendar, background meeting sync, launch-at-login jobs | Mac only |
| Supported shells and Pythons | PowerShell or Git Bash; python.org Python 3.12/3.13. Not supported: Cygwin, Microsoft Store Python, WSL folders under `/mnt` |
