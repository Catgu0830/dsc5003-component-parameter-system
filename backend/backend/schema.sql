-- =============================================================================
--  电子元器件参数自动提取查询系统 · 数据库脚本
--  01_schema.sql : 表 / 约束 / 索引 / 视图 / 触发器
--  DBMS   : SQLite 3.35+（用到 UPSERT、部分索引、生成默认值）
--  编码   : UTF-8
--  时间   : 统一存 UTC，格式 'YYYY-MM-DD HH:MM:SS.SSS'，展示层再转本地时间
-- =============================================================================
--  设计要点（与需求文档 4.x 的差异见 db/README.md）
--  1. 提取结果（extraction_param）与正式参数（component_parameter）分离：
--     只有审核通过的数据才进入正式参数表，满足 BR-02。
--  2. 审核作用在“提取结果”上，而不是“任务”上：一条 extraction_param 一条审核记录，
--     可以 4 条通过、1 条驳回；任务审核进度由视图 v_task_review 统计。
--  3. 参数值拆成 value_num + unit + value_text，支持范围查询与单位归一化。
--  4. 参数名走字典表 parameter_def + 别名表 parameter_alias，满足 NFR-18。
--  5. 封装、类别、厂商独立建模，型号在厂商内唯一（BR-01）。
--  6. 用户角色用单表 + role 区分（ISA 单表继承）；权限在 Flask 接口层校验，
--     数据库触发器只兜底“审核人必须是 auditor”这一类关键规则。
-- =============================================================================

PRAGMA foreign_keys = ON;

-- -----------------------------------------------------------------------------
-- 1. 类别（DS-03 预定义枚举，用字典表便于扩展）
-- -----------------------------------------------------------------------------
CREATE TABLE category (
    category_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT,
    CONSTRAINT ck_category_name CHECK (length(trim(name)) > 0)
);

-- -----------------------------------------------------------------------------
-- 2. 厂商（FR-27 / DS-05）
-- -----------------------------------------------------------------------------
CREATE TABLE manufacturer (
    manufacturer_id INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE COLLATE NOCASE,
    short_name      TEXT,
    website         TEXT,
    created_time    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    CONSTRAINT ck_manufacturer_name CHECK (length(trim(name)) > 0),
    CONSTRAINT ck_manufacturer_website CHECK (website IS NULL OR website GLOB 'http*')
);

-- -----------------------------------------------------------------------------
-- 3. 用户（FR-01~05）
--    ISA 采用单表继承：role 是判别字段；权限由 Flask 装饰器校验。
-- -----------------------------------------------------------------------------
CREATE TABLE users (
    user_id         INTEGER PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'user'
                    CHECK (role IN ('admin', 'auditor', 'user')),
    is_active       INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    last_login_time TEXT,
    created_time    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    CONSTRAINT ck_users_username CHECK (length(username) BETWEEN 3 AND 50)
);

-- -----------------------------------------------------------------------------
-- 4. 元器件（FR-26/28/32；BR-01 型号在同一厂商下唯一）
-- -----------------------------------------------------------------------------
CREATE TABLE component (
    component_id    INTEGER PRIMARY KEY,
    model           TEXT NOT NULL COLLATE NOCASE,
    category_id     INTEGER NOT NULL REFERENCES category(category_id)
                    ON UPDATE CASCADE ON DELETE RESTRICT,
    manufacturer_id INTEGER NOT NULL REFERENCES manufacturer(manufacturer_id)
                    ON UPDATE CASCADE ON DELETE RESTRICT,
    package         TEXT,
    description     TEXT,
    created_time    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    updated_time    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    CONSTRAINT uq_component_model UNIQUE (manufacturer_id, model),
    CONSTRAINT ck_component_model CHECK (length(trim(model)) > 0)
);

-- -----------------------------------------------------------------------------
-- 5. 提取任务（FR-06~11/18/19/49/50/53）
--    这里只存“提取作业”的状态；审核状态不在这里，在 extraction_param 上。
--    component_id 允许为空：新器件在审核通过前可能还没有正式元器件记录。
-- -----------------------------------------------------------------------------
CREATE TABLE extraction_task (
    task_id                INTEGER PRIMARY KEY,
    user_id                INTEGER NOT NULL REFERENCES users(user_id)
                           ON UPDATE CASCADE ON DELETE RESTRICT,
    component_id           INTEGER REFERENCES component(component_id)
                           ON UPDATE CASCADE ON DELETE SET NULL,
    source_type            TEXT NOT NULL
                           CHECK (source_type IN ('pdf', 'url', 'excel', 'csv', 'manual')),
    source_location        TEXT,
    source_hash            TEXT,
    extracted_model        TEXT,
    extracted_manufacturer TEXT,
    extracted_category     TEXT,
    extracted_package      TEXT,
    status                 TEXT NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending', 'processing', 'success', 'failed')),
    error_msg              TEXT,
    retry_count            INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    created_time           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    started_time           TEXT,
    finished_time          TEXT,
    CONSTRAINT ck_task_failed_msg CHECK (status <> 'failed' OR error_msg IS NOT NULL),
    CONSTRAINT ck_task_finished CHECK (
        finished_time IS NULL OR status IN ('success', 'failed')
    )
);

-- -----------------------------------------------------------------------------
-- 6. 参数名字典（DS-01/02/06，NFR-18）
--    unit 为该参数的标准单位；无单位的数值参数（如引脚数）unit 为 NULL
-- -----------------------------------------------------------------------------
CREATE TABLE parameter_def (
    parameter_id   INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name   TEXT NOT NULL,
    unit           TEXT,
    data_type      TEXT NOT NULL DEFAULT 'numeric'
                   CHECK (data_type IN ('numeric', 'text', 'boolean')),
    category_id    INTEGER REFERENCES category(category_id)
                   ON UPDATE CASCADE ON DELETE SET NULL,
    description    TEXT,
    CONSTRAINT ck_parameter_name CHECK (length(trim(canonical_name)) > 0),
    CONSTRAINT ck_parameter_display CHECK (length(trim(display_name)) > 0)
);

-- -----------------------------------------------------------------------------
-- 7. 参数别名（NFR-18：Voltage / V / 工作电压 → 同一个参数）
-- -----------------------------------------------------------------------------
CREATE TABLE parameter_alias (
    alias_id     INTEGER PRIMARY KEY,
    parameter_id INTEGER NOT NULL REFERENCES parameter_def(parameter_id)
                 ON UPDATE CASCADE ON DELETE CASCADE,
    alias        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    CONSTRAINT ck_alias CHECK (length(trim(alias)) > 0)
);

-- -----------------------------------------------------------------------------
-- 8. 提取结果（审核对象；FR-16/17/20/21/25）
--    一条记录 = 一个参数值，审核状态也在这里。
--    parameter_id 为空表示未映射到字典，审核员需先映射才能通过。
-- -----------------------------------------------------------------------------
CREATE TABLE extraction_param (
    extraction_param_id INTEGER PRIMARY KEY,
    task_id             INTEGER NOT NULL REFERENCES extraction_task(task_id)
                        ON UPDATE CASCADE ON DELETE CASCADE,
    parameter_id        INTEGER REFERENCES parameter_def(parameter_id)
                        ON UPDATE CASCADE ON DELETE SET NULL,
    raw_name            TEXT NOT NULL,
    raw_value           TEXT NOT NULL,
    value_num           REAL,
    unit                TEXT,
    confidence          REAL
                        CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    source_page         INTEGER CHECK (source_page IS NULL OR source_page > 0),
    source_snippet      TEXT,
    review_status       TEXT NOT NULL DEFAULT 'pending'
                        CHECK (review_status IN ('pending', 'approved', 'rejected')),
    reviewed_by         INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    reviewed_time       TEXT,
    review_comment      TEXT,
    created_time        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    CONSTRAINT uq_extraction_param UNIQUE (task_id, raw_name),
    CONSTRAINT ck_extraction_raw CHECK (
        length(trim(raw_name)) > 0 AND length(trim(raw_value)) > 0
    ),
    CONSTRAINT ck_extraction_reviewed CHECK (
        review_status = 'pending'
        OR (reviewed_by IS NOT NULL AND reviewed_time IS NOT NULL)
    )
);

-- -----------------------------------------------------------------------------
-- 9. 正式参数（当前有效值；来自提取的必须审核通过；FR-21/29/30/33）
--    主键 (component_id, parameter_id)：一个器件同一参数只保留当前有效值。
--    source_extraction_param_id 直接指向被批准的那条提取结果，来源信息全部从
--    extraction_param 回查，避免重复字段不一致。
-- -----------------------------------------------------------------------------
CREATE TABLE component_parameter (
    component_id   INTEGER NOT NULL REFERENCES component(component_id)
                   ON UPDATE CASCADE ON DELETE CASCADE,
    parameter_id   INTEGER NOT NULL REFERENCES parameter_def(parameter_id)
                   ON UPDATE CASCADE ON DELETE RESTRICT,
    value_num      REAL,
    unit           TEXT,
    value_text     TEXT,
    source_extraction_param_id INTEGER
                   REFERENCES extraction_param(extraction_param_id)
                   ON UPDATE CASCADE ON DELETE SET NULL,
    created_time   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    updated_time   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    PRIMARY KEY (component_id, parameter_id),
    CONSTRAINT ck_component_parameter_value CHECK (
        value_num IS NOT NULL
        OR (value_text IS NOT NULL AND length(trim(value_text)) > 0)
    )
);

-- -----------------------------------------------------------------------------
-- 10. 审核日志（FR-22/23/25；BR-02）
--     一条记录对应一条被审核的提取结果，而不是整个任务。
--     detail_json 保存审核员修改前后的值，便于追溯。
-- -----------------------------------------------------------------------------
CREATE TABLE audit_log (
    audit_log_id       INTEGER PRIMARY KEY,
    extraction_param_id INTEGER NOT NULL REFERENCES extraction_param(extraction_param_id)
                       ON UPDATE CASCADE ON DELETE CASCADE,
    auditor_id         INTEGER NOT NULL REFERENCES users(user_id)
                       ON UPDATE CASCADE ON DELETE RESTRICT,
    action             TEXT NOT NULL CHECK (action IN ('approve', 'reject')),
    comment            TEXT,
    detail_json        TEXT,
    audit_time         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    CONSTRAINT ck_audit_reject_comment CHECK (
        action <> 'reject' OR (comment IS NOT NULL AND length(trim(comment)) > 0)
    )
);

-- -----------------------------------------------------------------------------
-- 11. 操作日志（FR-51/52：登录、上传、提取、审核、删除、导出）
-- -----------------------------------------------------------------------------
CREATE TABLE operation_log (
    log_id       INTEGER PRIMARY KEY,
    user_id      INTEGER REFERENCES users(user_id)
                 ON UPDATE CASCADE ON DELETE SET NULL,
    action       TEXT NOT NULL,
    target_type  TEXT CHECK (
        target_type IS NULL
        OR target_type IN ('auth', 'user', 'component', 'parameter', 'task', 'export')
    ),
    target_id    INTEGER,
    detail       TEXT,
    ip_address   TEXT,
    created_time TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
    CONSTRAINT ck_operation_action CHECK (length(trim(action)) > 0)
);

-- =============================================================================
--  索引（4.4 节）
-- =============================================================================
CREATE INDEX idx_component_model        ON component (model);
CREATE INDEX idx_component_category     ON component (category_id, model);
CREATE INDEX idx_component_manufacturer ON component (manufacturer_id, model);
CREATE INDEX idx_component_package      ON component (package);
CREATE INDEX idx_alias_parameter        ON parameter_alias (parameter_id);

-- 参数范围查询的核心索引：按 parameter_id 定位，再按 value_num 做区间扫描
CREATE INDEX idx_cp_parameter_value ON component_parameter (parameter_id, value_num);
CREATE INDEX idx_cp_source_param    ON component_parameter (source_extraction_param_id);

CREATE INDEX idx_task_user_time ON extraction_task (user_id, created_time DESC);
CREATE INDEX idx_task_status    ON extraction_task (status);
CREATE INDEX idx_task_component ON extraction_task (component_id);

CREATE INDEX idx_ep_task        ON extraction_param (task_id, review_status);
CREATE INDEX idx_ep_review      ON extraction_param (review_status, task_id);
CREATE INDEX idx_ep_parameter   ON extraction_param (parameter_id, value_num);
CREATE INDEX idx_ep_confidence  ON extraction_param (confidence);

CREATE INDEX idx_audit_param    ON audit_log (extraction_param_id, audit_time DESC);
CREATE INDEX idx_audit_auditor  ON audit_log (auditor_id, audit_time DESC);

CREATE INDEX idx_oplog_user_time ON operation_log (user_id, created_time DESC);
CREATE INDEX idx_oplog_target    ON operation_log (target_type, target_id);

-- =============================================================================
--  视图
-- =============================================================================

-- 器件列表（关键词 / 类别 / 厂商 / 封装 查询的基础视图）
CREATE VIEW v_component_list AS
SELECT c.component_id,
       c.model,
       m.manufacturer_id,
       m.name AS manufacturer,
       cat.category_id,
       cat.name AS category,
       c.package,
       c.description,
       c.created_time
FROM component c
JOIN manufacturer m ON m.manufacturer_id = c.manufacturer_id
JOIN category cat   ON cat.category_id   = c.category_id;

-- 已发布参数（只有审核通过的数据会出现在这里）
CREATE VIEW v_approved_parameter AS
SELECT cp.component_id,
       c.model,
       m.name AS manufacturer,
       cat.name AS category,
       c.package,
       pd.parameter_id,
       pd.canonical_name,
       pd.display_name,
       COALESCE(pd.unit, cp.unit) AS unit,
       cp.value_num,
       cp.value_text,
       cp.unit AS stored_unit,
       ep.task_id       AS source_task_id,
       ep.source_page,
       ep.source_snippet,
       ep.reviewed_by   AS approved_by,
       ep.reviewed_time AS approved_time,
       cp.updated_time
FROM component_parameter cp
JOIN component c      ON c.component_id    = cp.component_id
JOIN manufacturer m   ON m.manufacturer_id = c.manufacturer_id
JOIN category cat     ON cat.category_id   = c.category_id
JOIN parameter_def pd ON pd.parameter_id   = cp.parameter_id
LEFT JOIN extraction_param ep
       ON ep.extraction_param_id = cp.source_extraction_param_id;

-- 任务审核进度（由参数审核状态聚合，不单独存任务级状态）
CREATE VIEW v_task_review AS
SELECT t.task_id,
       COUNT(ep.extraction_param_id) AS param_count,
       COALESCE(SUM(ep.review_status = 'pending'), 0)  AS pending_count,
       COALESCE(SUM(ep.review_status = 'approved'), 0) AS approved_count,
       COALESCE(SUM(ep.review_status = 'rejected'), 0) AS rejected_count,
       CASE
         WHEN COUNT(ep.extraction_param_id) = 0 THEN 'empty'
         WHEN SUM(ep.review_status = 'pending') = 0 THEN 'reviewed'
         WHEN SUM(ep.review_status = 'pending') = COUNT(ep.extraction_param_id) THEN 'pending'
         ELSE 'partial'
       END AS review_state
FROM extraction_task t
LEFT JOIN extraction_param ep ON ep.task_id = t.task_id
GROUP BY t.task_id;

-- 待审核列表（审核员的待办：一条记录就是一个待审参数）
CREATE VIEW v_pending_review AS
SELECT ep.extraction_param_id,
       ep.task_id,
       t.user_id,
       u.username,
       t.component_id,
       c.model,
       t.source_type,
       t.source_location,
       ep.parameter_id,
       pd.canonical_name,
       pd.display_name,
       ep.raw_name,
       ep.raw_value,
       ep.value_num,
       ep.unit,
       ep.confidence,
       ep.source_page,
       ep.source_snippet,
       ep.created_time
FROM extraction_param ep
JOIN extraction_task t      ON t.task_id      = ep.task_id
JOIN users u                ON u.user_id      = t.user_id
LEFT JOIN component c       ON c.component_id = t.component_id
LEFT JOIN parameter_def pd  ON pd.parameter_id = ep.parameter_id
WHERE ep.review_status = 'pending'
  AND t.status = 'success';

-- 任务总览（含审核进度与最近一次审核动作）
CREATE VIEW v_task_overview AS
SELECT t.task_id,
       u.username,
       t.component_id,
       c.model,
       t.source_type,
       t.source_location,
       t.status,
       t.retry_count,
       t.error_msg,
       t.created_time,
       t.finished_time,
       r.param_count,
       r.pending_count,
       r.approved_count,
       r.rejected_count,
       r.review_state,
       (SELECT a.action FROM audit_log a
         JOIN extraction_param ep ON ep.extraction_param_id = a.extraction_param_id
        WHERE ep.task_id = t.task_id
        ORDER BY a.audit_time DESC, a.audit_log_id DESC LIMIT 1) AS last_audit_action,
       (SELECT a.audit_time FROM audit_log a
         JOIN extraction_param ep ON ep.extraction_param_id = a.extraction_param_id
        WHERE ep.task_id = t.task_id
        ORDER BY a.audit_time DESC, a.audit_log_id DESC LIMIT 1) AS last_audit_time
FROM extraction_task t
JOIN users u            ON u.user_id = t.user_id
LEFT JOIN component c   ON c.component_id = t.component_id
LEFT JOIN v_task_review r ON r.task_id = t.task_id;

-- 提取明细（审核页面：原文、归一化值、置信度、来源、审核结果）
CREATE VIEW v_extraction_detail AS
SELECT ep.extraction_param_id,
       ep.task_id,
       ep.parameter_id,
       pd.canonical_name,
       pd.display_name,
       pd.unit AS canonical_unit,
       ep.raw_name,
       ep.raw_value,
       ep.value_num,
       ep.unit,
       ep.confidence,
       ep.source_page,
       ep.source_snippet,
       ep.review_status,
       ep.reviewed_by,
       ep.reviewed_time,
       ep.review_comment
FROM extraction_param ep
LEFT JOIN parameter_def pd ON pd.parameter_id = ep.parameter_id;

-- =============================================================================
--  触发器
-- =============================================================================

-- 1) 只有 role='auditor' 的用户可以写审核日志（权限矩阵：管理员也不能审核）
CREATE TRIGGER trg_audit_auditor_only
BEFORE INSERT ON audit_log
FOR EACH ROW
WHEN (SELECT role FROM users WHERE user_id = NEW.auditor_id) <> 'auditor'
BEGIN
    SELECT RAISE(ABORT, 'audit_log.auditor_id 必须是 role=auditor 的用户');
END;

-- 2) 只能审核提取成功的任务下的参数
CREATE TRIGGER trg_audit_requires_success
BEFORE INSERT ON audit_log
FOR EACH ROW
WHEN (
    SELECT t.status
      FROM extraction_param ep
      JOIN extraction_task t ON t.task_id = ep.task_id
     WHERE ep.extraction_param_id = NEW.extraction_param_id
) <> 'success'
BEGIN
    SELECT RAISE(ABORT, '只能审核 status=success 的任务下的提取结果');
END;

-- 3) 只能审核仍处于 pending 的提取结果，防止重复审核
CREATE TRIGGER trg_audit_requires_pending
BEFORE INSERT ON audit_log
FOR EACH ROW
WHEN (
    SELECT review_status
      FROM extraction_param
     WHERE extraction_param_id = NEW.extraction_param_id
) <> 'pending'
BEGIN
    SELECT RAISE(ABORT, '该提取结果已审核，不能重复审核');
END;

-- 4) 审核通过前，任务必须已绑定元器件（否则参数无法入库）
CREATE TRIGGER trg_audit_requires_component
BEFORE INSERT ON audit_log
FOR EACH ROW
WHEN NEW.action = 'approve'
 AND (
    SELECT t.component_id
      FROM extraction_param ep
      JOIN extraction_task t ON t.task_id = ep.task_id
     WHERE ep.extraction_param_id = NEW.extraction_param_id
 ) IS NULL
BEGIN
    SELECT RAISE(ABORT, '审核通过前必须先把任务绑定到 component.component_id');
END;

-- 5) 待审核参数必须映射到参数字典后才能通过
CREATE TRIGGER trg_ep_approved_requires_mapping
BEFORE UPDATE OF review_status ON extraction_param
FOR EACH ROW
WHEN NEW.review_status = 'approved' AND NEW.parameter_id IS NULL
BEGIN
    SELECT RAISE(ABORT, '参数未映射到 parameter_def，不能通过审核');
END;

-- 6) 审核动作落库后，只更新这一条提取结果；通过时把它写入正式参数表
CREATE TRIGGER trg_audit_apply
AFTER INSERT ON audit_log
FOR EACH ROW
BEGIN
    -- 6.1 更新被审参数的状态与审核信息
    UPDATE extraction_param
       SET review_status  = CASE NEW.action WHEN 'approve' THEN 'approved' ELSE 'rejected' END,
           reviewed_by    = NEW.auditor_id,
           reviewed_time  = NEW.audit_time,
           review_comment = NEW.comment
     WHERE extraction_param_id = NEW.extraction_param_id;

    -- 6.2 审核通过：把这一条提取结果 upsert 到正式参数表
    --     注意：SQLite 的 INSERT ... SELECT 带 UPSERT 时需要用 AND 1 消除解析歧义
    INSERT INTO component_parameter (
        component_id, parameter_id, value_num, unit, value_text,
        source_extraction_param_id, created_time, updated_time
    )
    SELECT t.component_id, ep.parameter_id, ep.value_num, ep.unit, ep.raw_value,
           ep.extraction_param_id, NEW.audit_time, NEW.audit_time
      FROM extraction_param ep
      JOIN extraction_task t ON t.task_id = ep.task_id
     WHERE ep.extraction_param_id = NEW.extraction_param_id
       AND NEW.action = 'approve'
       AND ep.parameter_id IS NOT NULL
       AND ep.review_status = 'approved'
       AND t.component_id IS NOT NULL
       AND 1
    ON CONFLICT(component_id, parameter_id) DO UPDATE SET
        value_num      = excluded.value_num,
        unit           = excluded.unit,
        value_text     = excluded.value_text,
        source_extraction_param_id = excluded.source_extraction_param_id,
        updated_time   = excluded.updated_time;
END;

-- 7) 审核日志只追加，不允许修改（保留完整审核历史）
CREATE TRIGGER trg_audit_immutable
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log 为只追加表，不允许修改');
END;

-- 8) 已审核的提取结果不允许再改，避免绕过审核改数据
CREATE TRIGGER trg_ep_locked_after_review
BEFORE UPDATE OF raw_value, value_num, unit, parameter_id ON extraction_param
FOR EACH ROW
WHEN OLD.review_status <> 'pending'
BEGIN
    SELECT RAISE(ABORT, '已审核的提取结果不可修改，请新建提取任务');
END;

-- 9) 自动维护 updated_time
CREATE TRIGGER trg_component_touch
AFTER UPDATE OF model, category_id, manufacturer_id, package, description ON component
FOR EACH ROW
BEGIN
    UPDATE component
       SET updated_time = strftime('%Y-%m-%d %H:%M:%f', 'now')
     WHERE component_id = NEW.component_id;
END;

CREATE TRIGGER trg_component_parameter_touch
AFTER UPDATE OF value_num, unit, value_text ON component_parameter
FOR EACH ROW
BEGIN
    UPDATE component_parameter
       SET updated_time = strftime('%Y-%m-%d %H:%M:%f', 'now')
     WHERE component_id = NEW.component_id
       AND parameter_id = NEW.parameter_id;
END;
