#!/usr/bin/env python3
"""Generate Obsidian config optimized for Dex"""
from pathlib import Path

from core.obsidian.preserve_config import write_obsidian_json


def generate_config(vault_path: Path):
    """Generate .obsidian/ config files without wiping a user's settings."""
    obsidian_dir = vault_path / '.obsidian'
    obsidian_dir.mkdir(exist_ok=True)
    backups: list[str] = []

    def write(name: str, payload: dict) -> None:
        backup = write_obsidian_json(obsidian_dir / name, payload)
        if backup is not None:
            backups.append(backup.name)

    # App config
    write(
        "app.json",
        {
            "alwaysUpdateLinks": True,
            "newLinkFormat": "shortest",
            "useMarkdownLinks": False,
            "showFrontmatter": True,
            "foldHeading": True,
            "foldIndent": True,
            "showLineNumber": False,
            "spellcheck": True,
            "strictLineBreaks": False,
            "readableLineLength": True,
            "defaultViewMode": "preview",
        },
    )

    write(
        "appearance.json",
        {
            "baseFontSize": 16,
            "theme": "moonstone",
        },
    )

    write(
        "hotkeys.json",
        {
            "graph:open": [{"modifiers": ["Mod"], "key": "g"}],
            "command-palette:open": [{"modifiers": ["Mod", "Shift"], "key": "p"}],
            "switcher:open": [{"modifiers": ["Mod"], "key": "o"}],
            "backlink:toggle-backlinks-in-document": [
                {"modifiers": ["Mod", "Shift"], "key": "b"}
            ],
        },
    )

    write(
        "workspace.json",
        {
            "main": {
                "id": "dex-main",
                "type": "split",
                "children": [
                    {
                        "id": "dex-editor",
                        "type": "leaf",
                        "state": {
                            "type": "markdown",
                            "state": {
                                "file": "README.md",
                                "mode": "preview",
                            },
                        },
                    }
                ],
            },
            "left": {
                "id": "dex-left",
                "type": "split",
                "children": [
                    {
                        "id": "file-explorer",
                        "type": "leaf",
                        "state": {"type": "file-explorer"},
                    }
                ],
                "collapsed": False,
            },
            "right": {
                "id": "dex-right",
                "type": "split",
                "children": [
                    {
                        "id": "backlinks",
                        "type": "leaf",
                        "state": {"type": "backlink"},
                    }
                ],
                "collapsed": True,
            },
        },
    )

    print("✅ Obsidian config generated")
    print("   - Existing settings kept or merged")
    print("   - Keyboard shortcuts configured")
    print("   - Default workspace layout")
    if backups:
        print("   - Backup saved: " + ", ".join(backups))


if __name__ == '__main__':
    import os
    vault_path = Path(os.environ.get('VAULT_PATH', Path.cwd()))
    generate_config(vault_path)
