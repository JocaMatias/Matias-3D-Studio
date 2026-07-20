import io
from PIL import Image
from fastapi.testclient import TestClient
import pytest
from app.main import app

client = TestClient(app)


def image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (800, 800), "teal").save(output, "JPEG")
    return output.getvalue()


def test_health_contract_identifies_the_current_desktop_api():
    with client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["api_version"] == "0.4.0"
        assert health.json()["generation_modes"] == ["ai_generation", "reality_scan"]


def test_vertical_project_flow():
    with client:
        created = client.post(
            "/api/projects",
            json={"name": "Teste", "capture_type": "small_object", "project_type": "ai_generation"},
        )
        assert created.status_code == 201
        project_id = created.json()["id"]
        upload = client.post(f"/api/projects/{project_id}/images", files=[("files", ("object.jpg", image_bytes(), "image/jpeg"))])
        assert upload.status_code == 201
        report = client.post(f"/api/projects/{project_id}/validate")
        assert report.status_code == 200
        assert 0 <= report.json()["score"] <= 100
        started = client.post(f"/api/projects/{project_id}/reconstruct")
        assert started.status_code == 202
        # QUEUE_MODE=inline executes the complete job inside the request. This
        # makes a stuck `processing` state a deterministic regression failure.
        job = started.json()
        assert job["status"] == "completed"
        assert job["progress"] == 100
        assert job["queue_id"].startswith("inline:")
        artifacts = client.get(f"/api/projects/{project_id}/artifacts").json()
        glb = next(artifact for artifact in artifacts if artifact["artifact_type"] == "glb")
        assert any(artifact["artifact_type"] == "preview" for artifact in artifacts)
        versions = client.get(f"/api/projects/{project_id}/versions").json()
        assert len(versions) == 1
        assert versions[0]["status"] == "completed"
        assert glb["version_id"] == versions[0]["id"]
        project = client.get(f"/api/projects/{project_id}").json()
        assert project["primary_version_number"] == 1
        preview = client.get(f"/api/projects/{project_id}/preview")
        assert preview.status_code == 200
        assert preview.headers["content-type"].startswith("image/jpeg")
        client.delete(f"/api/projects/{project_id}")


def test_reality_scan_minimum_is_enforced_in_inline_test_queue():
    with client:
        created = client.post(
            "/api/projects",
            json={"name": "Scan incompleto", "capture_type": "small_object", "project_type": "reality_scan"},
        )
        assert created.status_code == 201
        project_id = created.json()["id"]
        upload = client.post(
            f"/api/projects/{project_id}/images",
            files=[("files", ("object.jpg", image_bytes(), "image/jpeg"))],
        )
        assert upload.status_code == 201
        assert client.post(f"/api/projects/{project_id}/validate").status_code == 200
        started = client.post(f"/api/projects/{project_id}/reconstruct")
        assert started.status_code == 409
        assert "pelo menos 20" in started.json()["detail"]
        client.delete(f"/api/projects/{project_id}")
