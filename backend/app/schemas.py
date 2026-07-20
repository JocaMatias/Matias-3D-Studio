from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=1000)
    capture_type: str = Field(default="small_object", pattern="^(small_object|medium_object|environment)$")
    project_type: str = Field(default="ai_generation", pattern="^(ai_generation|reality_scan|ai_multiview|hybrid|precision_scan)$")
    category: str = Field(default="generic", pattern="^(generic|product|character|vehicle|architecture|furniture|other)$")
    object_profile: str = Field(default="auto", pattern="^(auto|compact|thin_parts|multi_component|handled_container|mechanical|organic|architecture)$")


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    capture_type: str | None = Field(default=None, pattern="^(small_object|medium_object|environment)$")
    project_type: str | None = Field(default=None, pattern="^(ai_generation|reality_scan|ai_multiview|hybrid|precision_scan)$")
    category: str | None = Field(default=None, pattern="^(generic|product|character|vehicle|architecture|furniture|other)$")
    object_profile: str | None = Field(default=None, pattern="^(auto|compact|thin_parts|multi_component|handled_container|mechanical|organic|architecture)$")


class ProjectOut(ORMModel):
    id: str
    name: str
    description: str
    capture_type: str
    project_type: str
    category: str
    object_profile: str
    status: str
    created_at: datetime
    updated_at: datetime
    image_count: int
    validation_score: int | None
    quality_score: int | None
    primary_version_id: str | None
    primary_version_number: int | None
    current_progress: int | None
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
    is_primary: bool
    consistency_score: float | None
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
    version_id: str | None
    queue_id: str | None
    status: str
    current_stage: str
    progress: int
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    metrics: dict
    stages: list[StageOut]


class VersionOut(ORMModel):
    id: str
    project_id: str
    number: int
    status: str
    engine: str | None
    reconstruction_type: str
    image_ids: list
    primary_image_id: str | None
    configuration: dict
    metrics: dict
    warnings: list
    duration_seconds: float | None
    is_primary: bool
    created_at: datetime
    completed_at: datetime | None


class ArtifactOut(ORMModel):
    id: str
    job_id: str
    version_id: str | None
    artifact_type: str
    filename: str
    mime_type: str
    file_size: int
    artifact_metadata: dict
    created_at: datetime
