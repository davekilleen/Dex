"""Read-only Obsidian Dex panel: today's brief, no writes, no network."""

from .brief import build_today_brief
from .install import install_local_plugin
from .safety import (
    inspect_plugin_source,
    refuse_network,
    refuse_vault_write,
)

__all__ = [
    "build_today_brief",
    "inspect_plugin_source",
    "install_local_plugin",
    "refuse_network",
    "refuse_vault_write",
]
