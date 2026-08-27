'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');

const CLIENT_PATH = require.resolve('../llm-client.cjs');

test('Anthropic returns the text block when thinking comes first', async () => {
  const originalLoad = Module._load;
  const originalApiKey = process.env.ANTHROPIC_API_KEY;

  class Anthropic {
    constructor() {
      this.messages = {
        create: async () => ({
          content: [
            { type: 'thinking', thinking: 'private reasoning' },
            { type: 'text', text: 'meeting analysis' },
          ],
        }),
      };
    }
  }

  Module._load = function loadWithAnthropicFixture(request, parent, isMain) {
    if (request === '@anthropic-ai/sdk') return Anthropic;
    if (request === 'dotenv') return { config() {} };
    return originalLoad.call(this, request, parent, isMain);
  };
  process.env.ANTHROPIC_API_KEY = 'local-test-key';
  delete require.cache[CLIENT_PATH];

  try {
    const { generateContent } = require(CLIENT_PATH);

    const result = await generateContent('analyse this meeting', {
      provider: 'anthropic',
    });

    assert.equal(result, 'meeting analysis');
  } finally {
    Module._load = originalLoad;
    delete require.cache[CLIENT_PATH];
    if (originalApiKey === undefined) delete process.env.ANTHROPIC_API_KEY;
    else process.env.ANTHROPIC_API_KEY = originalApiKey;
  }
});
