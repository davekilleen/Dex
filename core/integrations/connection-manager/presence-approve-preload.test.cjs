'use strict';

// Subprocess-only test fixture. Test files preload this module to exercise
// successful privileged CLI contracts without adding a production environment
// bypass to presence.cjs. It is excluded from release exports with all *.test.cjs.
const presence = require('./presence.cjs');

presence.resolveProvider = () => ({
  available: true,
  kind: 'test',
  async verify() {
    return true;
  },
});
