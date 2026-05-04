const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const improver = require('../../../.scripts/improve-prompt.cjs');

test('parseEnvFile handles comments, export syntax, and quoted values', () => {
  const parsed = improver.parseEnvFile([
    '# comment',
    'export OPENAI_API_KEY="sk-test"',
    "TARGET_MODEL='gpt-5.5'",
    'PLAIN=value # trailing comment',
  ].join('\n'));

  assert.deepEqual(parsed, {
    OPENAI_API_KEY: 'sk-test',
    TARGET_MODEL: 'gpt-5.5',
    PLAIN: 'value',
  });
});

test('buildRequestBody targets GPT-5.5 and includes target-model context', () => {
  const body = improver.buildRequestBody({
    originalPrompt: 'critique this memo',
    feedback: 'Focus on risks',
    targetModel: 'gpt-5.5',
    systemPrompt: 'Be blunt.',
  });

  assert.equal(body.model, improver.DEFAULT_IMPROVER_MODEL);
  assert.equal(body.store, false);
  assert.equal(body.reasoning.effort, 'medium');
  assert.match(body.input[0].content[0].text, /User guidance: Focus on risks/);
  assert.match(body.input[1].content[0].text, /Target model: gpt-5\.5/);
  assert.match(body.input[1].content[0].text, /Existing system prompt to incorporate:/);
});

test('extractResponseText falls back to message output content', () => {
  const text = improver.extractResponseText({
    output: [
      { type: 'reasoning', content: [] },
      {
        type: 'message',
        content: [
          { type: 'output_text', text: 'Improved prompt' },
        ],
      },
    ],
  });

  assert.equal(text, 'Improved prompt');
});

test('main loads OPENAI_API_KEY from .env and writes the improved prompt', async () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-prompt-improver-'));
  const written = [];
  let request;

  try {
    fs.writeFileSync(path.join(tempDir, '.env'), 'OPENAI_API_KEY=sk-from-env\n', 'utf8');

    const improved = await improver.main(
      ['review this code', 'Focus on security', 'gpt-5.5', 'Be concise.'],
      {
        cwd: tempDir,
        env: {},
        stdout: { write: (chunk) => written.push(chunk) },
        fetchImpl: async (url, init) => {
          request = { url, init };
          return {
            ok: true,
            json: async () => ({
              output: [
                {
                  type: 'message',
                  content: [{ type: 'output_text', text: 'Improved prompt result' }],
                },
              ],
            }),
          };
        },
      },
    );

    assert.equal(improved, 'Improved prompt result');
    assert.equal(written.join(''), 'Improved prompt result\n');
    assert.equal(request.url, improver.OPENAI_RESPONSES_URL);
    assert.match(request.init.headers.Authorization, /^Bearer sk-from-env$/);

    const parsedBody = JSON.parse(request.init.body);
    assert.equal(parsedBody.model, 'gpt-5.5');
    assert.match(parsedBody.input[1].content[0].text, /review this code/);
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
});

test('main fails fast when OPENAI_API_KEY is missing', async () => {
  await assert.rejects(
    improver.main(['critique this'], {
      cwd: os.tmpdir(),
      env: {},
      stdout: { write: () => {} },
      fetchImpl: async () => {
        throw new Error('fetch should not run');
      },
    }),
    /OPENAI_API_KEY is required/u,
  );
});
