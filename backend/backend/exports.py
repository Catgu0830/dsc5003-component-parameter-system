import csv
import io
import json

from flask import Blueprint, g, request, send_file
from openpyxl import Workbook

from .auth import login_required
from .common import APIError
from .components import component_access, comparison, query_components, serialize_component
from .db import get_db, log

bp = Blueprint("exports", __name__, url_prefix="/api/export")


def safe_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def export_data(data, compare=False):
    fmt = request.args.get("format", "csv").lower()
    if fmt not in ("json", "csv", "xlsx", "excel"):
        raise APIError("format must be csv, xlsx or json")
    if fmt == "json":
        buf = io.BytesIO(json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8"))
        mime, extension = "application/json", "json"
    else:
        components = data["components"] if compare else data["items"]
        names = {}
        for component in components:
            for parameter in component["parameters"]:
                names[parameter["parameter_id"]] = parameter
        names = [names[key] for key in sorted(names)]
        rows = [
            ["component_id", "model", "manufacturer", "category", "package"]
            + [label for parameter in names for label in (parameter["name"], parameter["name"] + "_unit")]
        ]
        for component in components:
            mapping = {p["parameter_id"]: p for p in component["parameters"]}
            row = [
                component["component_id"],
                component["model"],
                component["manufacturer"],
                component["category"],
                component.get("package"),
            ]
            for parameter in names:
                found = mapping.get(parameter["parameter_id"])
                row.extend([found["value"], found["unit"]] if found else [None, None])
            rows.append([safe_cell(value) for value in row])
        if fmt == "csv":
            stream = io.StringIO(newline="")
            writer = csv.writer(stream)
            writer.writerows(rows)
            buf = io.BytesIO(stream.getvalue().encode("utf-8-sig"))
            mime, extension = "text/csv", "csv"
        else:
            book = Workbook()
            sheet = book.active
            sheet.title = "Comparison" if compare else "Components"
            for row in rows:
                sheet.append(row)
            sheet.freeze_panes = "F2"
            sheet.auto_filter.ref = sheet.dimensions
            buf = io.BytesIO()
            book.save(buf)
            mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            extension = "xlsx"
    db = get_db()
    with db:
        log(db, g.user["user_id"], "export", "export", None, {"format": extension, "compare": compare})
    buf.seek(0)
    return send_file(
        buf,
        mimetype=mime,
        as_attachment=True,
        download_name=("comparison" if compare else "components") + "." + extension,
    )


@bp.get("/components")
@login_required()
def components():
    return export_data(query_components(export=True))


@bp.get("/components/<int:component_id>")
@login_required()
def component_detail(component_id):
    """FR-46: export one component's parameter detail as a table/JSON."""
    component = serialize_component(component_access(component_id))
    return export_data({"items": [component]}, False)


@bp.get("/compare")
@login_required()
def compare():
    return export_data(comparison(), True)
