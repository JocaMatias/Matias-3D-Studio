import io

from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.main import app


client = TestClient(app)


def jpeg_bytes(color: str = "teal") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (920, 920), color).save(output, "JPEG")
    return output.getvalue()


def create_project() -> str:
    response = client.post("/api/projects", json={"name": "Upload seguro", "project_type": "ai_references"})
    assert response.status_code == 201
    return response.json()["id"]


def test_upload_uses_file_signature_and_sanitizes_name():
    with client:
        project_id = create_project()
        response = client.post(
            f"/api/projects/{project_id}/images",
            files=[("files", ("../../referencia.png", jpeg_bytes(), "image/png"))],
        )
        assert response.status_code == 201
        item = response.json()[0]
        assert item["original_filename"] == "referencia.png"
        assert item["mime_type"] == "image/jpeg"
        assert item["is_primary"] is True
        client.delete(f"/api/projects/{project_id}")


def test_corrupt_batch_rolls_back_every_file():
    with client:
        project_id = create_project()
        response = client.post(
            f"/api/projects/{project_id}/images",
            files=[
                ("files", ("valid.jpg", jpeg_bytes(), "image/jpeg")),
                ("files", ("broken.jpg", b"not an image", "image/jpeg")),
            ],
        )
        assert response.status_code == 400
        assert client.get(f"/api/projects/{project_id}/images").json() == []
        assert client.get(f"/api/projects/{project_id}").json()["image_count"] == 0
        client.delete(f"/api/projects/{project_id}")


def test_streaming_limit_rejects_large_payload():
    with client:
        project_id = create_project()
        previous = settings.max_image_mb
        settings.max_image_mb = 1
        try:
            response = client.post(
                f"/api/projects/{project_id}/images",
                files=[("files", ("huge.jpg", b"x" * (1024 * 1024 + 1), "image/jpeg"))],
            )
            assert response.status_code == 413
            assert client.get(f"/api/projects/{project_id}/images").json() == []
        finally:
            settings.max_image_mb = previous
            client.delete(f"/api/projects/{project_id}")
