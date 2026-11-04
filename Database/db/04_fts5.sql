-- =============================================================================
--  04_fts5.sql : 可选 · 全文检索（FR-37 模糊搜索的索引方案）
--  依赖：SQLite 3.34+ 且编译时启用 FTS5（trigram 分词）
--  用法：在 01_schema.sql + 02_seed.sql 之后执行；或 python init_db.py --with-fts
--  说明：trigram 分词支持任意子串匹配，也支持中文（至少 3 个字符）
-- =============================================================================

DROP TRIGGER IF EXISTS component_fts_ai;
DROP TRIGGER IF EXISTS component_fts_ad;
DROP TRIGGER IF EXISTS component_fts_au;
DROP TABLE   IF EXISTS component_fts;

CREATE VIRTUAL TABLE component_fts USING fts5(
    model,
    package,
    description,
    content        = 'component',
    content_rowid  = 'component_id',
    tokenize       = 'trigram'
);

-- 用现有数据建立索引
INSERT INTO component_fts(component_fts) VALUES ('rebuild');

-- 保持索引与 component 同步
CREATE TRIGGER component_fts_ai AFTER INSERT ON component
BEGIN
    INSERT INTO component_fts(rowid, model, package, description)
    VALUES (new.component_id, new.model, new.package, new.description);
END;

CREATE TRIGGER component_fts_ad AFTER DELETE ON component
BEGIN
    INSERT INTO component_fts(component_fts, rowid, model, package, description)
    VALUES ('delete', old.component_id, old.model, old.package, old.description);
END;

CREATE TRIGGER component_fts_au
AFTER UPDATE OF model, package, description ON component
BEGIN
    INSERT INTO component_fts(component_fts, rowid, model, package, description)
    VALUES ('delete', old.component_id, old.model, old.package, old.description);
    INSERT INTO component_fts(rowid, model, package, description)
    VALUES (new.component_id, new.model, new.package, new.description);
END;

-- 示例：子串 / 中文检索（短语用双引号，避免 - 被当成查询运算符）
SELECT c.component_id, c.model, c.package, c.description
FROM component_fts f
JOIN component c ON c.component_id = f.rowid
WHERE component_fts MATCH '"LM358"'
ORDER BY rank;

SELECT c.component_id, c.model, c.package, c.description
FROM component_fts f
JOIN component c ON c.component_id = f.rowid
WHERE component_fts MATCH '"SOT-23"'
ORDER BY rank;

SELECT c.component_id, c.model, c.package, c.description
FROM component_fts f
JOIN component c ON c.component_id = f.rowid
WHERE component_fts MATCH '"连接器"'
ORDER BY rank;
