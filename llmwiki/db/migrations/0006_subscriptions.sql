-- 0006_subscriptions.sql
--
-- Phase 5: subscription queue for RSS/IMAP items. Tracks pending, ingested,
-- and dismissed items with deduplication via external_id + content_hash.
-- All DDL uses IF NOT EXISTS for idempotency.

CREATE TABLE IF NOT EXISTS subscription_items (
  item_id        TEXT PRIMARY KEY,
  workspace      TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,
  source_id      TEXT REFERENCES source_adapters(source_id) ON DELETE SET NULL,
  adapter_type   TEXT NOT NULL,
  external_id    TEXT,
  title          TEXT NOT NULL,
  author         TEXT,
  url            TEXT,
  published_at   TEXT,
  content_path   TEXT NOT NULL,
  content_hash   TEXT NOT NULL,
  excerpt        TEXT,
  metadata       TEXT NOT NULL DEFAULT '{}',
  status         TEXT NOT NULL DEFAULT 'pending',
  ingested_at    TEXT,
  dismissed_at   TEXT,
  created_at     TEXT NOT NULL,
  CHECK (status IN ('pending', 'ingested', 'dismissed'))
);

CREATE INDEX IF NOT EXISTS idx_subs_workspace_status
  ON subscription_items(workspace, status);
CREATE INDEX IF NOT EXISTS idx_subs_source
  ON subscription_items(source_id);
CREATE INDEX IF NOT EXISTS idx_subs_external_id
  ON subscription_items(workspace, external_id) WHERE external_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_subs_published
  ON subscription_items(workspace, published_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS subscription_items_fts USING fts5(
  title,
  excerpt,
  content='subscription_items',
  content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);

DROP TRIGGER IF EXISTS subs_fts_insert;
CREATE TRIGGER subs_fts_insert AFTER INSERT ON subscription_items BEGIN
  INSERT INTO subscription_items_fts(rowid, title, excerpt)
  VALUES (new.rowid, new.title, COALESCE(new.excerpt, ''));
END;

DROP TRIGGER IF EXISTS subs_fts_delete;
CREATE TRIGGER subs_fts_delete AFTER DELETE ON subscription_items BEGIN
  INSERT INTO subscription_items_fts(subscription_items_fts, rowid, title, excerpt)
  VALUES('delete', old.rowid, old.title, COALESCE(old.excerpt, ''));
END;

DROP TRIGGER IF EXISTS subs_fts_update;
CREATE TRIGGER subs_fts_update AFTER UPDATE ON subscription_items BEGIN
  INSERT INTO subscription_items_fts(subscription_items_fts, rowid, title, excerpt)
  VALUES('delete', old.rowid, old.title, COALESCE(old.excerpt, ''));
  INSERT INTO subscription_items_fts(rowid, title, excerpt)
  VALUES (new.rowid, new.title, COALESCE(new.excerpt, ''));
END;
