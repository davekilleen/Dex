"""Prove the Obsidian panel cannot write notes or use the internet."""

from __future__ import annotations

from pathlib import Path

PLUGIN_FILES = ("manifest.json", "main.js", "styles.css", "paths.js", "README.md")

WRITE_MARKERS = (
    "vault.create",
    "vault.modify",
    "vault.delete",
    "vault.append",
    "vault.process",
    "vault.copy",
    "vault.rename",
    "createFolder",
    "adapter.write",
    "adapter.remove",
    "adapter.mkdir",
    "adapter.rmdir",
    "adapter.trash",
    "write_text",
    "write_bytes",
    "unlink(",
    "addCommand",
    "addRibbonIcon",
)

NETWORK_MARKERS = (
    "fetch(",
    "requestUrl",
    "XMLHttpRequest",
    "WebSocket",
    "navigator.sendBeacon",
    "http://",
    "https://",
    "ws://",
    "wss://",
)


def inspect_plugin_source(plugin_root: str | Path) -> dict[str, str]:
    """Return the installed plugin sources for a closed safety scan."""
    root = Path(plugin_root)
    texts: dict[str, str] = {}
    for name in PLUGIN_FILES:
        path = root / name
        texts[name] = path.read_text(encoding="utf-8") if path.is_file() else ""
    return texts


def plugin_source_violations(
    plugin_root: str | Path,
    *,
    allow_readme_urls: bool = True,
) -> list[str]:
    """Return write or network markers found in the plugin files."""
    texts = inspect_plugin_source(plugin_root)
    violations: list[str] = []
    for name, text in texts.items():
        scan = text
        if allow_readme_urls and name == "README.md":
            continue
        for marker in WRITE_MARKERS + NETWORK_MARKERS:
            if marker in scan:
                violations.append(f"{name}: {marker}")
    return violations


def refuse_vault_write(path: str | Path, *_args: object, **_kwargs: object) -> None:
    """Refuse any attempt to change a vault file from this panel."""
    raise PermissionError(f"The Obsidian Dex panel does not write vault files: {path}")


def refuse_network(url: str, *_args: object, **_kwargs: object) -> None:
    """Refuse any attempt to use the internet from this panel."""
    raise PermissionError(f"The Obsidian Dex panel does not use the internet: {url}")
