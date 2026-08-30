import { spawn } from "node:child_process";


/** Return executable candidates without invoking a shell. */
export function pythonCandidates(platform = process.platform, env = process.env) {
  const candidates = [];
  const override = typeof env.DEX_PYTHON === "string" ? env.DEX_PYTHON.trim() : "";
  if (override) {
    candidates.push({ command: override, args: [] });
  }
  if (platform === "win32") {
    candidates.push(
      { command: "py", args: ["-3"] },
      { command: "python", args: [] },
      { command: "python3", args: [] },
    );
  } else {
    candidates.push(
      { command: "python3", args: [] },
      { command: "python", args: [] },
    );
  }
  return candidates.filter(
    (candidate, index, rows) =>
      rows.findIndex(
        (row) => row.command === candidate.command && JSON.stringify(row.args) === JSON.stringify(candidate.args),
      ) === index,
  );
}


function spawnCandidate(candidate, script, args, env) {
  return new Promise((resolve) => {
    const child = spawn(candidate.command, [...candidate.args, script, ...args], {
      env,
      stdio: "inherit",
      windowsHide: true,
    });
    child.once("error", (error) => resolve({ error }));
    child.once("exit", (code, signal) => resolve({ code, signal }));
  });
}


/** Run one Python bridge and preserve its exit code, including hook refusals. */
export async function runPython({ script, args = [], platform = process.platform, env = process.env }) {
  for (const candidate of pythonCandidates(platform, env)) {
    const result = await spawnCandidate(candidate, script, args, env);
    if (result.error?.code === "ENOENT") {
      continue;
    }
    if (result.error) {
      process.stderr.write(`Dex could not start ${candidate.command}: ${result.error.message}\n`);
      return 126;
    }
    if (typeof result.code === "number") {
      return result.code;
    }
    process.stderr.write(`Dex's Python bridge stopped by ${result.signal || "an unknown signal"}.\n`);
    return 1;
  }
  process.stderr.write(
    "Dex needs Python 3.11 or newer. Install Python, or set DEX_PYTHON to its executable path.\n",
  );
  return 127;
}
