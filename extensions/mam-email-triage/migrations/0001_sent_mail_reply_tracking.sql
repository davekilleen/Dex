-- Migration: sent-mail direction + reply tracking
-- Apply to the existing production D1 database with:
--   npx wrangler d1 execute mam-email-triage --remote --file=migrations/0001_sent_mail_reply_tracking.sql
-- (schema.sql already reflects this shape for fresh/local databases — this file
-- brings an already-deployed database up to date via ALTER TABLE.)
--
-- Note: schema.sql widens the UNIQUE constraint to include `direction`
-- (received_at, sender_email, subject, direction). SQLite can't alter a
-- UNIQUE constraint without rebuilding the table, and the collision this
-- guards against — an inbox row and a sent row sharing the exact same
-- received_at/sender_email/subject — isn't realistically reachable (sent
-- rows are keyed on Chris's own address, inbox rows on the counterparty's).
-- Left as-is on the live database rather than risking a table rebuild.

-- NOTE: production already has a `message_id` column (added out-of-band, not via
-- this repo). Do NOT re-add it here — `ADD COLUMN message_id` would fail with
-- "duplicate column name". Only the six genuinely-new columns are added below.

ALTER TABLE emails ADD COLUMN direction TEXT NOT NULL DEFAULT 'inbox' CHECK(direction IN ('inbox','sent'));
ALTER TABLE emails ADD COLUMN recipient_email TEXT;
ALTER TABLE emails ADD COLUMN recipient_name TEXT;
ALTER TABLE emails ADD COLUMN conversation_id TEXT;
ALTER TABLE emails ADD COLUMN reply_status TEXT CHECK(reply_status IN ('awaiting_reply','replied','no_reply_needed'));
ALTER TABLE emails ADD COLUMN replied_at TEXT;

CREATE INDEX IF NOT EXISTS idx_conversation_id ON emails(conversation_id);
CREATE INDEX IF NOT EXISTS idx_direction       ON emails(direction);
CREATE INDEX IF NOT EXISTS idx_reply_status    ON emails(reply_status);
