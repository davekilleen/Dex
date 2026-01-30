#!/usr/bin/env python3
"""Generate Obsidian config optimized for Dex"""
import json
from pathlib import Path

def generate_config(vault_path: Path):
    """Generate .obsidian/ config files"""
    obsidian_dir = vault_path / '.obsidian'
    obsidian_dir.mkdir(exist_ok=True)
    
    # App config
    app_config = {
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
        "defaultViewMode": "preview"
    }
    
    (obsidian_dir / 'app.json').write_text(json.dumps(app_config, indent=2))
    
    # Appearance
    appearance = {
        "baseFontSize": 16,
        "theme": "moonstone"
    }
    
    (obsidian_dir / 'appearance.json').write_text(json.dumps(appearance, indent=2))
    
    # Hotkeys
    hotkeys = {
        "graph:open": [{"modifiers": ["Mod"], "key": "g"}],
        "command-palette:open": [{"modifiers": ["Mod", "Shift"], "key": "p"}],
        "switcher:open": [{"modifiers": ["Mod"], "key": "o"}],
        "backlink:toggle-backlinks-in-document": [{"modifiers": ["Mod", "Shift"], "key": "b"}]
    }
    
    (obsidian_dir / 'hotkeys.json').write_text(json.dumps(hotkeys, indent=2))
    
    # Workspace (default layout)
    workspace = {
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
                            "mode": "preview"
                        }
                    }
                }
            ]
        },
        "left": {
            "id": "dex-left",
            "type": "split",
            "children": [
                {
                    "id": "file-explorer",
                    "type": "leaf",
                    "state": {
                        "type": "file-explorer"
                    }
                }
            ],
            "collapsed": False
        },
        "right": {
            "id": "dex-right",
            "type": "split",
            "children": [
                {
                    "id": "backlinks",
                    "type": "leaf",
                    "state": {
                        "type": "backlink"
                    }
                }
            ],
            "collapsed": True
        }
    }
    
    (obsidian_dir / 'workspace.json').write_text(json.dumps(workspace, indent=2))
    
    print("✅ Obsidian config generated")
    print("   - Optimized settings for Dex")
    print("   - Keyboard shortcuts configured")
    print("   - Default workspace layout")

if __name__ == '__main__':
    import os
    vault_path = Path(os.environ.get('VAULT_PATH', Path.cwd()))
    generate_config(vault_path)
