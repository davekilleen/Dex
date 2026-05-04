#!/usr/bin/env node

/**
 * Unified LLM Client
 * 
 * Supports OpenAI, Anthropic, and Google Gemini with automatic provider selection
 * based on available API keys.
 * 
 * Priority order: OpenAI > Anthropic > Gemini
 */

try {
  require('dotenv').config();
} catch {
  // Optional in test or stripped-down environments.
}

const DEFAULT_OPENAI_MODEL = 'gpt-5.5';
const DEFAULT_ANTHROPIC_MODEL = 'claude-sonnet-4-6';
const DEFAULT_GEMINI_MODEL = 'gemini-2.0-flash-thinking-exp-1219';

function getConfiguredApiKeys(env = process.env) {
  return {
    openai: env.OPENAI_API_KEY || '',
    anthropic: env.ANTHROPIC_API_KEY || '',
    gemini: env.GEMINI_API_KEY || '',
  };
}

// Determine which provider to use
function getAvailableProvider(env = process.env) {
  const keys = getConfiguredApiKeys(env);
  if (keys.openai) return 'openai';
  if (keys.anthropic) return 'anthropic';
  if (keys.gemini) return 'gemini';
  return null;
}

// ============================================================================
// ANTHROPIC CLIENT
// ============================================================================

async function generateWithAnthropic(prompt, options = {}) {
  const { anthropic: apiKey } = getConfiguredApiKeys(options.env);
  const anthropic =
    options.anthropicClient ||
    new (require('@anthropic-ai/sdk'))({ apiKey });
  
  const message = await anthropic.messages.create({
    model: options.model || DEFAULT_ANTHROPIC_MODEL,
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

function shouldUseReasoningConfig(model) {
  return typeof model === 'string' && model.startsWith('gpt-5');
}

function extractOpenAIResponseText(response) {
  if (typeof response?.output_text === 'string' && response.output_text.trim()) {
    return response.output_text.trim();
  }

  const output = Array.isArray(response?.output) ? response.output : [];
  const textParts = [];

  for (const item of output) {
    if (item?.type !== 'message' || !Array.isArray(item.content)) {
      continue;
    }

    for (const contentItem of item.content) {
      if (typeof contentItem?.text === 'string' && contentItem.text.trim()) {
        textParts.push(contentItem.text.trim());
      }
    }
  }

  if (textParts.length === 0) {
    throw new Error('OpenAI returned no output text');
  }

  return textParts.join('\n\n');
}

async function generateWithOpenAI(prompt, options = {}) {
  const { openai: apiKey } = getConfiguredApiKeys(options.env);
  const openai =
    options.openaiClient ||
    new (require('openai'))({ apiKey });
  const model = options.model || DEFAULT_OPENAI_MODEL;
  
  const request = {
    model,
    input: prompt,
    max_output_tokens: options.maxOutputTokens || 4096,
    store: false,
  };

  if (options.temperature !== undefined) {
    request.temperature = options.temperature;
  }

  if (shouldUseReasoningConfig(model)) {
    request.reasoning = {
      effort: options.reasoningEffort || 'medium',
    };
  }

  const response = await openai.responses.create(request);
  
  return extractOpenAIResponseText(response);
}

// ============================================================================
// GEMINI CLIENT
// ============================================================================

async function generateWithGemini(prompt, options = {}) {
  const { gemini: apiKey } = getConfiguredApiKeys(options.env);
  const genAI =
    options.geminiClient ||
    new (require('@google/generative-ai').GoogleGenerativeAI)(apiKey);
  
  const model = genAI.getGenerativeModel({
    model: options.model || DEFAULT_GEMINI_MODEL,
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
  const provider = options.provider || getAvailableProvider(options.env);
  
  if (!provider) {
    throw new Error(
      'No LLM API key found. Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY in your .env file'
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
  DEFAULT_OPENAI_MODEL,
  DEFAULT_ANTHROPIC_MODEL,
  DEFAULT_GEMINI_MODEL,
  getConfiguredApiKeys,
  getAvailableProvider,
  extractOpenAIResponseText,
  generateContent,
  generateWithOpenAI,
  getActiveProvider,
  isConfigured,
};
