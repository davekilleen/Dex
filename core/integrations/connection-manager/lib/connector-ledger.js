// Lifted from dex-desktop@2b34aa4d: packages/dex-engine/connector-ledger.js
// DEX CORE DIVERGENCE: files live directly in credentials/ledger, events use
// Core's connect/refresh/probe/break vocabulary, and fs-safe.cjs is the sole
// atomic writer plus cross-process lock implementation.
"use strict";

const nodeFs = require("fs");
const nodePath = require("path");
const { writeFileAtomic, withLockSync } = require("../fs-safe.cjs");

function serialize(entries) {
	return entries.map((entry) => JSON.stringify(entry)).join("\n") + (entries.length ? "\n" : "");
}

function parseFile(text) {
	const entries = [];
	for (const raw of String(text).split("\n")) {
		const line = raw.trim();
		if (!line) continue;
		try {
			const parsed = JSON.parse(line);
			if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) entries.push(parsed);
		} catch {
			// A malformed/truncated row is not evidence. Keep the other rows.
		}
	}
	return entries;
}

function normalizeError(error) {
	if (error == null) return null;
	if (typeof error === "string") return { message: error };
	if (typeof error !== "object") return null;
	const safe = {};
	for (const key of ["code", "category", "message"]) {
		if (error[key] != null) safe[key] = String(error[key]).slice(0, 500);
	}
	return Object.keys(safe).length ? safe : null;
}

function createConnectorLedger(opts = {}) {
	const fs = opts.fs || nodeFs;
	const stateDirOpt = opts.stateDir;
	const now = typeof opts.now === "function" ? opts.now : Date.now;
	const maxEntriesPerConnector =
		Number.isFinite(opts.maxEntriesPerConnector) && opts.maxEntriesPerConnector > 0
			? Math.floor(opts.maxEntriesPerConnector)
			: 500;
	if (stateDirOpt == null) throw new Error("createConnectorLedger requires opts.stateDir");

	function stateDir() {
		const resolved = typeof stateDirOpt === "function" ? stateDirOpt() : stateDirOpt;
		if (!resolved) throw new Error("createConnectorLedger: stateDir resolved to empty");
		return resolved;
	}

	function validateConnectorId(connectorId) {
		const value = String(connectorId || "");
		if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}(?::[a-z0-9_-]+)?$/.test(value)) {
			throw new Error("connector-ledger requires a safe connectorId");
		}
		return value;
	}

	function filePathFor(connectorId) {
		return nodePath.join(stateDir(), `${validateConnectorId(connectorId)}.jsonl`);
	}

	function readDisk(connectorId) {
		const file = filePathFor(connectorId);
		if (!fs.existsSync(file)) return [];
		try {
			return parseFile(fs.readFileSync(file, "utf8"));
		} catch {
			return [];
		}
	}

	function normalizeRow(connectorId, row = {}) {
		return {
			at: new Date(now()).toISOString(),
			connectorId,
			op: typeof row.op === "string" ? row.op : "unknown",
			httpStatus: Number.isFinite(row.httpStatus) ? row.httpStatus : null,
			ok: row.ok === true,
			latencyMs: Number.isFinite(row.latencyMs) ? row.latencyMs : null,
			error: normalizeError(row.error),
		};
	}

	function append(connectorId, row) {
		const safeId = validateConnectorId(connectorId);
		const dir = stateDir();
		fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
		const file = filePathFor(safeId);
		const stored = normalizeRow(safeId, row);
		return withLockSync(`${file}.lock`, () => {
			const entries = readDisk(safeId);
			const next = [...entries, stored].slice(-maxEntriesPerConnector);
			writeFileAtomic(file, serialize(next), { mode: 0o600 });
			return stored;
		});
	}

	function readAll(connectorId) {
		return connectorId ? readDisk(connectorId) : [];
	}

	function tail(connectorId, count = 50) {
		const entries = readAll(connectorId);
		const size = Number.isFinite(count) && count > 0 ? Math.floor(count) : entries.length;
		return entries.slice(-size);
	}

	function rollup(connectorId) {
		const entries = readAll(connectorId);
		// DEX CORE DIVERGENCE: a reconnect replaces the credential but preserves
		// historical evidence. Only probes from the current connect epoch may
		// verify the credential that is stored now.
		const latestConnect = entries.reduce(
			(lastIndex, entry, index) => (entry.op === "connect" ? index : lastIndex),
			-1
		);
		const currentEpoch = latestConnect >= 0 ? entries.slice(latestConnect) : entries;
		const probes = currentEpoch.filter((entry) => entry.op === "probe");
		const successful = probes.filter((entry) => entry.ok === true);
		const lastVerified = successful.length ? successful[successful.length - 1] : null;
		const lastProbe = probes.length ? probes[probes.length - 1] : null;
		return {
			lastVerifiedAt: lastVerified ? lastVerified.at : null,
			lastProbeAt: lastProbe ? lastProbe.at : null,
			lastProbe: lastProbe,
			operations: tail(connectorId, 50),
		};
	}

	return { append, tail, readAll, rollup, filePathFor };
}

module.exports = { createConnectorLedger };
