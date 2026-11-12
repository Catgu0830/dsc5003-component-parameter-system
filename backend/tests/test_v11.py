# -*- coding: utf-8 -*-


def test_health_and_catalog(client, auth):
    headers = auth("usr1")
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.get_json()["data"]["schema"] == "11-table"

    categories = client.get("/api/categories", headers=headers)
    assert categories.status_code == 200
    assert len(categories.get_json()["data"]["items"]) == 10

    parameters = client.get("/api/parameters", headers=headers)
    assert parameters.status_code == 200
    assert len(parameters.get_json()["data"]["items"]) == 17


def test_manual_task_and_parameter_level_review(client, auth):
    user = auth("usr1")
    auditor = auth("aud1")

    response = client.post(
        "/api/tasks",
        headers=user,
        json={
            "source_type": "manual",
            "component": {
                "model": "RC0603FR-0710KL",
                "manufacturer": "Yageo",
                "category": "电阻",
                "package": "0603",
                "parameters": [
                    {"name": "Resistance", "value": "10k", "unit": "Ω"},
                    {"name": "Tolerance", "value": "1", "unit": "%"},
                    {"name": "Power", "value": "0.1", "unit": "W"},
                ],
            },
        },
    )
    assert response.status_code == 202, response.get_json()
    task = response.get_json()["data"]
    task_id = task["task_id"]
    assert task["status"] == "success"
    assert task["review_state"] == "pending"

    detail = client.get(f"/api/audit/tasks/{task_id}", headers=auditor)
    assert detail.status_code == 200
    parameters = detail.get_json()["data"]["result"]["components"][0]["parameters"]
    assert len(parameters) == 3

    approved = client.post(
        f"/api/audit/params/{parameters[0]['extraction_param_id']}",
        headers=auditor,
        json={
            "action": "approve",
            "parameter_id": 1,
            "raw_value": "10kΩ",
            "value_num": 10000,
            "unit": "Ω",
        },
    )
    assert approved.status_code == 200, approved.get_json()

    rejected = client.post(
        f"/api/audit/params/{parameters[1]['extraction_param_id']}",
        headers=auditor,
        json={"action": "reject", "comment": "wrong tolerance"},
    )
    assert rejected.status_code == 200, rejected.get_json()

    task_after = client.get(f"/api/tasks/{task_id}", headers=user).get_json()["data"]
    assert task_after["review_state"] == "partial"
    assert task_after["approved_count"] == 1
    assert task_after["rejected_count"] == 1
    assert task_after["pending_count"] == 1

    components = client.get("/api/components?keyword=RC0603", headers=user)
    assert components.status_code == 200
    item = components.get_json()["data"]["items"][0]
    assert item["package"] == "0603"
    assert [p["canonical_name"] for p in item["parameters"]] == ["Resistance"]
    assert item["parameters"][0]["value_num"] == 10000


def test_rejection_requires_comment(client, auth):
    user = auth("usr1")
    auditor = auth("aud1")
    response = client.post(
        "/api/tasks",
        headers=user,
        json={
            "source_type": "manual",
            "component": {
                "model": "T1",
                "manufacturer": "Test",
                "category": "集成电路",
                "parameters": [{"name": "Voltage", "value": "3.3", "unit": "V"}],
            },
        },
    )
    task_id = response.get_json()["data"]["task_id"]
    detail = client.get(f"/api/audit/tasks/{task_id}", headers=auditor).get_json()["data"]
    parameter_id = detail["result"]["components"][0]["parameters"][0]["extraction_param_id"]
    rejected = client.post(
        f"/api/audit/params/{parameter_id}",
        headers=auditor,
        json={"action": "reject"},
    )
    assert rejected.status_code == 400
