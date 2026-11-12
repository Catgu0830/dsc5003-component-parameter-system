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

## 参数提取方法（最强 RAG）

PDF 和 URL 默认走 `最强RAG` 的方法，不再使用旧的规则/PDF 原文提取作为主路径：

- 父子块索引：按页/段落切父块，再切子块；
- 混合检索：embedding 向量 + BM25；
- 查询扩展 3 条 → RRF → LLM rerank top-5；
- 用 Prompt v7（`shape/unit/convention` 契约）生成；
- 每个 `parameter_def` 查一次，失败换查询重试一次；
- 结果写回 `extraction_param`，仍走参数级审核。

配置：

```dotenv
EXTRACTION_ENGINE=rag
# 最强RAG 默认在项目同级目录；也可用 RAG_HOME 指向别处
# RAG_HOME=D:\...\最强RAG
# 0 = 全部参数；设置 8 可限制单份文档的检索/生成次数
RAG_PARAMETER_LIMIT=0
RAG_MAX_PAGES=100
RAG_MAX_CHARS=120000
RAG_MAX_TOKENS=4096
# 不建议开启；开启后 RAG 失败不再回退旧方法
RAG_STRICT=0
```

`最强RAG` 自己读取 `最强RAG/.env` 或进程环境中的 `DASHSCOPE_API_KEY`。该 `.env` 已被 `.gitignore` 排除，不要提交。
本仓库只保留了运行 RAG 检索所需的最小源码（`chips_extractor/llm/rag_baseline.py`、Prompt v7、LLM/embedding client 等），没有提交论文面板、`output/` 索引和运行结果。完整实验目录请放在 `RAG_HOME` 指向的位置。
如果 RAG 目录、Key 或 embedding 服务不可用，后端会回退到原来的 PDF 原文/规则提取；设置 `RAG_STRICT=1` 可以强制失败而不是回退。
手工程录入和 CSV/XLSX 仍走原有解析逻辑。

> 成本提示：默认每个参数一次「扩展 + 混合检索 + rerank + 生成」，17 个参数会明显慢于旧方法、消耗更多 token。演示时可把 `RAG_PARAMETER_LIMIT` 设为 5～8，或只导入目标类别相关的参数。

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
- `/api/tasks`：手工任务；`/api/tasks/upload`：PDF/CSV/XLSX；`/api/tasks/{id}`：详情
- `/api/tasks/{id}/retry`、`/source`、`/source/page/{n}`
- `/api/audit/tasks`：待审任务；`/api/audit/tasks/{id}`：任务+参数明细
- `PUT /api/audit/tasks/{id}/identity`：审核员修改 model/manufacturer/category/package
- `POST /api/audit/params/{extraction_param_id}`：`{"action":"approve|reject","comment":"...","parameter_id":4,"raw_value":"3.3 V","value_num":3.3,"unit":"V"}`
- `/api/audit/logs`：审核日志
- `/api/export/components`、`/api/export/compare`
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

- 一个 `extraction_task` 对应一个元器件；多行 CSV/XLSX 需要拆成多个任务。
- 没有 OCR；扫描 PDF 需先 OCR。
- PDF 原文候选需要人工映射；自动识别厂商/型号只覆盖部分厂商。
- 没有保存筛选、相似推荐、详情 PDF 导出。
- 旧版 10 表数据库不能直接复用；如存在旧库，请备份后删除，首次启动会建 11 表。

## 目录

- `backend/`：Flask 应用、11 表 schema、提取/审核/查询/导出
- `run.py`：Waitress + 后台队列线程
- `requirements.txt`：依赖
- `examples/`：示例 PDF/CSV/XLSX
- `scripts/`：旧版交付脚本，使用前请按 11 表检查
- `docs/`：旧版接口/架构文档，可能仍描述 10 表；以本 README 和 `backend/schema.sql` 为准
- `tests/`：11 表核心流程测试（`pytest -q tests`）
