"""Parameter-level review against extraction_param / audit_log."""
import json
import math
from pathlib import Path

from flask import Blueprint, g, request

from .auth import login_required
from .catalog import load_catalog
from .common import APIError, body, integer, ok, pagination, text
from .db import dump, get_db, log
from .normalization import numeric
from .tasks import serialize_task, task_access

bp = Blueprint("audit", __name__, url_prefix="/api/audit")


def _param_access(extraction_param_id):
    db = get_db()
    row = db.execute(
        "SELECT ep.*, t.user_id AS task_user_id, t.status AS task_status, "
        "t.component_id, t.source_type, t.source_location "
        "FROM extraction_param ep JOIN extraction_task t ON t.task_id=ep.task_id "
        "WHERE ep.extraction_param_id=?",
        (extraction_param_id,),
    ).fetchone()
    if row is None:
        raise APIError("Extraction parameter not found", 404)
    if g.user["role"] == "user" and row["task_user_id"] != g.user["user_id"]:
        raise APIError("Extraction parameter belongs to another user", 403)
    return row


def _category(db, name):
    if not name:
        raise APIError("Category is required before publishing")
    row = db.execute("SELECT * FROM category WHERE name=? COLLATE NOCASE", (name.strip(),)).fetchone()
    if row is None:
        raise APIError(f"Category {name!r} is not in the category dictionary")
    return row


def _manufacturer(db, name):
    if not name or not name.strip():
        raise APIError("Manufacturer is required before publishing")
    name = name.strip()
    row = db.execute("SELECT * FROM manufacturer WHERE name=? COLLATE NOCASE", (name,)).fetchone()
    if row is not None:
        return row
    mid = db.execute("INSERT INTO manufacturer(name) VALUES(?)", (name,)).lastrowid
    return db.execute("SELECT * FROM manufacturer WHERE manufacturer_id=?", (mid,)).fetchone()


def ensure_component(db, task):
    """Create/find the component referenced by the task before approving a parameter."""
    if task["component_id"] is not None:
        row = db.execute("SELECT * FROM component WHERE component_id=?", (task["component_id"],)).fetchone()
        if row is None:
            raise APIError("Task component was deleted", 409)
        return row
    model = (task["extracted_model"] or "").strip()
    manufacturer_name = (task["extracted_manufacturer"] or "").strip()
    category_name = (task["extracted_category"] or "").strip()
    if not model or not manufacturer_name or not category_name:
        raise APIError("Set model, manufacturer and category before approving parameters")
    category = _category(db, category_name)
    manufacturer = _manufacturer(db, manufacturer_name)
    existing = db.execute(
        "SELECT * FROM component WHERE manufacturer_id=? AND model=?",
        (manufacturer["manufacturer_id"], model),
    ).fetchone()
    if existing is not None:
        component_id = existing["component_id"]
    else:
        component_id = db.execute(
            "INSERT INTO component(model,category_id,manufacturer_id,package) VALUES(?,?,?,?)",
            (model, category["category_id"], manufacturer["manufacturer_id"], task["extracted_package"]),
        ).lastrowid
        log(
            db,
            g.user["user_id"],
            "create",
            "component",
            component_id,
            {"model": model, "manufacturer": manufacturer_name, "category": category_name},
        )
    db.execute("UPDATE extraction_task SET component_id=? WHERE task_id=?", (component_id, task["task_id"]))
    return db.execute("SELECT * FROM component WHERE component_id=?", (component_id,)).fetchone()


def _mapped_definition(db, parameter_id):
    if parameter_id is None:
        return None
    row = db.execute("SELECT * FROM parameter_def WHERE parameter_id=?", (parameter_id,)).fetchone()
    if row is None:
        raise APIError("parameter_id does not exist")
    return row


@bp.get("/params")
@login_required("admin", "auditor")
def pending_params():
    """Parameter-level pending list: result, source and confidence per row."""
    page, size = pagination()
    db = get_db()
    where = "1=1"
    args = []
    if request.args.get("task_id"):
        where = "v.task_id=?"
        args = [integer(request.args["task_id"], "task_id")]
    total = db.execute(
        "SELECT COUNT(*) FROM v_pending_review v WHERE " + where, args
    ).fetchone()[0]
    rows = db.execute(
        "SELECT v.extraction_param_id,v.task_id,v.user_id,v.username,v.component_id,"
        "COALESCE(v.model,t.extracted_model) AS model,"
        "v.source_type,v.source_location,v.parameter_id,v.canonical_name,v.display_name,"
        "v.raw_name,v.raw_value,v.value_num,v.unit,v.confidence,v.source_page,v.source_snippet,v.created_time "
        "FROM v_pending_review v JOIN extraction_task t ON t.task_id=v.task_id "
        "WHERE " + where + " "
        "ORDER BY v.confidence IS NULL,v.confidence,v.extraction_param_id "
        "LIMIT ? OFFSET ?",
        args + [size, (page - 1) * size],
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        location = item.get("source_location") or ""
        if item.get("source_type") in ("pdf", "csv", "excel") and location:
            item["source_location"] = Path(location).name
            item["source_file"] = True
        else:
            item["source_file"] = False
        items.append(item)
    return ok({"items": items, "total": total, "page": page, "page_size": size})


@bp.get("/tasks")
@login_required("admin", "auditor")
def listing():
    page, size = pagination()
    db = get_db()
    clauses = ["t.status='success'", "r.pending_count>0"]
    args = []
    if request.args.get("task_id"):
        clauses.append("t.task_id=?")
        args.append(integer(request.args["task_id"], "task_id"))
    where = " AND ".join(clauses)
    total = db.execute(
        "SELECT COUNT(*) FROM extraction_task t JOIN v_task_review r ON r.task_id=t.task_id WHERE " + where,
        args,
    ).fetchone()[0]
    rows = db.execute(
        "SELECT t.* FROM extraction_task t JOIN v_task_review r ON r.task_id=t.task_id "
        "WHERE " + where + " ORDER BY t.task_id LIMIT ? OFFSET ?",
        args + [size, (page - 1) * size],
    ).fetchall()
    return ok({"items": [serialize_task(row) for row in rows], "total": total, "page": page, "page_size": size})


@bp.get("/tasks/<int:task_id>")
@login_required("admin", "auditor")
def detail(task_id):
    row = task_access(task_id)
    if row["status"] != "success":
        raise APIError("Only successful extraction tasks can be reviewed", 409)
    return ok(serialize_task(row, True))


@bp.put("/tasks/<int:task_id>/identity")
@login_required("auditor")
def identity(task_id):
    data = body()
    db = get_db()
    with db:
        db.execute("BEGIN IMMEDIATE")
        task = task_access(task_id)
        if task["status"] != "success":
            raise APIError("Only successful extraction tasks can be edited", 409)
        model = text(data.get("model"), "model", 100)
        manufacturer_name = text(data.get("manufacturer"), "manufacturer", 100)
        category_name = text(data.get("category"), "category", 100)
        category = _category(db, category_name)
        manufacturer = _manufacturer(db, manufacturer_name)
        package = text(data.get("package"), "package", 100, required=False)
        db.execute(
            "UPDATE extraction_task SET extracted_model=?,extracted_manufacturer=?,"
            "extracted_category=?,extracted_package=? WHERE task_id=?",
            (model, manufacturer_name, category["name"], package, task_id),
        )
        if task["component_id"] is not None:
            existing = db.execute(
                "SELECT * FROM component WHERE manufacturer_id=? AND model=? AND component_id<>?",
                (manufacturer["manufacturer_id"], model, task["component_id"]),
            ).fetchone()
            if existing:
                raise APIError("Another component already uses this manufacturer/model", 409)
            db.execute(
                "UPDATE component SET model=?,category_id=?,manufacturer_id=?,package=? WHERE component_id=?",
                (model, category["category_id"], manufacturer["manufacturer_id"], package, task["component_id"]),
            )
        log(db, g.user["user_id"], "edit_identity", "task", task_id, {"model": model})
    return ok(serialize_task(task_access(task_id), True))


def _apply_mapping(db, parameter, data):
    """Update a pending extraction_param before the audit_log row is inserted."""
    fields = {"parameter_id": parameter["parameter_id"]}
    definition = None
    if "parameter_id" in data:
        parameter_id = data.get("parameter_id")
        if parameter_id is not None:
            parameter_id = integer(parameter_id, "parameter_id")
            definition = _mapped_definition(db, parameter_id)
        fields["parameter_id"] = parameter_id

    raw_name = data.get("raw_name", parameter["raw_name"])
    raw_name = text(raw_name, "raw_name", 250)
    raw_value = data.get("raw_value", parameter["raw_value"])
    raw_value = text(raw_value, "raw_value", 4000)

    if "parameter_id" in data and definition is None and data.get("parameter_id") is not None:
        raise APIError("parameter_id does not exist")

    if definition is None and parameter["parameter_id"] is not None:
        definition = _mapped_definition(db, parameter["parameter_id"])

    value_num = data.get("value_num", parameter["value_num"])
    unit = data.get("unit", parameter["unit"])
    if value_num is not None:
        if isinstance(value_num, bool) or not isinstance(value_num, (int, float)) or not math.isfinite(value_num):
            raise APIError("value_num must be a finite number or null")
        value_num = float(value_num)
    if unit is not None and not isinstance(unit, str):
        raise APIError("unit must be a string or null")
    if unit:
        unit = unit.strip() or None

    if definition is not None and definition["data_type"] == "numeric":
        if value_num is None:
            value_num, parsed_unit = numeric(
                raw_value, unit, definition["unit"], definition["canonical_name"], True
            )
            unit = parsed_unit
        elif definition["unit"]:
            unit = definition["unit"]
    elif definition is not None:
        value_num, unit = None, None

    fields.update(
        raw_name=raw_name,
        raw_value=raw_value,
        value_num=value_num,
        unit=unit,
    )
    clash = db.execute(
        "SELECT 1 FROM extraction_param WHERE task_id=? AND raw_name=? AND extraction_param_id<>?",
        (parameter["task_id"], raw_name, parameter["extraction_param_id"]),
    ).fetchone()
    if clash:
        raise APIError("raw_name already exists in this task", 409)
    db.execute(
        "UPDATE extraction_param SET parameter_id=?,raw_name=?,raw_value=?,value_num=?,unit=? "
        "WHERE extraction_param_id=? AND review_status='pending'",
        (
            fields["parameter_id"],
            fields["raw_name"],
            fields["raw_value"],
            fields["value_num"],
            fields["unit"],
            parameter["extraction_param_id"],
        ),
    )
    return definition


@bp.post("/params/<int:extraction_param_id>")
@login_required("auditor")
def review_param(extraction_param_id):
    data = body()
    action = data.get("action")
    if action not in ("approve", "reject"):
        raise APIError("action must be approve or reject")
    comment = text(data.get("comment", ""), "comment", 2000, required=False)
    if action == "reject" and not comment:
        raise APIError("Rejection requires a comment")

    db = get_db()
    with db:
        db.execute("BEGIN IMMEDIATE")
        parameter = _param_access(extraction_param_id)
        if parameter["task_status"] != "success":
            raise APIError("Only parameters of successful tasks can be reviewed", 409)
        if parameter["review_status"] != "pending":
            raise APIError("This parameter has already been reviewed", 409)

        before = {
            key: parameter[key]
            for key in ("parameter_id", "raw_name", "raw_value", "value_num", "unit", "review_status")
        }
        definition = _apply_mapping(db, parameter, data) if action == "approve" else None
        parameter = db.execute(
            "SELECT * FROM extraction_param WHERE extraction_param_id=?", (extraction_param_id,)
        ).fetchone()

        if action == "approve":
            if parameter["parameter_id"] is None:
                raise APIError("Map this parameter to parameter_def before approving")
            task = db.execute(
                "SELECT * FROM extraction_task WHERE task_id=?", (parameter["task_id"],)
            ).fetchone()
            ensure_component(db, task)
            if parameter["value_num"] is None:
                check = db.execute(
                    "SELECT data_type FROM parameter_def WHERE parameter_id=?", (parameter["parameter_id"],)
                ).fetchone()
                if check and check["data_type"] == "numeric":
                    raise APIError("Numeric parameters need value_num before approval")

        after = {
            key: parameter[key]
            for key in ("parameter_id", "raw_name", "raw_value", "value_num", "unit")
        }
        detail = {"before": before, "after": after, "submitted": data}
        db.execute(
            "INSERT INTO audit_log(extraction_param_id,auditor_id,action,comment,detail_json) "
            "VALUES(?,?,?,?,?)",
            (extraction_param_id, g.user["user_id"], action, comment, dump(detail)),
        )
        log(
            db,
            g.user["user_id"],
            "audit_" + action,
            "parameter",
            extraction_param_id,
            {"task_id": parameter["task_id"], "comment": comment},
        )
    updated = db.execute(
        "SELECT ep.*, pd.canonical_name, pd.display_name "
        "FROM extraction_param ep LEFT JOIN parameter_def pd ON pd.parameter_id=ep.parameter_id "
        "WHERE ep.extraction_param_id=?",
        (extraction_param_id,),
    ).fetchone()
    return ok(
        {
            "extraction_param_id": extraction_param_id,
            "review_status": updated["review_status"],
            "parameter_id": updated["parameter_id"],
            "canonical_name": updated["canonical_name"],
            "raw_name": updated["raw_name"],
            "value_num": updated["value_num"],
            "unit": updated["unit"],
            "task_id": updated["task_id"],
        }
    )


@bp.get("/logs")
@login_required("admin", "auditor")
def logs():
    page, size = pagination()
    db = get_db()
    args = []
    where = "1=1"
    if request.args.get("task_id"):
        where = "ep.task_id=?"
        args = [integer(request.args["task_id"], "task_id")]
    total = db.execute(
        "SELECT COUNT(*) FROM audit_log a JOIN extraction_param ep "
        "ON ep.extraction_param_id=a.extraction_param_id WHERE " + where,
        args,
    ).fetchone()[0]
    rows = db.execute(
        "SELECT a.audit_log_id,a.extraction_param_id,ep.task_id,ep.raw_name,"
        "a.auditor_id,u.username AS auditor,a.action,a.comment,a.detail_json,a.audit_time "
        "FROM audit_log a JOIN extraction_param ep ON ep.extraction_param_id=a.extraction_param_id "
        "JOIN users u ON u.user_id=a.auditor_id WHERE " + where + " "
        "ORDER BY a.audit_log_id DESC LIMIT ? OFFSET ?",
        args + [size, (page - 1) * size],
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["detail"] = json.loads(item.pop("detail_json") or "{}")
        except (TypeError, ValueError):
            item["detail"] = {}
        items.append(item)
    return ok({"items": items, "total": total, "page": page, "page_size": size})
