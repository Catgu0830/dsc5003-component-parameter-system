# 电子元器件参数自动提取查询系统：后端（11 表版）

后端已按 `Database/db/01_schema.sql` 的 11 张表改造，审核粒度是**参数级**，不是任务级。

## 11 张表

`category`、`manufacturer`、`users`、`component`、`extraction_task`、`parameter_def`、`parameter_alias`、`extraction_param`、`component_parameter`、`audit_log`、`operation_log`

核心规则：

- 提取结果写入 `extraction_param`，每条参数独立审核。
- 审核只插入 `audit_log`；数据库触发器负责把该条参数改成 approved/rejected，并在通过时 UPSERT 到 `component_parameter`。
- `component` 没有 owner_id；任务属于 `extraction_task.user_id`，正式元器件是全局数据。
- `extraction_task` 没有 result_json / review_status；任务审核进度由 `v_task_review` 聚合。
- `extraction_task` 没有 paused/cancelled 状态，只有 pending/processing/success/failed。
- 没有 `tokens` 表，登录使用带签名的无状态 Token（`SECRET_KEY`）。
- 没有 `specifications` 表，PDF 原文片段作为未映射的 `extraction_param` 行保存，审核员映射到 `parameter_def` 后逐条通过。

## 参数提取

- PDF：默认 `PDF_EXTRACTION_MODE=verbatim`，按页提取原文候选并写入 `extraction_param`；`legacy` 使用规则/LLM 文本提取。
- URL：抓取网页后使用规则提取，或配置 `EXTRACTION_MODE=llm|hybrid` 使用 LLM。
- CSV/XLSX：按表头解析，每行生成一个独立任务。
- 审核：所有结果都进入参数级审核，不会直接写入正式参数。

## 快速运行

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m flask --app backend:create_app create-user --username admin --role admin
.\.venv\Scripts\python.exe run.py
```

- 默认数据库：`instance/components.sqlite3`，首次启动自动建 11 表并写入类别/参数词典。
- 使用现有演示库：

```powershell
$env:DATABASE = "D:\...\Database\db\demo.db"
.\.venv\Scripts\python.exe run.py
```

- 健康检查：`GET /api/health`
- 登录：`POST /api/auth/login`，请求体 `{"username":"...","password":"..."}`，后续使用 `Authorization: Bearer <token>`。
- 创建账号：`flask --app backend:create_app create-user --username ... --role admin|auditor|user`

## 主要接口

- `/api/auth/register`、`/login`、`/me`、`/logout`
- `/api/categories`、`/api/parameters`：类别/参数字典（审核映射用）
- `/api/components`：查询、筛选、分页、详情；管理员可 POST/PUT/DELETE
- `/api/components/compare?ids=1,2`
- `/api/tasks`：手工任务；`/api/tasks/batch`：批量手工任务；`/api/tasks/upload`：PDF/CSV/XLSX；CSV/XLSX 每行生成一个任务
- `/api/tasks/{id}`：详情；`DELETE /api/tasks/{id}`：任务所有者或管理员删除（有审核记录时禁止）
- `/api/tasks/{id}/retry`、`/source`、`/source/page/{n}`
- `/api/audit/tasks`：待审任务；`/api/audit/params`：参数级待审列表（含来源/置信度，按置信度升序）
- `/api/audit/tasks/{id}`：任务+参数明细
- `PUT /api/audit/tasks/{id}/identity`：审核员修改 model/manufacturer/category/package
- `POST /api/audit/params/{extraction_param_id}`：`{"action":"approve|reject","comment":"...","parameter_id":4,"raw_value":"3.3 V","value_num":3.3,"unit":"V"}`
- `/api/audit/logs`：审核日志
- `/api/components/{id}/versions`：同一器件最近两次提取的版本差异
- `/api/components/{id}/similar?limit=5`：同类且共享参数较多的相似器件
- `/api/manufacturers/{id}`：DELETE（仅管理员；被元器件引用时返回 409）
- `/api/export/components`、`/api/export/components/{id}`、`/api/export/compare`
- `/api/search`：数据库搜索，无结果时可转提取任务

## 审核流程

1. 提取任务成功，参数进入 `extraction_param`，`review_status='pending'`。
2. 审核员在审核页逐条修改/映射/通过/驳回。
3. 通过前必须：
   - 任务身份字段齐全（model/manufacturer/category）；
   - 参数已映射到 `parameter_def`；
   - 数值参数有 `value_num`。
4. 插入 `audit_log` 后由触发器更新参数状态并发布到 `component_parameter`。
5. 同一任务可以部分通过、部分驳回、部分保持待审。

## 边界

- 一个 `extraction_task` 对应一个元器件；CSV/XLSX 的每一行会自动生成一个独立任务，PDF/URL 一个任务一个元器件。
- 任务所有者或管理员可删除未被审核过的任务；有审核记录的任务保留审计链，不允许删除。
- 提取警告会通过任务 API 的 `warnings` 字段返回，审核页会显示。
- 没有 OCR；扫描 PDF 需先 OCR。
- PDF 原文候选需要人工映射；自动识别厂商/型号只覆盖部分厂商。
- 低优先级已补：保存筛选（前端 localStorage）、版本对比、相似器件推荐、单器件详情 CSV/XLSX/JSON 导出。
- 旧版 10 表数据库不能直接复用；如存在旧库，请备份后删除，首次启动会建 11 表。

## 目录

- `backend/`：Flask 应用、11 表 schema、提取/审核/查询/导出
- `run.py`：Waitress + 后台队列线程
- `requirements.txt`：依赖
- `examples/`：示例 PDF/CSV/XLSX
- `scripts/`：旧版交付脚本，使用前请按 11 表检查
- `docs/`：旧版接口/架构文档，可能仍描述 10 表；以本 README 和 `backend/schema.sql` 为准
- `tests/`：11 表核心流程测试（`pytest -q tests`）
