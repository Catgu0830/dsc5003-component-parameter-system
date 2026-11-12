"""SQLite-backed queue using extraction_task / extraction_param."""
import threading
from datetime import datetime, timedelta, timezone

from .catalog import load_catalog
from .common import APIError
from .db import connect, log, utc_now
from .extraction import extract


def _source_fields(component):
    return (
        component.get("model"),
        component.get("manufacturer"),
        component.get("category"),
        component.get("package"),
    )


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


def process_one(app):
    db = connect(app.config["DATABASE"])
    try:
        now = datetime.now(timezone.utc)
        stale = (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE extraction_task SET status='failed',"
                "error_msg='Worker lease expired; retry this task',"
                "finished_time=? "
                "WHERE status='processing' AND started_time IS NOT NULL AND started_time<?",
                (utc_now(), stale),
            )
            task = db.execute(
                "SELECT * FROM extraction_task WHERE status='pending' ORDER BY task_id LIMIT 1"
            ).fetchone()
            if not task:
                return False
            db.execute(
                "UPDATE extraction_task SET status='processing',started_time=?,error_msg=NULL "
                "WHERE task_id=? AND status='pending'",
                (utc_now(), task["task_id"]),
            )
            log(db, task["user_id"], "processing", "task", task["task_id"], {"attempt": task["retry_count"] + 1})

        try:
            catalog = load_catalog(db)
            result = extract(task, app.config, catalog)
            component = result["component"]
            model, manufacturer, category, package = _source_fields(component)
            with db:
                changed = db.execute(
                    "UPDATE extraction_task SET status='success',extracted_model=?,"
                    "extracted_manufacturer=?,extracted_category=?,extracted_package=?,"
                    "finished_time=?,error_msg=NULL "
                    "WHERE task_id=? AND status='processing'",
                    (model, manufacturer, category, package, utc_now(), task["task_id"]),
                ).rowcount
                if changed:
                    db.execute("DELETE FROM extraction_param WHERE task_id=?", (task["task_id"],))
                    _write_params(db, task["task_id"], component)
                    log(
                        db,
                        task["user_id"],
                        "extracted",
                        "task",
                        task["task_id"],
                        {"components": 1, "parameters": len(component["parameters"]), "warnings": result.get("warnings", [])},
                    )
        except Exception as exc:
            message = exc.message if isinstance(exc, APIError) else (
                f"Extraction failed ({type(exc).__name__}); verify source format or contact administrator"
            )
            if not isinstance(exc, APIError):
                app.logger.exception("Task %s extraction failed", task["task_id"])
            with db:
                changed = db.execute(
                    "UPDATE extraction_task SET status='failed',error_msg=?,finished_time=? "
                    "WHERE task_id=? AND status='processing'",
                    (message, utc_now(), task["task_id"]),
                ).rowcount
                if changed:
                    log(db, task["user_id"], "extraction_failed", "task", task["task_id"], {"error": message})
        return True
    finally:
        db.close()


def run_worker(app, stop=None):
    stop = stop or threading.Event()
    while not stop.is_set():
        try:
            worked = process_one(app)
        except Exception:
            app.logger.exception("Queue worker iteration failed")
            worked = False
        if not worked:
            stop.wait(0.5)


def start_worker(app):
    stop = threading.Event()
    thread = threading.Thread(target=run_worker, args=(app, stop), daemon=True, name="extraction-worker")
    thread.start()
    return stop, thread
