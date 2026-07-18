from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent if BACKEND_ROOT.name == "backend" else BACKEND_ROOT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'backend' / 'studio.db').as_posix()}"
    storage_root: Path = PROJECT_ROOT / "backend" / "storage"
    frontend_origin: str = "http://localhost:3000"
    reconstruction_mode: str = "colmap"
    queue_mode: str = "thread"
    redis_url: str = "redis://localhost:6379/0"
    queue_name: str = "matias-3d"
    queue_job_timeout_seconds: int = 43200
    meshroom_root: Path = PROJECT_ROOT / "tools" / "Meshroom-2025.1.0"
    meshroom_pipeline: str = "360"
    colmap_root: Path = PROJECT_ROOT / "tools" / "COLMAP-4.0.1"
    openmvs_root: Path = PROJECT_ROOT / "tools" / "OpenMVS-2.4"
    hunyuan_root: Path = PROJECT_ROOT / "tools" / "Hunyuan3D-2"
    hunyuan_python: Path = PROJECT_ROOT / "tools" / "hunyuan-env" / "python.exe"
    hunyuan_model_cache: Path = PROJECT_ROOT / "tools" / "hunyuan-models"
    # u2netp is fast enough for a laptop CPU and preserves small-object masks;
    # the former 178 MB ISNet model could take several minutes per photograph.
    segmentation_model: str = "u2netp"
    enable_object_segmentation: bool = True
    enable_ai_texturing: bool = True
    reconstruction_timeout_hours: float = 8
    max_images: int = 120
    max_image_mb: int = 25
    max_image_pixels: int = 80_000_000
    mock_stage_seconds: float = 1.5


settings = Settings()
