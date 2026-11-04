-- =============================================================================
--  03_queries.sql : 示例查询与事务
--  用法：在本文件所在目录执行
--      python init_db.py
--      sqlite3 -header -column demo.db < 03_queries.sql
--  说明：为便于直接运行，示例中使用字面量；后端代码请改成 ? 参数绑定
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Q1  关键词搜索（型号模糊匹配，FR-34/37）
-- -----------------------------------------------------------------------------
SELECT component_id, model, manufacturer, category, package
FROM v_component_list
WHERE model LIKE '%LM%'
ORDER BY model;

-- -----------------------------------------------------------------------------
-- Q2  按类别 + 厂商筛选（FR-34）
-- -----------------------------------------------------------------------------
SELECT component_id, model, manufacturer, category, package
FROM v_component_list
WHERE category = '集成电路'
  AND manufacturer = 'Texas Instruments'
ORDER BY model;

-- -----------------------------------------------------------------------------
-- Q3  单参数范围查询：电压 3.0V ~ 5.0V（FR-35）
--     走 idx_cp_parameter_value(parameter_id, value_num)
-- -----------------------------------------------------------------------------
SELECT component_id, model, manufacturer, category, package, value_num, unit
FROM v_approved_parameter
WHERE canonical_name = 'Voltage'
  AND value_num BETWEEN 3.0 AND 5.0
ORDER BY value_num, model;

-- -----------------------------------------------------------------------------
-- Q4  多条件组合：类别=集成电路 + 电压 3.0~5.5V（FR-36）
-- -----------------------------------------------------------------------------
SELECT c.component_id, c.model, c.package, v.value_num AS voltage_v
FROM v_component_list c
JOIN v_approved_parameter v ON v.component_id = c.component_id
WHERE c.category = '集成电路'
  AND v.canonical_name = 'Voltage'
  AND v.value_num BETWEEN 3.0 AND 5.5
ORDER BY c.model;

-- -----------------------------------------------------------------------------
-- Q5  多参数组合：电压 3~5V 且 引脚数 >= 24（FR-36）
--     EXISTS 写法可让每个参数条件独立走索引
-- -----------------------------------------------------------------------------
SELECT c.component_id, c.model, c.category, c.package
FROM v_component_list c
WHERE EXISTS (
        SELECT 1 FROM component_parameter cp
         WHERE cp.component_id = c.component_id
           AND cp.parameter_id = 4          -- Voltage
           AND cp.value_num BETWEEN 3 AND 5
      )
  AND EXISTS (
        SELECT 1 FROM component_parameter cp
         WHERE cp.component_id = c.component_id
           AND cp.parameter_id = 16         -- Pin Count
           AND cp.value_num >= 24
      )
ORDER BY c.model;

-- -----------------------------------------------------------------------------
-- Q6  多器件参数对比（行转列，FR-40/41）
-- -----------------------------------------------------------------------------
SELECT c.model,
       MAX(CASE WHEN cp.parameter_id = 1 THEN cp.value_num END) AS resistance_ohm,
       MAX(CASE WHEN cp.parameter_id = 7 THEN cp.value_num END) AS tolerance_pct,
       MAX(CASE WHEN cp.parameter_id = 6 THEN cp.value_num END) AS power_w,
       MAX(CASE WHEN cp.parameter_id = 4 THEN cp.value_num END) AS voltage_v
FROM component c
JOIN component_parameter cp ON cp.component_id = c.component_id
WHERE c.component_id IN (1, 2, 3)
GROUP BY c.component_id, c.model
ORDER BY c.model;

-- -----------------------------------------------------------------------------
-- Q7  参数缺失检查（FR-42）：还没有任何已发布参数的器件
-- -----------------------------------------------------------------------------
SELECT c.component_id, c.model, c.package, c.description
FROM component c
LEFT JOIN component_parameter cp ON cp.component_id = c.component_id
WHERE cp.component_id IS NULL
ORDER BY c.model;

-- -----------------------------------------------------------------------------
-- Q8  待审核列表（FR-20，参数级）：按置信度升序，低置信度优先审
-- -----------------------------------------------------------------------------
SELECT extraction_param_id, task_id, username, model,
       canonical_name, raw_name, raw_value, value_num, unit, confidence
FROM v_pending_review
ORDER BY confidence IS NULL, confidence;

-- -----------------------------------------------------------------------------
-- Q9  低置信度提取结果（FR-17）：审核员优先复核
-- -----------------------------------------------------------------------------
SELECT task_id, raw_name, raw_value, value_num, unit, confidence, source_page
FROM v_extraction_detail
WHERE review_status = 'pending'
  AND confidence < 0.9
ORDER BY confidence;

-- -----------------------------------------------------------------------------
-- Q10 审核统计：通过/驳回数量与通过率（FR-23）
-- -----------------------------------------------------------------------------
SELECT action, COUNT(*) AS cnt
FROM audit_log
GROUP BY action;

SELECT ROUND(100.0 * SUM(action = 'approve') / COUNT(*), 1) AS approve_rate_pct,
       COUNT(*) AS total_audits
FROM audit_log;

-- -----------------------------------------------------------------------------
-- Q11 类别维度统计（报告用）
-- -----------------------------------------------------------------------------
SELECT c.category,
       COUNT(DISTINCT c.component_id) AS component_count,
       COUNT(cp.parameter_id)         AS approved_param_count,
       ROUND(COUNT(cp.parameter_id) * 1.0 / COUNT(DISTINCT c.component_id), 1) AS avg_params
FROM v_component_list c
LEFT JOIN component_parameter cp ON cp.component_id = c.component_id
GROUP BY c.category
ORDER BY component_count DESC, c.category;

-- -----------------------------------------------------------------------------
-- Q12 厂商维度统计
-- -----------------------------------------------------------------------------
SELECT manufacturer, COUNT(*) AS component_count
FROM v_component_list
GROUP BY manufacturer
ORDER BY component_count DESC, manufacturer;

-- -----------------------------------------------------------------------------
-- Q13 任务状态分布与审核进度（FR-49）
-- -----------------------------------------------------------------------------
SELECT status, COUNT(*) AS cnt FROM extraction_task GROUP BY status ORDER BY cnt DESC;

SELECT task_id, param_count, pending_count, approved_count, rejected_count, review_state
FROM v_task_review
ORDER BY task_id;

-- -----------------------------------------------------------------------------
-- Q14 任务处理耗时（分钟，NFR-01 评估用）
-- -----------------------------------------------------------------------------
SELECT task_id, source_type,
       ROUND((julianday(finished_time) - julianday(started_time)) * 24 * 60, 2) AS minutes
FROM extraction_task
WHERE finished_time IS NOT NULL
ORDER BY task_id;

-- -----------------------------------------------------------------------------
-- Q15 数据质量检查：存储单位与字典标准单位是否一致（NFR-17/DS-01）
--     正常应返回 0 行
-- -----------------------------------------------------------------------------
SELECT cp.component_id, c.model, pd.canonical_name,
       cp.unit AS stored_unit, pd.unit AS expected_unit
FROM component_parameter cp
JOIN component c      ON c.component_id  = cp.component_id
JOIN parameter_def pd ON pd.parameter_id = cp.parameter_id
WHERE pd.unit IS NOT NULL
  AND cp.unit IS NOT NULL
  AND cp.unit <> pd.unit;

-- -----------------------------------------------------------------------------
-- Q16 重复型号检查（BR-01）：正常应返回 0 行
-- -----------------------------------------------------------------------------
SELECT manufacturer_id, model, COUNT(*) AS cnt
FROM component
GROUP BY manufacturer_id, model
HAVING COUNT(*) > 1;

-- -----------------------------------------------------------------------------
-- Q17 同一器件的多次提取历史（FR-25/FR-33，版本对比）
-- -----------------------------------------------------------------------------
SELECT t.task_id, t.source_type, t.source_location, t.created_time,
       ep.raw_name, ep.raw_value, ep.value_num, ep.unit, ep.review_status, ep.confidence
FROM extraction_task t
JOIN extraction_param ep ON ep.task_id = t.task_id
WHERE t.component_id = 1
ORDER BY t.created_time, ep.parameter_id;

-- -----------------------------------------------------------------------------
-- Q18 器件参数详情（含来源，FR-31/33）
-- -----------------------------------------------------------------------------
SELECT display_name, value_num, value_text, unit,
       source_page, source_snippet, approved_time
FROM v_approved_parameter
WHERE component_id = 1
ORDER BY parameter_id;

-- -----------------------------------------------------------------------------
-- Q19 参数别名匹配（NFR-18）：把“工作电压”映射到 Voltage
-- -----------------------------------------------------------------------------
SELECT pd.canonical_name, pd.display_name, pa.alias
FROM parameter_alias pa
JOIN parameter_def pd ON pd.parameter_id = pa.parameter_id
WHERE pa.alias LIKE '%电压%'
ORDER BY pd.parameter_id, pa.alias;

-- -----------------------------------------------------------------------------
-- Q20 排序 + 分页（FR-38）
-- -----------------------------------------------------------------------------
SELECT component_id, model, manufacturer, package
FROM v_component_list
ORDER BY model
LIMIT 5 OFFSET 5;

-- -----------------------------------------------------------------------------
-- Q21 导出查询结果（CSV/Excel 用，FR-45）
-- -----------------------------------------------------------------------------
SELECT c.model, m.name AS manufacturer, cat.name AS category, c.package,
       pd.display_name AS parameter_name, cp.value_num, cp.unit, cp.value_text
FROM component c
JOIN manufacturer m ON m.manufacturer_id = c.manufacturer_id
JOIN category cat   ON cat.category_id   = c.category_id
JOIN component_parameter cp ON cp.component_id = c.component_id
JOIN parameter_def pd       ON pd.parameter_id = cp.parameter_id
ORDER BY c.model, pd.parameter_id;

-- -----------------------------------------------------------------------------
-- Q22 最近操作日志（FR-51/52）
-- -----------------------------------------------------------------------------
SELECT l.created_time, u.username, l.action, l.target_type, l.target_id, l.detail
FROM operation_log l
LEFT JOIN users u ON u.user_id = l.user_id
ORDER BY l.created_time DESC
LIMIT 10;

-- -----------------------------------------------------------------------------
-- Q23 审核追溯：某条提取结果是谁、什么时候、以什么意见审的（FR-23）
-- -----------------------------------------------------------------------------
SELECT a.audit_time, u.username AS auditor, a.action, a.comment, a.detail_json
FROM audit_log a
JOIN users u ON u.user_id = a.auditor_id
JOIN extraction_param ep ON ep.extraction_param_id = a.extraction_param_id
WHERE ep.task_id = 7
ORDER BY a.audit_time, a.audit_log_id;

-- -----------------------------------------------------------------------------
-- Q24 关键查询的执行计划：确认范围查询命中索引
-- -----------------------------------------------------------------------------
EXPLAIN QUERY PLAN
SELECT component_id, value_num
FROM component_parameter
WHERE parameter_id = 4
  AND value_num BETWEEN 3.0 AND 5.0;


-- =============================================================================
--  事务示例（默认注释，需要时取消注释执行）
-- =============================================================================

-- 事务 1：审核通过一条参数（参数级审核）
-- 执行后 LM358 的 Voltage 参数会被发布
-- BEGIN IMMEDIATE;
-- INSERT INTO audit_log (extraction_param_id, auditor_id, action, comment, detail_json)
-- VALUES (
--     (SELECT extraction_param_id FROM extraction_param
--       WHERE task_id = 3 AND parameter_id = 4),
--     2, 'approve', '运放电源电压核对无误', NULL);
-- COMMIT;

-- 事务 1b：驳回同任务下另一条参数（同一次审核可以一部分通过、一部分驳回）
-- BEGIN IMMEDIATE;
-- INSERT INTO audit_log (extraction_param_id, auditor_id, action, comment, detail_json)
-- VALUES (
--     (SELECT extraction_param_id FROM extraction_param
--       WHERE task_id = 3 AND parameter_id = 15),
--     2, 'reject', '工作温度区间格式不规范，请重新提取', NULL);
-- COMMIT;

-- 事务 2：创建提取任务 + 批量写入提取结果
-- BEGIN IMMEDIATE;
-- INSERT INTO extraction_task
--     (user_id, component_id, source_type, source_location, extracted_model,
--      extracted_manufacturer, extracted_category, extracted_package, status)
-- VALUES
--     (3, 20, 'manual', NULL, 'AMS1117-3.3', 'AMS', '集成电路', 'SOT-223', 'success');
-- INSERT INTO extraction_param (task_id, parameter_id, raw_name, raw_value, value_num, unit, confidence, source_page)
-- VALUES
--     ((SELECT MAX(task_id) FROM extraction_task), 4,  'Voltage', '3.3 V', 3.3, 'V', 0.99, NULL),
--     ((SELECT MAX(task_id) FROM extraction_task), 5,  'Current', '1 A',   1,   'A', 0.99, NULL);
-- COMMIT;

-- 事务 3：失败任务重试（FR-18/53）
-- BEGIN IMMEDIATE;
-- UPDATE extraction_task
--    SET status = 'pending',
--        error_msg = NULL,
--        retry_count = retry_count + 1,
--        started_time = NULL,
--        finished_time = NULL
--  WHERE task_id = 5
--    AND status = 'failed'
--    AND retry_count < 3;
-- COMMIT;

-- 事务 4：审核员修改提取参数的值（FR-21，仅 pending 状态可改）
-- BEGIN IMMEDIATE;
-- UPDATE extraction_param
--    SET value_num = 1.0,
--        unit = 'V',
--        raw_value = '1.0 V'
--  WHERE extraction_param_id = 12
--    AND review_status = 'pending';
-- COMMIT;
