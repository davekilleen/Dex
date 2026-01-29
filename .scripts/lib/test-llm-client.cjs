#!/usr/bin/env node

/**
 * Test script for LLM client
 * 
 * Usage:
 *   node test-llm-client.cjs
 */

const { getActiveProvider, isConfigured, generateContent } = require('./llm-client.cjs');

async function test() {
  console.log('🔍 Testing LLM client...\n');
  
  console.log('Configuration status:');
  console.log(`  Configured: ${isConfigured()}`);
  console.log(`  Active provider: ${getActiveProvider() || 'none'}\n`);
  
  if (!isConfigured()) {
    console.log('❌ No API key found in .env');
    console.log('   Add ANTHROPIC_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY\n');
    process.exit(1);
  }
  
  try {
    console.log('Testing generation with: "What is 2+2? Answer in one word."\n');
    const result = await generateContent('What is 2+2? Answer in one word.', {
      maxOutputTokens: 100
    });
    
    console.log('✅ Success!');
    console.log(`Response: ${result.trim()}\n`);
  } catch (error) {
    console.log('❌ Error:', error.message);
    process.exit(1);
  }
}

test();
