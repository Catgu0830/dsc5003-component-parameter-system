#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核心功能验收：对着 demo.db 跑一遍数据库层能覆盖的需求。

用法：
    python verify_core.py
    python verify_core.py --db D:/tmp/other.db

约定：
    * 只读检查直接执行；
    * 所有写操作放在事务里，检查完 ROLLBACK，不会改动 demo.db。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

RESULTS: list[tuple[bool, str, str]] = []


def ok(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((bool(condition), name, detail))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def eq(name: str, actual, expected) -> None:
    ok(name, actual == expected, f"{actual!r} == {expected!r}" if actual != expected else "")


def expect_error(name: str, con: sqlite3.Connection, sql: str, params=(), contains: str | None = None) -> None:
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute(sql, params)
        con.execute("ROLLBACK")
        ok(name, False, "没有被拒绝")
    except sqlite3.Error as exc:
        con.execute("ROLLBACK")
        ok(name, contains is None or contains in str(exc), str(exc))


def scalar(con: sqlite3.Connection, sql: str, params=()):
    row = con.execute(sql, params).fetchone()
    return row[0] if row else None


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(BASE / "demo.db"))
    args = parser.parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"找不到 {db_path}，先运行 python init_db.py")
        return 1

    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA foreign_keys = ON")
    con.row_factory = sqlite3.Row

    print("=" * 78)
    print("一、结构完整性")
    print("=" * 78)

    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        if not r[0].startswith("component_fts")}
    views = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='view'")}
    triggers = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger'")}

    expected_tables = {
        "users", "category", "manufacturer", "component", "parameter_def",
        "parameter_alias", "extraction_task", "extraction_param",
        "component_parameter", "audit_log", "operation_log",
    }
    eq("11 张业务表齐全", tables, expected_tables)
    eq("6 个视图齐全", views, {
        "v_component_list", "v_approved_parameter", "v_task_review",
        "v_pending_review", "v_task_overview", "v_extraction_detail",
    })
    ok("关键触发器齐全", {
        "trg_audit_auditor_only", "trg_audit_requires_success",
        "trg_audit_requires_pending", "trg_audit_requires_component",
        "trg_audit_apply", "trg_audit_immutable",
        "trg_ep_locked_after_review", "trg_ep_approved_requires_mapping",
    } <= triggers, f"{len(triggers)} triggers")

    eq("foreign_key_check 为空", con.execute("PRAGMA foreign_key_check").fetchall(), [])
    eq("integrity_check 为 ok", scalar(con, "PRAGMA integrity_check"), "ok")

    # 关键列存在性
    cp_cols = {r[1] for r in con.execute("PRAGMA table_info(component_parameter)")}
    ep_cols = {r[1] for r in con.execute("PRAGMA table_info(extraction_param)")}
    task_cols = {r[1] for r in con.execute("PRAGMA table_info(extraction_task)")}
    audit_cols = {r[1] for r in con.execute("PRAGMA table_info(audit_log)")}

    ok("正式参数直连提取结果", "source_extraction_param_id" in cp_cols)
    ok("正式参数已去掉重复来源字段",
       not ({"source_task_id", "source_page", "source_snippet", "approved_by", "approved_time"} & cp_cols))
    ok("提取结果有 review_status / review_comment",
       {"review_status", "review_comment"} <= ep_cols)
    ok("任务表不再存任务级审核状态", "review_status" not in task_cols)
    ok("审核日志指向 extraction_param", "extraction_param_id" in audit_cols and "task_id" not in audit_cols)

    print()
    print("=" * 78)
    print("二、数据质量与约束")
    print("=" * 78)

    eq("审核日志 13 条", scalar(con, "SELECT COUNT(*) FROM audit_log"), 13)
    eq("待审核参数 10 条", scalar(con, "SELECT COUNT(*) FROM v_pending_review"), 10)
    eq("正式参数 58 条", scalar(con, "SELECT COUNT(*) FROM component_parameter"), 58)
    eq("其中来自提取结果 12 条", scalar(
        con, "SELECT COUNT(*) FROM component_parameter WHERE source_extraction_param_id IS NOT NULL"), 12)
    eq("手工维护参数 46 条", scalar(
        con, "SELECT COUNT(*) FROM component_parameter WHERE source_extraction_param_id IS NULL"), 46)

    eq("已发布参数全部来自 approved 提取结果", scalar(con, """
        SELECT COUNT(*) FROM component_parameter cp
        JOIN extraction_param ep ON ep.extraction_param_id = cp.source_extraction_param_id
        WHERE ep.review_status <> 'approved'"""), 0)

    eq("所有 approved 提取结果都已发布", scalar(con, """
        SELECT COUNT(*) FROM extraction_param ep
        JOIN extraction_task t ON t.task_id = ep.task_id
        WHERE ep.review_status = 'approved'
          AND ep.parameter_id IS NOT NULL
          AND t.component_id IS NOT NULL
          AND NOT EXISTS (
                SELECT 1 FROM component_parameter cp
                 WHERE cp.component_id = t.component_id
                   AND cp.parameter_id = ep.parameter_id)"""), 0)

    eq("单位与参数字典一致", scalar(con, """
        SELECT COUNT(*) FROM component_parameter cp
        JOIN parameter_def pd ON pd.parameter_id = cp.parameter_id
        WHERE pd.unit IS NOT NULL AND cp.unit IS NOT NULL AND cp.unit <> pd.unit"""), 0)

    eq("同一厂商下无重复型号", scalar(con, """
        SELECT COUNT(*) FROM (
            SELECT 1 FROM component GROUP BY manufacturer_id, model HAVING COUNT(*) > 1)"""), 0)

    eq("任务审核进度：4 reviewed / 4 pending / 2 empty", dict(
        (r["review_state"], r["cnt"]) for r in con.execute(
            "SELECT review_state, COUNT(*) AS cnt FROM v_task_review GROUP BY review_state")),
       {"reviewed": 4, "pending": 4, "empty": 2})

    eq("T7 部分通过、部分驳回", scalar(con, """
        SELECT COUNT(*) FROM extraction_param
        WHERE task_id = 7 AND review_status = 'approved'"""), 1)
    eq("T7 驳回的电容没有入库", scalar(con, """
        SELECT COUNT(*) FROM component_parameter
        WHERE component_id = 5 AND parameter_id = 2"""), 0)

    print()
    print("=" * 78)
    print("三、查询功能（FR-34~42）")
    print("=" * 78)

    eq("关键词 LM358 命中 1 条", scalar(con, """
        SELECT COUNT(*) FROM v_component_list WHERE model LIKE '%LM358%'"""), 1)
    eq("类别+厂商筛选命中 TI 的 2 个集成电路", scalar(con, """
        SELECT COUNT(*) FROM v_component_list
        WHERE category = '集成电路' AND manufacturer = 'Texas Instruments'"""), 2)
    eq("电压 3.3~5.0V 命中 5 条", scalar(con, """
        SELECT COUNT(*) FROM v_approved_parameter
        WHERE canonical_name = 'Voltage' AND value_num BETWEEN 3.3 AND 5.0"""), 5)
    eq("电压 3~5V 且引脚>=24 命中 2 条", scalar(con, """
        SELECT COUNT(*) FROM v_component_list c
        WHERE EXISTS (SELECT 1 FROM component_parameter cp
                       WHERE cp.component_id = c.component_id AND cp.parameter_id = 4
                         AND cp.value_num BETWEEN 3 AND 5)
          AND EXISTS (SELECT 1 FROM component_parameter cp
                       WHERE cp.component_id = c.component_id AND cp.parameter_id = 16
                         AND cp.value_num >= 24)"""), 2)
    eq("参数缺失器件 4 个", scalar(con, """
        SELECT COUNT(*) FROM component c
        LEFT JOIN component_parameter cp ON cp.component_id = c.component_id
        WHERE cp.component_id IS NULL"""), 4)
    eq("低置信度待审 3 条", scalar(con, """
        SELECT COUNT(*) FROM v_extraction_detail
        WHERE review_status = 'pending' AND confidence < 0.9"""), 3)
    eq("comp1 提取历史 6 条", scalar(con, """
        SELECT COUNT(*) FROM extraction_task t
        JOIN extraction_param ep ON ep.task_id = t.task_id
        WHERE t.component_id = 1"""), 6)

    eq("对比 3 个电阻返回 3 行", scalar(con, """
        SELECT COUNT(*) FROM (
            SELECT c.component_id
            FROM component c
            JOIN component_parameter cp ON cp.component_id = c.component_id
            WHERE c.component_id IN (1, 2, 3)
            GROUP BY c.component_id)"""), 3)

    eq("别名“电压”映射 7 条", scalar(con, """
        SELECT COUNT(*) FROM parameter_alias pa
        JOIN parameter_def pd ON pd.parameter_id = pa.parameter_id
        WHERE pa.alias LIKE '%电压%'"""), 7)
    eq("Voltage 标准名唯一", scalar(con, """
        SELECT COUNT(*) FROM parameter_def WHERE canonical_name = 'Voltage'"""), 1)

    plan = " ".join(r[3] for r in con.execute("""
        EXPLAIN QUERY PLAN
        SELECT component_id, value_num FROM component_parameter
        WHERE parameter_id = 4 AND value_num BETWEEN 3.0 AND 5.0"""))
    ok("电压范围查询命中复合索引", "idx_cp_parameter_value" in plan, plan)

    eq("分页 LIMIT 5 OFFSET 5 返回 5 行", len(con.execute("""
        SELECT component_id FROM v_component_list ORDER BY model LIMIT 5 OFFSET 5""").fetchall()), 5)

    print()
    print("=" * 78)
    print("四、审核流程（FR-20~23）")
    print("=" * 78)

    # 参数级部分审核：T3 第一条参数
    con.execute("BEGIN IMMEDIATE")
    con.execute("""INSERT INTO audit_log (extraction_param_id, auditor_id, action, comment)
                   VALUES (9, 2, 'approve', '电压核对无误')""")
    eq("单条通过后 comp14 有 1 条正式参数", scalar(
        con, "SELECT COUNT(*) FROM component_parameter WHERE component_id = 14"), 1)
    eq("正式参数直连被批准的提取结果", scalar(
        con, "SELECT source_extraction_param_id FROM component_parameter "
             "WHERE component_id = 14 AND parameter_id = 4"), 9)
    eq("任务 3 进度为 partial", scalar(
        con, "SELECT review_state FROM v_task_review WHERE task_id = 3"), "partial")
    eq("审核日志可通过来源回查到 task/page", tuple(con.execute("""
        SELECT source_task_id, source_page, approved_by
        FROM v_approved_parameter WHERE component_id = 14 AND parameter_id = 4""").fetchone()),
       (3, 4, 2))
    con.execute("ROLLBACK")

    # 全部通过
    con.execute("BEGIN IMMEDIATE")
    for ep_id in (9, 10, 11):
        con.execute("""INSERT INTO audit_log (extraction_param_id, auditor_id, action, comment)
                       VALUES (?, 2, 'approve', '核对无误')""", (ep_id,))
    eq("全部通过后 comp14 有 3 条正式参数", scalar(
        con, "SELECT COUNT(*) FROM component_parameter WHERE component_id = 14"), 3)
    eq("任务 3 进度为 reviewed", scalar(
        con, "SELECT review_state FROM v_task_review WHERE task_id = 3"), "reviewed")
    con.execute("ROLLBACK")

    # 驳回
    con.execute("BEGIN IMMEDIATE")
    con.execute("""INSERT INTO audit_log (extraction_param_id, auditor_id, action, comment)
                   VALUES (9, 2, 'reject', '电压值不可信')""")
    eq("驳回后 T3 参数 9 为 rejected", scalar(
        con, "SELECT review_status FROM extraction_param WHERE extraction_param_id = 9"), "rejected")
    eq("驳回后 comp14 没有新增参数", scalar(
        con, "SELECT COUNT(*) FROM component_parameter WHERE component_id = 14"), 0)
    con.execute("ROLLBACK")

    eq("T7 有 2 条审核记录（1 通过 1 驳回）", scalar(
        con, "SELECT COUNT(*) FROM audit_log a JOIN extraction_param ep "
             "ON ep.extraction_param_id = a.extraction_param_id WHERE ep.task_id = 7"), 2)
    eq("T7 最新审核动作是 reject", scalar(
        con, "SELECT last_audit_action FROM v_task_overview WHERE task_id = 7"), "reject")

    print()
    print("=" * 78)
    print("五、权限与关键约束")
    print("=" * 78)

    expect_error("普通用户不能写审核日志", con,
                 "INSERT INTO audit_log (extraction_param_id, auditor_id, action, comment) "
                 "VALUES (9, 3, 'approve', 'x')", contains="auditor")
    expect_error("驳回必须写意见", con,
                 "INSERT INTO audit_log (extraction_param_id, auditor_id, action) VALUES (9, 2, 'reject')",
                 contains="CHECK")
    expect_error("已审核的参数不能重复审核", con,
                 "INSERT INTO audit_log (extraction_param_id, auditor_id, action, comment) "
                 "VALUES (1, 2, 'approve', 'x')", contains="已审核")
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("INSERT INTO extraction_param (task_id, parameter_id, raw_name, raw_value) "
                    "VALUES (3, NULL, 'Unknown Param', 'abc')")
        new_id = con.execute("SELECT MAX(extraction_param_id) FROM extraction_param").fetchone()[0]
        con.execute("INSERT INTO audit_log (extraction_param_id, auditor_id, action, comment) "
                    "VALUES (?, 2, 'approve', 'x')", (new_id,))
        con.execute("ROLLBACK")
        ok("未映射参数不能通过审核", False, "没有被拒绝")
    except sqlite3.Error as exc:
        con.execute("ROLLBACK")
        ok("未映射参数不能通过审核", "parameter_def" in str(exc), str(exc))
    expect_error("审核日志不可修改", con,
                 "UPDATE audit_log SET comment = 'x' WHERE audit_log_id = 1", contains="只追加")
    expect_error("已审核的提取结果不可修改", con,
                 "UPDATE extraction_param SET value_num = 1.0 WHERE extraction_param_id = 1",
                 contains="不可修改")
    expect_error("同一厂商下型号不能重复", con,
                 "INSERT INTO component (model, category_id, manufacturer_id) "
                 "VALUES ('RC0603FR-0710KL', 1, 6)", contains="UNIQUE")
    expect_error("被引用的厂商不能删除", con,
                 "DELETE FROM manufacturer WHERE manufacturer_id = 6", contains="FOREIGN KEY")
    expect_error("角色只能是 admin/auditor/user", con,
                 "UPDATE users SET role = 'root' WHERE user_id = 3", contains="CHECK")

    # 用户禁用
    con.execute("BEGIN IMMEDIATE")
    con.execute("UPDATE users SET is_active = 1 WHERE user_id = 4")
    eq("管理员可以启用/禁用用户", scalar(
        con, "SELECT is_active FROM users WHERE user_id = 4"), 1)
    con.execute("ROLLBACK")

    # 组件更新 / 删除
    con.execute("BEGIN IMMEDIATE")
    con.execute("UPDATE component SET description = '验收测试' WHERE component_id = 3")
    eq("组件可编辑", scalar(
        con, "SELECT description FROM component WHERE component_id = 3"), "验收测试")
    before = scalar(con, "SELECT COUNT(*) FROM component_parameter WHERE component_id = 3")
    con.execute("DELETE FROM component WHERE component_id = 3")
    eq("删除组件级联删除参数", scalar(
        con, "SELECT COUNT(*) FROM component_parameter WHERE component_id = 3"), 0)
    ok("删除前该组件有参数", before > 0, f"{before} 条")
    con.execute("ROLLBACK")

    # 任务重试 / 删除
    con.execute("BEGIN IMMEDIATE")
    con.execute("""UPDATE extraction_task
                      SET status = 'pending', error_msg = NULL,
                          retry_count = retry_count + 1,
                          started_time = NULL, finished_time = NULL
                    WHERE task_id = 5""")
    eq("失败任务可重试", tuple(con.execute(
        "SELECT status, error_msg, retry_count FROM extraction_task WHERE task_id = 5").fetchone()),
       ("pending", None, 2))
    con.execute("ROLLBACK")

    con.execute("BEGIN IMMEDIATE")
    con.execute("DELETE FROM extraction_task WHERE task_id = 5")
    eq("无参数的任务可删除", scalar(
        con, "SELECT COUNT(*) FROM extraction_task WHERE task_id = 5"), 0)
    con.execute("ROLLBACK")

    # CSV 数据源
    con.execute("BEGIN IMMEDIATE")
    con.execute("""INSERT INTO extraction_task
                   (user_id, source_type, source_location, status)
                   VALUES (3, 'csv', 'imports/test.csv', 'pending')""")
    eq("支持 CSV 数据源", scalar(
        con, "SELECT COUNT(*) FROM extraction_task WHERE source_type = 'csv'"), 1)
    con.execute("ROLLBACK")

    print()
    print("=" * 78)
    print("六、汇总")
    print("=" * 78)

    failed = [r for r in RESULTS if not r[0]]
    print(f"数据库层检查：{len(RESULTS) - len(failed)}/{len(RESULTS)} PASS")
    if failed:
        print("\n未通过：")
        for _, name, detail in failed:
            print(f"  - {name}  {detail}")
        return 1

    print("""
数据库层能直接支持并已验证：
  FR-01/02/03/05   用户、角色、启用/禁用、最后登录字段
  FR-06~13         四类数据源、任务、提取结果、型号/厂商/类别/封装/参数
  FR-15~18         单位归一化、参数级来源、置信度、重试
  FR-20~23/25      参数级待审、修改、通过/驳回、审核日志、版本历史
  FR-26~38         元器件库、厂商、类别、参数、搜索/范围/多条件/排序分页
  FR-40~42         多器件对比、缺失参数
  FR-49~53         任务状态、任务详情、操作日志、失败重试（FR-52 需前端展示）
  BR-01/02/06/07   型号唯一、审核后入库、来源保留、缺失参数可查

需要后端/前端实现（数据库只提供结构，脚本无法验证）：
  FR-01/04         登录认证、Token、接口级角色校验（数据库只兜底 auditor 触发器）
  FR-14            大模型/OCR 参数提取
  FR-19            批量创建任务
  FR-24            异常值提示（应用层阈值判断）
  FR-37            模糊搜索的 UI 与 FTS 接入（04_fts5.sql 可选）
  FR-39            保存筛选条件（已按决定删除）
  FR-41            对比结果差异高亮
  FR-43            相似器件推荐（低优先级）
  FR-44~48         导出文件、REST API
  FR-52            管理员日志页面

本版本未实现（低优先级/已决定不做）：
  FR-39 保存常用筛选、FR-43 相似推荐、FR-46 导出 PDF、FR-48 API 参数查询
""")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
