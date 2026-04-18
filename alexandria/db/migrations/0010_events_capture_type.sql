-- 0010_events_capture_type.sql
--
-- Add 'capture' to events.source_type by recreating the table.
-- SQLite does not support ALTER CHECK, so we rebuild with FTS triggers.

-- Drop existing triggers (they reference the old table)
DROP TRIGGER IF EXISTS events_fts_insert;
DROP TRIGGER IF EXISTS events_fts_delete;
DROP TRIGGER IF EXISTS events_fts_update;

-- Rebuild table with expanded CHECK constraint
CREATE TABLE IF NOT EXISTS events_new (
  event_id      TEXT PRIMARY KEY,
  workspace     TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,
  source_id     TEXT REFERENCES source_adapters(source_id) ON DELETE SET NULL,
  source_type   TEXT NOT NULL,
  event_type    TEXT NOT NULL,
  title         TEXT NOT NULL,
  body          TEXT,
  url           TEXT,
  author        TEXT,
  event_data    TEXT NOT NULL DEFAULT '{}',
  occurred_at   TEXT NOT NULL,
  ingested_at   TEXT NOT NULL,
  CHECK (source_type IN ('local', 'git-local', 'github', 'rss', 'calendar', 'slack', 'discord', 'email', 'capture'))
);

INSERT OR IGNORE INTO events_new SELECT * FROM events;
DROP TABLE IF EXISTS events;
ALTER TABLE events_new RENAME TO events;

-- Recreate indexes
CREATE INDEX IF NOT EXISTS idx_events_workspace_occurred
  ON events(workspace, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_source_type
  ON events(source_type);
CREATE INDEX IF NOT EXISTS idx_events_source_id
  ON events(source_id) WHERE source_id IS NOT NULL;

-- Recreate FTS triggers
DROP TRIGGER IF EXISTS events_fts_insert;
CREATE TRIGGER events_fts_insert AFTER INSERT ON events BEGIN
  INSERT INTO events_fts(rowid, title, body, author)
  VALUES (new.rowid, new.title, COALESCE(new.body, ''), COALESCE(new.author, ''));
END;

DROP TRIGGER IF EXISTS events_fts_delete;
CREATE TRIGGER events_fts_delete AFTER DELETE ON events BEGIN
  INSERT INTO events_fts(events_fts, rowid, title, body, author)
  VALUES('delete', old.rowid, old.title, COALESCE(old.body, ''), COALESCE(old.author, ''));
END;

DROP TRIGGER IF EXISTS events_fts_update;
CREATE TRIGGER events_fts_update AFTER UPDATE ON events BEGIN
  INSERT INTO events_fts(events_fts, rowid, title, body, author)
  VALUES('delete', old.rowid, old.title, COALESCE(old.body, ''), COALESCE(old.author, ''));
  INSERT INTO events_fts(rowid, title, body, author)
  VALUES (new.rowid, new.title, COALESCE(new.body, ''), COALESCE(new.author, ''));
END;
