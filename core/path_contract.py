"""Build and export vault path contracts from core.paths."""

from __future__ import annotations

import json
from pathlib import Path

from core import paths


def _path_constants() -> dict[str, Path]:
    constants: dict[str, Path] = {}
    for name, value in vars(paths).items():
        if name.startswith("_"):
            continue
        if isinstance(value, Path):
            constants[name] = value
    return constants


def build_relative_paths_contract() -> dict[str, object]:
    """Return a deterministic, vault-relative contract dictionary."""
    constants = _path_constants()
    root = paths.VAULT_ROOT

    rel_map: dict[str, str] = {}
    for key in sorted(constants):
        value = constants[key]
        if key == "VAULT_ROOT":
            rel_map[key] = "."
            continue

        try:
            rel = value.relative_to(root)
            rel_map[key] = rel.as_posix() if rel.as_posix() else "."
        except ValueError:
            # Keep a stable fallback for any non-vault absolute path.
            rel_map[key] = value.as_posix()

    return {
        "contract_version": 1,
        "source": "core/paths.py",
        "vault_relative_paths": rel_map,
    }


def _schema() -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://dex/contracts/paths.schema.json",
        "title": "Dex Vault Paths Contract",
        "type": "object",
        "required": [
            "contract_version",
            "source",
            "vault_relative_paths",
        ],
        "properties": {
            "contract_version": {"type": "integer", "minimum": 1},
            "source": {"type": "string"},
            "vault_relative_paths": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {"type": "string"},
            },
        },
        "additionalProperties": False,
    }


def _index_js() -> str:
    return """import { readFileSync } from \"node:fs\";
import { dirname, join } from \"node:path\";
import { fileURLToPath } from \"node:url\";

const __dirname = dirname(fileURLToPath(import.meta.url));
const raw = readFileSync(join(__dirname, \"paths.contract.json\"), \"utf-8\");

export const PATHS_CONTRACT = JSON.parse(raw);
export const PATH_KEYS = Object.freeze(Object.keys(PATHS_CONTRACT.vault_relative_paths));

export function getVaultRelativePath(key) {
  return PATHS_CONTRACT.vault_relative_paths[key];
}
"""


def _index_d_ts() -> str:
    return """export interface PathsContract {
  contract_version: number;
  source: string;
  vault_relative_paths: Record<string, string>;
}

export declare const PATHS_CONTRACT: PathsContract;
export declare const PATH_KEYS: readonly string[];
export declare function getVaultRelativePath(key: string): string | undefined;
"""


def write_contract_package(dist_dir: Path) -> dict[str, object]:
    """Write contract JSON, schema and runtime helpers to dist_dir."""
    dist_dir.mkdir(parents=True, exist_ok=True)

    contract = build_relative_paths_contract()

    (dist_dir / "paths.contract.json").write_text(
        json.dumps(contract, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    (dist_dir / "paths.schema.json").write_text(
        json.dumps(_schema(), indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    (dist_dir / "index.js").write_text(_index_js(), encoding="utf-8")
    (dist_dir / "index.d.ts").write_text(_index_d_ts(), encoding="utf-8")

    return contract
