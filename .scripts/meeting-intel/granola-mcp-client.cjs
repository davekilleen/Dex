#!/usr/bin/env node

/**
 * Granola MCP Streamable HTTP Client
 *
 * Communicates with Granola's official MCP server at https://mcp.granola.ai/mcp
 * using the MCP Streamable HTTP transport (JSON-RPC 2.0 over HTTP with SSE support).
 *
 * No npm dependencies — uses Node.js built-in https module only.
 * Designed to run in a launchd background job.
 */

const https = require('https');
const fs = require('fs');
const path = require('path');
const os = require('os');
const { URL } = require('url');

// ============================================================================
// CONFIGURATION
// ============================================================================

const MCP_ENDPOINT = 'https://mcp.granola.ai/mcp';
const TOKEN_FILE = path.join(os.homedir(), '.config', 'dex', 'granola-tokens.json');
const MAX_RETRIES = 3;
const INITIAL_BACKOFF_MS = 1000;
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes

// ============================================================================
// LOGGING
// ============================================================================

function log(message) {
  const timestamp = new Date().toISOString();
  console.log(`[${timestamp}] [granola-mcp] ${message}`);
}

// ============================================================================
// TOKEN MANAGEMENT
// ============================================================================

/**
 * Load tokens from the tokens file.
 * Returns null if file doesn't exist or is unreadable.
 */
function loadTokens() {
  if (!fs.existsSync(TOKEN_FILE)) {
    return null;
  }
  try {
    const raw = fs.readFileSync(TOKEN_FILE, 'utf-8');
    return JSON.parse(raw);
  } catch (e) {
    log(`Failed to read tokens file: ${e.message}`);
    return null;
  }
}

/**
 * Save tokens back to the tokens file.
 */
function saveTokens(tokens) {
  try {
    const dir = path.dirname(TOKEN_FILE);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(TOKEN_FILE, JSON.stringify(tokens, null, 2));
  } catch (e) {
    log(`Failed to save tokens: ${e.message}`);
  }
}

/**
 * Check if the access token is expired.
 */
function isTokenExpired(tokens) {
  if (!tokens || !tokens.expires_at) return true;
  // Consider expired if within 60 seconds of expiry
  return Date.now() >= (tokens.expires_at * 1000 - 60000);
}

/**
 * Refresh the access token using the refresh token.
 * Returns updated tokens or null on failure.
 */
async function refreshAccessToken(tokens) {
  if (!tokens.refresh_token || !tokens.token_endpoint) {
    log('Cannot refresh: missing refresh_token or token_endpoint');
    return null;
  }

  log('Refreshing access token...');

  const body = new URLSearchParams({
    grant_type: 'refresh_token',
    refresh_token: tokens.refresh_token,
    client_id: tokens.client_id || '',
    client_secret: tokens.client_secret || '',
  }).toString();

  return new Promise((resolve) => {
    const url = new URL(tokens.token_endpoint);

    const req = https.request({
      hostname: url.hostname,
      port: url.port || 443,
      path: url.pathname + url.search,
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Content-Length': Buffer.byteLength(body),
      },
      timeout: 15000,
    }, (res) => {
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => {
        const responseBody = Buffer.concat(chunks).toString('utf-8');
        if (res.statusCode === 200) {
          try {
            const data = JSON.parse(responseBody);
            const updated = {
              ...tokens,
              access_token: data.access_token,
              refresh_token: data.refresh_token || tokens.refresh_token,
              expires_at: data.expires_in
                ? Math.floor(Date.now() / 1000) + data.expires_in
                : tokens.expires_at,
            };
            saveTokens(updated);
            log('Token refreshed successfully');
            resolve(updated);
          } catch (e) {
            log(`Token refresh parse error: ${e.message}`);
            resolve(null);
          }
        } else {
          log(`Token refresh failed with status ${res.statusCode}: ${responseBody.slice(0, 200)}`);
          resolve(null);
        }
      });
      res.on('error', (e) => {
        log(`Token refresh stream error: ${e.message}`);
        resolve(null);
      });
    });

    req.on('error', (e) => {
      log(`Token refresh request error: ${e.message}`);
      resolve(null);
    });
    req.on('timeout', () => {
      req.destroy();
      log('Token refresh timed out');
      resolve(null);
    });

    req.write(body);
    req.end();
  });
}

/**
 * Get a valid access token, refreshing if necessary.
 * Returns the token string or null.
 */
async function getValidToken() {
  let tokens = loadTokens();
  if (!tokens) return null;

  if (isTokenExpired(tokens)) {
    tokens = await refreshAccessToken(tokens);
    if (!tokens) return null;
  }

  return tokens.access_token || null;
}

// ============================================================================
// HTTP TRANSPORT
// ============================================================================

/**
 * Send a JSON-RPC 2.0 request to the MCP endpoint.
 * Handles both JSON and SSE (Server-Sent Events) responses.
 *
 * @param {object} payload - JSON-RPC 2.0 request body
 * @param {string} accessToken - Bearer token
 * @param {string|null} sessionId - MCP session ID (from previous responses)
 * @returns {Promise<{result: object, sessionId: string|null}>}
 */
async function mcpRequest(payload, accessToken, sessionId) {
  const url = new URL(MCP_ENDPOINT);
  const body = JSON.stringify(payload);

  const headers = {
    'Content-Type': 'application/json',
    'Accept': 'application/json, text/event-stream',
    'Authorization': `Bearer ${accessToken}`,
    'Content-Length': Buffer.byteLength(body),
  };

  if (sessionId) {
    headers['Mcp-Session-Id'] = sessionId;
  }

  return new Promise((resolve, reject) => {
    const req = https.request({
      hostname: url.hostname,
      port: url.port || 443,
      path: url.pathname + url.search,
      method: 'POST',
      headers,
      timeout: 30000,
    }, (res) => {
      const newSessionId = res.headers['mcp-session-id'] || sessionId;
      const contentType = (res.headers['content-type'] || '').toLowerCase();

      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => {
        const responseBody = Buffer.concat(chunks).toString('utf-8');

        if (res.statusCode === 401) {
          reject(new McpError('TOKEN_EXPIRED', `Authentication failed (401)`));
          return;
        }
        if (res.statusCode === 429) {
          reject(new McpError('RATE_LIMITED', `Rate limited (429)`));
          return;
        }
        if (res.statusCode >= 500) {
          reject(new McpError('SERVER_ERROR', `Server error (${res.statusCode})`));
          return;
        }
        if (res.statusCode !== 200) {
          reject(new McpError('HTTP_ERROR', `HTTP ${res.statusCode}: ${responseBody.slice(0, 200)}`));
          return;
        }

        // Handle SSE responses
        if (contentType.includes('text/event-stream')) {
          const result = parseSSEResponse(responseBody);
          resolve({ result, sessionId: newSessionId });
          return;
        }

        // Handle JSON responses
        try {
          const data = JSON.parse(responseBody);
          if (data.error) {
            reject(new McpError('RPC_ERROR', `JSON-RPC error: ${data.error.message || JSON.stringify(data.error)}`));
            return;
          }
          resolve({ result: data.result || data, sessionId: newSessionId });
        } catch (e) {
          reject(new McpError('PARSE_ERROR', `Failed to parse response: ${e.message}`));
        }
      });

      res.on('error', (e) => {
        reject(new McpError('STREAM_ERROR', `Response stream error: ${e.message}`));
      });
    });

    req.on('error', (e) => {
      reject(new McpError('REQUEST_ERROR', `Request error: ${e.message}`));
    });
    req.on('timeout', () => {
      req.destroy();
      reject(new McpError('TIMEOUT', 'Request timed out'));
    });

    req.write(body);
    req.end();
  });
}

/**
 * Parse a Server-Sent Events response body.
 * Extracts the last JSON-RPC result from the SSE stream.
 */
function parseSSEResponse(body) {
  const lines = body.split('\n');
  let lastData = null;

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('data:')) {
      const dataStr = trimmed.slice(5).trim();
      if (dataStr && dataStr !== '[DONE]') {
        try {
          const parsed = JSON.parse(dataStr);
          lastData = parsed;
        } catch (e) {
          // Not valid JSON, skip
        }
      }
    }
  }

  if (!lastData) {
    return null;
  }

  // Extract the result from the JSON-RPC response
  if (lastData.result) {
    return lastData.result;
  }
  if (lastData.error) {
    throw new McpError('RPC_ERROR', `SSE JSON-RPC error: ${lastData.error.message || JSON.stringify(lastData.error)}`);
  }

  return lastData;
}

// ============================================================================
// ERROR HANDLING
// ============================================================================

class McpError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
    this.name = 'McpError';
  }
}

/**
 * Determine if an error is retryable.
 */
function isRetryable(error) {
  if (!(error instanceof McpError)) return false;
  return ['RATE_LIMITED', 'SERVER_ERROR', 'TIMEOUT', 'REQUEST_ERROR', 'STREAM_ERROR'].includes(error.code);
}

// ============================================================================
// RESPONSE CACHE
// ============================================================================

class ResponseCache {
  constructor(ttlMs = CACHE_TTL_MS) {
    this.ttlMs = ttlMs;
    this.entries = new Map();
  }

  get(key) {
    const entry = this.entries.get(key);
    if (!entry) return null;
    if (Date.now() - entry.timestamp > this.ttlMs) {
      this.entries.delete(key);
      return null;
    }
    return entry.value;
  }

  set(key, value) {
    this.entries.set(key, {
      value,
      timestamp: Date.now(),
    });
  }

  clear() {
    this.entries.clear();
  }
}

// ============================================================================
// MCP CLIENT
// ============================================================================

/**
 * Create a new MCP client instance for communicating with Granola's MCP server.
 */
function createMcpClient() {
  let sessionId = null;
  let initialized = false;
  let requestIdCounter = 1;
  const cache = new ResponseCache();

  /**
   * Check if the MCP client can be used (tokens exist and are loadable).
   */
  function isAvailable() {
    const tokens = loadTokens();
    return tokens !== null && !!tokens.access_token;
  }

  /**
   * Build a JSON-RPC 2.0 request envelope.
   */
  function buildRequest(method, params = {}) {
    return {
      jsonrpc: '2.0',
      id: requestIdCounter++,
      method,
      params,
    };
  }

  /**
   * Send a request with retry and exponential backoff.
   */
  async function sendWithRetry(payload, cacheKey = null) {
    // Check cache first
    if (cacheKey) {
      const cached = cache.get(cacheKey);
      if (cached !== null) {
        log(`Cache hit for ${cacheKey}`);
        return cached;
      }
    }

    const token = await getValidToken();
    if (!token) {
      throw new McpError('NO_TOKEN', 'No valid access token available');
    }

    let lastError = null;
    let backoff = INITIAL_BACKOFF_MS;

    for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
      try {
        const response = await mcpRequest(payload, token, sessionId);
        sessionId = response.sessionId;

        // Cache the result
        if (cacheKey && response.result) {
          cache.set(cacheKey, response.result);
        }

        return response.result;
      } catch (error) {
        lastError = error;

        // Token expired — try refreshing once
        if (error instanceof McpError && error.code === 'TOKEN_EXPIRED' && attempt === 1) {
          log('Token expired, attempting refresh...');
          const tokens = loadTokens();
          if (tokens) {
            const refreshed = await refreshAccessToken(tokens);
            if (refreshed) {
              // Retry immediately with new token
              continue;
            }
          }
          throw error;
        }

        if (!isRetryable(error) || attempt === MAX_RETRIES) {
          throw error;
        }

        log(`Attempt ${attempt}/${MAX_RETRIES} failed (${error.code}), retrying in ${backoff}ms...`);
        await new Promise(r => setTimeout(r, backoff));
        backoff *= 2;
      }
    }

    throw lastError;
  }

  /**
   * Initialize the MCP session.
   * Must be called before any tool calls.
   */
  async function initialize() {
    if (initialized) return;

    log('Initializing MCP session...');
    const payload = buildRequest('initialize', {
      protocolVersion: '2025-03-26',
      capabilities: {},
      clientInfo: {
        name: 'dex-meeting-intel',
        version: '2.0.0',
      },
    });

    const result = await sendWithRetry(payload);
    initialized = true;
    log(`MCP session initialized (session: ${sessionId || 'none'})`);

    // Send initialized notification (no response expected, but some servers require it)
    try {
      const notifyPayload = {
        jsonrpc: '2.0',
        method: 'notifications/initialized',
        params: {},
      };
      const token = await getValidToken();
      if (token) {
        // Fire and forget — notifications don't get responses
        await mcpRequest(notifyPayload, token, sessionId).catch(() => {});
      }
    } catch (e) {
      // Notification failure is non-fatal
    }

    return result;
  }

  /**
   * Call an MCP tool by name.
   */
  async function callTool(name, args = {}, cacheKey = null) {
    if (!initialized) {
      await initialize();
    }

    const payload = buildRequest('tools/call', {
      name,
      arguments: args,
    });

    return sendWithRetry(payload, cacheKey);
  }

  /**
   * List meetings from Granola.
   * Returns meeting metadata (IDs, titles, dates, attendees) — no content.
   */
  async function listMeetings() {
    log('Calling list_meetings...');
    const result = await callTool('list_meetings', {}, 'list_meetings');
    return extractToolContent(result);
  }

  /**
   * Get full meeting content for specific meeting IDs.
   * Returns notes, attendees, enhanced notes.
   */
  async function getMeetings(meetingIds) {
    if (!meetingIds || meetingIds.length === 0) return [];
    log(`Calling get_meetings for ${meetingIds.length} meeting(s)...`);
    const result = await callTool('get_meetings', { meeting_ids: meetingIds });
    return extractToolContent(result);
  }

  /**
   * Get the raw transcript for a specific meeting.
   * May fail on free tiers.
   */
  async function getTranscript(meetingId) {
    log(`Calling get_meeting_transcript for ${meetingId}...`);
    try {
      const result = await callTool('get_meeting_transcript', { meeting_id: meetingId });
      return extractToolContent(result);
    } catch (e) {
      // Transcript may not be available on all tiers
      log(`Transcript unavailable for ${meetingId}: ${e.message}`);
      return null;
    }
  }

  /**
   * Query meetings using natural language.
   */
  async function queryMeetings(query) {
    log(`Calling query_granola_meetings: "${query}"...`);
    const result = await callTool('query_granola_meetings', { query });
    return extractToolContent(result);
  }

  /**
   * Extract content from tool call result.
   * MCP tool results come as: { content: [{ type: "text", text: "..." }] }
   */
  function extractToolContent(result) {
    if (!result) return null;

    // If result has content array (standard MCP tool result format)
    if (result.content && Array.isArray(result.content)) {
      const textParts = result.content
        .filter(c => c.type === 'text')
        .map(c => c.text);

      const combined = textParts.join('\n');

      // Try to parse as JSON
      try {
        return JSON.parse(combined);
      } catch (e) {
        // Return as plain text
        return combined;
      }
    }

    // If result is already structured data
    return result;
  }

  /**
   * Close the session (clean up).
   */
  function close() {
    sessionId = null;
    initialized = false;
    cache.clear();
    requestIdCounter = 1;
  }

  return {
    isAvailable,
    initialize,
    callTool,
    listMeetings,
    getMeetings,
    getTranscript,
    queryMeetings,
    close,
  };
}

// ============================================================================
// EXPORTS
// ============================================================================

module.exports = {
  createMcpClient,
};
