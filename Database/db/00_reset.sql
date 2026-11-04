-- =============================================================================
--  00_reset.sql : 清空数据库对象（开发期重建用，会删除所有数据！）
--  用法：sqlite3 demo.db < 00_reset.sql
-- =============================================================================

PRAGMA foreign_keys = OFF;

DROP VIEW  IF EXISTS v_extraction_detail;
DROP VIEW  IF EXISTS v_task_overview;
DROP VIEW  IF EXISTS v_pending_review;
DROP VIEW  IF EXISTS v_task_review;
DROP VIEW  IF EXISTS v_approved_parameter;
DROP VIEW  IF EXISTS v_component_list;

DROP TABLE IF EXISTS component_fts;        -- 可选 FTS5 表

DROP TABLE IF EXISTS operation_log;
DROP TABLE IF EXISTS audit_log;
DROP TABLE IF EXISTS component_parameter;
DROP TABLE IF EXISTS extraction_param;
DROP TABLE IF EXISTS parameter_alias;
DROP TABLE IF EXISTS parameter_def;
DROP TABLE IF EXISTS extraction_task;
DROP TABLE IF EXISTS component;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS manufacturer;
DROP TABLE IF EXISTS category;

PRAGMA foreign_keys = ON;
