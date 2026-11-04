# ER 图 v2（与 `db/01_schema.sql` 一致）

## 文件

| 文件 | 说明 |
|---|---|
| `../../数据库小组项目_v2.drawio` | **可编辑源文件**，用 diagrams.net 打开 |
| `../../数据库小组项目_v2.png` | 导出图（3520×1740），可直接插报告 |
| `er_v2.drawio` / `er_v2.png` | 同上，生成器输出副本 |
| `gen_er.py` | 生成脚本；改表结构后重新运行即可 |

## 怎么打开 / 导出

1. 浏览器打开 <https://app.diagrams.net>（或桌面版 draw.io）。
2. `File → Open From → Device`，选 `数据库小组项目_v2.drawio`。
3. 导出：`File → Export as → PNG`，Zoom 200%，取消 Transparent Background。

图里每个表是“绿色表头 + 白色字段行”的组合，**拖动表头整张表会跟着走**；双击某一行就能改字段名。

## 为什么换成 Crow's Foot

原来的 Chen 记号要画属性椭圆。现在有 11 张表、约 80 个字段，如果每个字段都画一个椭圆，A4 上会密到看不清，而且改一次 SQL 就要挪一次椭圆。

Crow's Foot（鸦爪）是 MySQL Workbench、Navicat、dbdiagram 等工具默认的 ER 表达，评审也认；字段类型、主键、外键、唯一约束都能直接读出来，和 SQL 一一对应。

## 旧图 → 新图

| 旧图 | 新图 | 变化 |
|---|---|---|
| `User` + ISA 子类 | `users` | ISA 合并为 `role`；新增 `is_active`、`last_login_time` |
| `Manufacturer` | `manufacturer` | 新增 `short_name`；`name` 唯一 |
| `Component` | `component` | 新增 `package`、`description`、`updated_time`；类别改为外键 |
| `Extraction_task` | `extraction_task` | 去掉任务级 `review_status` 和 `action/action_time`；新增 `retry_count` |
| `Parameters`（弱实体） | `extraction_param` + `component_parameter` | 拆成“待审核提取结果”和“正式参数”两张表；审核状态在 `extraction_param` |
| `Audit_log` | `audit_log` | 改为指向 `extraction_param`（参数级审核）；新增 `detail_json`；`user_id` 改名 `auditor_id` |
| — | `category` | 新增，类别字典 |
| — | `parameter_def` | 新增，参数名/单位字典 |
| — | `parameter_alias` | 新增，参数别名 |
| — | `operation_log` | 新增，通用操作日志 |

关系变化：

- `Extraction_task` — `Audit_log`：改为 `Extraction_param` — `Audit_log`，**一条参数一条审核记录**
- `Extraction_task` — `Extraction_param`：新增 1:N
- `Component_parameter` — `Component` / `Parameter_def` / `Extraction_param`：新增 N:1（`source_extraction_param_id` 指回被批准的提取结果）
- `Parameter_def` — `Parameter_alias`：新增 1:N
- `Users` — `Audit_log` / `Operation_log`：新增 1:N
- `Component` — `Category`、`Parameter_def` — `Category`：新增 N:1
- `Saved_filter` 已删除（FR-39 暂不做）

## 报告里怎么放

**如果老师接受 Crow's Foot：**

- 4.1 概念设计直接用这张图；
- 4.1 正文里把“弱实体 Parameters”“ISA”“聚合”改成：用户角色合并为 `role` 字段，参数拆成提取结果与正式参数两张表；
- 4.2 关系模式、4.3 表结构按 `01_schema.sql` 写。

**如果老师明确要求 Chen 记号：**

- 旧图保留在 4.1 作为概念图，但至少改三处：`Audit_log` 的连线从 `Extraction_task` 改到 `Extraction_param`、`Manufacurer_id` 拼写、去掉 `Extraction_task` 上的审核状态；
- 这张 Crow's Foot 图放 4.2 作为“关系模式图”，说明它是 4.1 概念图到物理表的落地；
- 两张图配合，比硬把 11 张表塞进 Chen 图更清楚。

## 重新生成

```bash
cd db/er_diagram
python gen_er.py
```

改字段：编辑 `gen_er.py` 里的 `TABLES`；改关系：编辑 `EDGES`。

## 注意

图里只画了主要外键关系；`parameter_def.category_id` 这类二级外键通过字段前的 `FK` 标记表达，没有单独拉线，避免交叉过多。完整约束以 `01_schema.sql` 为准。
