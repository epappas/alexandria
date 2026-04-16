-- 0008_eval.sql
--
-- Phase 9: evaluation scaffold. Stores eval run results and gold queries.
-- All DDL uses IF NOT EXISTS for idempotency.

CREATE TABLE IF NOT EXISTS eval_runs (
  run_id       TEXT PRIMARY KEY,
  workspace    TEXT NOT NULL,
  metric       TEXT NOT NULL,
  score        REAL,
  passed       INTEGER,
  detail       TEXT NOT NULL DEFAULT '{}',
  started_at   TEXT NOT NULL,
  ended_at     TEXT,
  error        TEXT
);

CREATE INDEX IF NOT EXISTS idx_eval_runs_workspace
  ON eval_runs(workspace, metric, started_at DESC);

CREATE TABLE IF NOT EXISTS eval_gold_queries (
  query_id     TEXT PRIMARY KEY,
  workspace    TEXT NOT NULL,
  query        TEXT NOT NULL,
  expected     TEXT NOT NULL,
  metric       TEXT NOT NULL DEFAULT 'M1',
  created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gold_workspace
  ON eval_gold_queries(workspace, metric);
