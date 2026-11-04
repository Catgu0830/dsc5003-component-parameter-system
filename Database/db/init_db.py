#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""初始化演示数据库：建表 + 种子数据 + 完整性检查。

用法：
    python init_db.py                  # 生成 demo.db
    python init_db.py --with-fts       # 额外建 FTS5 全文索引
    python init_db.py --run-queries    # 生成后顺带执行 03_queries.sql 做语法校验
    python init_db.py --db D:/tmp/x.db # 指定输出文件
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SCHEMA = BASE / "01_schema.sql"
SEED = BASE / "02_seed.sql"
QUERIES = BASE / "03_queries.sql"
FTS = BASE / "04_fts5.sql"

TABLES = [
    "users",
    "category",
    "manufacturer",
    "component",
    "parameter_def",
    "parameter_alias",
    "extraction_task",
    "extraction_param",
    "component_parameter",
    "audit_log",
    "operation_log",
]

# (说明, 期望值为 0 的检查 SQL)
INVARIANTS = [
    (
        "已通过审核的参数没有进入正式参数表",
        """SELECT COUNT(*) FROM extraction_param ep
             JOIN extraction_task t ON t.task_id = ep.task_id
            WHERE ep.review_status = 'approved'
              AND ep.parameter_id IS NOT NULL
              AND t.component_id IS NOT NULL
              AND NOT EXISTS (
                    SELECT 1 FROM component_parameter cp
                     WHERE cp.component_id = t.component_id
                       AND cp.parameter_id = ep.parameter_id)""",
    ),
    (
        "未通过审核的参数却已发布",
        """SELECT COUNT(*) FROM component_parameter cp
             JOIN extraction_param ep
               ON ep.extraction_param_id = cp.source_extraction_param_id
            WHERE ep.review_status <> 'approved'""",
    ),
    (
        "正式参数的来源参数与器件不一致",
        """SELECT COUNT(*) FROM component_parameter cp
             JOIN extraction_param ep
               ON ep.extraction_param_id = cp.source_extraction_param_id
             JOIN extraction_task t ON t.task_id = ep.task_id
            WHERE t.component_id IS NOT NULL
              AND t.component_id <> cp.component_id""",
    ),
    (
        "审核人的角色不是 auditor",
        """SELECT COUNT(*) FROM audit_log a
             JOIN users u ON u.user_id = a.auditor_id
            WHERE u.role <> 'auditor'""",
    ),
    (
        "审核日志与参数审核状态不一致",
        """SELECT COUNT(*) FROM audit_log a
             JOIN extraction_param ep
               ON ep.extraction_param_id = a.extraction_param_id
            WHERE (a.action = 'approve' AND ep.review_status <> 'approved')
               OR (a.action = 'reject'  AND ep.review_status <> 'rejected')""",
    ),
    (
        "同一厂商下型号重复",
        """SELECT COUNT(*) FROM (
               SELECT 1 FROM component
                GROUP BY manufacturer_id, model
               HAVING COUNT(*) > 1)""",
    ),
    (
        "存储单位与参数字典不一致",
        """SELECT COUNT(*) FROM component_parameter cp
             JOIN parameter_def pd ON pd.parameter_id = cp.parameter_id
            WHERE pd.unit IS NOT NULL
              AND cp.unit IS NOT NULL
              AND cp.unit <> pd.unit""",
    ),
    (
        "参数值既无数值也无文本",
        """SELECT COUNT(*) FROM component_parameter
            WHERE value_num IS NULL AND value_text IS NULL""",
    ),
]


def run_script(con: sqlite3.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    con.executescript(sql)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="初始化电子元器件数据库 demo.db")
    parser.add_argument("--db", default=str(BASE / "demo.db"), help="输出数据库文件")
    parser.add_argument("--with-fts", action="store_true", help="额外创建 FTS5 全文索引")
    parser.add_argument("--run-queries", action="store_true", help="执行 03_queries.sql 校验语法")
    parser.add_argument("--no-overwrite", action="store_true", help="数据库已存在时直接退出")
    args = parser.parse_args()

    db_path = Path(args.db)
    if db_path.exists():
        if args.no_overwrite:
            print(f"[skip] {db_path} 已存在")
            return 1
        db_path.unlink()
        print(f"[reset] 已删除旧的 {db_path}")

    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")

    scripts = [SCHEMA, SEED]
    if args.with_fts:
        scripts.append(FTS)

    for path in scripts:
        run_script(con, path)
        print(f"[ok] {path.name}")

    fk_errors = con.execute("PRAGMA foreign_key_check").fetchall()
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]

    print("\n表行数")
    print("-" * 40)
    for table in TABLES:
        n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table:<22}{n:>6}")

    print("\n完整性检查")
    print("-" * 40)
    print(f"foreign_key_check : {'PASS' if not fk_errors else fk_errors}")
    print(f"integrity_check   : {integrity}")

    failed = 0
    for label, sql in INVARIANTS:
        n = con.execute(sql).fetchone()[0]
        ok = n == 0
        failed += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL':<5}{label}" + ("" if ok else f"（{n} 条）"))

    if args.run_queries:
        run_script(con, QUERIES)
        print("\n[ok] 03_queries.sql 语法校验通过")

    con.close()

    if failed:
        print(f"\n{failed} 项检查未通过")
        return 1

    print(f"\n完成：{db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
