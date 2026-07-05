import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
  resolve: {
    alias: {
      'agents': path.resolve('./src/__mocks__/agents.js'),
    },
  },
});
