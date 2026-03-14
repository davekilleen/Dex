import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const raw = readFileSync(join(__dirname, "paths.contract.json"), "utf-8");

export const PATHS_CONTRACT = JSON.parse(raw);
export const PATH_KEYS = Object.freeze(Object.keys(PATHS_CONTRACT.vault_relative_paths));

export function getVaultRelativePath(key) {
  return PATHS_CONTRACT.vault_relative_paths[key];
}
