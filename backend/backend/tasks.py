"""Extraction tasks and the parameter-level extraction draft."""
import hashlib
import json
import re
import uuid
from pathlib import Path

from flask import Blueprint, current_app, g, request

from .auth import login_required
from .catalog import load_catalog
from .common import APIError, body, confirmed, integer, ok, pagination, text
from .db import get_db, log, utc_now
from .normalization import normalize_component
from .sources import check_xlsx, table_records, validate_url

bp = Blueprint("tasks", __name__, url_prefix="/api/tasks")


def task_access(task_id):
    row = get_db().execute("SELECT * FROM extraction_task WHERE task_id=?", (task_id,)).fetchone()
    if row is None:
        raise APIError("Task not found", 404)
    if g.user["role"] == "user" and row["user_id"] != g.user["user_id"]:
        raise APIError("Task belongs to another user", 403)
    return row


def _display_source(row):
    if row["source_type"] == "url":
        return row["source_location"]
    if row["source_location"]:
        return Path(row["source_location"]).name
    return row["source_type"]


def _review_counts(db, task_id):
    row = db.execute(
        "SELECT param_count,pending_count,approved_count,rejected_count,review_state "
        "FROM v_task_review WHERE task_id=?",
        (task_id,),
    ).fetchone()
    if row is None:
        return {
            "param_count": 0,
            "pending_count": 0,
            "approved_count": 0,
            "rejected_count": 0,
            "review_state": "empty",
        }
    return dict(row)


def _parameter_payload(row):
    parameter_id = row["parameter_id"]
    name = row["display_name"] or row["canonical_name"] or row["raw_name"]
    return {
        "extraction_param_id": row["extraction_param_id"],
        "task_id": row["task_id"],
        "parameter_id": parameter_id,
        "name": name,
        "canonical_name": row["canonical_name"] or row["raw_name"],
        "raw_name": row["raw_name"],
        "raw_value": row["raw_value"],
        "value": row["value_num"] if row["value_num"] is not None else row["raw_value"],
        "value_num": row["value_num"],
        "value_text": row["raw_value"] if row["value_num"] is None else None,
        "unit": row["unit"],
        "confidence": row["confidence"],
        "source": {"page": row["source_page"], "snippet": row["source_snippet"]},
        "review_status": row["review_status"],
        "review_comment": row["review_comment"],
        "reviewed_by": row["reviewed_by"],
        "reviewed_time": row["reviewed_time"],
        "is_specification": row["raw_name"].startswith("[原文] "),
    }


def task_parameters(db, task_id):
    rows = db.execute(
        "SELECT ep.*, pd.canonical_name, pd.display_name, pd.data_type, pd.unit AS canonical_unit "
        "FROM extraction_param ep "
        "LEFT JOIN parameter_def pd ON pd.parameter_id=ep.parameter_id "
        "WHERE ep.task_id=? ORDER BY ep.extraction_param_id",
        (task_id,),
    )
    return [_parameter_payload(row) for row in rows]


def component_payload(db, task):
    if task["component_id"] is not None:
        row = db.execute(
            "SELECT c.*, cat.name AS category, m.name AS manufacturer "
            "FROM component c JOIN category cat ON cat.category_id=c.category_id "
            "JOIN manufacturer m ON m.manufacturer_id=c.manufacturer_id "
            "WHERE c.component_id=?",
            (task["component_id"],),
        ).fetchone()
        if row is not None:
            model = row["model"]
            manufacturer = row["manufacturer"]
            category = row["category"]
            package = row["package"]
            component_id = row["component_id"]
        else:
            model = task["extracted_model"]
            manufacturer = task["extracted_manufacturer"]
            category = task["extracted_category"]
            package = task["extracted_package"]
            component_id = None
    else:
        model = task["extracted_model"]
        manufacturer = task["extracted_manufacturer"]
        category = task["extracted_category"]
        package = task["extracted_package"]
        component_id = None
    return {
        "component_id": component_id,
        "model": model,
        "manufacturer": manufacturer,
        "category": category,
        "package": package,
        "parameters": task_parameters(db, task["task_id"]),
    }


def _warnings_for_task(db, task_id):
    row = db.execute(
        "SELECT detail FROM operation_log WHERE target_type='task' AND target_id=? "
        "AND action IN ('create','extracted') ORDER BY log_id DESC LIMIT 1",
        (task_id,),
    ).fetchone()
    if row is None or not row["detail"]:
        return []
    try:
        detail = json.loads(row["detail"])
    except (TypeError, ValueError):
        return []
    warnings = detail.get("warnings") if isinstance(detail, dict) else None
    return warnings if isinstance(warnings, list) else []


def serialize_task(row, detail=False):
    db = get_db()
    counts = _review_counts(db, row["task_id"])
    source = _display_source(row)
    result = {
        "task_id": row["task_id"],
        "user_id": row["user_id"],
        "component_id": row["component_id"],
        "source_type": row["source_type"],
        "source_location": source,
        "original_filename": source if row["source_type"] in ("pdf", "csv", "excel") else None,
        "source_file": bool(row["source_location"] and row["source_type"] in ("pdf", "csv", "excel")),
        "source_sha256": row["source_hash"],
        "extracted_model": row["extracted_model"],
        "extracted_manufacturer": row["extracted_manufacturer"],
        "extracted_category": row["extracted_category"],
        "extracted_package": row["extracted_package"],
        "status": row["status"],
        "error_msg": row["error_msg"],
        "retry_count": row["retry_count"],
        "created_time": row["created_time"],
        "started_time": row["started_time"],
        "finished_time": row["finished_time"],
        **counts,
    }
    result["warnings"] = _warnings_for_task(db, row["task_id"])
    if detail:
        result["result"] = {"components": [component_payload(db, row)], "warnings": result["warnings"]}
        result["audit_history"] = [
            dict(item)
            for item in db.execute(
                "SELECT a.audit_log_id,a.extraction_param_id,ep.raw_name,u.username AS auditor,"
                "a.action,a.comment,a.audit_time "
                "FROM audit_log a JOIN extraction_param ep ON ep.extraction_param_id=a.extraction_param_id "
                "JOIN users u ON u.user_id=a.auditor_id "
                "WHERE ep.task_id=? ORDER BY a.audit_time,a.audit_log_id",
                (row["task_id"],),
            )
        ]
    return result


def _safe_original(filename, extension):
    name = Path(filename).name.strip()
    name = re.sub(r"[\x00-\x1f]", "_", name)
    if len(name) > 120:
        stem = Path(name).stem[:100]
        name = stem + extension
    return name or ("upload" + extension)


def _write_params(db, task_id, component):
    for parameter in component["parameters"]:
        source = parameter.get("source") or {}
        page = source.get("page")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            page = None
        snippet = source.get("snippet")
        if not isinstance(snippet, str):
            snippet = None
        if snippet is not None:
            snippet = snippet[:4000]
        db.execute(
            "INSERT INTO extraction_param"
            "(task_id,parameter_id,raw_name,raw_value,value_num,unit,confidence,source_page,source_snippet) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                parameter.get("parameter_id"),
                parameter["raw_name"],
                parameter["raw_value"],
                parameter.get("value_num"),
                parameter.get("unit"),
                parameter.get("confidence"),
                page,
                snippet,
            ),
        )


def _insert_task(
    db,
    user_id,
    source_type,
    source_location,
    source_hash,
    component,
    component_id=None,
    status="success",
    warnings=None,
):
    cursor = db.execute(
        "INSERT INTO extraction_task"
        "(user_id,component_id,source_type,source_location,source_hash,extracted_model,"
        "extracted_manufacturer,extracted_category,extracted_package,status,finished_time) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            user_id,
            component_id,
            source_type,
            source_location,
            source_hash,
            component.get("model"),
            component.get("manufacturer"),
            component.get("category"),
            component.get("package"),
            status,
            utc_now() if status == "success" else None,
        ),
    )
    task_id = cursor.lastrowid
    if status == "success":
        _write_params(db, task_id, component)
    log(
        db,
        user_id,
        "create",
        "task",
        task_id,
        {"source_type": source_type, "warnings": warnings or []},
    )
    return task_id


def create_task(data, component_id=None):
    source_type = data.get("source_type", "manual")
    if source_type not in ("manual", "url"):
        raise APIError("For PDF/CSV/XLSX use /api/tasks/upload")
    db = get_db()
    catalog = load_catalog(db)
    if source_type == "url":
        location = text(data.get("url", data.get("source_location")), "url", 2000)
        validate_url(location, current_app.config["URL_ALLOWED_HOSTS"])
        with db:
            task_id = _insert_task(
                db, g.user["user_id"], "url", location, None, {}, component_id, status="pending"
            )
        return db.execute("SELECT * FROM extraction_task WHERE task_id=?", (task_id,)).fetchone()

    records = data.get("components", [data.get("component", data)])
    if not isinstance(records, list) or len(records) != 1:
        raise APIError("One component per extraction task")
    component = normalize_component(records[0], catalog, {"type": "manual", "snippet": "User-supplied structured entry"}, False)
    if not component.get("model") or not component.get("manufacturer") or not component.get("category"):
        raise APIError("Manual entry requires model, manufacturer and category")
    with db:
        task_id = _insert_task(
            db,
            g.user["user_id"],
            "manual",
            "manual",
            None,
            component,
            component_id,
            status="success",
            warnings=component.get("warnings"),
        )
    return db.execute("SELECT * FROM extraction_task WHERE task_id=?", (task_id,)).fetchone()


@bp.get("")
@login_required()
def list_tasks():
    page, size = pagination()
    clauses = ["1=1"]
    args = []
    if g.user["role"] == "user":
        clauses.append("t.user_id=?")
        args.append(g.user["user_id"])
    if request.args.get("status"):
        clauses.append("t.status=?")
        args.append(request.args["status"])
    if request.args.get("review_state"):
        clauses.append("r.review_state=?")
        args.append(request.args["review_state"])
    if request.args.get("component_id"):
        clauses.append("t.component_id=?")
        args.append(integer(request.args["component_id"], "component_id"))
    where = " AND ".join(clauses)
    db = get_db()
    base = (
        " FROM extraction_task t LEFT JOIN v_task_review r ON r.task_id=t.task_id WHERE " + where
    )
    total = db.execute("SELECT COUNT(*)" + base, args).fetchone()[0]
    rows = db.execute(
        "SELECT t.*" + base + " ORDER BY t.task_id DESC LIMIT ? OFFSET ?",
        args + [size, (page - 1) * size],
    ).fetchall()
    return ok(
        {
            "items": [serialize_task(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": size,
        }
    )


@bp.post("")
@login_required()
def post_task():
    row = create_task(body())
    return ok(serialize_task(row), 202)


@bp.post("/upload")
@login_required()
def upload():
    file = request.files.get("file")
    if not file or not file.filename:
        raise APIError("multipart file field is required")
    extension = Path(file.filename).suffix.lower()
    types = {".pdf": "pdf", ".csv": "csv", ".xlsx": "excel"}
    if extension not in types:
        raise APIError("Only .pdf, .csv and .xlsx are supported")
    original = _safe_original(file.filename, extension)
    destination = Path(current_app.config["UPLOAD_DIR"]) / uuid.uuid4().hex / original
    destination.parent.mkdir(parents=True, exist_ok=True)
    file.save(destination)
    try:
        raw = destination.read_bytes()
        if not raw:
            raise APIError("File is empty")
        if extension == ".pdf" and not raw.startswith(b"%PDF-"):
            raise APIError("Invalid PDF signature")
        if extension == ".xlsx":
            check_xlsx(destination)
        if extension == ".csv":
            try:
                raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                raise APIError("CSV must be UTF-8 encoded")
            if b"\x00" in raw:
                raise APIError("Invalid CSV content")
        db = get_db()
        source_type = types[extension]
        source_hash = hashlib.sha256(raw).hexdigest()

        if source_type in ("csv", "excel"):
            records = table_records(destination, source_type)
            if not 1 <= len(records) <= 1000:
                raise APIError("Import must contain 1-1000 component rows")
            catalog = load_catalog(db)
            context = {
                "type": source_type,
                "location": str(destination),
                "filename": original,
                "sha256": source_hash,
            }
            components = []
            for index, record in enumerate(records, 1):
                try:
                    component = normalize_component(record, catalog, context, False)
                except APIError as exc:
                    raise APIError(f"Row {index}: {exc.message}")
                if not component.get("model") or not component.get("manufacturer") or not component.get("category"):
                    raise APIError(f"Row {index}: model, manufacturer and category are required")
                components.append(component)
            with db:
                tasks = []
                for component in components:
                    task_id = _insert_task(
                        db,
                        g.user["user_id"],
                        source_type,
                        str(destination),
                        source_hash,
                        component,
                        warnings=component.get("warnings"),
                    )
                    tasks.append(
                        serialize_task(
                            db.execute(
                                "SELECT * FROM extraction_task WHERE task_id=?", (task_id,)
                            ).fetchone()
                        )
                    )
                log(
                    db,
                    g.user["user_id"],
                    "upload_batch",
                    "task",
                    None,
                    {"filename": original, "count": len(tasks), "source_type": source_type},
                )
            return ok({"tasks": tasks, "count": len(tasks)}, 201)

        with db:
            cursor = db.execute(
                "INSERT INTO extraction_task"
                "(user_id,source_type,source_location,source_hash,status) VALUES(?,?,?,?, 'pending')",
                (
                    g.user["user_id"],
                    source_type,
                    str(destination),
                    source_hash,
                ),
            )
            log(
                db,
                g.user["user_id"],
                "upload",
                "task",
                cursor.lastrowid,
                {"filename": original, "bytes": len(raw)},
            )
        return ok(
            serialize_task(
                db.execute("SELECT * FROM extraction_task WHERE task_id=?", (cursor.lastrowid,)).fetchone()
            ),
            202,
        )
    except Exception:
        import shutil

        shutil.rmtree(destination.parent, ignore_errors=True)
        raise


@bp.get("/<int:task_id>")
@login_required()
def detail(task_id):
    return ok(serialize_task(task_access(task_id), True))


@bp.get("/<int:task_id>/source")
@login_required()
def source(task_id):
    from flask import send_file

    row = task_access(task_id)
    if row["source_type"] not in ("pdf", "csv", "excel") or not row["source_location"]:
        raise APIError("No downloadable source file", 404)
    path = Path(row["source_location"]).resolve()
    upload = Path(current_app.config["UPLOAD_DIR"]).resolve()
    if upload not in path.parents:
        raise APIError("Source file is outside the upload directory", 404)
    return send_file(path, as_attachment=True, download_name=path.name)


@bp.post("/<int:task_id>/retry")
@login_required()
def retry(task_id):
    db = get_db()
    with db:
        db.execute("BEGIN IMMEDIATE")
        row = task_access(task_id)
        if row["status"] != "failed":
            raise APIError("Only failed tasks may be retried", 409)
        if row["retry_count"] >= current_app.config["MAX_RETRIES"]:
            raise APIError("Retry limit reached; create a new task", 409)
        db.execute(
            "UPDATE extraction_task SET status='pending',retry_count=retry_count+1,"
            "error_msg=NULL,started_time=NULL,finished_time=NULL WHERE task_id=?",
            (task_id,),
        )
        log(db, g.user["user_id"], "retry", "task", task_id)
    return ok(serialize_task(task_access(task_id)), 202)


@bp.delete("/<int:task_id>")
@login_required()
def delete(task_id):
    confirmed(body())
    db = get_db()
    with db:
        db.execute("BEGIN IMMEDIATE")
        row = task_access(task_id)
        if g.user["role"] not in ("admin", "user"):
            raise APIError("Only the task owner or an administrator may delete a task", 403)
        if row["status"] == "processing":
            raise APIError("A processing task cannot be deleted", 409)
        audit = db.execute(
            "SELECT 1 FROM audit_log a JOIN extraction_param ep "
            "ON ep.extraction_param_id=a.extraction_param_id WHERE ep.task_id=? LIMIT 1",
            (task_id,),
        ).fetchone()
        if audit:
            raise APIError("Task with audit history cannot be deleted", 409)
        db.execute("DELETE FROM extraction_task WHERE task_id=?", (task_id,))
        log(db, g.user["user_id"], "delete", "task", task_id)
    return ok()


@bp.get("/<int:task_id>/source/page/<int:page_no>")
@login_required()
def source_page(task_id, page_no):
    import io

    import pymupdf
    from flask import send_file

    row = task_access(task_id)
    if row["source_type"] != "pdf" or not row["source_location"]:
        raise APIError("Source is not a PDF", 400)
    path = Path(row["source_location"]).resolve()
    upload = Path(current_app.config["UPLOAD_DIR"]).resolve()
    if upload not in path.parents:
        raise APIError("Source file is outside the upload directory", 404)
    with pymupdf.open(path) as doc:
        if doc.needs_pass:
            raise APIError("PDF requires a password", 400)
        if page_no < 1 or page_no > len(doc):
            raise APIError("PDF page not found", 404)
        page = doc[page_no - 1]
        scale = min(1.5, 1800 / max(page.rect.width, page.rect.height))
        raw = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")
    return send_file(io.BytesIO(raw), mimetype="image/png", download_name=f"page-{page_no}.png")
