"""Copy the local Obsidian panel into a Dex folder. Notes stay untouched."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

PLUGIN_ID = "dex-readonly"
PLUGIN_FILES = ("manifest.json", "main.js", "styles.css", "paths.js")
REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = REPO_ROOT / "packages" / "dex-obsidian-plugin"


def plugin_install_dir(vault: str | Path) -> Path:
    return Path(vault).expanduser() / ".obsidian" / "plugins" / PLUGIN_ID


def install_local_plugin(
    vault: str | Path,
    *,
    package: str | Path | None = None,
) -> Path:
    """Place the read-only panel files in a local Dex folder."""
    source = Path(package) if package is not None else PACKAGE_ROOT
    dest = plugin_install_dir(vault)
    dest.mkdir(parents=True, exist_ok=True)
    for name in PLUGIN_FILES:
        src = source / name
        if not src.is_file():
            raise FileNotFoundError(f"Missing panel file: {src}")
        shutil.copy2(src, dest / name)
    _enable_plugin(Path(vault).expanduser())
    return dest


def _enable_plugin(vault: Path) -> None:
    community = vault / ".obsidian" / "community-plugins.json"
    community.parent.mkdir(parents=True, exist_ok=True)
    enabled: list[str] = []
    if community.is_file():
        try:
            payload = json.loads(community.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = []
        if isinstance(payload, list):
            enabled = [str(item) for item in payload if isinstance(item, str)]
    if PLUGIN_ID not in enabled:
        enabled.append(PLUGIN_ID)
        community.write_text(json.dumps(enabled, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install the local read-only Dex panel into an Obsidian vault."
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=("install",),
        default="install",
        help="Install the local panel. The only action.",
    )
    parser.add_argument("--vault", required=True, help="Path to the Dex folder")
    args = parser.parse_args(argv)
    dest = install_local_plugin(args.vault)
    print(f"Installed the Dex panel at {dest}")
    print("Open that Dex folder in Obsidian, turn off Restricted Mode, and enable Dex.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
