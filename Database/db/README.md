# 数据库脚本说明（SQLite）

电子元器件参数自动提取查询系统的数据库实现，对应需求规格说明书第 4 章。
脚本已在 SQLite 3.53 上完整执行并通过约束/触发器测试。

## 1. 文件说明

| 文件 | 用途 |
|---|---|
| `00_reset.sql` | 删除全部视图/表（**会清空数据**，开发期重建用） |
| `01_schema.sql` | 建表、约束、索引、视图、触发器（核心脚本） |
| `02_seed.sql` | 演示数据：21 个器件、10 个提取任务、13 条审核记录 |
| `03_queries.sql` | 24 组示例查询 + 5 个事务模板 |
| `04_fts5.sql` | 可选：FTS5 trigram 全文索引（型号/封装/描述子串搜索） |
| `init_db.py` | 一键生成 `demo.db`，并做外键/完整性/业务不变量检查 |
| `verify_core.py` | 核心功能验收：60 项检查，覆盖结构、约束、查询、审核流程 |
| `demo.db` | 生成物，可直接用 DB Browser for SQLite 打开 |

## 1.1 ER 图

与 `01_schema.sql` 一致的 ER 图（Crow's Foot）已经生成：

- `../数据库小组项目_v2.drawio`：可编辑源文件（diagrams.net 打开）
- `../数据库小组项目_v2.png`：导出图，可直接插入报告
- `er_diagram/README.md`：旧图 → 新图对照、报告放置建议、重新生成方式

## 2. 快速开始

```bash
cd db

# 方式一：Python（推荐，会自动做检查）
python init_db.py --with-fts

# 方式二：sqlite3 命令行
sqlite3 demo.db < 01_schema.sql
sqlite3 demo.db < 02_seed.sql
sqlite3 -header -column demo.db < 03_queries.sql
```

`init_db.py` 默认会删除旧的 `demo.db` 再重建；加 `--no-overwrite` 可避免误删。
`--run-queries` 会在建库后顺带执行 `03_queries.sql` 做语法校验。

建库后跑核心功能验收（不会修改 `demo.db`）：

```bash
python verify_core.py
```

### 演示账号

| 用户名 | 角色 | 状态 | 密码 |
|---|---|---|---|
| `admin` | admin | 启用 | `Passw0rd!` |
| `auditor` | auditor | 启用 | `Passw0rd!` |
| `user01` | user | 启用 | `Passw0rd!` |
| `user02` | user | 禁用 | `Passw0rd!` |

密码字段存的是 Werkzeug 格式哈希（`pbkdf2:sha256:600000$salt$hash`），
后端可直接用 `werkzeug.security.check_password_hash()` 校验。

## 3. 表结构总览（11 张表）

| 表 | 作用 | 关键约束 |
|---|---|---|
| `users` | 用户与角色 | `username` 唯一；`role` CHECK；`is_active` |
| `category` | 器件类别字典 | `name` 唯一 |
| `manufacturer` | 厂商 | `name` 唯一；`short_name` |
| `component` | 元器件 | `UNIQUE(manufacturer_id, model)`；`package` |
| `parameter_def` | 参数名字典（标准名/单位/类型） | `canonical_name` 唯一 |
| `parameter_alias` | 参数别名（Voltage/V/工作电压） | `alias` 全局唯一 |
| `extraction_task` | 提取任务（只存作业状态） | 状态机 CHECK；`retry_count` |
| `extraction_param` | 提取结果（审核对象） | 一条记录一个参数；`review_status` |
| `component_parameter` | 正式参数（当前有效值；提取来源须审核通过） | PK `(component_id, parameter_id)`；`source_extraction_param_id` 指回提取结果 |
| `audit_log` | 审核日志（只追加） | 指向 `extraction_param`；只能 auditor 写入 |
| `operation_log` | 通用操作日志 | 登录/上传/审核/删除/导出 |

> `saved_filter`（FR-39，低优先级）已按讨论删除，先保证核心功能。

视图：

- `v_component_list`：器件 + 厂商 + 类别（查询基础视图）
- `v_approved_parameter`：已发布参数（带来源与审核信息）
- `v_task_review`：任务审核进度（由参数状态聚合，不存任务级状态）
- `v_pending_review`：待审核参数列表（一条记录一个待审参数）
- `v_task_overview`：任务总览 + 审核进度 + 最近审核动作
- `v_extraction_detail`：审核页明细（原文/归一化值/来源/置信度/审核结果）

## 4. 审核流程（本设计的核心）

审核对象是**提取结果**，不是任务：

```
提取：INSERT extraction_task + extraction_param(review_status='pending')
        ↓
审核员核对：UPDATE extraction_param（只允许 pending 状态修改）
        ↓
对每一条参数：
  通过：INSERT audit_log(extraction_param_id, auditor_id, 'approve', comment)
        ↓ 触发器 trg_audit_apply：
        1) 这一条 extraction_param.review_status = 'approved'
        2) UPSERT 到 component_parameter（正式参数）
        3) component_parameter.source_extraction_param_id 指回这一条提取结果
  驳回：INSERT audit_log(..., 'reject', comment)
        这一条参数变为 rejected，不进入正式参数表
```

因此同一个任务可以“4 条通过、1 条驳回”；任务进度由 `v_task_review` 统计：

| review_state | 含义 |
|---|---|
| `empty` | 任务还没有提取出参数 |
| `pending` | 所有参数都未审核 |
| `partial` | 一部分已审、一部分待审 |
| `reviewed` | 没有待审参数（可能有通过也有驳回） |

**后端只需要插一条 `audit_log`，不要手工改 `review_status` / `component_parameter`**，
状态同步与入库全部由触发器保证，避免“审核了但没入库”的不一致。

触发器清单：

| 触发器 | 作用 |
|---|---|
| `trg_audit_auditor_only` | 只有 `role='auditor'` 能写审核日志 |
| `trg_audit_requires_success` | 只能审核 `status='success'` 的任务下的参数 |
| `trg_audit_requires_pending` | 只能审核仍为 `pending` 的参数，防止重复审核 |
| `trg_audit_requires_component` | 通过前任务必须已绑定 `component_id` |
| `trg_ep_approved_requires_mapping` | 参数未映射到字典不能通过 |
| `trg_audit_apply` | 更新这一条参数状态；通过时自动入库 |
| `trg_audit_immutable` | 审核日志禁止修改 |
| `trg_ep_locked_after_review` | 已审核的提取结果禁止再改 |
| `trg_component_touch` / `trg_component_parameter_touch` | 自动维护 `updated_time` |

## 5. 与需求文档的对应关系

| 需求文档（4.2/4.3） | 本脚本 | 变化 |
|---|---|---|
| `User` | `users` | `password` → `password_hash`；新增 `is_active`、`last_login_time` |
| `Manufacturer` | `manufacturer` | 新增 `short_name`；`name` 唯一 |
| `Component` | `component` | 新增 `package`、`category_id`、`description`、`updated_time`；型号厂商内唯一 |
| `Extraction_task` | `extraction_task` | 去掉 `action/action_time` 和任务级审核状态；新增 `retry_count`、`source_hash`、`extracted_*` |
| `Parameters` | `component_parameter` | 值拆成 `value_num/unit/value_text`；`source_extraction_param_id` 直连提取结果，来源信息回查 |
| `Audit_log` | `audit_log` | `task_id` → `extraction_param_id`；`user_id` → `auditor_id`；新增 `detail_json` |
| — | `category` | 新增（DS-03 类别枚举） |
| — | `parameter_def` / `parameter_alias` | 新增（DS-01/02、NFR-18 参数标准化） |
| — | `extraction_param` | 新增（提取结果 + 参数级审核状态） |
| — | `operation_log` | 新增（FR-51/52 操作日志） |

### 角色与权限怎么落地

`users.role` 是 ISA 单表继承的判别字段，它**不直接限制权限**；权限检查在 Flask 接口层：

```python
@app.delete("/api/components/<int:cid>")
@require_role("admin")
def delete_component(cid): ...
```

数据库只兜底最关键的规则：`audit_log.auditor_id` 必须是 `role='auditor'` 的用户
（`trg_audit_auditor_only`）。所以“普通用户不能审核”由两层保证：
接口层拒绝 + 触发器拒绝。报告里可以这样写，比“拆成三张用户表”更符合本项目的规模。

### 原设计中的问题已在脚本里修正

1. **参数直接入库、无法审核**：拆成 `extraction_param`（待审）与 `component_parameter`（正式），满足 BR-02、FR-20~23。
2. **审核粒度错误**：审核从“任务级”改为“参数级”，`audit_log` 指向 `extraction_param`，支持部分通过、部分驳回，满足 FR-21/22。
3. **`parameter_value VARCHAR` 无法做范围查询**：拆 `value_num` + `unit` + `value_text`，满足 FR-35/36、DS-06、NFR-17。
4. **缺参数级来源/置信度**：`extraction_param` 增加 `source_page`、`source_snippet`、`confidence`，满足 FR-16/17/31、DQ-04。
5. **缺封装、类别是自由文本**：`component.package` + `category` 字典表，满足 FR-13/28/34、DS-03/04。
6. **唯一约束缺失**：`UNIQUE(manufacturer_id, model)`、`manufacturer.name UNIQUE`，满足 BR-01、DS-05。
7. **没有通用操作日志**：新增 `operation_log`，满足 FR-51/52。
8. **用户不能禁用、没有最后登录时间**：`is_active`、`last_login_time`，满足 FR-02/05。
9. **审核日志基数错误**：`Audit_log` 与 `Extraction_task` 的 1:1 改为 `Audit_log` N:1 `Extraction_param`。
10. **索引与查询方式不匹配**：`(parameter_id, value_num)` 复合索引支持范围查询；子串搜索提供可选 FTS5。
11. **时间语义未定义**：统一存 UTC 的 `TEXT`（`YYYY-MM-DD HH:MM:SS.SSS`），展示层转本地时间。
12. **删除策略未定义**：参数随器件 `CASCADE`；厂商/参数字典被引用时 `RESTRICT`；任务删除时来源置空。
13. **正式参数与提取结果没有直连**：增加 `component_parameter.source_extraction_param_id`，去掉重复的来源/审核快照字段，追溯链变成 `audit_log → extraction_param → component_parameter`。

## 6. 报告需要同步修改的地方

- **4.1 概念设计**：ER 图增加 `extraction_param`、`category`、`parameter_def`、`parameter_alias`、`operation_log`；`Audit_log` 连到 `Extraction_param`，`Component_parameter` 也连到 `Extraction_param`（来源）。
- **4.2 关系模式**：按第 3 节的新表名重写；`Extraction_task` 不再有 `review_status`；`Component_parameter` 用 `source_extraction_param_id` 指回提取结果。
- **4.3 表结构**：直接按 `01_schema.sql` 更新字段、类型、约束。
- **4.4 索引设计**：补充复合索引 `(parameter_id, value_num)`、`audit_log(extraction_param_id)` 与 FTS5 方案。
- **4.5 设计小结**：补充“提取与发布分离”“参数级审核”“任务审核进度由视图统计”。
- **2.5.2 DS-06**：原文要求“数值型参数存数值类型并附带单位”，与 4.3.5 的 `VARCHAR(100)` 矛盾，现已按 DS-06 实现。
- **第 5 章接口**：审核接口改为传 `extraction_param_id` + `action` + `comment`，不是 `task_id`。
- **权限章节**：写明 ISA 单表继承 + 应用层权限 + 数据库触发器兜底。

## 7. 后端接入注意事项

1. **每个连接都要开外键**，否则 `ON DELETE` / FK 约束不生效：

   ```python
   def get_db():
       con = sqlite3.connect("db/demo.db")
       con.execute("PRAGMA foreign_keys = ON")
       con.execute("PRAGMA busy_timeout = 5000")
       con.row_factory = sqlite3.Row
       return con
   ```

2. 并发写建议开 WAL：`PRAGMA journal_mode = WAL;`（只需设置一次）。
3. **审核只插 `audit_log`**，字段是 `extraction_param_id`，不是 `task_id`；不要手工改状态。
4. 审核员改参数值：只更新 `extraction_param` 且 `review_status='pending'`；审核后触发器会锁住。
5. 查询“对外可见”的参数一律走 `component_parameter` / `v_approved_parameter`；待审核数据只在审核页查 `extraction_param`。
6. `source_type` 用固定枚举：`pdf` / `url` / `excel` / `csv` / `manual`；任务状态：`pending/processing/success/failed`。
7. 时间统一按 UTC 写入，前端展示时再 `+8`；SQLite 的 `datetime('now')` 本身就是 UTC。
8. 演示前备份 `demo.db`（NFR-10），或保留 `02_seed.sql` 随时重建。

## 8. 版本与移植

- 需要 SQLite **3.24+**（UPSERT）；`04_fts5.sql` 需要 **3.34+** 且编译了 FTS5。
- Python 3.8+ 自带的 `sqlite3` 通常满足；可用 `python -c "import sqlite3; print(sqlite3.sqlite_version)"` 检查。
- 若组内最终决定改用 PostgreSQL/MySQL（TeamForming 里写的是 PostgreSQL/MySQL，需求书写的是 SQLite，**需要先统一**），主要改动：
  - `INTEGER PRIMARY KEY` → `SERIAL` / `IDENTITY`
  - `strftime(...)` 默认值 → `CURRENT_TIMESTAMP`
  - `COLLATE NOCASE` → `utf8mb4_0900_ai_ci` / `CITEXT`
  - 触发器里的 `ON CONFLICT ... DO UPDATE` → `ON DUPLICATE KEY UPDATE` / `ON CONFLICT`
  - FTS5 → MySQL `FULLTEXT`（ngram）或 PostgreSQL `pg_trgm`
  - `SUM(action='approve')` → `SUM(CASE WHEN action='approve' THEN 1 ELSE 0 END)`

课程演示建议坚持 SQLite：零安装、单文件、备份方便，和需求书一致。

## 9. 示例查询

`03_queries.sql` 覆盖了报告中需要展示的查询类型：

- 关键词/类别/厂商筛选、排序分页（FR-34/38）
- 单参数范围、多参数组合（FR-35/36）
- 多器件参数对比（行转列，FR-40）
- 参数缺失、低置信度、参数级待审核列表（FR-20/42）
- 审核统计、类别/厂商统计、任务状态与审核进度
- 数据质量检查（单位一致性、重复型号）
- 提取历史与版本对比（FR-25/33）、审核追溯（FR-23）
- `EXPLAIN QUERY PLAN` 验证索引命中

其中 `EXPLAIN QUERY PLAN` 的输出确认了范围查询走
`idx_cp_parameter_value (parameter_id=? AND value_num>? AND value_num<?)`。
