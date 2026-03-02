#!/usr/bin/env node

/**
 * Multi-provider LLM client
 * Supports Anthropic, OpenAI, and Google Gemini
 */

const https = require('https');

// API endpoints
const ANTHROPIC_API = 'https://api.anthropic.com/v1/messages';
const OPENAI_API = 'https://api.openai.com/v1/chat/completions';
const GEMINI_API_BASE = 'https://generativelanguage.googleapis.com/v1beta/models';

// Load API keys from environment
const ANTHROPIC_KEY = process.env.ANTHROPIC_API_KEY;
const OPENAI_KEY = process.env.OPENAI_API_KEY;
const GEMINI_KEY = process.env.GEMINI_API_KEY;

// Model configuration
const ANTHROPIC_MODEL = process.env.ANTHROPIC_MODEL || 'claude-sonnet-4-5-20250929';
const OPENAI_MODEL = process.env.OPENAI_MODEL || 'gpt-4o';
const GEMINI_MODEL = process.env.GEMINI_MODEL || 'gemini-2.0-flash-exp';

/**
 * Determine which provider is configured
 * Priority order: Anthropic > Gemini > OpenAI
 */
function getActiveProvider() {
  if (ANTHROPIC_KEY) return 'anthropic';
  if (GEMINI_KEY) return 'gemini';
  if (OPENAI_KEY) return 'openai';
  return null;
}

/**
 * Check if any LLM provider is configured
 */
function isConfigured() {
  return getActiveProvider() !== null;
}

/**
 * Make HTTPS request with 120-second timeout
 */
function httpsRequest(url, options, body) {
  return new Promise((resolve, reject) => {
    const urlObj = new URL(url);
    const reqOptions = {
      ...options,
      hostname: urlObj.hostname,
      path: urlObj.pathname + urlObj.search,
      port: 443,
      method: options.method || 'POST',
      timeout: 120000
    };

    const req = https.request(reqOptions, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          try {
            resolve(JSON.parse(data));
          } catch (e) {
            resolve(data);
          }
        } else {
          reject(new Error(`HTTP ${res.statusCode}: ${data}`));
        }
      });
    });

    req.on('timeout', () => {
      req.destroy();
      reject(new Error(`Request timed out after 120 seconds: ${url}`));
    });
    req.on('error', reject);
    if (body) req.write(JSON.stringify(body));
    req.end();
  });
}

/**
 * Call Anthropic API
 */
async function callAnthropic(prompt, options = {}) {
  const { maxOutputTokens = 4096 } = options;

  const body = {
    model: ANTHROPIC_MODEL,
    max_tokens: maxOutputTokens,
    messages: [{ role: 'user', content: prompt }]
  };

  const response = await httpsRequest(ANTHROPIC_API, {
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': ANTHROPIC_KEY,
      'anthropic-version': '2023-06-01'
    }
  }, body);

  if (!response.content || !response.content[0] || !response.content[0].text) {
    throw new Error('Unexpected Anthropic response: missing content[0].text');
  }
  return response.content[0].text;
}

/**
 * Call OpenAI API
 */
async function callOpenAI(prompt, options = {}) {
  const { maxOutputTokens = 4096 } = options;

  const body = {
    model: OPENAI_MODEL,
    max_tokens: maxOutputTokens,
    messages: [{ role: 'user', content: prompt }]
  };

  const response = await httpsRequest(OPENAI_API, {
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${OPENAI_KEY}`
    }
  }, body);

  if (!response.choices || !response.choices[0] || !response.choices[0].message) {
    throw new Error('Unexpected OpenAI response: missing choices[0].message.content');
  }
  return response.choices[0].message.content;
}

/**
 * Call Google Gemini API
 */
async function callGemini(prompt, options = {}) {
  const { maxOutputTokens = 4096 } = options;

  // Gemini uses API key as a URL query parameter per Google's API design
  const url = `${GEMINI_API_BASE}/${GEMINI_MODEL}:generateContent?key=${GEMINI_KEY}`;
  const body = {
    contents: [{ parts: [{ text: prompt }] }],
    generationConfig: { maxOutputTokens }
  };

  const response = await httpsRequest(url, {
    headers: { 'Content-Type': 'application/json' }
  }, body);

  if (!response.candidates || !response.candidates[0] || !response.candidates[0].content ||
      !response.candidates[0].content.parts || !response.candidates[0].content.parts[0]) {
    throw new Error('Unexpected Gemini response: missing candidates[0].content.parts[0].text');
  }
  return response.candidates[0].content.parts[0].text;
}

/**
 * Generate content using configured provider
 */
async function generateContent(prompt, options = {}) {
  const provider = getActiveProvider();

  if (!provider) {
    throw new Error('No LLM API key configured. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY');
  }

  switch (provider) {
    case 'anthropic':
      return callAnthropic(prompt, options);
    case 'openai':
      return callOpenAI(prompt, options);
    case 'gemini':
      return callGemini(prompt, options);
    default:
      throw new Error(`Unknown provider: ${provider}`);
  }
}

module.exports = {
  generateContent,
  isConfigured,
  getActiveProvider
};
