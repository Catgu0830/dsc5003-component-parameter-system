"""Admin APIs for users, manufacturers and operation logs."""
import json
import sqlite3

from flask import Blueprint, g, request
from werkzeug.security import generate_password_hash

from .auth import login_required, public_user
from .common import APIError, body, confirmed, ok, pagination, text
from .db import get_db, log

bp = Blueprint("admin", __name__, url_prefix="/api")


@bp.get("/users")
@login_required("admin")
def users():
    page, size = pagination()
    db = get_db()
    return ok(
        {
            "items": [
                public_user(row)
                for row in db.execute(
                    "SELECT * FROM users ORDER BY user_id LIMIT ? OFFSET ?",
                    (size, (page - 1) * size),
                )
            ],
            "total": db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "page": page,
            "page_size": size,
        }
    )


@bp.post("/users")
@login_required("admin")
def create_user():
    data = body()
    username = text(data.get("username"), "username", 50)
    password = text(data.get("password"), "password", 256)
    role = data.get("role", "user")
    if not 3 <= len(username) <= 50 or len(password) < 8:
        raise APIError("Username must be 3-50 characters; password at least 8")
    if role not in ("admin", "auditor", "user"):
        raise APIError("Invalid role")
    db = get_db()
    with db:
        uid = db.execute(
            "INSERT INTO users(username,password_hash,role,is_active) VALUES(?,?,?,1)",
            (username, generate_password_hash(password), role),
        ).lastrowid
        log(db, g.user["user_id"], "create_user", "user", uid, {"role": role})
    return ok(public_user(db.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()), 201)


@bp.put("/users/<int:user_id>")
@login_required("admin")
def update_user(user_id):
    data = body()
    db = get_db()
    with db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if row is None:
            raise APIError("User not found", 404)
        role = data.get("role", row["role"])
        if role not in ("admin", "auditor", "user"):
            raise APIError("Invalid role")
        if "is_active" in data:
            is_active = data["is_active"]
        elif "disabled" in data:
            is_active = not data["disabled"]
        else:
            is_active = bool(row["is_active"])
        if not isinstance(is_active, bool):
            raise APIError("is_active must be a boolean")
        if row["role"] == "admin" and row["is_active"] and (role != "admin" or not is_active):
            count = db.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
            ).fetchone()[0]
            if count <= 1:
                raise APIError("Cannot disable or demote the last active administrator", 409)
        db.execute(
            "UPDATE users SET role=?,is_active=? WHERE user_id=?",
            (role, int(is_active), user_id),
        )
        if "password" in data:
            password = text(data["password"], "password", 256)
            if len(password) < 8:
                raise APIError("Password too short")
            db.execute(
                "UPDATE users SET password_hash=? WHERE user_id=?",
                (generate_password_hash(password), user_id),
            )
        log(db, g.user["user_id"], "update_user", "user", user_id, {"role": role, "is_active": is_active})
    return ok(public_user(db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()))


@bp.get("/manufacturers")
@login_required()
def manufacturers():
    page, size = pagination()
    db = get_db()
    rows = [
        dict(row)
        for row in db.execute(
            "SELECT * FROM manufacturer ORDER BY name LIMIT ? OFFSET ?",
            (size, (page - 1) * size),
        )
    ]
    return ok(
        {
            "items": rows,
            "total": db.execute("SELECT COUNT(*) FROM manufacturer").fetchone()[0],
            "page": page,
            "page_size": size,
        }
    )


@bp.post("/manufacturers")
@login_required("admin", "auditor")
def create_manufacturer():
    return save_manufacturer()


@bp.put("/manufacturers/<int:manufacturer_id>")
@login_required("admin", "auditor")
def update_manufacturer(manufacturer_id):
    return save_manufacturer(manufacturer_id)


@bp.delete("/manufacturers/<int:manufacturer_id>")
@login_required("admin")
def delete_manufacturer(manufacturer_id):
    confirmed(body())
    db = get_db()
    with db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT * FROM manufacturer WHERE manufacturer_id=?", (manufacturer_id,)
        ).fetchone()
        if row is None:
            raise APIError("Manufacturer not found", 404)
        try:
            db.execute("DELETE FROM manufacturer WHERE manufacturer_id=?", (manufacturer_id,))
        except sqlite3.IntegrityError:
            raise APIError("Manufacturer is referenced by components and cannot be deleted", 409)
        log(db, g.user["user_id"], "delete_manufacturer", "component", manufacturer_id, {"name": row["name"]})
    return ok()


def save_manufacturer(mid=None):
    data = body()
    name = text(data.get("name"), "name", 100)
    short_name = text(data.get("short_name"), "short_name", 50, required=False)
    website = data.get("website")
    if website is not None:
        website = text(website, "website", 500, required=False)
        if website and not website.startswith(("https://", "http://")):
            raise APIError("website must be HTTP(S)")
    db = get_db()
    with db:
        db.execute("BEGIN IMMEDIATE")
        if mid is not None and not db.execute(
            "SELECT 1 FROM manufacturer WHERE manufacturer_id=?", (mid,)
        ).fetchone():
            raise APIError("Manufacturer not found", 404)
        if mid is None:
            mid = db.execute(
                "INSERT INTO manufacturer(name,short_name,website) VALUES(?,?,?)",
                (name, short_name, website),
            ).lastrowid
        else:
            db.execute(
                "UPDATE manufacturer SET name=?,short_name=?,website=? WHERE manufacturer_id=?",
                (name, short_name, website, mid),
            )
        log(db, g.user["user_id"], "save_manufacturer", "component", mid, {"name": name})
    row = db.execute("SELECT * FROM manufacturer WHERE manufacturer_id=?", (mid,)).fetchone()
    return ok(dict(row))


@bp.get("/logs")
@login_required("admin")
def logs():
    page, size = pagination()
    db = get_db()
    items = []
    for row in db.execute(
        "SELECT l.*,u.username FROM operation_log l LEFT JOIN users u ON u.user_id=l.user_id "
        "ORDER BY l.log_id DESC LIMIT ? OFFSET ?",
        (size, (page - 1) * size),
    ):
        item = dict(row)
        try:
            item["detail"] = json.loads(item.pop("detail") or "{}")
        except (TypeError, ValueError):
            item["detail"] = {}
        items.append(item)
    return ok(
        {
            "items": items,
            "total": db.execute("SELECT COUNT(*) FROM operation_log").fetchone()[0],
            "page": page,
            "page_size": size,
        }
    )
