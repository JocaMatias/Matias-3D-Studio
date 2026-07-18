import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, String, Integer, Float, DateTime, ForeignKey, JSON, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    capture_type: Mapped[str] = mapped_column(String(30), default="small_object")
    project_type: Mapped[str] = mapped_column(String(30), default="real_photos")
    category: Mapped[str] = mapped_column(String(40), default="generic")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    validation_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    primary_version_id: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    images = relationship("ProjectImage", cascade="all, delete-orphan")
    jobs = relationship("ReconstructionJob", cascade="all, delete-orphan")
    artifacts = relationship("Artifact", cascade="all, delete-orphan")
    versions = relationship("ReconstructionVersion", cascade="all, delete-orphan")

    @property
    def primary_version_number(self) -> int | None:
        primary = next((version for version in self.versions if version.id == self.primary_version_id), None)
        return primary.number if primary else None

    @property
    def current_progress(self) -> int | None:
        active = [job for job in self.jobs if job.status in {"queued", "processing"}]
        if not active:
            return None
        latest = max(active, key=lambda job: job.created_at or job.started_at or self.created_at)
        return latest.progress


class ProjectImage(Base):
    __tablename__ = "project_images"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    original_filename: Mapped[str] = mapped_column(String)
    storage_path: Mapped[str] = mapped_column(String)
    thumbnail_path: Mapped[str] = mapped_column(String)
    mime_type: Mapped[str] = mapped_column(String)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    file_size: Mapped[int] = mapped_column(Integer)
    blur_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    exposure_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    duplicate_group: Mapped[str | None] = mapped_column(String, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    consistency_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    validation_status: Mapped[str] = mapped_column(String, default="pending")
    validation_messages: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReconstructionJob(Base):
    __tablename__ = "reconstruction_jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    version_id: Mapped[str | None] = mapped_column(ForeignKey("reconstruction_versions.id", ondelete="SET NULL"), nullable=True)
    queue_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="queued")
    current_stage: Mapped[str] = mapped_column(String, default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    logs_path: Mapped[str | None] = mapped_column(String, nullable=True)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    stages = relationship("ReconstructionStage", cascade="all, delete-orphan")


class ReconstructionVersion(Base):
    __tablename__ = "reconstruction_versions"
    __table_args__ = (UniqueConstraint("project_id", "number", name="uq_project_version_number"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="queued")
    engine: Mapped[str | None] = mapped_column(String(60), nullable=True)
    reconstruction_type: Mapped[str] = mapped_column(String(30), default="real_photos")
    image_ids: Mapped[list] = mapped_column(JSON, default=list)
    primary_image_id: Mapped[str | None] = mapped_column(String, nullable=True)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    logs_path: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReconstructionStage(Base):
    __tablename__ = "reconstruction_stages"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("reconstruction_jobs.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String)
    order: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="pending")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message: Mapped[str] = mapped_column(String, default="")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    job_id: Mapped[str] = mapped_column(ForeignKey("reconstruction_jobs.id", ondelete="CASCADE"))
    version_id: Mapped[str | None] = mapped_column(ForeignKey("reconstruction_versions.id", ondelete="SET NULL"), nullable=True)
    artifact_type: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(String)
    storage_path: Mapped[str] = mapped_column(String)
    mime_type: Mapped[str] = mapped_column(String)
    file_size: Mapped[int] = mapped_column(Integer)
    artifact_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
