-- 0013_jobs.sql
--
-- Async job queue. Long-running ingests enqueue a job and return
-- immediately; a background worker inside the MCP server process picks
-- up jobs and runs them serially. Progress + cancellation are exposed
-- via the jobs_* MCP tools and the `alxia jobs` CLI.

CREATE TABLE IF NOT EXISTS jobs (
  job_id          TEXT PRIMARY KEY,
  workspace       TEXT NOT NULL REFERENCES workspaces(slug) ON DELETE CASCADE,
  job_type        TEXT NOT NULL,         -- 'ingest' for now
  spec            TEXT NOT NULL,         -- JSON: source, topic, no_merge, scope, ...
  status          TEXT NOT NULL DEFAULT 'queued',
  files_total     INTEGER NOT NULL DEFAULT 0,
  files_done      INTEGER NOT NULL DEFAULT 0,
  files_failed    INTEGER NOT NULL DEFAULT 0,
  message         TEXT,                  -- latest human-readable status line
  error           TEXT,                  -- only set on status='failed'
  result          TEXT,                  -- JSON summary on completion
  run_ids         TEXT NOT NULL DEFAULT '[]',   -- JSON array of run_ids produced
  enqueued_at     TEXT NOT NULL,
  started_at      TEXT,
  updated_at      TEXT,
  finished_at     TEXT,
  CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_enqueued
  ON jobs(status, enqueued_at);
CREATE INDEX IF NOT EXISTS idx_jobs_workspace_enqueued
  ON jobs(workspace, enqueued_at DESC);
