'use strict';

const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const test = require('node:test');
const { companyNameFromDomain, isFreemail, registrableDomain } = require('../lib/company-domains.cjs');

test('company domain helpers match the shared golden fixture', () => {
  const fixturePath = path.join(__dirname, '..', '..', '..', 'core', 'tests', 'fixtures', 'entity_pages', 'company_domains.json');
  for (const fixture of JSON.parse(fs.readFileSync(fixturePath, 'utf8'))) {
    assert.equal(registrableDomain(fixture.input), fixture.registrable_domain);
    assert.equal(companyNameFromDomain(fixture.input), fixture.company_name);
    assert.equal(isFreemail(fixture.input), fixture.freemail);
  }
});
