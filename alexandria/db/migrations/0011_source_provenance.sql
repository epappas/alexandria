-- 0011_source_provenance.sql
--
-- Add source_kind to beliefs and ai_authored to documents.
-- Distinguishes papers from opinions, code from conversations.

ALTER TABLE wiki_beliefs ADD COLUMN source_kind TEXT DEFAULT 'unknown';

ALTER TABLE documents ADD COLUMN ai_authored INTEGER NOT NULL DEFAULT 0;
