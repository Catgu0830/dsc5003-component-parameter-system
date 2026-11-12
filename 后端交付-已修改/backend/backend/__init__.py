import os
import sqlite3
from pathlib import Path

import click
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from itsdangerous import URLSafeTimedSerializer
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash

from .common import APIError, ok
from .db import get_db, init_db, log


def create_app(test_config=None):
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")
    app = Flask(__name__, instance_path=str(root / "instance"))
    app.json.ensure_ascii = False
    instance = Path(app.instance_path)
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "dsc5003-dev-secret-change-me"),
        DATABASE=os.getenv("DATABASE", str(instance / "components.sqlite3")),
        UPLOAD_DIR=str(instance / "uploads"),
        MAX_CONTENT_LENGTH=int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024 * 1024,
        TOKEN_HOURS=int(os.getenv("TOKEN_HOURS", "24")),
        MAX_RETRIES=int(os.getenv("MAX_RETRIES", "3")),
        CORS_ORIGINS=[
            x.strip()
            for x in os.getenv(
                "CORS_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500"
            ).split(",")
            if x.strip()
        ],
        URL_ALLOWED_HOSTS=[
            x.strip() for x in os.getenv("URL_ALLOWED_HOSTS", "").split(",") if x.strip()
        ],
        PDF_EXTRACTION_MODE=os.getenv("PDF_EXTRACTION_MODE", "verbatim"),
        EXTRACTION_MODE=os.getenv("EXTRACTION_MODE", "rules"),
        LLM_API_BASE=os.getenv("LLM_API_BASE", "https://api.openai.com/v1"),
        LLM_API_KEY=os.getenv("LLM_API_KEY", ""),
        LLM_MODEL=os.getenv("LLM_MODEL", ""),
        LLM_TIMEOUT=int(os.getenv("LLM_TIMEOUT", "60")),
    )
    if test_config:
        app.config.update(test_config)
    if app.config["PDF_EXTRACTION_MODE"] not in ("verbatim", "legacy"):
        raise ValueError("Invalid PDF_EXTRACTION_MODE")
    if app.config["EXTRACTION_MODE"] not in ("rules", "llm", "hybrid"):
        raise ValueError("Invalid EXTRACTION_MODE")
    Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)
    init_db(app.config["DATABASE"])
    app.extensions["auth_serializer"] = URLSafeTimedSerializer(
        app.config["SECRET_KEY"], salt="dsc5003-auth"
    )
    app.extensions["login_attempts"] = {}
    app.extensions["revoked_tokens"] = {}

    from .admin import bp as admin
    from .audit import bp as audit
    from .auth import bp as auth
    from .catalog import bp as catalog
    from .components import bp as components
    from .exports import bp as exports
    from .search import bp as search
    from .tasks import bp as tasks

    for blueprint in (auth, catalog, components, tasks, audit, admin, exports, search):
        app.register_blueprint(blueprint)

    @app.teardown_appcontext
    def close_db(error):
        from flask import g

        if "db" in g:
            g.pop("db").close()

    @app.errorhandler(APIError)
    def api_error(error):
        return jsonify(code=error.status, message=error.message, data=error.data), error.status

    @app.errorhandler(sqlite3.IntegrityError)
    def conflict(error):
        return (
            jsonify(
                code=409,
                message="Data conflicts with an existing record or database constraint",
                data=None,
            ),
            409,
        )

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(code=error.code, message=error.description, data=None), error.code

    @app.errorhandler(Exception)
    def unknown(error):
        app.logger.exception("Unhandled API error")
        return jsonify(code=500, message="Internal server error; contact administrator", data=None), 500

    @app.before_request
    def cors_preflight():
        if request.method == "OPTIONS":
            return "", 204

    @app.after_request
    def headers(response):
        origin = request.headers.get("Origin")
        if origin and origin in app.config["CORS_ORIGINS"]:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers.add("Vary", "Origin")
            response.headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health():
        get_db().execute("SELECT 1")
        return ok({"status": "ok", "database": "sqlite", "schema": "11-table", "extraction_mode": app.config["EXTRACTION_MODE"]})

    @app.cli.command("init-db")
    def initialize():
        init_db(app.config["DATABASE"])
        click.echo("Database initialized (existing rows preserved)")

    @app.cli.command("create-user")
    @click.option("--username", prompt=True)
    @click.option("--role", type=click.Choice(["admin", "auditor", "user"]), default="admin")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_user(username, role, password):
        if not username.strip() or not 3 <= len(username) <= 50 or not 8 <= len(password) <= 256:
            raise click.ClickException("Invalid username/password length")
        db = get_db()
        try:
            with db:
                uid = db.execute(
                    "INSERT INTO users(username,password_hash,role,is_active) VALUES(?,?,?,1)",
                    (username.strip(), generate_password_hash(password), role),
                ).lastrowid
                log(db, uid, "cli_create_user", "user", uid)
        except sqlite3.IntegrityError:
            raise click.ClickException("Username already exists")
        click.echo(f"Created {role} user: {username}")

    @app.cli.command("worker")
    @click.option("--once", is_flag=True, help="Process at most one task and exit")
    def worker(once):
        from .worker import process_one, run_worker

        if once:
            click.echo("processed" if process_one(app) else "queue empty")
        else:
            run_worker(app)

    @app.cli.command("backup-db")
    @click.argument("destination", type=click.Path())
    def backup(destination):
        from contextlib import closing

        if Path(destination).resolve() == Path(app.config["DATABASE"]).resolve():
            raise click.ClickException("Backup path must differ from active database")
        if Path(destination).exists():
            raise click.ClickException("Backup destination already exists")
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(destination)) as target:
            get_db().backup(target)
        click.echo(f"Backup saved: {destination}")

    return app
