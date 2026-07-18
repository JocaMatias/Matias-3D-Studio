import io
import time
from PIL import Image
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings


client = TestClient(app)


def image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (800, 800), "teal").save(output, "JPEG")
    return output.getvalue()


def test_vertical_project_flow():
    with client:
        settings.reconstruction_mode = "mock"
        created = client.post("/api/projects", json={"name": "Teste", "capture_type": "small_object"})
        assert created.status_code == 201
        project_id = created.json()["id"]
        upload = client.post(f"/api/projects/{project_id}/images", files=[("files", ("object.jpg", image_bytes(), "image/jpeg"))])
        assert upload.status_code == 201
        report = client.post(f"/api/projects/{project_id}/validate")
        assert report.status_code == 200
        assert 0 <= report.json()["score"] <= 100
        settings.mock_stage_seconds = 0.01
        started = client.post(f"/api/projects/{project_id}/reconstruct")
        assert started.status_code == 202
        for _ in range(150):
            job = client.get(f"/api/projects/{project_id}/job").json()
            if job["status"] == "completed":
                break
            time.sleep(0.02)
        assert job["status"] == "completed"
        assert job["progress"] == 100
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
