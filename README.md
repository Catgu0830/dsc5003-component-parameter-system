# 仓库结构

```text
5003_Team_Project/
├── README.md
├── .gitignore
├── backend/                             # Flask + SQLite（11 表、参数级审核）
│   ├── backend/
│   │   ├── schema.sql                   # 与 Database/db/01_schema.sql 一致
│   │   ├── seed_catalog.sql             # 类别/参数词典
│   │   ├── auth.py                      # 无状态 Token、登录/注册
│   │   ├── tasks.py                     # 任务、上传、提取结果
│   │   ├── audit.py                     # 参数级审核
│   │   ├── components.py                # 查询/筛选/对比/管理
│   │   ├── exports.py                   # CSV/XLSX/JSON 导出
│   │   └── ...
│   ├── tests/                           # 11 表核心流程测试
│   ├── examples/                        # 示例 PDF/CSV/XLSX
│   ├── run.py
│   └── README.md
├── frontend/                            # 原生 HTML/CSS/JS
│   ├── login.html
│   ├── css/
│   ├── js/
│   └── pages/                           # 7 个业务页面
├── 最强RAG/                             # PDF/URL 参数提取的 RAG 方法
│   ├── chips_extractor/llm/             # 混合检索、RRF、rerank、Prompt v7
│   ├── chips_extractor/settings.py
│   ├── config.yaml
│   └── requirements.txt
├── Database/
│   ├── db/                              # SQLite 数据库脚本与验收
│   │   ├── 00_reset.sql
│   │   ├── 01_schema.sql                # 表、约束、索引、视图、触发器
│   │   ├── 02_seed.sql                  # 演示数据
│   │   ├── 03_queries.sql               # 示例查询与事务
│   │   ├── 04_fts5.sql                  # 可选 FTS5 全文索引
│   │   ├── init_db.py                   # 一键建库
│   │   ├── verify_core.py               # 核心功能验收
│   │   ├── README.md                    # 数据库说明
│   │   └── er_diagram/                  # ER 图生成脚本与说明
│   ├── 数据库小组项目_v2.drawio          # 最终 ER 图（可编辑）
│   ├── 数据库小组项目_v2.drawio.png      # 最终 ER 图（导出）
│   ├── 数据库小组项目.drawio             # 初版 ER 图（历史）
│   └── 数据库小组项目.drawio.png
└── 电子元器件参数自动提取系统需求规格说明书/
    ├── v1.0.docx
    └── v1.1.docx
```
