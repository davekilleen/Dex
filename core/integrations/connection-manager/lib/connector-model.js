// Lifted from dex-desktop@2b34aa4d: packages/dex-engine/connector-model.js
// DEX CORE DIVERGENCE: Core has credentials but no sync jobs, so this keeps
// Desktop's evidence-only principle while retaining Core's five public states.
"use strict";

const CONNECTOR_STATUSES = Object.freeze([
	"connected",
	"expiring",
	"expired",
	"needs_reauth",
	"not_connected",
]);

/**
 * Derive Core's credential status strictly from durable evidence.
 * A credential may be connected without being live-verified; verification is
 * deliberately a separate evidence field rather than a fabricated sync state.
 */
function deriveStatus(evidence = {}) {
	if (evidence.credentialPresent !== true) return "not_connected";
	if (evidence.registryError) return "needs_reauth";
	if (!evidence.expiresAt) return "connected";
	const nowMs = Number.isFinite(evidence.nowMs) ? evidence.nowMs : Date.now();
	if (nowMs >= evidence.expiresAt) {
		return evidence.hasRefreshToken ? "expired" : "needs_reauth";
	}
	if (nowMs >= evidence.expiresAt - 5 * 60 * 1000) return "expiring";
	return "connected";
}

function deriveVerification(evidence = {}) {
	const lastVerifiedAt = typeof evidence.lastVerifiedAt === "string" ? evidence.lastVerifiedAt : null;
	return {
		verified: lastVerifiedAt !== null,
		verification: lastVerifiedAt === null ? "unverified" : "verified",
		lastVerifiedAt,
		lastProbeAt: typeof evidence.lastProbeAt === "string" ? evidence.lastProbeAt : null,
	};
}

function buildModel(base = {}, evidence = {}) {
	return {
		...base,
		status: deriveStatus(evidence),
		...deriveVerification(evidence),
	};
}

module.exports = { CONNECTOR_STATUSES, deriveStatus, deriveVerification, buildModel };
