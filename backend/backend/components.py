"""Component queries, approved parameters, compare and admin CRUD."""
import json

from flask import Blueprint, g, request

from .auth import login_required
from .catalog import load_catalog
from .common import APIError, body, confirmed, integer, ok, pagination, text
from .db import get_db, log
from .normalization import numeric
from .tasks import create_task, serialize_task

bp = Blueprint("components", __name__, url_prefix="/api/components")


def component_access(component_id):
    row = get_db().execute(
        "SELECT c.*, cat.name AS category, m.name AS manufacturer, m.website "
        "FROM component c JOIN category cat ON cat.category_id=c.category_id "
        "JOIN manufacturer m ON m.manufacturer_id=c.manufacturer_id "
        "WHERE c.component_id=?",
        (component_id,),
    ).fetchone()
    if row is None:
        raise APIError("Component not found", 404)
    return row


def serialize_component(row):
    params = []
    for item in get_db().execute(
        "SELECT cp.*, pd.canonical_name, pd.display_name, pd.unit AS canonical_unit, "
        "ep.task_id AS source_task_id, ep.source_page, ep.source_snippet "
        "FROM component_parameter cp JOIN parameter_def pd ON pd.parameter_id=cp.parameter_id "
        "LEFT JOIN extraction_param ep ON ep.extraction_param_id=cp.source_extraction_param_id "
        "WHERE cp.component_id=? ORDER BY pd.parameter_id",
        (row["component_id"],),
    ):
        params.append(
            {
                "component_id": item["component_id"],
                "parameter_id": item["parameter_id"],
                "name": item["display_name"] or item["canonical_name"],
                "canonical_name": item["canonical_name"],
                "display_name": item["display_name"],
                "value": item["value_num"] if item["value_num"] is not None else item["value_text"],
                "value_num": item["value_num"],
                "value_text": item["value_text"],
                "unit": item["unit"] or item["canonical_unit"],
                "source": {
                    "task_id": item["source_task_id"],
                    "page": item["source_page"],
                    "snippet": item["source_snippet"],
                },
                "updated_time": item["updated_time"],
            }
        )
    return {
        "component_id": row["component_id"],
        "model": row["model"],
        "category_id": row["category_id"],
        "category": row["category"],
        "manufacturer_id": row["manufacturer_id"],
        "manufacturer": row["manufacturer"],
        "website": row["website"],
        "package": row["package"],
        "description": row["description"],
        "created_time": row["created_time"],
        "updated_time": row["updated_time"],
        "parameters": params,
    }


def _category_row(db, value):
    if value in (None, ""):
        raise APIError("Category is required")
    if isinstance(value, bool):
        raise APIError("Invalid category")
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        row = db.execute("SELECT * FROM category WHERE category_id=?", (int(value),)).fetchone()
    else:
        row = db.execute("SELECT * FROM category WHERE name=? COLLATE NOCASE", (str(value).strip(),)).fetchone()
    if row is None:
        raise APIError("Category not found")
    return row


def _manufacturer_row(db, value, create=False):
    if value in (None, ""):
        raise APIError("Manufacturer is required")
    if isinstance(value, bool):
        raise APIError("Invalid manufacturer")
    if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
        row = db.execute("SELECT * FROM manufacturer WHERE manufacturer_id=?", (int(value),)).fetchone()
        if row is None:
            raise APIError("Manufacturer not found")
        return row
    name = str(value).strip()
    row = db.execute("SELECT * FROM manufacturer WHERE name=? COLLATE NOCASE", (name,)).fetchone()
    if row is None:
        if not create:
            raise APIError("Manufacturer not found")
        mid = db.execute("INSERT INTO manufacturer(name) VALUES(?)", (name,)).lastrowid
        row = db.execute("SELECT * FROM manufacturer WHERE manufacturer_id=?", (mid,)).fetchone()
    return row


def filters(query=None):
    query = request.args if query is None else query
    db = get_db()
    catalog = load_catalog(db)
    where = ["1=1"]
    args = []
    if query.get("component_id"):
        where.append("c.component_id=?")
        args.append(integer(query["component_id"], "component_id"))
    keyword = query.get("keyword", query.get("q", ""))
    if not isinstance(keyword, str):
        raise APIError("keyword must be a string")
    keyword = keyword.strip()
    if keyword:
        if len(keyword) > 200:
            raise APIError("keyword too long")
        pattern = "%" + keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append(
            "(c.model LIKE ? ESCAPE '\\' OR m.name LIKE ? ESCAPE '\\' OR cat.name LIKE ? ESCAPE '\\' "
            "OR c.package LIKE ? ESCAPE '\\' OR c.description LIKE ? ESCAPE '\\' "
            "OR EXISTS(SELECT 1 FROM component_parameter cp JOIN parameter_def pd "
            "ON pd.parameter_id=cp.parameter_id WHERE cp.component_id=c.component_id "
            "AND (pd.display_name LIKE ? ESCAPE '\\' OR pd.canonical_name LIKE ? ESCAPE '\\' "
            "OR cp.value_text LIKE ? ESCAPE '\\')))"
        )
        args.extend([pattern] * 8)
    if query.get("category_id"):
        where.append("c.category_id=?")
        args.append(integer(query["category_id"], "category_id"))
    elif query.get("category"):
        category = _category_row(db, query["category"])
        where.append("c.category_id=?")
        args.append(category["category_id"])
    if query.get("manufacturer_id"):
        where.append("c.manufacturer_id=?")
        args.append(integer(query["manufacturer_id"], "manufacturer_id"))
    elif query.get("manufacturer"):
        manufacturer = _manufacturer_row(db, query["manufacturer"])
        where.append("c.manufacturer_id=?")
        args.append(manufacturer["manufacturer_id"])
    if query.get("package"):
        if not isinstance(query["package"], str):
            raise APIError("package must be a string")
        where.append("c.package=?")
        args.append(query["package"].strip().upper().replace(" ", ""))

    raw = query.get("filters", "[]")
    try:
        ranges = raw if isinstance(raw, list) else json.loads(raw)
    except (ValueError, TypeError):
        raise APIError("filters must be a JSON array")
    if not isinstance(ranges, list) or len(ranges) > 10:
        raise APIError("At most 10 range filters")
    for condition in ranges:
        if not isinstance(condition, dict):
            raise APIError("Each filter must be an object")
        definition = catalog.parameter(condition.get("name"))
        if definition is None:
            raise APIError("Unknown parameter in filter")
        if definition["data_type"] != "numeric":
            raise APIError("Only numeric parameters support range filters")
        checks = ["cp.component_id=c.component_id", "cp.parameter_id=?", "cp.value_num IS NOT NULL"]
        values = [definition["parameter_id"]]
        bounds = {}
        for key, operator in (("min", ">="), ("max", "<=")):
            if key in condition:
                value, _ = numeric(
                    condition[key], condition.get("unit"), definition["unit"],
                    definition["canonical_name"], True,
                )
                bounds[key] = value
                checks.append(f"cp.value_num{operator}?")
                values.append(value)
        if not bounds:
            raise APIError("Range filter needs min or max")
        if bounds.get("min", float("-inf")) > bounds.get("max", float("inf")):
            raise APIError("min cannot exceed max")
        where.append("EXISTS(SELECT 1 FROM component_parameter cp WHERE " + " AND ".join(checks) + ")")
        args.extend(values)

    required = query.get("required_parameters", [])
    if not isinstance(required, list) or len(required) > 20:
        raise APIError("required_parameters must be an array of at most 20 names")
    for name in required:
        definition = catalog.parameter(name)
        if definition is None:
            raise APIError("Unknown required parameter")
        where.append(
            "EXISTS(SELECT 1 FROM component_parameter cp WHERE cp.component_id=c.component_id "
            "AND cp.parameter_id=?)"
        )
        args.append(definition["parameter_id"])
    return " AND ".join(where), args


def query_components(export=False, query=None):
    query = request.args if query is None else query
    page, size = pagination(query)
    where, args = filters(query)
    sort = query.get("sort", "component_id")
    order = query.get("order", "desc")
    allowed = {
        "component_id": "c.component_id",
        "model": "c.model",
        "category": "cat.name",
        "manufacturer": "m.name",
        "package": "c.package",
        "created_time": "c.created_time",
        "updated_time": "c.updated_time",
    }
    if not isinstance(sort, str) or sort not in allowed:
        raise APIError("Unsupported sort")
    if not isinstance(order, str) or order.lower() not in ("asc", "desc"):
        raise APIError("Unsupported order")
    order = order.lower()
    db = get_db()
    base = (
        " FROM component c JOIN category cat ON cat.category_id=c.category_id "
        "JOIN manufacturer m ON m.manufacturer_id=c.manufacturer_id WHERE " + where
    )
    total = db.execute("SELECT COUNT(*)" + base, args).fetchone()[0]
    if export and total > 10000:
        raise APIError("Export limited to 10000 components; narrow filters")
    limit, offset = (10000, 0) if export else (size, (page - 1) * size)
    rows = db.execute(
        "SELECT c.*,cat.name AS category,m.name AS manufacturer,m.website" + base
        + f" ORDER BY {allowed[sort]} {order},c.component_id {order} LIMIT ? OFFSET ?",
        args + [limit, offset],
    ).fetchall()
    return {
        "items": [serialize_component(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": size,
    }


@bp.get("")
@login_required()
def listing():
    return ok(query_components())


@bp.post("")
@login_required("admin")
def create():
    data = body()
    db = get_db()
    model = text(data.get("model"), "model", 100)
    category = _category_row(db, data.get("category", data.get("category_id")))
    manufacturer = _manufacturer_row(db, data.get("manufacturer", data.get("manufacturer_id")), create=True)
    package = text(data.get("package"), "package", 100, required=False)
    description = text(data.get("description"), "description", 1000, required=False)
    with db:
        cursor = db.execute(
            "INSERT INTO component(model,category_id,manufacturer_id,package,description) VALUES(?,?,?,?,?)",
            (model, category["category_id"], manufacturer["manufacturer_id"], package, description),
        )
        log(db, g.user["user_id"], "create", "component", cursor.lastrowid, {"model": model})
    return ok(serialize_component(component_access(cursor.lastrowid)), 201)


@bp.get("/<int:component_id>")
@login_required()
def detail(component_id):
    item = serialize_component(component_access(component_id))
    item["history"] = [
        dict(row)
        for row in get_db().execute(
            "SELECT t.task_id,t.source_type,t.status,t.created_time,t.finished_time,"
            "r.param_count,r.pending_count,r.approved_count,r.rejected_count,r.review_state "
            "FROM extraction_task t LEFT JOIN v_task_review r ON r.task_id=t.task_id "
            "WHERE t.component_id=? ORDER BY t.task_id DESC",
            (component_id,),
        )
    ]
    return ok(item)


@bp.put("/<int:component_id>")
@login_required("admin")
def update(component_id):
    data = body()
    db = get_db()
    row = component_access(component_id)
    model = text(data.get("model", row["model"]), "model", 100)
    category = _category_row(db, data.get("category", data.get("category_id", row["category_id"])))
    manufacturer = _manufacturer_row(
        db, data.get("manufacturer", data.get("manufacturer_id", row["manufacturer_id"])), create=True
    )
    package = text(data.get("package", row["package"]), "package", 100, required=False)
    description = text(data.get("description", row["description"]), "description", 1000, required=False)
    with db:
        db.execute(
            "UPDATE component SET model=?,category_id=?,manufacturer_id=?,package=?,description=? "
            "WHERE component_id=?",
            (model, category["category_id"], manufacturer["manufacturer_id"], package, description, component_id),
        )
        log(db, g.user["user_id"], "update", "component", component_id, {"model": model})
    return ok(serialize_component(component_access(component_id)))


@bp.delete("/<int:component_id>")
@login_required("admin")
def delete(component_id):
    confirmed(body())
    db = get_db()
    with db:
        db.execute("BEGIN IMMEDIATE")
        component_access(component_id)
        db.execute("DELETE FROM component WHERE component_id=?", (component_id,))
        log(db, g.user["user_id"], "delete", "component", component_id)
    return ok()


@bp.get("/<int:component_id>/parameters")
@login_required()
def parameters(component_id):
    return ok(serialize_component(component_access(component_id))["parameters"])


@bp.post("/<int:component_id>/parameters")
@login_required("admin")
def add_parameters(component_id):
    row = component_access(component_id)
    current = serialize_component(row)
    data = body()
    if "parameters" in data:
        current["parameters"] = data["parameters"]
    task = create_task({"component": current}, component_id)
    return ok({"task": serialize_task(task), "publication": "pending_review"}, 202)


def comparison():
    raw = request.args.get("ids", "").split(",")
    if not 2 <= len(raw) <= 10:
        raise APIError("Compare requires 2-10 component ids")
    ids = [integer(value, "id") for value in raw]
    if len(set(ids)) != len(ids):
        raise APIError("Comparison ids must be unique")
    items = [serialize_component(component_access(component_id)) for component_id in ids]
    names = {}
    for component in items:
        for parameter in component["parameters"]:
            names[parameter["parameter_id"]] = parameter
    rows = []
    for parameter_id, sample in sorted(names.items()):
        values = []
        maps = []
        for component in items:
            mapping = {p["parameter_id"]: p for p in component["parameters"]}
            maps.append(mapping)
            values.append(mapping.get(parameter_id))
        comparable = [(p["value"], p["unit"]) if p else None for p in values]
        rows.append(
            {
                "parameter_id": parameter_id,
                "name": sample["name"],
                "canonical_name": sample["canonical_name"],
                "unit": sample["unit"],
                "values": values,
                "missing_component_ids": [ids[i] for i, p in enumerate(values) if p is None],
                "different": any(v != comparable[0] for v in comparable[1:]),
            }
        )
    return {"components": items, "rows": rows}


@bp.get("/compare")
@login_required()
def compare():
    return ok(comparison())
