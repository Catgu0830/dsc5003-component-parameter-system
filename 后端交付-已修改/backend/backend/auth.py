"""Authentication with stateless signed tokens (the 11-table schema has no tokens table)."""
import hashlib
import time
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, current_app, g, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from .common import APIError, body, ok, text
from .db import get_db, log, utc_now

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def serializer():
    return current_app.extensions["auth_serializer"]


def public_user(row):
    return {
        key: row[key]
        for key in ("user_id", "username", "role", "is_active", "created_time", "last_login_time")
    }


def login_required(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer ") or len(header) > 500:
                raise APIError("Bearer token required", 401)
            token = header[7:]
            token_hash = hash_token(token)
            revoked = current_app.extensions.setdefault("revoked_tokens", {})
            if revoked.get(token_hash, 0) > time.time():
                raise APIError("Token has been revoked", 401)
            try:
                payload = serializer().loads(
                    token, max_age=current_app.config["TOKEN_HOURS"] * 3600
                )
            except SignatureExpired:
                raise APIError("Token expired", 401)
            except BadSignature:
                raise APIError("Token invalid", 401)
            user = get_db().execute(
                "SELECT * FROM users WHERE user_id=? AND is_active=1", (payload.get("uid"),)
            ).fetchone()
            if user is None:
                raise APIError("Token invalid or account disabled", 401)
            g.user, g.token_hash = user, token_hash
            if roles and user["role"] not in roles:
                raise APIError("Insufficient role", 403)
            return fn(*args, **kwargs)

        return wrapped

    return decorator


@bp.post("/register")
def register():
    data = body()
    username = text(data.get("username"), "username", 50)
    password = text(data.get("password"), "password", 256)
    if not 3 <= len(username) <= 50:
        raise APIError("Username must contain 3-50 characters")
    if len(password) < 8:
        raise APIError("Password must contain at least 8 characters")
    if data.get("role", "user") != "user":
        raise APIError("Public registration cannot assign privileged roles", 403)
    db = get_db()
    with db:
        cursor = db.execute(
            "INSERT INTO users(username,password_hash,role,is_active) VALUES(?,?, 'user',1)",
            (username, generate_password_hash(password)),
        )
        log(db, cursor.lastrowid, "register", "auth", cursor.lastrowid, ip=request.remote_addr)
    return ok(public_user(db.execute("SELECT * FROM users WHERE user_id=?", (cursor.lastrowid,)).fetchone()), 201)


@bp.post("/login")
def login():
    data = body()
    username = text(data.get("username"), "username", 50)
    password = text(data.get("password"), "password", 256)
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    key = (request.remote_addr or "", username.casefold())
    state = current_app.extensions["login_attempts"]
    now = time.monotonic()
    recent = [t for t in state.get(key, []) if now - t < 300]
    if len(recent) >= 10:
        raise APIError("Too many login attempts; try again in 5 minutes", 429)
    if user is None or not user["is_active"] or not check_password_hash(user["password_hash"], password):
        if len(state) > 10000:
            state.clear()
        state[key] = recent + [now]
        raise APIError("Invalid username or password", 401)
    state.pop(key, None)
    token = serializer().dumps({"uid": user["user_id"]})
    expires = (datetime.now(timezone.utc) + timedelta(hours=current_app.config["TOKEN_HOURS"])).isoformat(
        timespec="seconds"
    )
    with db:
        db.execute("UPDATE users SET last_login_time=? WHERE user_id=?", (utc_now(), user["user_id"]))
        log(db, user["user_id"], "login", "auth", user["user_id"], ip=request.remote_addr)
    return ok(
        {
            "token": token,
            "token_type": "Bearer",
            "expires_at": expires,
            "user": public_user(db.execute("SELECT * FROM users WHERE user_id=?", (user["user_id"],)).fetchone()),
        }
    )


@bp.get("/me")
@login_required()
def me():
    return ok(public_user(g.user))


@bp.post("/logout")
@login_required()
def logout():
    db = get_db()
    revoked = current_app.extensions.setdefault("revoked_tokens", {})
    revoked[g.token_hash] = time.time() + current_app.config["TOKEN_HOURS"] * 3600
    # Drop expired revocation entries so the in-memory map cannot grow forever.
    now = time.time()
    for token_hash, expiry in list(revoked.items()):
        if expiry <= now:
            revoked.pop(token_hash, None)
    with db:
        log(db, g.user["user_id"], "logout", "auth", g.user["user_id"], ip=request.remote_addr)
    return ok()
