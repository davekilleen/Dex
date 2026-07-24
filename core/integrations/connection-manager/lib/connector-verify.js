// Lifted from dex-desktop@2b34aa4d: packages/dex-engine/connector-verify.js
// DEX CORE DIVERGENCE: provider ids/endpoints match Core (google calendarList,
// slack auth.test, Linear viewer GraphQL); only 401/403-class evidence breaks.
"use strict";

const rateLimit = require("./rate-limit");

const DEFAULT_TIMEOUT_MS = 5 * 1000;
const CATEGORY = Object.freeze({
	NO_TOKEN: "no_token",
	UNSUPPORTED: "unsupported",
	AUTH_PERMANENT: "auth_permanent",
	RATE_LIMITED: "rate_limited",
	TIMEOUT: "timeout",
	OFFLINE: "offline",
	HTTP_ERROR: "http_error",
	OK: "ok",
});

const PROBES = Object.freeze({
	google: {
		buildRequest(token) {
			return {
				url: "https://www.googleapis.com/calendar/v3/users/me/calendarList?maxResults=1",
				method: "GET",
				headers: { Authorization: `Bearer ${token}` },
			};
		},
		parseIdentity(status, body) {
			if (status !== 200 || !body || !Array.isArray(body.items)) return null;
			const calendar = body.items.find((item) => item && item.primary === true) || body.items[0];
			return calendar && calendar.id ? { id: calendar.id, provider: "google" } : null;
		},
	},
	slack: {
		buildRequest(token) {
			return {
				url: "https://slack.com/api/auth.test",
				method: "POST",
				headers: {
					Authorization: `Bearer ${token}`,
					"Content-Type": "application/x-www-form-urlencoded",
				},
			};
		},
		parseIdentity(_status, body) {
			if (!body || body.ok !== true) return null;
			return {
				teamId: body.team_id || null,
				userId: body.user_id || null,
			};
		},
	},
	linear: {
		buildRequest(token) {
			return {
				url: "https://api.linear.app/graphql",
				method: "POST",
				headers: { Authorization: token, "Content-Type": "application/json" },
				body: JSON.stringify({ query: "{ viewer { id } }" }),
			};
		},
		parseIdentity(status, body) {
			const id = status === 200 && body && body.data && body.data.viewer && body.data.viewer.id;
			return id ? { id, provider: "linear" } : null;
		},
	},
});

function baseResult(overrides) {
	return {
		ok: false,
		httpStatus: null,
		accountIdentity: null,
		error: null,
		at: null,
		...overrides,
	};
}

function linearAuthStatus(body) {
	if (!body || !Array.isArray(body.errors)) return null;
	for (const error of body.errors) {
		const ext = error && error.extensions;
		if (!ext || ext.code !== "AUTHENTICATION_ERROR") continue;
		const status = Number(ext.statusCode || ext.status || (ext.http && ext.http.status));
		if (status === 401 || status === 403) return status;
	}
	return null;
}

function mapProbeResult(response, probe, nowMs = Date.now()) {
	const status = Number.isFinite(response && response.status) ? response.status : null;
	const body = response && response.body != null ? response.body : null;

	if (rateLimit.is429(status) || rateLimit.is429(body)) {
		const retryAfterMs =
			rateLimit.retryAfterMs(body, nowMs) ??
			(response && response.headers != null ? rateLimit.retryAfterMs(response, nowMs) : null);
		return {
			ok: false,
			httpStatus: status,
			error: {
				category: CATEGORY.RATE_LIMITED,
				...(retryAfterMs != null ? { retryAfterMs } : {}),
			},
		};
	}

	const embeddedAuthStatus = linearAuthStatus(body);
	if (status === 401 || status === 403 || embeddedAuthStatus) {
		const authStatus = embeddedAuthStatus || status;
		return {
			ok: false,
			httpStatus: status,
			error: { category: CATEGORY.AUTH_PERMANENT, code: authStatus, message: `HTTP ${authStatus}` },
		};
	}

	if (body && body.ok === false) {
		return {
			ok: false,
			httpStatus: status,
			error: { category: CATEGORY.HTTP_ERROR, code: body.error || status || undefined },
		};
	}

	if (status != null && status >= 200 && status < 300) {
		const accountIdentity = probe.parseIdentity(status, body);
		if (accountIdentity) return { ok: true, httpStatus: status, accountIdentity, error: null };
	}

	return {
		ok: false,
		httpStatus: status,
		error: { category: CATEGORY.HTTP_ERROR, code: status },
	};
}

function toLedgerRow(connectorId, result) {
	return {
		op: "probe",
		connectorId: connectorId != null ? connectorId : null,
		ok: result && result.ok === true,
		httpStatus: result && result.httpStatus != null ? result.httpStatus : null,
		latencyMs: result && Number.isFinite(result.latencyMs) ? result.latencyMs : null,
		error: result && result.error != null ? result.error : null,
	};
}

function createConnectorVerify({ fetchImpl = globalThis.fetch, timeoutMs = DEFAULT_TIMEOUT_MS, now = Date.now } = {}) {
	async function verify(connectorId, opts = {}) {
		const startedAt = now();
		const finish = (partial) =>
			baseResult({
				...partial,
				latencyMs: Math.max(0, now() - startedAt),
				at: new Date(now()).toISOString(),
			});
		if (!opts.token) return finish({ error: { category: CATEGORY.NO_TOKEN } });
		const probe = PROBES[opts.provider];
		if (!probe) return finish({ error: { category: CATEGORY.UNSUPPORTED } });
		if (typeof fetchImpl !== "function") {
			return finish({ error: { category: CATEGORY.OFFLINE, message: "no fetch implementation available" } });
		}

		const request = probe.buildRequest(opts.token, opts);
		const controller = new AbortController();
		const timer = setTimeout(() => controller.abort(), timeoutMs);
		let response;
		try {
			response = await fetchImpl(request.url, {
				method: request.method || "GET",
				headers: request.headers || {},
				...(request.body != null ? { body: request.body } : {}),
				signal: controller.signal,
				// DEX CORE DIVERGENCE: verification requests carry credentials.
				// The provider must answer directly; redirects are never trusted.
				redirect: "error",
			});
		} catch (error) {
			const timedOut = controller.signal.aborted || (error && error.name === "AbortError");
			return finish({
				error: {
					category: timedOut ? CATEGORY.TIMEOUT : CATEGORY.OFFLINE,
					message: timedOut
						? `verify timed out after ${timeoutMs}ms`
						: `verify request failed: ${(error && error.message) || "unknown"}`,
				},
			});
		} finally {
			clearTimeout(timer);
		}

		let body;
		try {
			body = await response.json();
		} catch (error) {
			return finish({
				httpStatus: Number.isFinite(response && response.status) ? response.status : null,
				error: { category: CATEGORY.OFFLINE, message: `verify returned non-JSON: ${error.message}` },
			});
		}
		return finish(
			mapProbeResult(
				{ status: response.status, body, headers: response.headers },
				probe,
				now(),
			),
		);
	}

	return { verify, PROBES, mapProbeResult, toLedgerRow };
}

module.exports = {
	createConnectorVerify,
	PROBES,
	mapProbeResult,
	toLedgerRow,
	CATEGORY,
	DEFAULT_TIMEOUT_MS,
};
