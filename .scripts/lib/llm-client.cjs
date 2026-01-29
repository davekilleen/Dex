#!/usr/bin/env node

/**
 * Unified LLM Client
 * 
 * Supports Anthropic, OpenAI, and Google Gemini with automatic provider selection
 * based on available API keys.
 * 
 * Priority order: Anthropic > OpenAI > Gemini
 */

require('dotenv').config();

const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY;
const OPENAI_API_KEY = process.env.OPENAI_API_KEY;
const GEMINI_API_KEY = process.env.GEMINI_API_KEY;

// Determine which provider to use
function getAvailableProvider() {
  if (ANTHROPIC_API_KEY) return 'anthropic';
  if (OPENAI_API_KEY) return 'openai';
  if (GEMINI_API_KEY) return 'gemini';
  return null;
}

// ============================================================================
// ANTHROPIC CLIENT
// ============================================================================

async function generateWithAnthropic(prompt, options = {}) {
  const Anthropic = require('@anthropic-ai/sdk');
  const anthropic = new Anthropic({ apiKey: ANTHROPIC_API_KEY });
  
  const message = await anthropic.messages.create({
    model: options.model || 'claude-3-5-sonnet-20241022',
    max_tokens: options.maxOutputTokens || 4096,
    messages: [
      {
        role: 'user',
        content: prompt
      }
    ]
  });
  
  return message.content[0].text;
}

// ============================================================================
// OPENAI CLIENT
// ============================================================================

async function generateWithOpenAI(prompt, options = {}) {
  const OpenAI = require('openai');
  const openai = new OpenAI({ apiKey: OPENAI_API_KEY });
  
  const completion = await openai.chat.completions.create({
    model: options.model || 'gpt-4o',
    max_tokens: options.maxOutputTokens || 4096,
    messages: [
      {
        role: 'user',
        content: prompt
      }
    ]
  });
  
  return completion.choices[0].message.content;
}

// ============================================================================
// GEMINI CLIENT
// ============================================================================

async function generateWithGemini(prompt, options = {}) {
  const { GoogleGenerativeAI } = require('@google/generative-ai');
  const genAI = new GoogleGenerativeAI(GEMINI_API_KEY);
  
  const model = genAI.getGenerativeModel({
    model: options.model || 'gemini-2.0-flash-thinking-exp-1219',
    generationConfig: {
      maxOutputTokens: options.maxOutputTokens || 4096,
      temperature: options.temperature || 1.0,
    }
  });
  
  const result = await model.generateContent(prompt);
  return result.response.text();
}

// ============================================================================
// UNIFIED INTERFACE
// ============================================================================

/**
 * Generate content using the first available LLM provider
 * 
 * @param {string} prompt - The prompt to send to the LLM
 * @param {object} options - Generation options
 * @param {string} options.model - Model to use (provider-specific)
 * @param {number} options.maxOutputTokens - Max tokens to generate
 * @param {number} options.temperature - Temperature (0-1)
 * @param {string} options.provider - Force a specific provider ('anthropic', 'openai', 'gemini')
 * @returns {Promise<string>} Generated text
 */
async function generateContent(prompt, options = {}) {
  const provider = options.provider || getAvailableProvider();
  
  if (!provider) {
    throw new Error(
      'No LLM API key found. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY in your .env file'
    );
  }
  
  switch (provider) {
    case 'anthropic':
      return await generateWithAnthropic(prompt, options);
    case 'openai':
      return await generateWithOpenAI(prompt, options);
    case 'gemini':
      return await generateWithGemini(prompt, options);
    default:
      throw new Error(`Unknown provider: ${provider}`);
  }
}

/**
 * Get the currently active provider
 */
function getActiveProvider() {
  return getAvailableProvider();
}

/**
 * Check if any API key is configured
 */
function isConfigured() {
  return getAvailableProvider() !== null;
}

module.exports = {
  generateContent,
  getActiveProvider,
  isConfigured,
  ANTHROPIC_API_KEY,
  OPENAI_API_KEY,
  GEMINI_API_KEY
};
