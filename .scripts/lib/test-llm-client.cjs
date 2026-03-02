#!/usr/bin/env node

const { generateContent, isConfigured, getActiveProvider } = require('./llm-client.cjs');

async function test() {
  console.log('Testing LLM client...');
  console.log('Provider:', getActiveProvider());
  console.log('Configured:', isConfigured());

  if (!isConfigured()) {
    console.error('No API key configured');
    process.exit(1);
  }

  const response = await generateContent('Say "Hello, World!" and nothing else.');
  console.log('Response:', response);
  console.log('✅ LLM client working');
}

test().catch(console.error);
