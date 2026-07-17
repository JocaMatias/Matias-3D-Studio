from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=1000)
    capture_type: str = Field(default="small_object", pattern="^(small_object|medium_object|environment)$")


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)


class ProjectOut(ORMModel):
    id: str
    name: str
    description: str
    capture_type: str
    status: str
    created_at: datetime
    updated_at: datetime
    image_count: int
    validation_score: int | None
    quality_score: int | None
    error_message: str | None


class ImageOut(ORMModel):
    id: str
    original_filename: str
    mime_type: str
    width: int
    height: int
    file_size: int
    blur_score: float | None
    exposure_score: float | None
    validation_status: str
    validation_messages: list
    created_at: datetime


class StageOut(ORMModel):
    name: str
    order: int
    status: str
    progress: int
    message: str
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None


class JobOut(ORMModel):
    id: str
    status: str
    current_stage: str
    progress: int
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    metrics: dict
    stages: list[StageOut]


class ArtifactOut(ORMModel):
    id: str
    job_id: str
    artifact_type: str
    filename: str
    mime_type: str
    file_size: int
    artifact_metadata: dict
    created_at: datetime
