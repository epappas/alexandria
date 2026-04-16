-- 0002_runs_and_provenance.sql
--
-- Phase 2a: staged-write transaction (runs table) and citation provenance
-- with verbatim quote anchors. All DDL uses IF NOT EXISTS for idempotency.

-- ---------------------------------------------------------------------------
-- runs: every wiki write is wrapped in a run with a 5-state machine.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runs (
  run_id                    TEXT PRIMARY KEY,
  workspace                 TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,
  triggered_by              TEXT NOT NULL,
  run_type                  TEXT NOT NULL,
  status                    TEXT NOT NULL DEFAULT 'pending',
  started_at                TEXT NOT NULL,
  ended_at                  TEXT,
  verifier_preset           TEXT,
  verdict                   TEXT,
  reject_reason             TEXT,
  loop_count                INTEGER NOT NULL DEFAULT 1,
  parent_run_id             TEXT REFERENCES runs(run_id),
  budget_input_tokens_used  INTEGER DEFAULT 0,
  budget_output_tokens_used INTEGER DEFAULT 0,
  budget_usd_used           REAL DEFAULT 0,
  anchor_format_version     INTEGER NOT NULL DEFAULT 1,
  CHECK (status IN ('pending', 'verifying', 'committed', 'rejected', 'abandoned'))
);

CREATE INDEX IF NOT EXISTS idx_runs_workspace_started
  ON runs(workspace, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status_started
  ON runs(status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_parent
  ON runs(parent_run_id);

-- ---------------------------------------------------------------------------
-- wiki_claim_provenance: every footnote citation links wiki → raw source
-- with a verbatim quote anchor for deterministic hash verification.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wiki_claim_provenance (
  id                  TEXT PRIMARY KEY,
  workspace           TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,
  wiki_document_id    TEXT NOT NULL,
  footnote_id         TEXT NOT NULL,
  raw_document_id     TEXT,
  raw_path            TEXT NOT NULL,
  page_hint           INTEGER,
  source_quote        TEXT NOT NULL,
  source_quote_hash   TEXT NOT NULL,
  source_quote_offset INTEGER,
  anchor_format_version INTEGER NOT NULL DEFAULT 1,
  run_id              TEXT REFERENCES runs(run_id),
  created_at          TEXT NOT NULL,
  UNIQUE(wiki_document_id, footnote_id)
);

CREATE INDEX IF NOT EXISTS idx_provenance_raw_path
  ON wiki_claim_provenance(raw_path);
CREATE INDEX IF NOT EXISTS idx_provenance_quote_hash
  ON wiki_claim_provenance(source_quote_hash);
CREATE INDEX IF NOT EXISTS idx_provenance_workspace
  ON wiki_claim_provenance(workspace);
CREATE INDEX IF NOT EXISTS idx_provenance_run
  ON wiki_claim_provenance(run_id);
