// Lifted from dex-desktop@2b34aa4d: packages/dex-engine/oauth-refresh.js
// ============================================================================
// DEX ENGINE — shared OAuth refresh-token-grant machinery
// ----------------------------------------------------------------------------
// Generalized from the Slack-first rotating-token refresh
// (integration-token-auto-refresh, shipped 2026-07-03). Any integration that
// holds an OAuth `refresh_token` plus an access-token expiry can reuse this
// module: decide whether a token is due for renewal, exchange the refresh
// token for a new access token, and tell a dead grant (the user must
// reconnect) apart from a flaky network call (safe to keep using the stored
// token and retry next time).
//
// Pure module: no Electron, no fs, no app state. Callers own persistence.
// ============================================================================

"use strict";

const rateLimit = require("./rate-limit");

// Upper bound on how long we honor a provider-supplied `Retry-After`. A 429
// carrying a huge delay must never be allowed to stall the refresh path for
// minutes — we cap the honored backoff at a sane maximum.
const MAX_RETRY_AFTER_MS = 60 * 1000;

// A token can be renewed once it is within this many ms of expiring. Callers
// may pass a tighter/looser buffer per integration.
const DEFAULT_REFRESH_BUFFER_MS = 5 * 60 * 1000;

// How long to wait for the token endpoint before giving up. Without this a
// hung TCP connect blocks the whole chat/routine spawn that awaited the
// refresh — a stalled provider must never freeze a reply. Treated as a
// transient failure (keep the stored token, try again next time).
const DEFAULT_REFRESH_TIMEOUT_MS = 10 * 1000;

// A single retry smooths over a one-off network blip so a transient hiccup
// doesn't force the caller to wait for the next natural refresh trigger.
// Permanent errors (a dead grant) are never retried.
const DEFAULT_REFRESH_MAX_RETRIES = 1;
const DEFAULT_REFRESH_RETRY_DELAY_MS = 500;

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Error codes (OAuth2 standard + Slack's own) that mean the refresh token
// itself is dead — no amount of retrying fixes these; the user must sign in
// again. Anything else (network errors, timeouts, 5xx, an unrecognized code)
// is treated as transient so a flaky moment never forces a needless reconnect.
const PERMANENT_ERROR_CODES = new Set([
	"invalid_grant",
	"invalid_refresh_token",
	"token_revoked",
	"token_expired",
	"account_inactive",
	"invalid_client",
	"unauthorized_client",
]);

// True once `record` (an on-disk token record shaped { refreshToken, expiresAt })
// is close enough to expiry to renew. Both fields must be present: a token
// with no refresh_token or no known expiry can never be proactively refreshed
// — the caller just keeps using it until the provider itself rejects it.
function isRefreshDue(record, bufferMs = DEFAULT_REFRESH_BUFFER_MS) {
	return !!(record && record.refreshToken && record.expiresAt && Date.now() >= record.expiresAt - bufferMs);
}

class RefreshError extends Error {
	constructor(message, { permanent = false, cause, retryAfterMs } = {}) {
		super(message);
		this.name = "RefreshError";
		this.permanent = permanent;
		// A rate-limit hint (ms) carried on a transient 429 so the retry loop
		// can back off appropriately. Null when there is no usable hint.
		this.retryAfterMs = retryAfterMs ?? null;
		if (cause) this.cause = cause;
	}
}

// Standard OAuth2 token-response shape: { access_token, refresh_token, expires_in }.
// Slack nests the rotated user token under `authed_user` on some grants; the
// caller resolves that before calling this (see `refreshOAuthToken` below).
function defaultParseTokenResponse(data) {
	const accessToken = typeof data?.access_token === "string" ? data.access_token.trim() : "";
	if (!accessToken) return null;
	return {
		accessToken,
		refreshToken: typeof data?.refresh_token === "string" && data.refresh_token ? data.refresh_token : null,
		expiresIn: Number(data?.expires_in),
	};
}

// Exchange a refresh token for a fresh access token via the standard
// `grant_type=refresh_token` flow. Resolves to
// `{ accessToken, refreshToken, expiresAt, raw }` (raw is the parsed provider
// response, for callers that need a provider-specific extra like Slack's
// `team.id`). Throws a `RefreshError` on any failure; `.permanent` tells the
// caller whether this is a dead grant (reconnect) or a transient hiccup
// (keep the existing token, try again next time).
async function refreshOAuthToken({
	tokenUrl,
	refreshToken,
	clientId,
	clientSecret,
	fetchImpl = globalThis.fetch,
	extraParams = {},
	parseTokenResponse = defaultParseTokenResponse,
	isPermanentError = (data) => PERMANENT_ERROR_CODES.has(String(data?.error || "").trim()),
	timeoutMs = DEFAULT_REFRESH_TIMEOUT_MS,
	maxRetries = DEFAULT_REFRESH_MAX_RETRIES,
	retryDelayMs = DEFAULT_REFRESH_RETRY_DELAY_MS,
	// DEX CORE DIVERGENCE: injectable delay keeps Retry-After/clamp tests instant.
	delayImpl = delay,
} = {}) {
	if (typeof fetchImpl !== "function") {
		throw new RefreshError("No fetch implementation available for token refresh", { permanent: false });
	}
	if (!refreshToken) {
		throw new RefreshError("No refresh token on file", { permanent: false });
	}

	const body = new URLSearchParams({
		grant_type: "refresh_token",
		refresh_token: refreshToken,
		client_id: clientId,
		...(clientSecret ? { client_secret: clientSecret } : {}),
		...extraParams,
	}).toString();

	// One network exchange, bounded by a timeout. A hang or transient network
	// error throws a non-permanent RefreshError so the retry loop below can try
	// again; a dead grant throws a permanent one that must not be retried.
	async function attemptRefresh() {
		const controller = new AbortController();
		const timer = setTimeout(() => controller.abort(), timeoutMs);
		let response;
		try {
			response = await fetchImpl(tokenUrl, {
				method: "POST",
				headers: { "Content-Type": "application/x-www-form-urlencoded" },
				body,
				signal: controller.signal,
				// DEX CORE DIVERGENCE: A 307/308 can preserve the POST body.
				// Never let a refresh token or client secret cross a redirect.
				redirect: "error",
			});
		} catch (error) {
			const timedOut = controller.signal.aborted || error?.name === "AbortError";
			throw new RefreshError(
				timedOut ? `Token refresh timed out after ${timeoutMs}ms` : `Token refresh request failed: ${error?.message || "unknown"}`,
				{ permanent: false, cause: error },
			);
		} finally {
			clearTimeout(timer);
		}

		let data;
		try {
			data = await response.json();
		} catch (error) {
			throw new RefreshError("Token refresh returned a non-JSON response", { permanent: false, cause: error });
		}

		// Slack signals failure via `ok: false` (HTTP 200, error in the body);
		// standard OAuth2 signals failure via an `error` field, usually with a
		// 4xx status. Either way, classify before trusting the payload.
		const failed = data?.ok === false || !!data?.error;
		if (failed) {
			// A Slack `{ ok:false, error:"ratelimited" }` body is a rate limit,
			// never a dead grant: force transient and carry the Retry-After hint
			// (from the body `retry_after` or the response headers). Other error
			// codes keep the existing permanent/transient classification.
			if (rateLimit.is429(data)) {
				throw new RefreshError(data?.error_description || data?.error || "Token refresh was rate limited", {
					permanent: false,
					retryAfterMs: rateLimit.retryAfterMs(data) ?? rateLimit.retryAfterMs(response),
				});
			}
			throw new RefreshError(data?.error_description || data?.error || "Token refresh was rejected", {
				permanent: isPermanentError(data),
			});
		}
		if (response && typeof response.ok === "boolean" && !response.ok) {
			const status = Number(response.status) || 0;
			// A 429 on the token endpoint is a rate limit, NOT a dead grant —
			// classify it transient and honor Retry-After. Only genuine 4xx auth
			// failures (400/401/403 …) stay permanent.
			const isRateLimited = status === 429;
			throw new RefreshError(`Token refresh failed (HTTP ${status})`, {
				permanent: status >= 400 && status < 500 && !isRateLimited,
				retryAfterMs: isRateLimited ? rateLimit.retryAfterMs(response) ?? rateLimit.retryAfterMs(data) : null,
			});
		}

		// Slack nests the rotated user token under `authed_user`; Google and
		// Microsoft use the top-level standard shape.
		const source = data?.authed_user && typeof data.authed_user === "object" ? data.authed_user : data;
		const parsed = parseTokenResponse(source);
		if (!parsed || !parsed.accessToken) {
			throw new RefreshError("Token refresh response did not include a usable access token", { permanent: false });
		}

		const expiresIn = Number(parsed.expiresIn);
		return {
			accessToken: parsed.accessToken,
			refreshToken: parsed.refreshToken || refreshToken,
			expiresAt: Number.isFinite(expiresIn) && expiresIn > 0 ? Date.now() + expiresIn * 1000 : null,
			raw: data,
		};
	}

	let attempt = 0;
	for (;;) {
		try {
			return await attemptRefresh();
		} catch (error) {
			const transient = error instanceof RefreshError && error.permanent === false;
			if (transient && attempt < maxRetries) {
				attempt += 1;
				// Honor a rate-limit hint (a 429's Retry-After) when it is longer
				// than the flat retry delay, but never wait an unbounded
				// provider-supplied delay — clamp to MAX_RETRY_AFTER_MS.
				const hint = Number.isFinite(error.retryAfterMs) && error.retryAfterMs > 0 ? error.retryAfterMs : 0;
				const waitMs = Math.min(Math.max(retryDelayMs, hint), MAX_RETRY_AFTER_MS);
				if (waitMs > 0) await delayImpl(waitMs);
				continue;
			}
			throw error;
		}
	}
}

// Dedupe concurrent refreshes for the same credential. The chat lane and the
// routines lane can each decide "this token is due" in the same tick; without
// this they would fire two refresh requests and race two writes to the same
// token file. Callers share one instance and key by provider/group name.
function createSingleFlight() {
	const inFlight = new Map();
	return function run(key, fn) {
		if (inFlight.has(key)) return inFlight.get(key);
		const promise = Promise.resolve()
			.then(fn)
			.finally(() => inFlight.delete(key));
		inFlight.set(key, promise);
		return promise;
	};
}

module.exports = {
	DEFAULT_REFRESH_BUFFER_MS,
	DEFAULT_REFRESH_TIMEOUT_MS,
	DEFAULT_REFRESH_MAX_RETRIES,
	PERMANENT_ERROR_CODES,
	RefreshError,
	isRefreshDue,
	refreshOAuthToken,
	createSingleFlight,
};
