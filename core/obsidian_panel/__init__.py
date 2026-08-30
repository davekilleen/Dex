"""Read-only Obsidian Dex panel: today's brief, Decided lately, a topic ask, no writes, no network."""

from .brief import build_today_brief
from .decisions import ask_recorded_decisions, recent_recorded_decisions
from .install import install_local_plugin
from .safety import (
    inspect_plugin_source,
    refuse_network,
    refuse_vault_write,
)

__all__ = [
    "ask_recorded_decisions",
    "build_today_brief",
    "inspect_plugin_source",
    "install_local_plugin",
    "recent_recorded_decisions",
    "refuse_network",
    "refuse_vault_write",
]
