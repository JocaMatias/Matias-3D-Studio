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
        for _ in range(50):
            job = client.get(f"/api/projects/{project_id}/job").json()
            if job["status"] == "completed":
                break
            time.sleep(0.02)
        assert job["status"] == "completed"
        assert job["progress"] == 100
        artifacts = client.get(f"/api/projects/{project_id}/artifacts").json()
        assert artifacts[0]["artifact_type"] == "glb"
