/**
 * Shared Gemini Client for Dex Intel Scripts
 * 
 * Uses Gemini 3 Pro via the Google Generative AI SDK.
 * API Key: Set GEMINI_API_KEY environment variable
 * 
 * Model: gemini-3-pro-preview (1M context, dynamic thinking)
 * Pricing: $2/M input, $12/M output
 * 
 * @see https://ai.google.dev/gemini-api/docs/gemini-3
 */

const path = require('path');
require('dotenv').config({ path: path.resolve(__dirname, '../../.env') });

const { GoogleGenerativeAI } = require('@google/generative-ai');

// Configuration
const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
const DEFAULT_MODEL = 'gemini-3-pro-preview';

/**
 * Create a Gemini client instance
 */
function createClient() {
  if (!GEMINI_API_KEY) {
    throw new Error('GEMINI_API_KEY environment variable is required');
  }
  return new GoogleGenerativeAI(GEMINI_API_KEY);
}

/**
 * Generate content using Gemini 3 Pro
 * 
 * @param {string} prompt - The prompt to send
 * @param {Object} options - Optional configuration
 * @param {string} options.model - Model ID (default: gemini-3-pro-preview)
 * @param {number} options.maxOutputTokens - Max output tokens (default: 2000)
 * @param {string} options.thinkingLevel - Thinking level: 'LOW' or 'HIGH' (default: 'LOW')
 * @returns {Promise<string>} - The generated text
 */
async function generateContent(prompt, options = {}) {
  const {
    model = DEFAULT_MODEL,
    maxOutputTokens = 2000,
    thinkingLevel = 'LOW'
  } = options;

  const client = createClient();
  const genModel = client.getGenerativeModel({ 
    model,
    generationConfig: {
      maxOutputTokens,
    }
  });

  // Note: SDK may not support thinkingConfig yet, use generateContentRaw for full control
  const result = await genModel.generateContent({
    contents: [{ role: 'user', parts: [{ text: prompt }] }],
    generationConfig: {
      maxOutputTokens,
    }
  });

  const response = result.response;
  return response.text();
}

/**
 * Generate content with raw https (recommended for Gemini 3 with thinking control)
 * 
 * @param {string} prompt - The prompt to send
 * @param {Object} options - Optional configuration
 * @param {string} options.thinkingLevel - 'LOW' for fast responses, 'HIGH' for deep reasoning
 * @returns {Promise<string>} - The generated text
 */
function generateContentRaw(prompt, options = {}) {
  const https = require('https');
  
  const {
    model = DEFAULT_MODEL,
    maxOutputTokens = 2000,
    thinkingLevel = 'LOW'  // 'LOW' for speed, 'HIGH' for complex reasoning
  } = options;

  return new Promise((resolve, reject) => {
    if (!GEMINI_API_KEY) {
      reject(new Error('GEMINI_API_KEY environment variable is required'));
      return;
    }

    const data = JSON.stringify({
      contents: [{ 
        role: 'user', 
        parts: [{ text: prompt }] 
      }],
      generationConfig: {
        maxOutputTokens,
        thinkingConfig: {
          thinkingLevel
        }
      }
    });

    const requestOptions = {
      hostname: 'generativelanguage.googleapis.com',
      port: 443,
      path: `/v1beta/models/${model}:generateContent?key=${GEMINI_API_KEY}`,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(data)
      }
    };

    const req = https.request(requestOptions, (res) => {
      let responseData = '';
      res.on('data', chunk => responseData += chunk);
      res.on('end', () => {
        try {
          const json = JSON.parse(responseData);
          if (json.error) {
            reject(new Error(json.error.message));
          } else {
            const text = json.candidates?.[0]?.content?.parts?.[0]?.text || '';
            resolve(text);
          }
        } catch (e) {
          reject(new Error(`Failed to parse response: ${responseData.substring(0, 200)}`));
        }
      });
    });

    req.on('error', reject);
    req.setTimeout(120000, () => {
      req.destroy();
      reject(new Error('Request timeout'));
    });

    req.write(data);
    req.end();
  });
}

module.exports = {
  createClient,
  generateContent,
  generateContentRaw,
  DEFAULT_MODEL,
  GEMINI_API_KEY
};
