#!/usr/bin/env node

/**
 * Persistent memory layer for Dex Slack bot.
 * SQLite-backed conversation history, interaction tracking, and preferences.
 */

const path = require('path');
const Database = require('better-sqlite3');

const DB_PATH = path.join(__dirname, 'state', 'bot-memory.db');
let db;

function getDb() {
  if (db) return db;
  db = new Database(DB_PATH);
  db.pragma('journal_mode = WAL');
  db.exec(`
    CREATE TABLE IF NOT EXISTS conversations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id TEXT NOT NULL,
      role TEXT NOT NULL,
      text TEXT NOT NULL,
      intent TEXT,
      created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS interactions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      entity_type TEXT NOT NULL,
      entity_name TEXT NOT NULL,
      last_asked_at TEXT DEFAULT (datetime('now')),
      ask_count INTEGER DEFAULT 1,
      last_context TEXT
    );
    CREATE TABLE IF NOT EXISTS preferences (
      key TEXT PRIMARY KEY,
      value TEXT,
      updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_conv_user_time ON conversations(user_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_interactions_entity ON interactions(entity_type, entity_name);
  `);
  return db;
}

/**
 * Add a message to conversation history.
 */
function addMessage(userId, role, text, intent) {
  getDb().prepare(
    'INSERT INTO conversations (user_id, role, text, intent) VALUES (?, ?, ?, ?)'
  ).run(userId, role, text.slice(0, 2000), intent || null);
}

/**
 * Get recent conversation history for a user.
 * Returns messages within the time window, up to limit.
 */
function getRecentHistory(userId, limit = 10, withinMinutes = 60) {
  return getDb().prepare(`
    SELECT role, text, intent, created_at FROM conversations
    WHERE user_id = ? AND created_at > datetime('now', ?)
    ORDER BY created_at DESC LIMIT ?
  `).all(userId, `-${withinMinutes} minutes`, limit).reverse();
}

/**
 * Track an interaction with an entity (person, project, company, topic).
 * Upserts: increments ask_count if already tracked.
 */
function trackInteraction(entityType, entityName, context) {
  const existing = getDb().prepare(
    'SELECT id, ask_count FROM interactions WHERE entity_type = ? AND entity_name = ?'
  ).get(entityType, entityName.toLowerCase());

  if (existing) {
    getDb().prepare(
      'UPDATE interactions SET last_asked_at = datetime("now"), ask_count = ?, last_context = ? WHERE id = ?'
    ).run(existing.ask_count + 1, (context || '').slice(0, 500), existing.id);
  } else {
    getDb().prepare(
      'INSERT INTO interactions (entity_type, entity_name, last_context) VALUES (?, ?, ?)'
    ).run(entityType, entityName.toLowerCase(), (context || '').slice(0, 500));
  }
}

/**
 * Get last interaction with an entity.
 * Returns { entity_name, last_asked_at, ask_count, last_context } or null.
 */
function getLastInteraction(entityType, entityName) {
  return getDb().prepare(
    'SELECT entity_name, last_asked_at, ask_count, last_context FROM interactions WHERE entity_type = ? AND entity_name = ?'
  ).get(entityType, entityName.toLowerCase()) || null;
}

/**
 * Set a preference (key-value, upsert).
 */
function setPref(key, value) {
  getDb().prepare(
    "INSERT INTO preferences (key, value, updated_at) VALUES (?, ?, datetime('now')) ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = datetime('now')"
  ).run(key, value, value);
}

/**
 * Get a preference value. Returns string or null.
 */
function getPref(key) {
  const row = getDb().prepare('SELECT value FROM preferences WHERE key = ?').get(key);
  return row ? row.value : null;
}

/**
 * Close the database (for clean shutdown).
 */
function close() {
  if (db) { db.close(); db = null; }
}

module.exports = {
  addMessage,
  getRecentHistory,
  trackInteraction,
  getLastInteraction,
  setPref,
  getPref,
  close
};
