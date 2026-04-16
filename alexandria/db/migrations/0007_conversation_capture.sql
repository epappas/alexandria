-- 0007_conversation_capture.sql
--
-- Phase 7: MCP session log and capture queue for conversation capture.
-- All DDL uses IF NOT EXISTS for idempotency.

-- MCP session log: every tool call from connected agents
CREATE TABLE IF NOT EXISTS mcp_session_log (
  log_id       TEXT PRIMARY KEY,
  session_id   TEXT NOT NULL,
  client_name  TEXT,
  caller_model TEXT,
  tool_name    TEXT NOT NULL,
  workspace    TEXT,
  request_data TEXT NOT NULL DEFAULT '{}',
  response_summary TEXT,
  called_at    TEXT NOT NULL,
  duration_ms  INTEGER
);

CREATE INDEX IF NOT EXISTS idx_mcp_log_session
  ON mcp_session_log(session_id, called_at);
CREATE INDEX IF NOT EXISTS idx_mcp_log_tool
  ON mcp_session_log(tool_name);

-- Capture queue: serializes concurrent conversation captures
CREATE TABLE IF NOT EXISTS capture_queue (
  session_id        TEXT PRIMARY KEY,
  workspace         TEXT NOT NULL,
  client            TEXT NOT NULL,
  transcript_path   TEXT NOT NULL,
  status            TEXT NOT NULL DEFAULT 'pending',
  enqueued_at       TEXT NOT NULL,
  started_at        TEXT,
  completed_at      TEXT,
  last_content_hash TEXT,
  error             TEXT,
  CHECK (status IN ('pending', 'processing', 'done', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_capture_status
  ON capture_queue(status);
