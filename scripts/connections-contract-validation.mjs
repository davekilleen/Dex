import fs from 'node:fs';

function typeMatches(value, type) {
  if (type === 'null') return value === null;
  if (type === 'array') return Array.isArray(value);
  if (type === 'object') return value !== null && typeof value === 'object' && !Array.isArray(value);
  if (type === 'number') return typeof value === 'number' && Number.isFinite(value);
  if (type === 'integer') return Number.isInteger(value);
  return typeof value === type;
}

export function validateAgainstSchema(value, schema, root = schema, at = '$') {
  if (schema.$ref) {
    if (!schema.$ref.startsWith('#/$defs/')) throw new Error(`${at}: unsupported schema ref ${schema.$ref}`);
    return validateAgainstSchema(value, root.$defs[schema.$ref.slice('#/$defs/'.length)], root, at);
  }
  if (schema.anyOf) {
    const errors = [];
    for (const option of schema.anyOf) {
      try {
        validateAgainstSchema(value, option, root, at);
        return;
      } catch (error) {
        errors.push(error.message);
      }
    }
    throw new Error(`${at}: matched no anyOf option (${errors.join('; ')})`);
  }
  if ('const' in schema && value !== schema.const) throw new Error(`${at}: expected constant ${JSON.stringify(schema.const)}`);
  if (schema.enum && !schema.enum.includes(value)) throw new Error(`${at}: expected one of ${schema.enum.join(', ')}`);
  if (schema.type) {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!types.some((type) => typeMatches(value, type))) throw new Error(`${at}: expected ${types.join('|')}`);
  }
  if (typeof value === 'string') {
    if (schema.minLength != null && value.length < schema.minLength) throw new Error(`${at}: string is too short`);
    if (schema.pattern && !new RegExp(schema.pattern).test(value)) throw new Error(`${at}: does not match ${schema.pattern}`);
  }
  if (Array.isArray(value) && schema.items) {
    value.forEach((item, index) => validateAgainstSchema(item, schema.items, root, `${at}[${index}]`));
  }
  if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
    if (schema.minProperties != null && Object.keys(value).length < schema.minProperties) {
      throw new Error(`${at}: expected at least ${schema.minProperties} properties`);
    }
    for (const key of schema.required || []) {
      if (!(key in value)) throw new Error(`${at}: missing required property ${key}`);
    }
    for (const [key, child] of Object.entries(value)) {
      if (schema.properties && schema.properties[key]) {
        validateAgainstSchema(child, schema.properties[key], root, `${at}.${key}`);
      } else if (schema.additionalProperties === false) {
        throw new Error(`${at}: unexpected property ${key}`);
      } else if (schema.additionalProperties && typeof schema.additionalProperties === 'object') {
        validateAgainstSchema(child, schema.additionalProperties, root, `${at}.${key}`);
      }
    }
  }
}

export function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}
