import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Depends, File, HTTPException, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from .config import settings
from .database import SessionLocal, get_db, migrate_database
from .models import Artifact, Project, ProjectImage, ReconstructionJob, ReconstructionStage, ReconstructionVersion
from .schemas import ProjectCreate, ProjectPatch, ProjectOut, ImageOut, JobOut, ArtifactOut, VersionOut
from .validation import photogrammetry_trackability, validate_project
from .reconstruction import PIPELINE_VERSION, STAGES, _render_model_preview, queue_job, reconstruction_engine_status
from .strategy import (
    capture_metrics,
    minimum_images_for_mode,
    next_capture_suggestion,
    normalize_generation_mode,
    recommended_images_for_mode,
    strategy_for_project,
)
from .uploads import cleanup_orphaned_temporary_uploads, prepare_image_upload, remove_prepared_upload
from .diagnostics import system_diagnostics


API_VERSION = "0.3.0"
GENERATION_MODE_KEYS = ["ai_multiview", "hybrid", "precision_scan"]


def backfill_legacy_versions(*, render_previews: bool = False) -> None:
    """Attach legacy records without delaying API startup on heavy GLB renders."""
    with SessionLocal() as db:
        projects = db.scalars(select(Project)).all()
        changed = False
        for project in projects:
            image_ids = [image.id for image in project.images]
            primary_image = next((image.id for image in project.images if image.is_primary), None)
            next_number = (db.scalar(select(func.max(ReconstructionVersion.number)).where(
                ReconstructionVersion.project_id == project.id,
            )) or 0) + 1
            legacy_jobs = db.scalars(select(ReconstructionJob).where(
                ReconstructionJob.project_id == project.id,
                ReconstructionJob.version_id.is_(None),
            ).order_by(ReconstructionJob.created_at, ReconstructionJob.started_at)).all()
            for job in legacy_jobs:
                configuration = job.configuration or {}
                version = ReconstructionVersion(
                    project_id=project.id,
                    number=next_number,
                    status=job.status,
                    engine=str(configuration.get("engine") or settings.reconstruction_mode),
                    reconstruction_type=project.project_type,
                    image_ids=image_ids,
                    primary_image_id=primary_image,
                    configuration=configuration,
                    metrics=job.metrics or {},
                    warnings=[job.error_message] if job.error_message else [],
                    logs_path=job.logs_path,
                    created_at=job.created_at or job.started_at or project.created_at,
                    completed_at=job.completed_at,
                )
                db.add(version)
                db.flush()
                job.version_id = version.id
                for artifact in db.scalars(select(Artifact).where(Artifact.job_id == job.id)):
                    artifact.version_id = version.id
                next_number += 1
                changed = True

            if not project.primary_version_id:
                primary = db.scalar(select(ReconstructionVersion).where(
                    ReconstructionVersion.project_id == project.id,
                    ReconstructionVersion.status == "completed",
                ).order_by(ReconstructionVersion.number.desc()))
                if primary:
                    primary.is_primary = True
                    project.primary_version_id = primary.id
                    project.status = "completed"
                    project.quality_score = (primary.metrics or {}).get("quality_score", project.quality_score)
                    changed = True

            if not render_previews:
                continue

            glb_artifacts = db.scalars(select(Artifact).where(
                Artifact.project_id == project.id,
                Artifact.artifact_type == "glb",
                Artifact.version_id.is_not(None),
            )).all()
            for glb in glb_artifacts:
                preview = db.scalar(select(Artifact).where(
                    Artifact.version_id == glb.version_id,
                    Artifact.artifact_type == "preview",
                ))
                source = Path(glb.storage_path)
                if not source.is_file() or (
                    preview and (preview.artifact_metadata or {}).get("renderer") == "software-v2"
                ):
                    continue
                preview_path = source.with_name(f"{glb.job_id}-preview.jpg")
                try:
                    _render_model_preview(source, preview_path)
                except Exception:
                    preview_path.unlink(missing_ok=True)
                    continue
                if preview:
                    preview.storage_path = str(preview_path)
                    preview.file_size = preview_path.stat().st_size
                    preview.artifact_metadata = {"renderer": "software-v2", "source": "glb", "backfilled": True}
                else:
                    db.add(Artifact(
                        project_id=project.id,
                        job_id=glb.job_id,
                        version_id=glb.version_id,
                        artifact_type="preview",
                        filename="pre-visualizacao.jpg",
                        storage_path=str(preview_path),
                        mime_type="image/jpeg",
                        file_size=preview_path.stat().st_size,
                        artifact_metadata={"renderer": "software-v2", "source": "glb", "backfilled": True},
                    ))
                changed = True
        if changed:
            db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    cleanup_orphaned_temporary_uploads()
    migrate_database()
    backfill_legacy_versions()
    if settings.queue_mode.lower() == "thread":
        with SessionLocal() as db:
            interrupted = db.scalars(select(ReconstructionJob).where(ReconstructionJob.status.in_(["queued", "processing"]))).all()
            for job in interrupted:
                job.status = "failed"
                job.error_message = "O processo local foi interrompido. Podes repetir esta versão em segurança."
                project = db.get(Project, job.project_id)
                version = db.get(ReconstructionVersion, job.version_id) if job.version_id else None
                if project:
                    project.status = "completed" if project.primary_version_id else "ready"
                if version:
                    version.status = "failed"
                    version.warnings = [job.error_message]
            db.commit()
    yield

app = FastAPI(title="Matias 3D Studio API", version=API_VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Projeto não encontrado.")
    return project


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "api_version": API_VERSION,
        "generation_modes": GENERATION_MODE_KEYS,
        "queue_mode": settings.queue_mode,
        "reconstruction": reconstruction_engine_status(),
    }


@app.get("/api/system/diagnostics")
def diagnostics():
    return system_diagnostics()


@app.get("/api/reconstruction/engine")
def reconstruction_engine():
    return reconstruction_engine_status()


@app.post("/api/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    values = body.model_dump()
    values["project_type"] = normalize_generation_mode(values["project_type"])
    project = Project(**values)
    db.add(project); db.commit(); db.refresh(project)
    return project


@app.get("/api/projects", response_model=list[ProjectOut])
def list_projects(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    return db.scalars(select(Project).order_by(Project.updated_at.desc()).offset(skip).limit(limit)).all()


@app.get("/api/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    return project_or_404(db, project_id)


@app.get("/api/projects/{project_id}/preview")
def project_preview(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    preview_query = select(Artifact).where(
        Artifact.project_id == project_id,
        Artifact.artifact_type == "preview",
    )
    if project.primary_version_id:
        preview_query = preview_query.where(Artifact.version_id == project.primary_version_id)
    preview = db.scalar(preview_query.order_by(Artifact.created_at.desc()))
    if preview and Path(preview.storage_path).is_file():
        return FileResponse(preview.storage_path, media_type=preview.mime_type)
    image = db.scalar(select(ProjectImage).where(
        ProjectImage.project_id == project_id,
        ProjectImage.is_primary.is_(True),
    )) or db.scalar(select(ProjectImage).where(ProjectImage.project_id == project_id).order_by(ProjectImage.created_at))
    if not image or not Path(image.thumbnail_path).is_file():
        raise HTTPException(404, "Este projeto ainda não tem pré-visualização.")
    return FileResponse(image.thumbnail_path, media_type="image/jpeg")


@app.patch("/api/projects/{project_id}", response_model=ProjectOut)
def patch_project(project_id: str, body: ProjectPatch, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(project, key, normalize_generation_mode(value) if key == "project_type" else value)
    db.commit(); return project


@app.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    shutil.rmtree(settings.storage_root / project.id, ignore_errors=True)
    db.delete(project); db.commit()


@app.post("/api/projects/{project_id}/images", response_model=list[ImageOut], status_code=201)
async def upload_images(project_id: str, files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    if project.image_count + len(files) > settings.max_images: raise HTTPException(400, f"Limite de {settings.max_images} imagens excedido.")
    prepared = []
    created = []
    has_primary = any(image.is_primary for image in project.images)
    try:
        for upload in files:
            stored = await prepare_image_upload(project.id, upload)
            prepared.append(stored)
            item = ProjectImage(
                id=stored.image_id,
                project_id=project.id,
                original_filename=stored.original_filename,
                storage_path=str(stored.storage_path),
                thumbnail_path=str(stored.thumbnail_path),
                mime_type=stored.mime_type,
                width=stored.width,
                height=stored.height,
                file_size=stored.file_size,
                is_primary=not has_primary and not created,
            )
            db.add(item)
            created.append(item)
        project.image_count += len(created)
        project.status = "uploading"
        project.validation_score = None
        db.commit()
        return created
    except Exception:
        db.rollback()
        for item in prepared:
            remove_prepared_upload(item)
        raise


@app.get("/api/projects/{project_id}/images", response_model=list[ImageOut])
def list_images(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    return db.scalars(select(ProjectImage).where(ProjectImage.project_id == project_id).order_by(ProjectImage.created_at)).all()


@app.get("/api/projects/{project_id}/images/{image_id}/thumbnail")
def image_thumbnail(project_id: str, image_id: str, db: Session = Depends(get_db)):
    item = db.get(ProjectImage, image_id)
    if not item or item.project_id != project_id: raise HTTPException(404, "Imagem não encontrada.")
    return FileResponse(item.thumbnail_path, media_type="image/jpeg")


@app.delete("/api/projects/{project_id}/images/{image_id}", status_code=204)
def delete_image(project_id: str, image_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id); item = db.get(ProjectImage, image_id)
    if not item or item.project_id != project_id: raise HTTPException(404, "Imagem não encontrada.")
    Path(item.storage_path).unlink(missing_ok=True); Path(item.thumbnail_path).unlink(missing_ok=True)
    was_primary = item.is_primary
    db.delete(item); project.image_count = max(0, project.image_count - 1); project.validation_score = None
    if was_primary:
        replacement = db.scalar(select(ProjectImage).where(ProjectImage.project_id == project.id, ProjectImage.id != image_id).order_by(ProjectImage.created_at))
        if replacement:
            replacement.is_primary = True
    db.commit()


@app.post("/api/projects/{project_id}/images/{image_id}/primary", response_model=ImageOut)
def set_primary_image(project_id: str, image_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    item = db.get(ProjectImage, image_id)
    if not item or item.project_id != project_id:
        raise HTTPException(404, "Imagem não encontrada.")
    for image in db.scalars(select(ProjectImage).where(ProjectImage.project_id == project_id)):
        image.is_primary = image.id == image_id
    db.commit()
    return item


@app.post("/api/projects/{project_id}/validate")
def validate(project_id: str, db: Session = Depends(get_db)):
    return validate_project(db, project_or_404(db, project_id))


@app.get("/api/projects/{project_id}/validation")
def validation_report(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    items = db.scalars(select(ProjectImage).where(ProjectImage.project_id == project_id)).all()
    approved = sum(item.validation_status == "approved" for item in items)
    warnings = sum(item.validation_status == "warning" for item in items)
    rejected = sum(item.validation_status == "rejected" for item in items)
    usable = approved + warnings
    trackability = photogrammetry_trackability(items)
    messages = []
    minimum_images = minimum_images_for_mode(project.project_type)
    if usable < minimum_images:
        messages.append(f"Faltam {minimum_images - usable} imagem(ns) para ativar o modo escolhido.")
    elif normalize_generation_mode(project.project_type) == "ai_multiview":
        messages.append("IA Multivista disponível; superfícies não observadas serão inferidas.")
    elif normalize_generation_mode(project.project_type) == "hybrid":
        messages.append("Reconstrução híbrida disponível; vistas adicionais reduzem zonas inferidas.")
    else:
        messages.append("Digitalização precisa disponível; todas as vistas serão usadas no alinhamento.")
    if trackability["level"] == "low" and usable >= minimum_images:
        messages.append("Objeto liso: a IA mantém um fallback caso a fotogrametria não alinhe câmaras suficientes.")
    if project.error_message and "multi-vista" in project.error_message:
        messages.append(project.error_message)
    consistency_values = [image.consistency_score for image in items if image.consistency_score is not None and image.validation_status != "rejected"]
    technical_score = round((approved + warnings * 0.72) / max(1, len(items)) * 100)
    return {
        "score": project.validation_score,
        "capture_preparation_score": project.validation_score,
        "input_quality_score": technical_score,
        "structural_consistency_estimate": round(sum(consistency_values) / len(consistency_values)) if consistency_values else 0,
        "view_diversity_estimate": min(100, round(usable / 10 * 100)),
        "approved": approved,
        "warnings": warnings,
        "rejected": rejected,
        "messages": messages,
        "recommended_images": recommended_images_for_mode(project.project_type),
        "minimum_images": minimum_images_for_mode(project.project_type),
        "real_reconstruction_ready": usable >= minimum_images_for_mode(project.project_type),
        "next_capture_suggestion": next_capture_suggestion(usable),
        "photogrammetry_trackability": trackability,
        **capture_metrics(usable, project.validation_score, trackability["level"], project.project_type),
        "images": [ImageOut.model_validate(item) for item in items],
    }


@app.post("/api/projects/{project_id}/reconstruct", response_model=JobOut, status_code=202)
def reconstruct(
    project_id: str,
    quality_profile: str = Query("standard", pattern="^(preview|standard|high)$"),
    db: Session = Depends(get_db),
):
    project = project_or_404(db, project_id)
    if project.image_count < 1 or project.validation_score is None: raise HTTPException(409, "Valida as imagens antes de iniciar.")
    engine = reconstruction_engine_status()
    if not engine["available"]:
        raise HTTPException(503, engine["message"])
    usable_images = sum(image.validation_status != "rejected" for image in project.images)
    minimum_images = minimum_images_for_mode(project.project_type)
    if usable_images < minimum_images:
        raise HTTPException(
            409,
            f"Há {usable_images} imagens utilizáveis. São necessárias pelo menos {minimum_images} para este modo.",
        )
    active = db.scalar(select(ReconstructionJob).where(ReconstructionJob.project_id == project.id, ReconstructionJob.status.in_(["queued", "processing"])))
    if active: raise HTTPException(409, "Já existe uma reconstrução ativa.")
    trackability = photogrammetry_trackability(project.images)
    strategy = strategy_for_project(project.project_type, usable_images, trackability["level"])
    image_ids = [image.id for image in project.images if image.validation_status != "rejected"]
    primary_image = next((image for image in project.images if image.is_primary), None)
    version_number = (db.scalar(select(func.max(ReconstructionVersion.number)).where(ReconstructionVersion.project_id == project.id)) or 0) + 1
    profile_settings = {
        "preview": {"target_faces": 25000, "label": "Pré-visualização rápida"},
        "standard": {"target_faces": 60000, "label": "Equilibrado"},
        "high": {"target_faces": 120000, "label": "Alta qualidade"},
    }[quality_profile]
    configuration = {
        "mode": settings.reconstruction_mode,
        "pipeline_version": PIPELINE_VERSION,
        "strategy": strategy.as_dict(),
        "photogrammetry_trackability": trackability,
        "project_type": project.project_type,
        "category": project.category,
        "quality_profile": quality_profile,
        **profile_settings,
    }
    version = ReconstructionVersion(
        project_id=project.id,
        number=version_number,
        reconstruction_type=project.project_type,
        image_ids=image_ids,
        primary_image_id=primary_image.id if primary_image else None,
        configuration=configuration,
    )
    db.add(version)
    db.flush()
    job = ReconstructionJob(
        project_id=project.id,
        version_id=version.id,
        configuration=configuration,
    )
    db.add(job); db.flush()
    for i, name in enumerate(STAGES, 1): db.add(ReconstructionStage(job_id=job.id, name=name, order=i))
    project.status = "queued"; db.commit()
    job = db.scalar(select(ReconstructionJob).options(selectinload(ReconstructionJob.stages)).where(ReconstructionJob.id == job.id))
    queue_job(job.id)
    if settings.queue_mode.lower() == "inline":
        db.expire_all()
        job = db.scalar(
            select(ReconstructionJob)
            .options(selectinload(ReconstructionJob.stages))
            .where(ReconstructionJob.id == job.id)
        )
        job.stages.sort(key=lambda stage: stage.order)
    return job


@app.post("/api/projects/{project_id}/reconstruct/retry", response_model=JobOut, status_code=202)
def retry(project_id: str, db: Session = Depends(get_db)):
    return reconstruct(project_id, "standard", db)


@app.get("/api/projects/{project_id}/job", response_model=JobOut)
def get_job(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    job = db.scalar(select(ReconstructionJob).options(selectinload(ReconstructionJob.stages)).where(ReconstructionJob.project_id == project_id).order_by(ReconstructionJob.created_at.desc(), ReconstructionJob.started_at.desc()))
    if not job: raise HTTPException(404, "Ainda não existe reconstrução.")
    job.stages.sort(key=lambda x: x.order)
    return job


@app.post("/api/projects/{project_id}/job/cancel", response_model=JobOut)
def cancel_job(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    job = db.scalar(select(ReconstructionJob).options(selectinload(ReconstructionJob.stages)).where(
        ReconstructionJob.project_id == project_id,
        ReconstructionJob.status.in_(["queued", "processing"]),
    ).order_by(ReconstructionJob.created_at.desc()))
    if not job:
        raise HTTPException(409, "Não existe uma reconstrução ativa.")
    job.status = "cancelled"
    project.status = "completed" if project.primary_version_id else "ready"
    version = db.get(ReconstructionVersion, job.version_id) if job.version_id else None
    if version:
        version.status = "cancelled"
    db.commit()
    return job


@app.get("/api/projects/{project_id}/versions", response_model=list[VersionOut])
def list_versions(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    return db.scalars(select(ReconstructionVersion).where(ReconstructionVersion.project_id == project_id).order_by(ReconstructionVersion.number.desc())).all()


@app.get("/api/projects/{project_id}/versions/{version_id}", response_model=VersionOut)
def get_version(project_id: str, version_id: str, db: Session = Depends(get_db)):
    version = db.get(ReconstructionVersion, version_id)
    if not version or version.project_id != project_id:
        raise HTTPException(404, "Versão não encontrada.")
    return version


@app.post("/api/projects/{project_id}/versions/{version_id}/primary", response_model=VersionOut)
def set_primary_version(project_id: str, version_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    version = db.get(ReconstructionVersion, version_id)
    if not version or version.project_id != project_id or version.status != "completed":
        raise HTTPException(409, "Só uma versão concluída pode ser definida como principal.")
    for candidate in db.scalars(select(ReconstructionVersion).where(ReconstructionVersion.project_id == project_id)):
        candidate.is_primary = candidate.id == version_id
    project.primary_version_id = version_id
    project.quality_score = version.metrics.get("quality_score")
    db.commit()
    return version


@app.get("/api/projects/{project_id}/versions/compare/{left_id}/{right_id}")
def compare_versions(project_id: str, left_id: str, right_id: str, db: Session = Depends(get_db)):
    versions = db.scalars(select(ReconstructionVersion).where(
        ReconstructionVersion.project_id == project_id,
        ReconstructionVersion.id.in_([left_id, right_id]),
    )).all()
    if len(versions) != 2:
        raise HTTPException(404, "Uma das versões não foi encontrada.")
    by_id = {version.id: VersionOut.model_validate(version) for version in versions}
    return {"left": by_id[left_id], "right": by_id[right_id]}


@app.get("/api/projects/{project_id}/artifacts", response_model=list[ArtifactOut])
def artifacts(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    return db.scalars(select(Artifact).where(Artifact.project_id == project_id)).all()


@app.get("/api/projects/{project_id}/download/{artifact_id}")
def download(project_id: str, artifact_id: str, inline: bool = False, db: Session = Depends(get_db)):
    artifact = db.get(Artifact, artifact_id)
    if not artifact or artifact.project_id != project_id: raise HTTPException(404, "Artefacto não encontrado.")
    return FileResponse(artifact.storage_path, media_type=artifact.mime_type, filename=None if inline else artifact.filename, content_disposition_type="inline" if inline else "attachment")
