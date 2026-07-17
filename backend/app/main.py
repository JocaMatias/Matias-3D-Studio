import shutil
import uuid
from pathlib import Path
from fastapi import FastAPI, Depends, File, HTTPException, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from .config import settings
from .database import Base, engine, get_db
from .models import Artifact, Project, ProjectImage, ReconstructionJob, ReconstructionStage
from .schemas import ProjectCreate, ProjectPatch, ProjectOut, ImageOut, JobOut, ArtifactOut
from .validation import photogrammetry_trackability, validate_project
from .reconstruction import STAGES, queue_job, reconstruction_engine_status
from .strategy import MINIMUM_AI_IMAGES, RECOMMENDED_AI_IMAGES, capture_metrics, next_capture_suggestion, strategy_for_images

app = FastAPI(title="ImageTo3D Studio API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)


def project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Projeto não encontrado.")
    return project


@app.get("/api/health")
def health():
    return {"status": "ok", "reconstruction": reconstruction_engine_status()}


@app.get("/api/reconstruction/engine")
def reconstruction_engine():
    return reconstruction_engine_status()


@app.post("/api/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    project = Project(**body.model_dump())
    db.add(project); db.commit(); db.refresh(project)
    return project


@app.get("/api/projects", response_model=list[ProjectOut])
def list_projects(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    return db.scalars(select(Project).order_by(Project.updated_at.desc()).offset(skip).limit(limit)).all()


@app.get("/api/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    return project_or_404(db, project_id)


@app.patch("/api/projects/{project_id}", response_model=ProjectOut)
def patch_project(project_id: str, body: ProjectPatch, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    for key, value in body.model_dump(exclude_none=True).items(): setattr(project, key, value)
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
    output = settings.storage_root / project.id / "originals"; thumbs = settings.storage_root / project.id / "thumbnails"
    output.mkdir(parents=True, exist_ok=True); thumbs.mkdir(parents=True, exist_ok=True)
    created = []
    for upload in files:
        if upload.content_type not in {"image/jpeg", "image/png"}: raise HTTPException(415, f"Formato inválido: {upload.filename}")
        data = await upload.read()
        if len(data) > settings.max_image_mb * 1024 * 1024: raise HTTPException(413, f"Ficheiro demasiado grande: {upload.filename}")
        image_id = str(uuid.uuid4()); ext = ".jpg" if upload.content_type == "image/jpeg" else ".png"
        path = output / f"{image_id}{ext}"; path.write_bytes(data)
        try:
            with Image.open(path) as im:
                im.verify()
            with Image.open(path) as im:
                width, height = im.size
                thumb_path = thumbs / f"{image_id}.jpg"
                ImageOps.exif_transpose(im).convert("RGB").thumbnail((480, 360)); im = ImageOps.exif_transpose(im).convert("RGB"); im.thumbnail((480, 360)); im.save(thumb_path, "JPEG", quality=82)
        except Exception:
            path.unlink(missing_ok=True); raise HTTPException(400, f"Imagem corrompida: {upload.filename}")
        item = ProjectImage(id=image_id, project_id=project.id, original_filename=Path(upload.filename or "image").name, storage_path=str(path), thumbnail_path=str(thumb_path), mime_type=upload.content_type, width=width, height=height, file_size=len(data))
        db.add(item); created.append(item)
    project.image_count += len(created); project.status = "uploading"; db.commit()
    return created


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
    db.delete(item); project.image_count = max(0, project.image_count - 1); project.validation_score = None; db.commit()


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
    if usable < MINIMUM_AI_IMAGES:
        messages.append(f"Faltam {MINIMUM_AI_IMAGES - usable} fotografia(s) para ativar a reconstrução por IA.")
    elif usable <= 10:
        messages.append("A reconstrução por IA está disponível; mais ângulos aumentam a confiança geométrica.")
    elif usable < 20:
        messages.append("Boa cobertura para IA multivista; as vistas extra reforçam a seleção da melhor forma.")
    if trackability["level"] == "low" and usable >= MINIMUM_AI_IMAGES:
        messages.append("Objeto liso: adequado para IA multivista, mas pouco fiável para fotogrametria clássica.")
    if project.error_message and "multi-vista" in project.error_message:
        messages.append(project.error_message)
    return {
        "score": project.validation_score,
        "approved": approved,
        "warnings": warnings,
        "rejected": rejected,
        "messages": messages,
        "recommended_images": RECOMMENDED_AI_IMAGES,
        "minimum_images": MINIMUM_AI_IMAGES,
        "real_reconstruction_ready": usable >= MINIMUM_AI_IMAGES,
        "next_capture_suggestion": next_capture_suggestion(usable),
        "photogrammetry_trackability": trackability,
        **capture_metrics(usable, project.validation_score, trackability["level"]),
        "images": [ImageOut.model_validate(item) for item in items],
    }


@app.post("/api/projects/{project_id}/reconstruct", response_model=JobOut, status_code=202)
def reconstruct(project_id: str, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    if project.image_count < 1 or project.validation_score is None: raise HTTPException(409, "Valida as imagens antes de iniciar.")
    engine = reconstruction_engine_status()
    if not engine["available"]:
        raise HTTPException(503, engine["message"])
    usable_images = sum(image.validation_status != "rejected" for image in project.images)
    if engine["real_reconstruction"] and usable_images < MINIMUM_AI_IMAGES:
        raise HTTPException(
            409,
            f"Há {usable_images} imagens utilizáveis. São necessárias pelo menos {MINIMUM_AI_IMAGES}.",
        )
    active = db.scalar(select(ReconstructionJob).where(ReconstructionJob.project_id == project.id, ReconstructionJob.status.in_(["queued", "processing"])))
    if active: raise HTTPException(409, "Já existe uma reconstrução ativa.")
    trackability = photogrammetry_trackability(project.images)
    strategy = strategy_for_images(usable_images, trackability["level"])
    job = ReconstructionJob(
        project_id=project.id,
        configuration={
            "mode": settings.reconstruction_mode,
            "pipeline_version": "adaptive-ai-v2",
            "strategy": strategy.as_dict(),
            "photogrammetry_trackability": trackability,
        },
    )
    db.add(job); db.flush()
    for i, name in enumerate(STAGES, 1): db.add(ReconstructionStage(job_id=job.id, name=name, order=i))
    project.status = "queued"; db.commit()
    job = db.scalar(select(ReconstructionJob).options(selectinload(ReconstructionJob.stages)).where(ReconstructionJob.id == job.id))
    queue_job(job.id)
    return job


@app.post("/api/projects/{project_id}/reconstruct/retry", response_model=JobOut, status_code=202)
def retry(project_id: str, db: Session = Depends(get_db)):
    return reconstruct(project_id, db)


@app.get("/api/projects/{project_id}/job", response_model=JobOut)
def get_job(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    job = db.scalar(select(ReconstructionJob).options(selectinload(ReconstructionJob.stages)).where(ReconstructionJob.project_id == project_id).order_by(ReconstructionJob.started_at.desc()))
    if not job: raise HTTPException(404, "Ainda não existe reconstrução.")
    job.stages.sort(key=lambda x: x.order)
    return job


@app.get("/api/projects/{project_id}/artifacts", response_model=list[ArtifactOut])
def artifacts(project_id: str, db: Session = Depends(get_db)):
    project_or_404(db, project_id)
    return db.scalars(select(Artifact).where(Artifact.project_id == project_id)).all()


@app.get("/api/projects/{project_id}/download/{artifact_id}")
def download(project_id: str, artifact_id: str, inline: bool = False, db: Session = Depends(get_db)):
    artifact = db.get(Artifact, artifact_id)
    if not artifact or artifact.project_id != project_id: raise HTTPException(404, "Artefacto não encontrado.")
    return FileResponse(artifact.storage_path, media_type=artifact.mime_type, filename=None if inline else artifact.filename, content_disposition_type="inline" if inline else "attachment")
