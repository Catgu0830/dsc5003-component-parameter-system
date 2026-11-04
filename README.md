# 仓库结构

```text
5003_Team_Project/
├── README.md
├── .gitignore
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
