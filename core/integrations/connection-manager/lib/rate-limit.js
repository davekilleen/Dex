// Lifted from dex-desktop@2b34aa4d: packages/dex-engine/rate-limit.js
// ============================================================================
// DEX ENGINE — pure rate-limit / 429 / Retry-After helpers
// ----------------------------------------------------------------------------
// A dependency-free CommonJS module shared by `oauth-refresh`, the read MCP
// servers (slack-mcp / google-mcp), and `connector-verify`. Its job is to turn
// the several shapes a "you are rate limited" signal arrives in — an HTTP 429
// status, a Slack `{ error: "ratelimited" }` body, a `Retry-After` header in
// either delta-seconds or HTTP-date form, or a Slack body-level `retry_after`
// hint — into two plain answers:
//
//   * is it a 429? (`is429`)
//   * how long should we wait before retrying, in ms? (`parseRetryAfter` /
//     `retryAfterMs`)
//
// PURE: no I/O, no ambient clock beyond the injectable `nowMs` parameter used
// solely to convert an HTTP-date `Retry-After` into a delta. Everything else is
// a pure function of its inputs so callers can be unit-tested with a fixed
// clock and no network.
// ============================================================================

"use strict";

/**
 * Parse an HTTP `Retry-After` value into milliseconds.
 *
 * The header (RFC 7231 §7.1.3) is EITHER:
 *   - delta-seconds: a non-negative integer, e.g. "120" → 120000 ms.
 *   - an HTTP-date (IMF-fixdate), e.g. "Wed, 21 Oct 2026 07:28:00 GMT" →
 *     max(0, Date.parse(value) - nowMs).
 *
 * A bare number input is treated as delta-seconds too. We try the pure-integer
 * (delta-seconds) form first, then fall back to `Date.parse` for a date string.
 * Negative HTTP-date deltas (a date already in the past) clamp to 0.
 *
 * @param {string|number|null|undefined} value Raw Retry-After value.
 * @param {number} [nowMs=Date.now()] Injectable clock, for the HTTP-date form.
 * @returns {number|null} Milliseconds ≥ 0, or null when absent/unparseable.
 */
function parseRetryAfter(value, nowMs = Date.now()) {
	if (value == null) return null;

	// Numeric input = delta-seconds. Reject NaN / negative / non-finite.
	if (typeof value === "number") {
		if (!Number.isFinite(value) || value < 0) return null;
		return Math.floor(value * 1000);
	}

	if (typeof value !== "string") return null;
	const str = value.trim();
	if (str === "") return null;

	// Pure-digit string = delta-seconds (integer). Try this before Date.parse
	// so a numeric header never gets mistaken for a date.
	if (/^\d+$/.test(str)) {
		const secs = Number(str);
		if (!Number.isFinite(secs) || secs < 0) return null;
		return secs * 1000;
	}

	// Otherwise treat it as an HTTP-date and compute a delta from `nowMs`.
	const parsed = Date.parse(str);
	if (!Number.isFinite(parsed)) return null;
	const base = Number.isFinite(nowMs) ? nowMs : Date.now();
	return Math.max(0, parsed - base);
}

/**
 * Is this a 429 (rate limited) across the shapes callers produce?
 *
 * True when:
 *   - a number === 429;
 *   - an object with `.status === 429`, `.httpStatus === 429`, or
 *     `.statusCode === 429`;
 *   - a Slack-style body `{ error: "ratelimited" }` or `{ error: "rate_limited" }`.
 *
 * Null/undefined-safe.
 *
 * @param {*} statusOrError
 * @returns {boolean}
 */
function is429(statusOrError) {
	if (statusOrError == null) return false;
	if (typeof statusOrError === "number") return statusOrError === 429;
	if (typeof statusOrError !== "object") return false;

	if (
		statusOrError.status === 429 ||
		statusOrError.httpStatus === 429 ||
		statusOrError.statusCode === 429
	) {
		return true;
	}

	const errCode = String(statusOrError.error || "").trim();
	return errCode === "ratelimited" || errCode === "rate_limited";
}

/**
 * Extract a `Retry-After` hint (in ms) from a variety of sources and run it
 * through `parseRetryAfter`.
 *
 * Supported `source` shapes:
 *   - a fetch `Response`-like object (has `.headers.get`);
 *   - a `Headers` instance (has `.get`);
 *   - a plain headers object `{ 'retry-after': '30' }` / `{ 'Retry-After': ... }`
 *     (case-insensitive lookup);
 *   - a bare Retry-After string or number;
 *   - a parsed JSON body object carrying a Slack-style `{ retry_after: <seconds> }`.
 *
 * Returns null when no usable hint is present.
 *
 * @param {*} source
 * @param {number} [nowMs=Date.now()]
 * @returns {number|null}
 */
function retryAfterMs(source, nowMs = Date.now()) {
	if (source == null) return null;

	// Bare value: a string or number is the Retry-After itself.
	if (typeof source === "string" || typeof source === "number") {
		return parseRetryAfter(source, nowMs);
	}

	if (typeof source !== "object") return null;

	// A body-level `retry_after` hint (Slack sometimes puts seconds in the JSON
	// body) is honored first when present — it is the most specific signal.
	if (source.retry_after != null) {
		const fromBody = parseRetryAfter(source.retry_after, nowMs);
		if (fromBody != null) return fromBody;
	}

	// A fetch Response or Headers instance exposes a case-insensitive
	// `headers.get` / `.get`.
	const headers = source.headers != null ? source.headers : source;
	if (headers && typeof headers.get === "function") {
		const raw = headers.get("retry-after");
		if (raw != null) return parseRetryAfter(raw, nowMs);
		return null;
	}

	// Plain object: case-insensitive lookup for the `retry-after` key.
	if (headers && typeof headers === "object") {
		for (const key of Object.keys(headers)) {
			if (key.toLowerCase() === "retry-after") {
				return parseRetryAfter(headers[key], nowMs);
			}
		}
	}

	return null;
}

module.exports = {
	parseRetryAfter,
	is429,
	retryAfterMs,
};
