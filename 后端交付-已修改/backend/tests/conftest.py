# -*- coding: utf-8 -*-
import sys
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import create_app
from backend.db import get_db


@pytest.fixture()
def app(tmp_path):
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": str(tmp_path / "test.sqlite3"),
            "UPLOAD_DIR": str(tmp_path / "uploads"),
        }
    )
    with application.app_context():
        db = get_db()
        with db:
            for username, role in (("usr1", "user"), ("aud1", "auditor"), ("adm1", "admin")):
                db.execute(
                    "INSERT INTO users(username,password_hash,role,is_active) VALUES(?,?,?,1)",
                    (username, generate_password_hash("Passw0rd!"), role),
                )
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth(client):
    def login(username):
        response = client.post(
            "/api/auth/login", json={"username": username, "password": "Passw0rd!"}
        )
        assert response.status_code == 200, response.get_json()
        return {"Authorization": "Bearer " + response.get_json()["data"]["token"]}

    return login
