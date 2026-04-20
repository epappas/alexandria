-- 0012_retag_ast_beliefs.sql
--
-- Retag beliefs matching AST-extraction signatures as source_kind='code'.
-- Fixes a gap where beliefs carrying an AST fingerprint were inheriting
-- the containing wiki page's markdown-inferred 'manual' source_kind.

UPDATE wiki_beliefs
SET source_kind = 'code'
WHERE source_kind != 'code'
  AND predicate = 'is_a'
  AND object IN ('type', 'function');

UPDATE wiki_beliefs
SET source_kind = 'code'
WHERE source_kind != 'code'
  AND predicate = 'depends_on'
  AND statement LIKE 'Module depends on %';

UPDATE wiki_beliefs
SET source_kind = 'code'
WHERE source_kind != 'code'
  AND predicate = 'is_a'
  AND statement LIKE 'Defines % resource %';
