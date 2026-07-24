"""Consent-gated registration data for a future Doctor/setup flow."""

from __future__ import annotations


def mcp_registration_snippet() -> dict[str, object]:
    return {
        "customization-migration": {
            "command": "python3",
            "args": ["-m", "core.mcp.customization_migration_server"],
            "env": {"VAULT_PATH": "{{VAULT_PATH}}"},
        }
    }


__all__ = ["mcp_registration_snippet"]
