-- 0001_initial.sql
--
-- Phase 0 schema. All DDL uses IF NOT EXISTS for idempotency.

CREATE TABLE IF NOT EXISTS schema_migrations (
  version       INTEGER PRIMARY KEY,
  name          TEXT NOT NULL,
  script_path   TEXT NOT NULL,
  script_sha256 TEXT NOT NULL,
  applied_at    TEXT NOT NULL,
  applied_by    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspaces (
  slug             TEXT PRIMARY KEY,
  name             TEXT NOT NULL,
  description      TEXT,
  path             TEXT NOT NULL,
  contract_version TEXT NOT NULL DEFAULT 'v1',
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workspaces_updated ON workspaces(updated_at DESC);

CREATE TABLE IF NOT EXISTS documents (
  id              TEXT PRIMARY KEY,
  workspace       TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,
  layer           TEXT NOT NULL CHECK (layer IN ('raw', 'wiki')),
  path            TEXT NOT NULL,
  filename        TEXT NOT NULL,
  title           TEXT,
  file_type       TEXT NOT NULL,
  content         TEXT,
  content_hash    TEXT NOT NULL,
  size_bytes      INTEGER NOT NULL,
  page_count      INTEGER,
  tags            TEXT NOT NULL DEFAULT '[]',
  metadata        TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_ws_path_file
  ON documents(workspace, path, filename);
CREATE INDEX IF NOT EXISTS idx_documents_workspace_layer
  ON documents(workspace, layer);
CREATE INDEX IF NOT EXISTS idx_documents_updated
  ON documents(workspace, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_hash
  ON documents(content_hash);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
  title,
  content,
  tags,
  content='documents',
  content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);

DROP TRIGGER IF EXISTS documents_fts_insert;
CREATE TRIGGER documents_fts_insert AFTER INSERT ON documents BEGIN
  INSERT INTO documents_fts(rowid, title, content, tags)
  VALUES (new.rowid, COALESCE(new.title, ''), COALESCE(new.content, ''), new.tags);
END;

DROP TRIGGER IF EXISTS documents_fts_delete;
CREATE TRIGGER documents_fts_delete AFTER DELETE ON documents BEGIN
  INSERT INTO documents_fts(documents_fts, rowid, title, content, tags)
  VALUES('delete', old.rowid, COALESCE(old.title, ''), COALESCE(old.content, ''), old.tags);
END;

DROP TRIGGER IF EXISTS documents_fts_update;
CREATE TRIGGER documents_fts_update AFTER UPDATE ON documents BEGIN
  INSERT INTO documents_fts(documents_fts, rowid, title, content, tags)
  VALUES('delete', old.rowid, COALESCE(old.title, ''), COALESCE(old.content, ''), old.tags);
  INSERT INTO documents_fts(rowid, title, content, tags)
  VALUES (new.rowid, COALESCE(new.title, ''), COALESCE(new.content, ''), new.tags);
END;

CREATE TABLE IF NOT EXISTS daemon_heartbeats (
  child_name TEXT PRIMARY KEY,
  pid        INTEGER NOT NULL,
  started_at TEXT NOT NULL,
  last_beat  TEXT NOT NULL,
  state      TEXT NOT NULL CHECK (state IN ('starting', 'running', 'draining', 'failed'))
);
