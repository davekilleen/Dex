#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');

const DEFAULT_IMPROVER_MODEL = 'gpt-5.5';
const OPENAI_RESPONSES_URL = 'https://api.openai.com/v1/responses';

function parseEnvFile(content) {
  const parsed = {};

  for (const rawLine of content.split(/\r?\n/u)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) {
      continue;
    }

    const match = line.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/u);
    if (!match) {
      continue;
    }

    const [, key, rawValue] = match;
    let value = rawValue;

    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    } else {
      value = value.replace(/\s+#.*$/u, '');
    }

    parsed[key] = value.replace(/\\n/gu, '\n').trim();
  }

  return parsed;
}

function loadDotEnvFile(filePath, env = process.env) {
  if (!fs.existsSync(filePath)) {
    return env;
  }

  const parsed = parseEnvFile(fs.readFileSync(filePath, 'utf8'));
  for (const [key, value] of Object.entries(parsed)) {
    if (env[key] === undefined) {
      env[key] = value;
    }
  }

  return env;
}

function buildSystemPrompt({ feedback = '', targetModel = '', systemPrompt = '' } = {}) {
  const targetLine = targetModel.trim()
    ? `Optimize the improved prompt for this target model: ${targetModel.trim()}.`
    : 'Optimize the improved prompt for the current model in the active session.';

  const systemLine = systemPrompt.trim()
    ? 'A separate system prompt is provided. Preserve its intent and important constraints when you rewrite the prompt.'
    : 'No separate system prompt is provided.';

  const focusLine = feedback.trim()
    ? `User guidance: ${feedback.trim()}`
    : 'User guidance: prioritize clarity, structure, and actionable output.';

  return [
    'You are an expert prompt engineer using OpenAI prompt engineering best practices.',
    'Transform vague or ambiguous prompts into clear, structured prompts that are ready to execute.',
    targetLine,
    systemLine,
    '',
    'Improve prompts using these techniques when helpful:',
    '1. Add clear structure with concise headers or sections.',
    '2. Make the task, context, and success criteria explicit.',
    '3. Clarify output format, scope, and constraints.',
    '4. Add examples only when they materially improve execution.',
    '5. Break complex tasks into ordered instructions.',
    '6. Preserve the user intent while removing ambiguity.',
    '',
    'Return only the improved prompt.',
    focusLine,
  ].join('\n');
}

function buildUserMessage({ originalPrompt, targetModel = '', systemPrompt = '' }) {
  const sections = [
    'Rewrite the following prompt so it is ready to execute.',
    targetModel.trim()
      ? `Target model: ${targetModel.trim()}`
      : 'Target model: current active model',
    '',
    'Original prompt:',
    originalPrompt.trim(),
  ];

  if (systemPrompt.trim()) {
    sections.push('', 'Existing system prompt to incorporate:', systemPrompt.trim());
  }

  return sections.join('\n');
}

function buildRequestBody({ originalPrompt, feedback = '', targetModel = '', systemPrompt = '' }) {
  return {
    model: DEFAULT_IMPROVER_MODEL,
    store: false,
    reasoning: { effort: 'medium' },
    input: [
      {
        role: 'system',
        content: [
          {
            type: 'input_text',
            text: buildSystemPrompt({ feedback, targetModel, systemPrompt }),
          },
        ],
      },
      {
        role: 'user',
        content: [
          {
            type: 'input_text',
            text: buildUserMessage({ originalPrompt, targetModel, systemPrompt }),
          },
        ],
      },
    ],
  };
}

function extractResponseText(response) {
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
    throw new Error('OpenAI returned no output text.');
  }

  return textParts.join('\n\n');
}

async function callOpenAI({ apiKey, requestBody, fetchImpl = globalThis.fetch }) {
  if (typeof fetchImpl !== 'function') {
    throw new Error('Global fetch is unavailable. Use Node 18+ or provide a fetch implementation.');
  }

  const response = await fetchImpl(OPENAI_RESPONSES_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify(requestBody),
  });

  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const message = data?.error?.message || `OpenAI request failed with HTTP ${response.status}`;
    throw new Error(message);
  }

  return data;
}

async function main(argv = process.argv.slice(2), options = {}) {
  const [originalPrompt = '', feedback = '', targetModel = '', systemPrompt = ''] = argv;
  if (!originalPrompt.trim()) {
    throw new Error('Usage: node .scripts/improve-prompt.cjs "<prompt>" "[feedback]" "[target_model]" "[system_prompt]"');
  }

  const cwd = options.cwd || process.cwd();
  const env = options.env || process.env;
  loadDotEnvFile(path.join(cwd, '.env'), env);

  const apiKey = env.OPENAI_API_KEY;
  if (!apiKey) {
    throw new Error('OPENAI_API_KEY is required for .scripts/improve-prompt.cjs');
  }

  const requestBody = buildRequestBody({ originalPrompt, feedback, targetModel, systemPrompt });
  const response = await callOpenAI({
    apiKey,
    requestBody,
    fetchImpl: options.fetchImpl,
  });

  const improvedPrompt = extractResponseText(response);
  const stdout = options.stdout || process.stdout;
  stdout.write(`${improvedPrompt}\n`);
  return improvedPrompt;
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}

module.exports = {
  DEFAULT_IMPROVER_MODEL,
  OPENAI_RESPONSES_URL,
  parseEnvFile,
  loadDotEnvFile,
  buildSystemPrompt,
  buildUserMessage,
  buildRequestBody,
  extractResponseText,
  callOpenAI,
  main,
};
