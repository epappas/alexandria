-- 0005_events.sql
--
-- Phase 4: event stream table. Stores structured events from external sources
-- (git commits, GitHub issues/PRs, calendar entries, etc.) with FTS5 search.
-- All DDL uses IF NOT EXISTS for idempotency.

CREATE TABLE IF NOT EXISTS events (
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
  CHECK (source_type IN ('local', 'git-local', 'github', 'rss', 'calendar', 'slack', 'discord', 'email'))
);

CREATE INDEX IF NOT EXISTS idx_events_workspace_occurred
  ON events(workspace, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_source_type
  ON events(workspace, source_type);
CREATE INDEX IF NOT EXISTS idx_events_event_type
  ON events(workspace, event_type);
CREATE INDEX IF NOT EXISTS idx_events_source_id
  ON events(source_id);

CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
  title,
  body,
  author,
  content='events',
  content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);

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
