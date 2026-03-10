export interface PathsContract {
  contract_version: number;
  source: string;
  vault_relative_paths: Record<string, string>;
}

export declare const PATHS_CONTRACT: PathsContract;
export declare const PATH_KEYS: readonly string[];
export declare function getVaultRelativePath(key: string): string | undefined;
