-- 0009_dedup_indexes.sql
--
-- Composite index for belief deduplication GROUP BY queries.

CREATE INDEX IF NOT EXISTS idx_beliefs_dedup
  ON wiki_beliefs(workspace, statement, wiki_document_path, subject, predicate, object)
  WHERE superseded_at IS NULL;
