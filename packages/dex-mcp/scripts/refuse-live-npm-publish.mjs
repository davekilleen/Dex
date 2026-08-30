#!/usr/bin/env node
const dryRun = process.env.npm_config_dry_run === "true";
if (!dryRun) {
  process.stderr.write(
    "Dex MCP is unreleased. Use npm publish --dry-run only. Do not publish.\n",
  );
  process.exit(1);
}
