"""SQLite helpers for the 11-table schema."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from flask import current_app, g

SCHEMA_FILE = Path(__file__).with_name("schema.sql")
CATALOG_FILE = Path(__file__).with_name("seed_catalog.sql")


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def connect(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=15000")
    return db


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def _tables(db):
    return {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def init_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        tables = _tables(db)
        if "extraction_param" not in tables and "tasks" in tables:
            raise RuntimeError(
                "Existing database uses the old 10-table schema. "
                "Back it up and remove it before starting the 11-table backend."
            )
        if "category" not in tables:
            db.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
            db.executescript(CATALOG_FILE.read_text(encoding="utf-8"))
        elif (
            db.execute("SELECT COUNT(*) FROM category").fetchone()[0] == 0
            or db.execute("SELECT COUNT(*) FROM parameter_def").fetchone()[0] == 0
        ):
            db.executescript(CATALOG_FILE.read_text(encoding="utf-8"))
        # Keep the connection's WAL setting and make sure pending writes are visible.
        db.commit()


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def log(db, user_id, action, target_type=None, target_id=None, detail=None, ip=None):
    """Write to operation_log; target_type must match the schema CHECK list."""
    allowed = {None, "auth", "user", "component", "parameter", "task", "export"}
    if target_type not in allowed:
        raise ValueError(f"Invalid operation_log target_type: {target_type}")
    db.execute(
        "INSERT INTO operation_log(user_id,action,target_type,target_id,detail,ip_address) "
        "VALUES(?,?,?,?,?,?)",
        (
            user_id,
            action,
            target_type,
            target_id,
            dump(detail or {}),
            ip,
        ),
    )
