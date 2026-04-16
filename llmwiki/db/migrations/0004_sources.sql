-- 0004_sources.sql
--
-- Phase 4: source adapters and sync tracking. Stores adapter configuration
-- and tracks each sync run with a state machine. All DDL uses IF NOT EXISTS
-- for idempotency.

-- ---------------------------------------------------------------------------
-- source_adapters: configured external sources (local, git-local, github).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_adapters (
  source_id    TEXT PRIMARY KEY,
  workspace    TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,
  adapter_type TEXT NOT NULL,
  name         TEXT NOT NULL,
  config_json  TEXT NOT NULL DEFAULT '{}',
  enabled      INTEGER NOT NULL DEFAULT 1,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  CHECK (adapter_type IN ('local', 'git-local', 'github', 'rss', 'imap'))
);

CREATE INDEX IF NOT EXISTS idx_sources_workspace
  ON source_adapters(workspace);
CREATE INDEX IF NOT EXISTS idx_sources_type
  ON source_adapters(adapter_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_ws_name
  ON source_adapters(workspace, name);

-- ---------------------------------------------------------------------------
-- source_runs: tracks each sync execution with a 5-state machine.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_runs (
  source_run_id TEXT PRIMARY KEY,
  source_id     TEXT NOT NULL REFERENCES source_adapters(source_id) ON DELETE CASCADE,
  run_id        TEXT REFERENCES runs(run_id),
  status        TEXT NOT NULL DEFAULT 'pending',
  started_at    TEXT NOT NULL,
  ended_at      TEXT,
  items_synced  INTEGER NOT NULL DEFAULT 0,
  items_errored INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  triggered_by  TEXT NOT NULL DEFAULT 'cli:sync',
  CHECK (status IN ('pending', 'running', 'completed', 'failed', 'abandoned'))
);

CREATE INDEX IF NOT EXISTS idx_source_runs_source
  ON source_runs(source_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_source_runs_status
  ON source_runs(status);
