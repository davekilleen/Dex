"""Write the ChatGPT Work personal-copy and home marketplace path.

This is the mechanical install path up to, and not including, the vault-folder
grant. A person still has to grant the Dex vault folder on a real desktop.
This module never writes a grant, a grant receipt, or a grant environment flag.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
ADAPTER_PATH = Path(__file__).with_name("adapters") / "chatgpt-work.json"
DEFAULT_PLUGIN_ROOT = REPO_ROOT / "packages" / "dex-agent-plugin"
PERSONAL_COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


@dataclass(frozen=True)
class PersonalCopyLayout:
    """Honest filesystem layout for the ChatGPT Work personal-copy path."""

    home: Path
    plugin_copy: Path
    marketplace: Path
    marketplace_root: Path
    source_path: str
    leftover: str


def load_chatgpt_work_adapter() -> dict[str, Any]:
    """Return the ChatGPT Work adapter contract."""
    payload = json.loads(ADAPTER_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise RuntimeError("ChatGPT Work adapter must be a JSON object")
    example = payload.get("example")
    if not isinstance(example, Mapping):
        raise RuntimeError("ChatGPT Work adapter is missing its install example")
    return json.loads(json.dumps(payload))


def _home_relative(home: Path, listed: str, *, label: str) -> Path:
    if not isinstance(listed, str):
        raise RuntimeError(f"{label} must be a home-relative path")
    if listed == "~":
        return Path(home)
    if not listed.startswith("~/"):
        raise RuntimeError(f"{label} must be a home-relative path")
    relative = Path(listed[2:])
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"{label} must stay inside the home folder")
    return home.joinpath(*relative.parts)


def write_personal_copy(
    *,
    home: Path,
    plugin_root: Path | None = None,
) -> PersonalCopyLayout:
    """Copy the reviewed plugin and write the home marketplace document.

    The leftover vault-folder grant is named, not performed.
    """
    home_path = Path(home)
    source = Path(plugin_root) if plugin_root is not None else DEFAULT_PLUGIN_ROOT
    adapter = load_chatgpt_work_adapter()
    example = adapter["example"]
    document = example["personal_marketplace_document"]
    source_path = document["plugins"][0]["source"]["path"]
    if source_path != "./.codex/plugins/dex":
        raise RuntimeError("personal marketplace source.path must be ./.codex/plugins/dex")

    plugin_copy = _home_relative(
        home_path, example["personal_plugin_copy"], label="personal_plugin_copy"
    )
    marketplace = _home_relative(
        home_path, example["personal_marketplace"], label="personal_marketplace"
    )
    marketplace_root = _home_relative(
        home_path, example["personal_marketplace_root"], label="personal_marketplace_root"
    )
    leftover = str(example["vault_grant"])

    if plugin_copy.exists():
        shutil.rmtree(plugin_copy)
    plugin_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, plugin_copy, ignore=PERSONAL_COPY_IGNORE)

    marketplace.parent.mkdir(parents=True, exist_ok=True)
    marketplace.write_text(
        json.dumps(document, indent=2) + "\n",
        encoding="utf-8",
    )

    resolved = (marketplace_root / source_path.removeprefix("./")).resolve()
    if resolved != plugin_copy.resolve():
        raise RuntimeError(
            "home marketplace source.path must resolve from the home root "
            "to ~/.codex/plugins/dex"
        )
    return PersonalCopyLayout(
        home=home_path,
        plugin_copy=plugin_copy,
        marketplace=marketplace,
        marketplace_root=marketplace_root,
        source_path=source_path,
        leftover=leftover,
    )
