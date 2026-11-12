# -*- coding: utf-8 -*-
import io


def _manual(client, headers, model="T-1", tolerance="150"):
    return client.post(
        "/api/tasks",
        headers=headers,
        json={
            "source_type": "manual",
            "component": {
                "model": model,
                "manufacturer": "Test",
                "category": "电阻",
                "parameters": [
                    {"name": "Resistance", "value": "10", "unit": "kΩ"},
                    {"name": "Tolerance", "value": tolerance, "unit": "%"},
                ],
            },
        },
    )


def test_multi_row_csv_creates_one_task_per_component(client, auth):
    headers = auth("usr1")
    auditor = auth("aud1")
    csv_data = (
        "model,manufacturer,category,package,Resistance,Resistance_unit,Tolerance,Tolerance_unit\n"
        "BATCH-R1,Test,电阻,0603,10k,Ω,1,%\n"
        "BATCH-C1,Test,电容,0603,,,10,%\n"
    )
    response = client.post(
        "/api/tasks/upload",
        headers=headers,
        data={"file": (io.BytesIO(csv_data.encode("utf-8")), "batch.csv")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 201, response.get_json()
    data = response.get_json()["data"]
    assert data["count"] == 2
    assert len(data["tasks"]) == 2

    pending = client.get("/api/audit/params", headers=auditor)
    assert pending.status_code == 200
    assert pending.get_json()["data"]["total"] >= 2
    first = pending.get_json()["data"]["items"][0]
    assert first["model"] == "BATCH-R1"
    assert first["source_location"] == "batch.csv"


def test_warnings_and_owner_task_delete(client, auth):
    headers = auth("usr1")
    response = _manual(client, headers)
    assert response.status_code == 202, response.get_json()
    task = response.get_json()["data"]
    assert any("Tolerance" in warning for warning in task["warnings"])

    detail = client.get(f"/api/tasks/{task['task_id']}", headers=headers)
    assert detail.get_json()["data"]["warnings"] == task["warnings"]

    deleted = client.delete(
        f"/api/tasks/{task['task_id']}", headers=headers, json={"confirm": True}
    )
    assert deleted.status_code == 200
    assert client.get(f"/api/tasks/{task['task_id']}", headers=headers).status_code == 404


def test_audited_task_and_referenced_manufacturer_cannot_be_deleted(client, auth):
    user = auth("usr1")
    auditor = auth("aud1")
    admin = auth("adm1")

    response = _manual(client, user, model="T-2")
    task_id = response.get_json()["data"]["task_id"]
    detail = client.get(f"/api/audit/tasks/{task_id}", headers=auditor).get_json()["data"]
    parameter = detail["result"]["components"][0]["parameters"][0]
    approved = client.post(
        f"/api/audit/params/{parameter['extraction_param_id']}",
        headers=auditor,
        json={
            "action": "approve",
            "parameter_id": 1,
            "raw_value": "10kΩ",
            "value_num": 10000,
            "unit": "Ω",
        },
    )
    assert approved.status_code == 200
    deleted = client.delete(
        f"/api/tasks/{task_id}", headers=user, json={"confirm": True}
    )
    assert deleted.status_code == 409

    created = client.post(
        "/api/components",
        headers=admin,
        json={"model": "M-1", "manufacturer": "M1", "category": "集成电路"},
    )
    manufacturer_id = created.get_json()["data"]["manufacturer_id"]
    blocked = client.delete(
        f"/api/manufacturers/{manufacturer_id}", headers=admin, json={"confirm": True}
    )
    assert blocked.status_code == 409

    free = client.post("/api/manufacturers", headers=admin, json={"name": "M2"})
    free_id = free.get_json()["data"]["manufacturer_id"]
    removed = client.delete(
        f"/api/manufacturers/{free_id}", headers=admin, json={"confirm": True}
    )
    assert removed.status_code == 200
