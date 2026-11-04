#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 ER 图：er_v2.drawio（可在 diagrams.net 编辑）+ er_v2.png（预览）。

表结构以 db/01_schema.sql 为准。
"""

from __future__ import annotations

import html
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent
S = 2  # PNG 放大倍数

HEADER = 30
ROW = 20
PAD = 8

# -----------------------------------------------------------------------------
# 表定义：(marker, name, type, nullable, unique)
# -----------------------------------------------------------------------------
TABLES = [
    {
        "id": "users", "title": "users（用户）", "x": 40, "y": 440, "w": 280,
        "rows": [
            ("PK", "user_id", "INTEGER", False, False),
            ("", "username", "TEXT", False, True),
            ("", "password_hash", "TEXT", False, False),
            ("", "role", "TEXT", False, False),
            ("", "is_active", "INTEGER", False, False),
            ("", "last_login_time", "TEXT", True, False),
            ("", "created_time", "TEXT", False, False),
        ],
    },
    {
        "id": "category", "title": "category（类别）", "x": 865, "y": 20, "w": 230,
        "rows": [
            ("PK", "category_id", "INTEGER", False, False),
            ("", "name", "TEXT", False, True),
            ("", "description", "TEXT", True, False),
        ],
    },
    {
        "id": "manufacturer", "title": "manufacturer（厂商）", "x": 1150, "y": 200, "w": 230,
        "rows": [
            ("PK", "manufacturer_id", "INTEGER", False, False),
            ("", "name", "TEXT", False, True),
            ("", "short_name", "TEXT", True, False),
            ("", "website", "TEXT", True, False),
        ],
    },
    {
        "id": "component", "title": "component（元器件）", "x": 850, "y": 200, "w": 260,
        "rows": [
            ("PK", "component_id", "INTEGER", False, False),
            ("FK", "category_id", "INTEGER", False, False),
            ("FK", "manufacturer_id", "INTEGER", False, False),
            ("", "model", "TEXT", False, False),
            ("", "package", "TEXT", True, False),
            ("", "description", "TEXT", True, False),
            ("", "created_time", "TEXT", False, False),
            ("", "updated_time", "TEXT", False, False),
        ],
    },
    {
        "id": "parameter_def", "title": "parameter_def（参数定义）", "x": 1150, "y": 720, "w": 300,
        "rows": [
            ("PK", "parameter_id", "INTEGER", False, False),
            ("", "canonical_name", "TEXT", False, True),
            ("", "display_name", "TEXT", False, False),
            ("", "unit", "TEXT", True, False),
            ("", "data_type", "TEXT", False, False),
            ("FK", "category_id", "INTEGER", True, False),
        ],
    },
    {
        "id": "parameter_alias", "title": "parameter_alias（参数别名）", "x": 1500, "y": 750, "w": 260,
        "rows": [
            ("PK", "alias_id", "INTEGER", False, False),
            ("FK", "parameter_id", "INTEGER", False, False),
            ("", "alias", "TEXT", False, True),
        ],
    },
    {
        "id": "extraction_task", "title": "extraction_task（提取任务）", "x": 380, "y": 440, "w": 300,
        "rows": [
            ("PK", "task_id", "INTEGER", False, False),
            ("FK", "user_id", "INTEGER", False, False),
            ("FK", "component_id", "INTEGER", True, False),
            ("", "source_type", "TEXT", False, False),
            ("", "source_location", "TEXT", True, False),
            ("", "status", "TEXT", False, False),
            ("", "retry_count", "INTEGER", False, False),
            ("", "created_time", "TEXT", False, False),
            ("", "finished_time", "TEXT", True, False),
        ],
    },
    {
        "id": "extraction_param", "title": "extraction_param（提取结果）", "x": 740, "y": 440, "w": 300,
        "rows": [
            ("PK", "extraction_param_id", "INTEGER", False, False),
            ("FK", "task_id", "INTEGER", False, False),
            ("FK", "parameter_id", "INTEGER", True, False),
            ("", "raw_name", "TEXT", False, False),
            ("", "raw_value", "TEXT", False, False),
            ("", "value_num", "REAL", True, False),
            ("", "unit", "TEXT", True, False),
            ("", "confidence", "REAL", True, False),
            ("", "review_status", "TEXT", False, False),
            ("", "review_comment", "TEXT", True, False),
            ("", "source_page", "INTEGER", True, False),
        ],
    },
    {
        "id": "component_parameter", "title": "component_parameter（正式参数）", "x": 1150, "y": 440, "w": 300,
        "rows": [
            ("PK/FK", "component_id", "INTEGER", False, False),
            ("PK/FK", "parameter_id", "INTEGER", False, False),
            ("", "value_num", "REAL", True, False),
            ("", "unit", "TEXT", True, False),
            ("", "value_text", "TEXT", True, False),
            ("FK", "source_extraction_param_id", "INTEGER", True, False),
            ("", "created_time", "TEXT", False, False),
            ("", "updated_time", "TEXT", False, False),
        ],
    },
    {
        "id": "audit_log", "title": "audit_log（审核日志）", "x": 380, "y": 740, "w": 300,
        "rows": [
            ("PK", "audit_log_id", "INTEGER", False, False),
            ("FK", "extraction_param_id", "INTEGER", False, False),
            ("FK", "auditor_id", "INTEGER", False, False),
            ("", "action", "TEXT", False, False),
            ("", "comment", "TEXT", True, False),
            ("", "detail_json", "TEXT", True, False),
            ("", "audit_time", "TEXT", False, False),
        ],
    },
    {
        "id": "operation_log", "title": "operation_log（操作日志）", "x": 40, "y": 740, "w": 280,
        "rows": [
            ("PK", "log_id", "INTEGER", False, False),
            ("FK", "user_id", "INTEGER", True, False),
            ("", "action", "TEXT", False, False),
            ("", "target_type", "TEXT", True, False),
            ("", "target_id", "INTEGER", True, False),
            ("", "detail", "TEXT", True, False),
            ("", "ip_address", "TEXT", True, False),
            ("", "created_time", "TEXT", False, False),
        ],
    },
]

# -----------------------------------------------------------------------------
# 关系：(id, source, target, exitX, exitY, entryX, entryY, label, startArrow, endArrow, waypoints, style)
# -----------------------------------------------------------------------------
EDGES = [
    ("e_user_task", "users", "extraction_task", 1, 0.5, 0, 0.5, "1 : N", "ERone", "ERmany", [], "ortho"),
    ("e_user_audit", "users", "audit_log", 0.8, 1, 0.5, 0, "1 : N", "ERone", "ERmany",
     [(264, 680), (530, 680)], "ortho"),
    ("e_user_oplog", "users", "operation_log", 0.4, 1, 0.4, 0, "1 : N", "ERone", "ERmany", [], "ortho"),
    ("e_task_param", "extraction_task", "extraction_param", 1, 0.5, 0, 0.5, "1 : N", "ERone", "ERmany", [], "ortho"),
    ("e_cp_param", "component_parameter", "extraction_param", 0, 0.5, 1, 0.5, "N : 1", "ERmany", "ERone", [], "ortho"),
    ("e_cp_component", "component_parameter", "component", 0, 0, 1, 1, None, "ERmany", "ERone", [], "straight"),
    ("e_cp_def", "component_parameter", "parameter_def", 0.5, 1, 0.5, 0, "N : 1", "ERmany", "ERone", [], "ortho"),
    ("e_param_def", "extraction_param", "parameter_def", 1, 1, 0, 0, "N : 1", "ERmany", "ERone", [], "straight"),
    ("e_def_alias", "parameter_def", "parameter_alias", 1, 0.5, 0, 0.5, None, "ERone", "ERmany", [], "ortho"),
    ("e_component_cat", "component", "category", 0.5, 0, 0.5, 1, "N : 1", "ERmany", "ERone", [], "ortho"),
    ("e_component_mfr", "component", "manufacturer", 1, 0.5, 0, 0.5, None, "ERmany", "ERone", [], "straight"),
    ("e_task_component", "extraction_task", "component", 0.5, 0, 0.5, 1, None, "ERmany", "ERone",
     [(530, 420), (980, 420)], "ortho"),
    ("e_param_audit", "extraction_param", "audit_log", 0, 1, 1, 0, None, "ERone", "ERmany",
     [(710, 698), (710, 740)], "ortho"),
]

TITLE = "电子元器件参数自动提取查询系统 · 数据库 ER 图（Crow's Foot）"
NOTE = ("注：User 的 ISA 子类（Admin / Auditor / Regular_user）合并为 users.role；"
        "原 Parameters 拆分为 extraction_param（待审）与 component_parameter（正式）；"
        "审核对象是 extraction_param（参数级），任务进度由视图统计。")

COLORS = {
    "header": "#d5e8d4",
    "border": "#82b366",
    "body": "#ffffff",
    "row": "#333333",
    "type": "#666666",
    "pk": "#b85450",
    "fk": "#6c8ebf",
    "null": "#d79b00",
    "uniq": "#2d7600",
    "edge": "#7f7f7f",
    "label": "#444444",
}


def table_height(t):
    return HEADER + len(t["rows"]) * ROW + PAD


def anchor(t, fx, fy):
    return (t["x"] + t["w"] * fx, t["y"] + table_height(t) * fy)


def route(edge):
    _, src, dst, sx, sy, tx, ty, _, _, _, points, style = edge
    s = anchor(BY_ID[src], sx, sy)
    t = anchor(BY_ID[dst], tx, ty)
    if points:
        return [s] + list(points) + [t]
    if style == "straight":
        return [s, t]
    s_h = sx in (0, 1)
    t_h = tx in (0, 1)
    if s_h and t_h:
        mx = (s[0] + t[0]) / 2
        return [s, (mx, s[1]), (mx, t[1]), t]
    if not s_h and not t_h:
        my = (s[1] + t[1]) / 2
        return [s, (s[0], my), (t[0], my), t]
    if s_h:
        return [s, (t[0], s[1]), t]
    return [s, (s[0], t[1]), t]


BY_ID = {t["id"]: t for t in TABLES}


def row_html(marker, name, typ, nullable, unique):
    if marker == "PK":
        m = '<font color="%s"><b>PK</b></font>' % COLORS["pk"]
    elif marker == "FK":
        m = '<font color="%s"><b>FK</b></font>' % COLORS["fk"]
    elif marker == "PK/FK":
        m = '<font color="%s"><b>PK/FK</b></font>' % COLORS["pk"]
    else:
        m = ""
    pad1 = "&nbsp;" * max(0, 7 - len(marker))
    pad2 = "&nbsp;" * max(0, 27 - len(name))
    out = f"{m}{pad1}{html.escape(name)}{pad2}{html.escape(typ)}"
    if nullable:
        out += '&nbsp;<font color="%s">?</font>' % COLORS["null"]
    if unique:
        out += '&nbsp;<font color="%s">U</font>' % COLORS["uniq"]
    return out


def esc(s):
    return html.escape(s, quote=True)


def make_drawio():
    cells = [
        '<mxCell id="0" />',
        '<mxCell id="1" parent="0" />',
        ('<mxCell id="title" value="%s" style="text;html=1;align=left;verticalAlign=middle;'
         'fontSize=16;fontStyle=1;fontFamily=Microsoft YaHei;" vertex="1" parent="1">'
         '<mxGeometry x="40" y="4" width="800" height="28" as="geometry" /></mxCell>') % esc(TITLE),
    ]

    for t in TABLES:
        h = table_height(t)
        cells.append(
            '<mxCell id="t_%s" value="%s" style="rounded=0;whiteSpace=wrap;html=1;'
            'container=1;collapsible=0;recursiveResize=0;'
            'fillColor=%s;strokeColor=%s;verticalAlign=top;fontStyle=1;fontSize=13;'
            'fontFamily=Microsoft YaHei;spacingTop=4;" vertex="1" parent="1">'
            '<mxGeometry x="%d" y="%d" width="%d" height="%d" as="geometry" /></mxCell>'
            % (t["id"], esc(t["title"]), COLORS["header"], COLORS["border"],
               t["x"], t["y"], t["w"], h)
        )
        cells.append(
            '<mxCell id="t_%s_body" style="rounded=0;html=1;fillColor=#ffffff;strokeColor=none;" '
            'vertex="1" parent="t_%s"><mxGeometry x="1" y="%d" width="%d" height="%d" as="geometry" /></mxCell>'
            % (t["id"], t["id"], HEADER, t["w"] - 2, h - HEADER - 1)
        )
        cells.append(
            '<mxCell id="t_%s_sep" style="line;strokeWidth=1;strokeColor=%s;html=1;" '
            'vertex="1" parent="t_%s"><mxGeometry x="0" y="%d" width="%d" height="1" as="geometry" /></mxCell>'
            % (t["id"], COLORS["border"], t["id"], HEADER, t["w"])
        )
        for i, (marker, name, typ, nullable, unique) in enumerate(t["rows"]):
            cells.append(
                '<mxCell id="t_%s_r%d" value="%s" style="text;html=1;align=left;verticalAlign=middle;'
                'spacingLeft=6;fontSize=10;fontFamily=Consolas;strokeColor=none;fillColor=none;" '
                'vertex="1" parent="t_%s"><mxGeometry x="0" y="%d" width="%d" height="%d" as="geometry" /></mxCell>'
                % (t["id"], i, esc(row_html(marker, name, typ, nullable, unique)), t["id"],
                   HEADER + i * ROW, t["w"], ROW)
            )

    for edge in EDGES:
        eid, src, dst, sx, sy, tx, ty, label, start, end, points, style = edge
        value = (' value="%s"' % esc(label)) if label else ""
        edge_style = "none" if style == "straight" else "orthogonalEdgeStyle"
        st = (
            f"edgeStyle={edge_style};rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
            f"strokeColor={COLORS['edge']};strokeWidth=1;startArrow={start};startFill=0;"
            f"endArrow={end};endFill=0;fontSize=9;fontFamily=Consolas;"
            f"labelBackgroundColor=#ffffff;exitX={sx};exitY={sy};entryX={tx};entryY={ty};"
        )
        pts = ""
        if points:
            pts = "<Array as=\"points\">" + "".join(
                '<mxPoint x="%d" y="%d" />' % (p[0], p[1]) for p in points
            ) + "</Array>"
        cells.append(
            f'<mxCell id="{eid}"{value} style="{st}" edge="1" parent="1" source="t_{src}" target="t_{dst}">'
            f'<mxGeometry relative="1" as="geometry">{pts}</mxGeometry></mxCell>'
        )

    legend_value = (
        "<b>图例</b><br>"
        '<font color="#b85450"><b>PK</b></font> 主键　'
        '<font color="#6c8ebf"><b>FK</b></font> 外键<br>'
        "<b>PK/FK</b> 复合主键兼外键<br>"
        '<font color="#2d7600"><b>U</b></font> 唯一　'
        '<font color="#d79b00"><b>?</b></font> 可空<br>'
        "单线 = 1　鸦爪 = N<br>"
        "1 : N　关系基数"
    )
    cells.append(
        '<mxCell id="legend" value="%s" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#fff2cc;'
        'strokeColor=#d6b656;dashed=1;align=left;verticalAlign=top;spacingLeft=8;spacingTop=6;'
        'fontSize=10;fontFamily=Microsoft YaHei;" vertex="1" parent="1">'
        '<mxGeometry x="1500" y="400" width="260" height="160" as="geometry" /></mxCell>' % esc(legend_value)
    )
    cells.append(
        '<mxCell id="note" value="%s" style="text;html=1;align=left;verticalAlign=top;'
        'fontSize=10;fontColor=#666666;fontFamily=Microsoft YaHei;whiteSpace=wrap;" '
        'vertex="1" parent="1"><mxGeometry x="40" y="950" width="1600" height="26" as="geometry" /></mxCell>'
        % esc(NOTE)
    )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mxfile host="app.diagrams.net" agent="gen_er.py" version="24.0.0">\n'
        '  <diagram id="er-v2" name="ER v2">\n'
        '    <mxGraphModel dx="1600" dy="900" grid="1" gridSize="10" guides="1" tooltips="1" '
        'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1800" pageHeight="980" '
        'math="0" shadow="0">\n'
        '      <root>\n        '
        + "\n        ".join(cells)
        + "\n      </root>\n    </mxGraphModel>\n  </diagram>\n</mxfile>\n"
    )


def draw_arrow(draw, p, prev, kind):
    ang = math.atan2(p[1] - prev[1], p[0] - prev[0])
    color = COLORS["edge"]
    if kind == "ERmany":
        for d in (-0.45, 0, 0.45):
            x = p[0] - 13 * math.cos(ang + d)
            y = p[1] - 13 * math.sin(ang + d)
            draw.line([p, (x, y)], fill=color, width=2)
    else:
        cx = p[0] - 7 * math.cos(ang)
        cy = p[1] - 7 * math.sin(ang)
        dx = 7 * math.sin(ang)
        dy = -7 * math.cos(ang)
        draw.line([(cx - dx, cy - dy), (cx + dx, cy + dy)], fill=color, width=2)


def polyline_midpoint(points):
    lengths = []
    total = 0.0
    for a, b in zip(points, points[1:]):
        d = math.dist(a, b)
        lengths.append(d)
        total += d
    half = total / 2
    acc = 0.0
    for (a, b), d in zip(zip(points, points[1:]), lengths):
        if acc + d >= half:
            r = (half - acc) / d if d else 0
            return (a[0] + (b[0] - a[0]) * r, a[1] + (b[1] - a[1]) * r)
        acc += d
    return points[-1]


def make_png():
    width, height = 1800, 980
    img = Image.new("RGB", (width * S, height * S), "white")
    draw = ImageDraw.Draw(img)

    f_title = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 16 * S)
    f_head = ImageFont.truetype(r"C:\Windows\Fonts\msyhbd.ttc", 12 * S)
    f_row = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 10 * S)
    f_edge = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 9 * S)
    f_note = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 10 * S)
    f_legend = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 10 * S)

    def sc(p):
        return (p[0] * S, p[1] * S)

    # 连线
    routes = {}
    for edge in EDGES:
        pts = [sc(p) for p in route(edge)]
        routes[edge[0]] = pts
        draw.line(pts, fill=COLORS["edge"], width=2 * S // 2)

    # 表
    cw = draw.textlength("M", font=f_row)
    for t in TABLES:
        h = table_height(t)
        x, y, w = t["x"], t["y"], t["w"]
        draw.rectangle([x * S, y * S, (x + w) * S, (y + h) * S],
                       fill=COLORS["body"], outline=COLORS["border"], width=2)
        draw.rectangle([x * S, y * S, (x + w) * S, (y + HEADER) * S],
                       fill=COLORS["header"], outline=COLORS["border"], width=2)
        draw.line([x * S, (y + HEADER) * S, (x + w) * S, (y + HEADER) * S],
                  fill=COLORS["border"], width=2)
        draw.text(((x + w / 2) * S, (y + HEADER / 2) * S), t["title"],
                  font=f_head, fill="#222222", anchor="mm")

        for i, (marker, name, typ, nullable, unique) in enumerate(t["rows"]):
            cy = (y + HEADER + i * ROW + ROW / 2) * S
            mx = (x + 8) * S
            nx = mx + cw * 7
            tx = nx + cw * 27
            mcolor = COLORS["pk"] if "PK" in marker else (COLORS["fk"] if marker == "FK" else COLORS["row"])
            if marker:
                draw.text((mx, cy), marker, font=f_row, fill=mcolor, anchor="lm")
            draw.text((nx, cy), name, font=f_row, fill=COLORS["row"], anchor="lm")
            draw.text((tx, cy), typ, font=f_row, fill=COLORS["type"], anchor="lm")
            cur = tx + cw * (len(typ) + 1)
            if nullable:
                draw.text((cur, cy), "?", font=f_row, fill=COLORS["null"], anchor="lm")
                cur += cw * 2
            if unique:
                draw.text((cur, cy), "U", font=f_row, fill=COLORS["uniq"], anchor="lm")

    # 端点标记
    for edge in EDGES:
        eid, _, _, _, _, _, _, _, start, end, _, _ = edge
        pts = routes[eid]
        draw_arrow(draw, pts[0], pts[1], start)
        draw_arrow(draw, pts[-1], pts[-2], end)

    # 连线标签
    for edge in EDGES:
        eid, _, _, _, _, _, _, label, _, _, _, _ = edge
        if not label:
            continue
        mx, my = polyline_midpoint(routes[eid])
        bbox = draw.textbbox((0, 0), label, font=f_edge)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.rectangle([mx - tw / 2 - 4, my - th / 2 - 3, mx + tw / 2 + 4, my + th / 2 + 3],
                       fill="white")
        draw.text((mx, my), label, font=f_edge, fill=COLORS["label"], anchor="mm")

    # 标题
    draw.text((40 * S, 18 * S), TITLE, font=f_title, fill="#222222", anchor="lm")

    # 图例
    lx, ly, lw, lh = 1500, 400, 260, 160
    draw.rectangle([lx * S, ly * S, (lx + lw) * S, (ly + lh) * S],
                   fill="#fff2cc", outline="#d6b656", width=2)
    lines = [
        ("图例", f_legend, "#333333"),
        ("PK 主键   FK 外键", f_legend, "#333333"),
        ("PK/FK 复合主键兼外键", f_legend, "#333333"),
        ("U 唯一    ? 可空", f_legend, "#333333"),
        ("单线 = 1   鸦爪 = N", f_legend, "#333333"),
        ("1 : N  关系基数", f_legend, "#333333"),
    ]
    for i, (line, font, color) in enumerate(lines):
        draw.text(((lx + 10) * S, (ly + 12 + i * 24) * S), line, font=font, fill=color, anchor="lm")

    # 注释
    draw.text((40 * S, 950 * S), NOTE, font=f_note, fill="#666666", anchor="lm")

    img.save(BASE / "er_v2.png", "PNG")
    return img.size


def main():
    (BASE / "er_v2.drawio").write_text(make_drawio(), encoding="utf-8")
    size = make_png()
    print("wrote", BASE / "er_v2.drawio")
    print("wrote", BASE / "er_v2.png", size)


if __name__ == "__main__":
    main()
