-- 0003_beliefs.sql
--
-- Phase 3: belief revision and traceability. Beliefs are structured rows
-- extracted from wiki pages at write time, with stable identity,
-- supersession history, and provenance chains to verbatim source quotes.
-- All DDL uses IF NOT EXISTS for idempotency.

CREATE TABLE IF NOT EXISTS wiki_beliefs (
  belief_id               TEXT PRIMARY KEY,
  workspace               TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,

  statement               TEXT NOT NULL,
  topic                   TEXT NOT NULL,

  subject                 TEXT,
  predicate               TEXT,
  object                  TEXT,

  wiki_document_path      TEXT NOT NULL,
  wiki_section_anchor     TEXT,
  footnote_ids            TEXT NOT NULL DEFAULT '[]',
  provenance_ids          TEXT NOT NULL DEFAULT '[]',

  asserted_at             TEXT NOT NULL,
  asserted_in_run         TEXT,

  superseded_at           TEXT,
  superseded_by_belief_id TEXT REFERENCES wiki_beliefs(belief_id),
  superseded_in_run       TEXT,
  supersession_reason     TEXT,

  source_valid_from       TEXT,
  source_valid_to         TEXT,

  supporting_count        INTEGER NOT NULL DEFAULT 1,
  contradicting_belief_ids TEXT DEFAULT '[]',
  confidence_hint         TEXT,

  created_at              TEXT NOT NULL,

  CHECK (length(statement) <= 500),
  CHECK (supersession_reason IS NULL OR superseded_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_beliefs_workspace_topic
  ON wiki_beliefs(workspace, topic);
CREATE INDEX IF NOT EXISTS idx_beliefs_workspace_current
  ON wiki_beliefs(workspace) WHERE superseded_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_beliefs_subject_predicate
  ON wiki_beliefs(workspace, subject, predicate) WHERE subject IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_beliefs_wiki_doc
  ON wiki_beliefs(wiki_document_path);
CREATE INDEX IF NOT EXISTS idx_beliefs_asserted_at
  ON wiki_beliefs(workspace, asserted_at DESC);
CREATE INDEX IF NOT EXISTS idx_beliefs_superseded
  ON wiki_beliefs(workspace, superseded_at DESC) WHERE superseded_at IS NOT NULL;

CREATE VIRTUAL TABLE IF NOT EXISTS wiki_beliefs_fts USING fts5(
  statement,
  topic,
  subject,
  predicate,
  object,
  content='wiki_beliefs',
  content_rowid='rowid',
  tokenize='unicode61 remove_diacritics 2'
);

DROP TRIGGER IF EXISTS beliefs_fts_insert;
CREATE TRIGGER beliefs_fts_insert AFTER INSERT ON wiki_beliefs BEGIN
  INSERT INTO wiki_beliefs_fts(rowid, statement, topic, subject, predicate, object)
  VALUES (new.rowid, new.statement, new.topic,
          COALESCE(new.subject, ''), COALESCE(new.predicate, ''), COALESCE(new.object, ''));
END;

DROP TRIGGER IF EXISTS beliefs_fts_delete;
CREATE TRIGGER beliefs_fts_delete AFTER DELETE ON wiki_beliefs BEGIN
  INSERT INTO wiki_beliefs_fts(wiki_beliefs_fts, rowid, statement, topic, subject, predicate, object)
  VALUES('delete', old.rowid, old.statement, old.topic,
         COALESCE(old.subject, ''), COALESCE(old.predicate, ''), COALESCE(old.object, ''));
END;

DROP TRIGGER IF EXISTS beliefs_fts_update;
CREATE TRIGGER beliefs_fts_update AFTER UPDATE ON wiki_beliefs BEGIN
  INSERT INTO wiki_beliefs_fts(wiki_beliefs_fts, rowid, statement, topic, subject, predicate, object)
  VALUES('delete', old.rowid, old.statement, old.topic,
         COALESCE(old.subject, ''), COALESCE(old.predicate, ''), COALESCE(old.object, ''));
  INSERT INTO wiki_beliefs_fts(rowid, statement, topic, subject, predicate, object)
  VALUES (new.rowid, new.statement, new.topic,
          COALESCE(new.subject, ''), COALESCE(new.predicate, ''), COALESCE(new.object, ''));
END;
