const test = require('node:test');
const assert = require('node:assert/strict');

const llmClient = require('../../../.scripts/lib/llm-client.cjs');

test('getAvailableProvider prefers OpenAI over Anthropic and Gemini', () => {
  const provider = llmClient.getAvailableProvider({
    OPENAI_API_KEY: 'sk-openai',
    ANTHROPIC_API_KEY: 'sk-ant',
    GEMINI_API_KEY: 'gem-key',
  });

  assert.equal(provider, 'openai');
});

test('generateWithOpenAI uses responses API with GPT-5.5 defaults', async () => {
  let requestBody;

  const result = await llmClient.generateWithOpenAI('Summarize this', {
    env: { OPENAI_API_KEY: 'sk-openai' },
    maxOutputTokens: 256,
    openaiClient: {
      responses: {
        create: async (body) => {
          requestBody = body;
          return { output_text: 'Concise summary' };
        },
      },
    },
  });

  assert.equal(result, 'Concise summary');
  assert.equal(requestBody.model, llmClient.DEFAULT_OPENAI_MODEL);
  assert.equal(requestBody.input, 'Summarize this');
  assert.equal(requestBody.max_output_tokens, 256);
  assert.equal(requestBody.store, false);
  assert.deepEqual(requestBody.reasoning, { effort: 'medium' });
});

test('extractOpenAIResponseText falls back to message content when output_text is absent', () => {
  const text = llmClient.extractOpenAIResponseText({
    output: [
      { type: 'reasoning', content: [] },
      {
        type: 'message',
        content: [
          { type: 'output_text', text: 'First paragraph' },
          { type: 'output_text', text: 'Second paragraph' },
        ],
      },
    ],
  });

  assert.equal(text, 'First paragraph\n\nSecond paragraph');
});

test('generateContent error message prefers OPENAI_API_KEY wording first', async () => {
  await assert.rejects(
    llmClient.generateContent('Hello', { env: {} }),
    /Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY/u,
  );
});
