import json
import hashlib
import os
import queue
import shutil
import struct
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from .config import PROJECT_ROOT, settings
from .database import SessionLocal
from .models import Artifact, Project, ReconstructionJob
from .strategy import MINIMUM_AI_IMAGES, capture_metrics, strategy_for_images
from .validation import photogrammetry_trackability

STAGES = [
    "Preparar imagens",
    "Encontrar correspondências",
    "Calcular câmaras",
    "Criar nuvem de pontos",
    "Criar mesh",
    "Aplicar texturas",
    "Exportar GLB",
]


def _now():
    return datetime.now(timezone.utc)


def _resolved_meshroom_root() -> Path:
    root = settings.meshroom_root
    return root if root.is_absolute() else PROJECT_ROOT / root


def _find_meshroom_executable() -> Path | None:
    root = _resolved_meshroom_root()
    direct = [
        root / "meshroom_batch.exe",
        root / "meshroom_batch",
        root / "Meshroom_batch.exe",
    ]
    for candidate in direct:
        if candidate.is_file():
            return candidate
    if root.is_dir():
        for name in ("meshroom_batch.exe", "meshroom_batch"):
            found = next(root.rglob(name), None)
            if found:
                return found
    return None


def _find_meshroom_pipeline() -> Path | None:
    root = _resolved_meshroom_root()
    if not root.is_dir():
        return None
    pipelines = list(root.rglob("*.mg"))
    requested = settings.meshroom_pipeline.lower()

    def rank(path: Path) -> tuple[int, int]:
        name = path.stem.lower().replace("_", " ").replace("-", " ")
        if requested == "360":
            priority = 5 if "360" in name and "object" in name else 0
        elif requested == "turntable":
            priority = 5 if "turntable" in name else 0
        else:
            priority = 5 if requested in name else 0
        if not priority and "object" in name and "reconstruction" in name:
            priority = 4
        if not priority and "photogrammetry" in name:
            priority = 2
        return priority, -len(str(path))

    candidates = sorted(pipelines, key=rank, reverse=True)
    return candidates[0] if candidates and rank(candidates[0])[0] else None


def _resolved_tool_root(root: Path) -> Path:
    return root if root.is_absolute() else PROJECT_ROOT / root


def _stored_file(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or path.exists():
        return path
    legacy = PROJECT_ROOT / "backend" / path
    return legacy if legacy.exists() else path


def _find_colmap_executable() -> Path | None:
    root = _resolved_tool_root(settings.colmap_root)
    for candidate in (root / "bin" / "colmap.exe", root / "colmap.exe"):
        if candidate.is_file():
            return candidate
    system = shutil.which("colmap")
    return Path(system) if system else None


def _find_openmvs_executable(name: str) -> Path | None:
    root = _resolved_tool_root(settings.openmvs_root)
    direct = root / "vc17" / "x64" / "Release" / f"{name}.exe"
    if direct.is_file():
        return direct
    return next(root.rglob(f"{name}.exe"), None) if root.is_dir() else None


def _find_hunyuan_runtime() -> tuple[Path | None, Path | None]:
    python = _resolved_tool_root(settings.hunyuan_python)
    root = _resolved_tool_root(settings.hunyuan_root)
    generator = PROJECT_ROOT / "scripts" / "hunyuan_generate.py"
    if not python.is_file() or not root.is_dir() or not generator.is_file():
        return None, None
    return python, generator


def reconstruction_engine_status() -> dict:
    mode = settings.reconstruction_mode.lower()
    if mode == "mock":
        return {
            "mode": mode,
            "available": True,
            "real_reconstruction": False,
            "message": "Modo de demonstração; não reconstrói a geometria das fotografias.",
        }
    if mode == "meshroom":
        executable = _find_meshroom_executable()
        pipeline = _find_meshroom_pipeline()
        available = executable is not None and pipeline is not None
        return {
            "mode": mode,
            "available": available,
            "real_reconstruction": True,
            "executable": str(executable) if executable else None,
            "pipeline": str(pipeline) if pipeline else None,
            "message": "Meshroom pronto." if available else "Meshroom ainda não está instalado ou não foi encontrado.",
        }
    executable = _find_colmap_executable()
    required_openmvs = [
        _find_openmvs_executable("InterfaceCOLMAP"),
        _find_openmvs_executable("DensifyPointCloud"),
        _find_openmvs_executable("ReconstructMesh"),
        _find_openmvs_executable("TextureMesh"),
    ]
    photogrammetry_available = executable is not None and all(required_openmvs)
    hunyuan_python, hunyuan_generator = _find_hunyuan_runtime()
    generative_available = hunyuan_python is not None and hunyuan_generator is not None
    available = photogrammetry_available or generative_available
    if photogrammetry_available and generative_available:
        message = "IA multivista e fotogrametria prontas; o modo é escolhido automaticamente."
    elif generative_available:
        message = "IA multivista pronta para reconstrução com 5–10 fotografias."
    else:
        message = "Os motores de reconstrução não foram encontrados."
    return {
        "mode": mode,
        "pipeline_version": "adaptive-ai-v2",
        "available": available,
        "real_reconstruction": True,
        "executable": str(executable) if executable else None,
        "pipeline": "Hunyuan3D multi-candidato + PBR · COLMAP adaptativo",
        "generative_ai": generative_available,
        "photogrammetry": photogrammetry_available,
        "minimum_images": MINIMUM_AI_IMAGES,
        "recommended_images": "5–10",
        "message": message,
    }


def create_mock_glb(path: Path) -> None:
    """Create a tiny valid GLB used only by automated development tests."""
    positions = struct.pack("<9f", -1, -1, 0, 1, -1, 0, 0, 1, 0)
    indices = struct.pack("<3H", 0, 1, 2) + b"\x00\x00"
    binary = positions + indices
    document = {
        "asset": {"version": "2.0", "generator": "ImageTo3D Studio test fixture"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36, "target": 34962},
            {"buffer": 0, "byteOffset": 36, "byteLength": 6, "target": 34963},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [-1, -1, 0], "max": [1, 1, 0]},
            {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
    }
    raw = json.dumps(document, separators=(",", ":")).encode()
    raw += b" " * ((4 - len(raw) % 4) % 4)
    binary += b"\x00" * ((4 - len(binary) % 4) % 4)
    total = 12 + 8 + len(raw) + 8 + len(binary)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, total)
        + struct.pack("<I4s", len(raw), b"JSON")
        + raw
        + struct.pack("<I4s", len(binary), b"BIN\x00")
        + binary
    )


def queue_job(job_id: str) -> None:
    threading.Thread(target=run_job, args=(job_id,), daemon=True).start()


def run_job(job_id: str) -> None:
    db = SessionLocal()
    job = db.get(ReconstructionJob, job_id)
    if not job:
        db.close()
        return
    project = db.get(Project, job.project_id)
    try:
        job.status = project.status = "processing"
        job.started_at = _now()
        project.error_message = None
        db.commit()
        mode = settings.reconstruction_mode.lower()
        if mode == "meshroom":
            _run_meshroom(db, job, project)
        elif mode == "colmap":
            usable = sum(image.validation_status != "rejected" for image in project.images)
            trackability = photogrammetry_trackability(project.images)
            strategy = strategy_for_images(usable, trackability["level"])
            job.configuration = {
                **(job.configuration or {}),
                "pipeline_version": "adaptive-ai-v2",
                "photogrammetry_trackability": trackability,
                "strategy": strategy.as_dict(),
            }
            db.commit()
            hunyuan_python, _ = _find_hunyuan_runtime()
            if strategy.key == "hybrid" and _find_colmap_executable():
                try:
                    _run_colmap(db, job, project)
                except Exception as photogrammetry_error:
                    if not hunyuan_python:
                        raise
                    _reset_job_for_fallback(db, job)
                    job.configuration = {
                        **(job.configuration or {}),
                        "photogrammetry_fallback_reason": str(photogrammetry_error),
                    }
                    db.commit()
                    _run_hunyuan(db, job, project, strategy_key="hybrid_fallback")
            else:
                _run_hunyuan(db, job, project, strategy_key=strategy.key)
        else:
            _run_mock(db, job, project)
    except Exception as exc:
        job.status = project.status = "failed"
        job.error_message = project.error_message = str(exc)
        db.commit()
    finally:
        db.close()


def _reset_job_for_fallback(db, job):
    job.progress = 0
    job.current_stage = STAGES[0]
    job.error_message = None
    for stage in job.stages:
        stage.status = "pending"
        stage.progress = 0
        stage.message = ""
        stage.started_at = None
        stage.completed_at = None
        stage.error_message = None
    db.commit()


def _advance(db, job, stage, percent: int, message: str):
    stage.status = "processing" if percent < 100 else "completed"
    stage.started_at = stage.started_at or _now()
    stage.progress = percent
    stage.message = message
    job.current_stage = stage.name
    job.progress = min(99, round(((stage.order - 1) + percent / 100) / len(STAGES) * 100))
    if percent == 100:
        stage.completed_at = _now()
    db.commit()


def _finish(db, job, project, output: Path, metrics: dict, metadata: dict):
    artifact = Artifact(
        project_id=project.id,
        job_id=job.id,
        artifact_type="glb",
        filename="modelo-3d.glb",
        storage_path=str(output),
        mime_type="model/gltf-binary",
        file_size=output.stat().st_size,
        artifact_metadata=metadata,
    )
    db.add(artifact)
    job.status = project.status = "completed"
    job.progress = 100
    job.completed_at = project.completed_at = _now()
    job.metrics = metrics
    project.quality_score = metrics.get("quality_score")
    db.commit()


def _run_mock(db, job, project):
    for stage in sorted(job.stages, key=lambda value: value.order):
        for percent in (12, 38, 67, 88, 100):
            _advance(db, job, stage, percent, f"Simulação de desenvolvimento: {percent}%")
            time.sleep(settings.mock_stage_seconds / 5)
    output_dir = settings.storage_root / project.id / "artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{job.id}.glb"
    create_mock_glb(output)
    _finish(
        db,
        job,
        project,
        output,
        {"cameras": 0, "points": 0, "vertices": 3, "triangles": 1, "simulated": True, "quality_score": 0},
        {"simulated": True, "engine": "mock", "displayable": False},
    )


def _prepare_images(project: Project, destination: Path) -> int:
    destination.mkdir(parents=True, exist_ok=True)
    valid_images = sorted(
        (image for image in project.images if image.validation_status != "rejected"),
        key=lambda image: (image.created_at, image.original_filename),
    )
    for index, item in enumerate(valid_images):
        output = destination / f"image-{index:04d}.jpg"
        with Image.open(_stored_file(item.storage_path)) as source:
            ImageOps.exif_transpose(source).convert("RGB").save(output, "JPEG", quality=96, subsampling=0)
    return len(valid_images)


def _stage_from_log(line: str) -> int | None:
    value = line.lower()
    mappings = [
        (1, ("featureextraction", "featurematching", "imagematching")),
        (2, ("structurefrommotion", "incrementalsfm", "camera poses")),
        (3, ("preparedensescene", "depthmap", "depth map")),
        (4, ("meshfiltering", "meshing", "mesh filtering")),
        (5, ("texturing", "texture atlas")),
    ]
    for stage, keywords in mappings:
        if any(keyword in value for keyword in keywords):
            return stage
    return None


def _run_external_with_progress(db, job, command: list[str], log_path: Path):
    stages = sorted(job.stages, key=lambda value: value.order)
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creation_flags,
    )
    output_queue: queue.Queue[str] = queue.Queue()
    tail: deque[str] = deque(maxlen=30)

    def read_output():
        assert process.stdout is not None
        for line in process.stdout:
            output_queue.put(line)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    current = 1
    _advance(db, job, stages[current], 8, "A iniciar o motor fotogramétrico…")
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        while process.poll() is None:
            detected = None
            while True:
                try:
                    line = output_queue.get_nowait()
                except queue.Empty:
                    break
                log.write(line)
                log.flush()
                tail.append(line.rstrip())
                detected = _stage_from_log(line) or detected
            if detected is not None and detected > current:
                for index in range(current, detected):
                    _advance(db, job, stages[index], 100, "Concluído")
                current = detected
                _advance(db, job, stages[current], 10, "A processar com Meshroom/AliceVision…")
            elif stages[current].progress < 90:
                _advance(db, job, stages[current], min(90, stages[current].progress + 1), "A processar com Meshroom/AliceVision…")
            if time.monotonic() - started > settings.reconstruction_timeout_hours * 3600:
                process.kill()
                raise RuntimeError("A reconstrução excedeu o tempo máximo configurado.")
            time.sleep(2)
        reader.join(timeout=5)
        while not output_queue.empty():
            line = output_queue.get_nowait()
            log.write(line)
            tail.append(line.rstrip())
    if process.returncode != 0:
        detail = "\n".join(list(tail)[-8:])
        raise RuntimeError(
            "O motor não conseguiu alinhar/gerar geometria suficiente. "
            "Adiciona vistas intermédias nítidas, sem flash, mantendo o objeto na mesma orientação."
            + (f" Detalhe técnico: {detail}" if detail else "")
        )
    for index in range(current, 6):
        _advance(db, job, stages[index], 100, "Concluído")


def _best_mesh_source(output_dir: Path, cache_dir: Path) -> Path | None:
    candidates: list[Path] = []
    for root in (output_dir, cache_dir):
        if root.is_dir():
            candidates.extend(
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in {".glb", ".gltf", ".obj", ".ply"}
            )

    def rank(path: Path):
        name = path.name.lower()
        textured = 2 if "textur" in name else 0
        preferred = {".glb": 4, ".gltf": 3, ".obj": 2, ".ply": 1}.get(path.suffix.lower(), 0)
        return textured + preferred, path.stat().st_size

    return max(candidates, key=rank) if candidates else None


def _convert_to_glb(source: Path, output: Path) -> dict:
    import numpy as np
    import trimesh

    scene = trimesh.load(str(source), force="scene", process=False)
    if not scene.geometry:
        raise RuntimeError("O motor terminou sem produzir uma mesh utilizável.")
    bounds = scene.bounds
    extent = float(np.max(bounds[1] - bounds[0]))
    if extent > 0:
        scene.apply_translation(-scene.centroid)
        scene.apply_scale(2.4 / extent)
    vertices = sum(len(geometry.vertices) for geometry in scene.geometry.values())
    triangles = sum(len(geometry.faces) for geometry in scene.geometry.values())
    output.write_bytes(scene.export(file_type="glb"))
    return {"vertices": vertices, "triangles": triangles}


def _run_meshroom(db, job, project):
    executable = _find_meshroom_executable()
    pipeline = _find_meshroom_pipeline()
    if not executable or not pipeline:
        raise RuntimeError("Meshroom não está instalado ou o pipeline de reconstrução de objetos não foi encontrado.")
    workspace = settings.storage_root / project.id / "reconstruction" / job.id
    images_dir = workspace / "images"
    output_dir = workspace / "output"
    cache_dir = workspace / "cache"
    artifacts_dir = settings.storage_root / project.id / "artifacts"
    for directory in (output_dir, cache_dir, artifacts_dir):
        directory.mkdir(parents=True, exist_ok=True)
    stages = sorted(job.stages, key=lambda value: value.order)
    _advance(db, job, stages[0], 15, "A corrigir orientação e preservar a máxima qualidade…")
    camera_count = _prepare_images(project, images_dir)
    if camera_count < 20:
        raise RuntimeError("O modo fotogramétrico precisa de pelo menos 20 fotografias válidas; com menos imagens usa a reconstrução por IA.")
    _advance(db, job, stages[0], 100, f"{camera_count} imagens preparadas")
    log_path = workspace / "meshroom.log"
    job.logs_path = str(log_path)
    job.configuration = {
        **(job.configuration or {}),
        "engine": "Meshroom/AliceVision",
        "pipeline": pipeline.name,
        "automatic_object_segmentation": True,
    }
    db.commit()
    command = [
        str(executable),
        "--input",
        str(images_dir),
        "--output",
        str(output_dir),
        "--cache",
        str(cache_dir),
        "--pipeline",
        str(pipeline),
        "--save",
        str(workspace / "reconstruction.mg"),
    ]
    _run_external_with_progress(db, job, command, log_path)
    source = _best_mesh_source(output_dir, cache_dir)
    if source is None:
        raise RuntimeError("O Meshroom terminou sem gerar uma mesh. A captura não contém correspondências suficientes no objeto.")
    _advance(db, job, stages[6], 20, f"A converter {source.suffix.upper()} para GLB…")
    glb_path = artifacts_dir / f"{job.id}.glb"
    geometry = _convert_to_glb(source, glb_path)
    _advance(db, job, stages[6], 100, "GLB criado e verificado")
    quality = min(96, round(35 + min(camera_count, 50) * 0.9 + min(geometry["triangles"], 500_000) / 25_000))
    _finish(
        db,
        job,
        project,
        glb_path,
        {
            "cameras": camera_count,
            "points": None,
            **geometry,
            "simulated": False,
            "quality_score": quality,
        },
        {
            "simulated": False,
            "displayable": True,
            "engine": "Meshroom/AliceVision",
            "pipeline": pipeline.name,
            "source_format": source.suffix.lower(),
        },
    )


def _clean_mask_components(mask: Image.Image) -> np.ndarray:
    from scipy import ndimage

    values = np.asarray(mask.convert("L"), dtype=np.uint8) > 24
    labels, component_count = ndimage.label(values)
    if not component_count:
        return values
    height, width = values.shape
    components = []
    for label_id in range(1, component_count + 1):
        ys, xs = np.where(labels == label_id)
        if not len(xs):
            continue
        area = len(xs)
        center_distance = np.hypot(xs.mean() - width / 2, ys.mean() - height / 2) / np.hypot(width / 2, height / 2)
        central = np.mean((xs > width * 0.15) & (xs < width * 0.85) & (ys > height * 0.15) & (ys < height * 0.9))
        score = area * (0.35 + max(0, 1 - center_distance)) * (1 + central)
        components.append((score, label_id, area, xs.min(), xs.max(), ys.min(), ys.max()))
    primary = max(components)
    _, primary_id, primary_area, x0, x1, y0, y1 = primary
    margin_x = max(20, round((x1 - x0) * 0.25))
    margin_y = max(20, round((y1 - y0) * 0.25))
    keep = {primary_id}
    for _, label_id, area, cx0, cx1, cy0, cy1 in components:
        center_x = (cx0 + cx1) / 2
        center_y = (cy0 + cy1) / 2
        if area >= primary_area * 0.008 and x0 - margin_x <= center_x <= x1 + margin_x and y0 - margin_y <= center_y <= y1 + margin_y:
            keep.add(label_id)
    return np.isin(labels, list(keep))


def _prepare_object_masks(images_dir: Path, masks_dir: Path) -> int:
    if not settings.enable_object_segmentation:
        return 0
    input_images = sorted(images_dir.glob("*.jpg"))
    signature = {
        "model": settings.segmentation_model,
        "images": [
            {"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in input_images
        ],
    }
    manifest_path = masks_dir / "mask-manifest.json"
    try:
        cached_signature = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cached_signature = None
    masks_complete = input_images and all(
        (masks_dir / f"{image_path.name}.png").is_file()
        and (masks_dir / f"{image_path.stem}.mask.png").is_file()
        for image_path in input_images
    )
    if masks_complete and (cached_signature == signature or cached_signature is None):
        # Adopt masks produced by older versions once; future changes are
        # protected by the content/model manifest.
        masks_dir.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(signature, indent=2), encoding="utf-8")
        return len(input_images)
    model_dir = PROJECT_ROOT / "tools" / "rembg-models"
    model_dir.mkdir(parents=True, exist_ok=True)
    os.environ["U2NET_HOME"] = str(model_dir)
    masks_dir.mkdir(parents=True, exist_ok=True)
    created = 0
    neural_pending: list[Path] = []
    for image_path in input_images:
        fast_mask = _fast_uniform_background_mask(image_path)
        if fast_mask is None:
            neural_pending.append(image_path)
            continue
        fast_mask.save(masks_dir / f"{image_path.name}.png")
        fast_mask.save(masks_dir / f"{image_path.stem}.mask.png")
        created += 1

    if neural_pending:
        try:
            from rembg import new_session, remove
        except ImportError as exc:
            raise RuntimeError("A segmentação automática não está instalada. Executa pip install 'rembg[cpu]'.") from exc
        session = new_session(settings.segmentation_model)
    for image_path in neural_pending:
        with Image.open(image_path) as source:
            mask = remove(source.convert("RGB"), session=session, only_mask=True).convert("L")
        values = _clean_mask_components(mask)
        coverage = float(np.mean(values))
        if coverage < 0.01 or coverage > 0.85:
            raise RuntimeError(
                f"A segmentação não conseguiu isolar o objeto em {image_path.name}. "
                "Usa um fundo simples e contrastante, sem outros objetos próximos."
            )
        # Expand a few pixels to preserve the cup rim and thin handle edges.
        mask = Image.fromarray((values * 255).astype(np.uint8), mode="L").filter(ImageFilter.MaxFilter(7))
        mask.save(masks_dir / f"{image_path.name}.png")
        mask.save(masks_dir / f"{image_path.stem}.mask.png")
        created += 1
    manifest_path.write_text(json.dumps(signature, indent=2), encoding="utf-8")
    return created


def _fast_uniform_background_mask(image_path: Path) -> Image.Image | None:
    """Segment controlled studio captures without invoking a neural network.

    Most five-view inputs use a plain backdrop.  Border-colour modelling is
    effectively instantaneous and lets the slower local AI fallback focus only
    on genuinely complex real-world backgrounds.
    """
    from scipy import ndimage

    with Image.open(image_path) as source:
        original_size = source.size
        working = source.convert("RGB")
        working.thumbnail((640, 640), Image.Resampling.LANCZOS)
    pixels = np.asarray(working, dtype=np.float32)
    height, width = pixels.shape[:2]
    band = max(8, round(min(height, width) * 0.055))
    border = np.concatenate(
        [
            pixels[:band].reshape(-1, 3),
            pixels[-band:].reshape(-1, 3),
            pixels[:, :band].reshape(-1, 3),
            pixels[:, -band:].reshape(-1, 3),
        ]
    )
    background = np.median(border, axis=0)
    border_distance = np.linalg.norm(border - background, axis=1)
    spread = float(np.percentile(border_distance, 90))
    if spread > 24:
        return None
    distance = np.linalg.norm(pixels - background, axis=2)
    foreground = distance > max(10.0, spread + 4.0)
    foreground = ndimage.binary_opening(foreground, iterations=1)
    foreground = ndimage.binary_closing(foreground, iterations=2)
    foreground = _clean_mask_components(Image.fromarray((foreground * 255).astype(np.uint8)))
    coverage = float(np.mean(foreground))
    if coverage < 0.045 or coverage > 0.72:
        return None
    ys, xs = np.where(foreground)
    if not len(xs) or abs(float(xs.mean()) / width - 0.5) > 0.3 or abs(float(ys.mean()) / height - 0.5) > 0.34:
        return None
    mask = Image.fromarray((foreground * 255).astype(np.uint8), mode="L").filter(ImageFilter.MaxFilter(5))
    if mask.size != original_size:
        mask = mask.resize(original_size, Image.Resampling.NEAREST)
    return mask


def _run_stage_command(
    db,
    job,
    stage,
    command: list[str],
    message: str,
    log,
    cwd: Path,
    env: dict | None = None,
    timeout_seconds: float | None = None,
):
    _advance(db, job, stage, 5, message)
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creation_flags,
    )
    tail: deque[str] = deque(maxlen=25)
    output_queue: queue.Queue[str] = queue.Queue()

    def reader():
        assert process.stdout is not None
        for line in process.stdout:
            output_queue.put(line)

    output_reader = threading.Thread(target=reader, daemon=True)
    output_reader.start()
    started = time.monotonic()
    timeout = timeout_seconds or settings.reconstruction_timeout_hours * 3600
    while process.poll() is None:
        while True:
            try:
                line = output_queue.get_nowait()
            except queue.Empty:
                break
            log.write(line)
            log.flush()
            tail.append(line.rstrip())
        if stage.progress < 90:
            _advance(db, job, stage, min(90, stage.progress + 2), message)
        if time.monotonic() - started > timeout:
            process.kill()
            raise RuntimeError(f"A etapa '{stage.name}' excedeu o tempo máximo configurado.")
        time.sleep(2)
    output_reader.join(timeout=5)
    while not output_queue.empty():
        line = output_queue.get_nowait()
        log.write(line)
        tail.append(line.rstrip())
    if process.returncode != 0:
        detail = "\n".join(list(tail)[-8:])
        raise RuntimeError(f"Falha em '{stage.name}'. {detail}".strip())
    _advance(db, job, stage, 100, "Concluído")


def _colmap_environment(executable: Path) -> dict:
    env = os.environ.copy()
    env["PATH"] = str(executable.parent) + os.pathsep + env.get("PATH", "")
    plugin_dir = executable.parent.parent / "plugins"
    if plugin_dir.is_dir():
        env["QT_PLUGIN_PATH"] = str(plugin_dir)
    return env


def _colmap_model_stats(text_model: Path) -> tuple[int, int]:
    images_file = text_model / "images.txt"
    points_file = text_model / "points3D.txt"
    image_lines = []
    point_lines = []
    if images_file.is_file():
        image_lines = [line for line in images_file.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
    if points_file.is_file():
        point_lines = [line for line in points_file.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
    return len(image_lines) // 2, len(point_lines)


def _copy_openmvs_masks(masks_dir: Path, dense_images: Path):
    for image_path in dense_images.glob("*"):
        if not image_path.is_file() or image_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        source = masks_dir / f"{image_path.stem}.mask.png"
        if source.is_file():
            with Image.open(source) as source_mask, Image.open(image_path) as dense_image:
                mask = source_mask.convert("L")
                if mask.size != dense_image.size:
                    mask = mask.resize(dense_image.size, Image.Resampling.NEAREST)
                mask.save(image_path.with_suffix(".mask.png"))


def _apply_dense_masks(masks_dir: Path, dense_images: Path):
    """Remove the static background before multi-view stereo.

    The source set is a turntable-style capture: the cup changes orientation while
    the table remains fixed.  Leaving the table visible makes dense stereo favour
    the background instead of the object, so use the same foreground masks that
    constrained feature extraction to composite the undistorted images on black.
    """
    for image_path in dense_images.glob("*"):
        if not image_path.is_file() or image_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        source = masks_dir / f"{image_path.stem}.mask.png"
        if not source.is_file():
            continue
        with Image.open(source) as source_mask, Image.open(image_path) as dense_image:
            image = dense_image.convert("RGB")
            mask = source_mask.convert("L")
            if mask.size != image.size:
                mask = mask.resize(image.size, Image.Resampling.NEAREST)
            foreground = Image.composite(image, Image.new("RGB", image.size, "black"), mask)
            foreground.save(image_path, quality=96, subsampling=0)


def _evenly_spaced_views(images: list[Path], limit: int = 4) -> list[Path]:
    if len(images) <= limit:
        return images
    indices = np.linspace(0, len(images) - 1, limit, dtype=int)
    return [images[int(index)] for index in indices]


def _mask_shape_signature(mask_path: Path) -> tuple[float, float]:
    """Return normalized foreground height and aspect ratio for view filtering."""
    with Image.open(mask_path) as source:
        foreground = np.asarray(source.convert("L")) > 127
    ys, xs = np.where(foreground)
    if not len(xs):
        return 1.0, 1.0
    height, width = foreground.shape
    box_height = float(ys.max() - ys.min() + 1)
    box_width = float(xs.max() - xs.min() + 1)
    return box_height / max(height, 1), box_width / max(box_height, 1.0)


def _mask_vertical_asymmetry(mask_path: Path) -> float:
    """Separate top-down circular views from upright object views."""
    with Image.open(mask_path) as source:
        foreground = np.asarray(source.convert("L")) > 127
    ys, xs = np.where(foreground)
    if not len(xs):
        return 0.0
    crop = foreground[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    profile = crop.mean(axis=1)
    return float(np.mean(np.abs(profile - profile[::-1])) / max(float(profile.mean()), 1e-6))


def _view_internal_edge_imbalance(image_path: Path, mask_path: Path) -> float:
    """Detect oblique base views whose strong internal rim sits at one extreme."""
    from scipy import ndimage

    try:
        with Image.open(image_path) as source:
            gray = np.asarray(source.convert("L").resize((256, 256)), dtype=np.float32)
        with Image.open(mask_path) as source:
            mask = np.asarray(source.convert("L").resize((256, 256), Image.Resampling.NEAREST)) > 127
    except (OSError, ValueError):
        return 0.0
    ys, xs = np.where(mask)
    if not len(xs):
        return 0.0
    gray = gray[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    mask = mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    interior = ndimage.binary_erosion(mask, iterations=max(2, round(min(mask.shape) * 0.03)))
    vertical, horizontal = np.gradient(gray)
    energy = np.hypot(vertical, horizontal)
    values = energy[interior]
    if not len(values):
        return 0.0
    strong = (energy >= np.percentile(values, 92)) & interior
    edge_y, _ = np.where(strong)
    if not len(edge_y):
        return 0.0
    top = float(np.mean(edge_y < gray.shape[0] * 0.3))
    bottom = float(np.mean(edge_y > gray.shape[0] * 0.7))
    return abs(top - bottom)


def _mask_handle_hole(mask_path: Path) -> tuple[float, float] | None:
    """Return horizontal offset and area of a handle-like enclosed hole."""
    from scipy import ndimage

    with Image.open(mask_path) as source:
        foreground = np.asarray(source.convert("L")) > 127
    ys, xs = np.where(foreground)
    if not len(xs):
        return None
    crop = foreground[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    labels, count = ndimage.label(~crop)
    border_labels = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])).tolist())
    holes = []
    for label in range(1, count + 1):
        if label in border_labels:
            continue
        hole_y, hole_x = np.where(labels == label)
        area = len(hole_x) / max(crop.size, 1)
        if area >= 0.008 and abs(float(hole_y.mean()) / crop.shape[0] - 0.5) < 0.34:
            offset = float(hole_x.mean()) / crop.shape[1] - 0.5
            holes.append((area, offset))
    if not holes:
        return None
    area, offset = max(holes)
    return offset, area


def _semantic_handle_order(images: list[Path], masks_dir: Path) -> list[Path] | None:
    """Map cup-like views to Hunyuan's front/left/back/right slots."""
    features = []
    for image in images:
        hole = _mask_handle_hole(masks_dir / f"{image.stem}.mask.png")
        offset, area = hole if hole else (0.0, 0.0)
        features.append((image, offset, area))
    left = sorted((item for item in features if item[1] < -0.18), key=lambda item: item[2], reverse=True)
    right = sorted((item for item in features if item[1] > 0.18), key=lambda item: item[2], reverse=True)
    neutral = [item for item in features if abs(item[1]) <= 0.18]
    if left and right and len(neutral) >= 2:
        return [neutral[0][0], left[0][0], neutral[-1][0], right[0][0]]
    return None


def _select_conditioning_views(images: list[Path], masks_dir: Path, limit: int = 4) -> list[Path]:
    """Prefer a consistent lateral orbit, then sample it in capture order.

    A capture often includes useful top and inverted-base shots.  Those improve
    confidence, but mixing one of them into the four fixed Hunyuan side slots can
    distort the generated body.  Foreground shape gives us a cheap, category-
    independent way to keep the dominant orbit while still preserving its order.
    """
    if len(images) <= limit:
        return images
    signatures = [
        _mask_shape_signature(masks_dir / f"{image.stem}.mask.png")
        for image in images
    ]
    heights = np.asarray([signature[0] for signature in signatures], dtype=float)
    aspects = np.asarray([signature[1] for signature in signatures], dtype=float)
    median_height = max(float(np.median(heights)), 1e-6)
    median_aspect = max(float(np.median(aspects)), 1e-6)
    asymmetries = np.asarray(
        [_mask_vertical_asymmetry(masks_dir / f"{image.stem}.mask.png") for image in images],
        dtype=float,
    )
    upright_threshold = max(0.055, float(np.median(asymmetries)) * 0.34)
    upright = set(np.flatnonzero(asymmetries >= upright_threshold).tolist())
    # Only apply this exclusion when a complete lateral set remains.  Generic
    # symmetric objects legitimately have symmetric upright silhouettes.
    if len(upright) < limit:
        upright = set(range(len(images)))
    edge_balanced = {
        index
        for index, image in enumerate(images)
        if _view_internal_edge_imbalance(image, masks_dir / f"{image.stem}.mask.png") <= 0.38
    }
    if len(upright & edge_balanced) >= limit:
        upright &= edge_balanced
    consistent = [
        index
        for index, (height, aspect) in enumerate(signatures)
        if index in upright
        and height <= median_height * 1.35
        and abs(float(np.log(max(aspect, 1e-6) / median_aspect))) <= 0.35
    ]
    if len(consistent) < limit:
        consistency = np.abs(np.log(np.maximum(heights, 1e-6) / median_height))
        consistency += np.abs(np.log(np.maximum(aspects, 1e-6) / median_aspect))
        consistent = sorted(np.argsort(consistency)[: max(limit, round(len(images) * 0.55))].tolist())
    orbit = [images[index] for index in consistent]
    if limit == 4:
        semantic_order = _semantic_handle_order(orbit, masks_dir)
        if semantic_order:
            return semantic_order
    return _evenly_spaced_views(orbit, limit)


def _read_hunyuan_result(log_path: Path) -> dict:
    if not log_path.is_file():
        return {}
    for line in reversed(log_path.read_text(encoding="utf-8", errors="replace").splitlines()):
        if line.startswith("HUNYUAN_RESULT "):
            try:
                return json.loads(line.removeprefix("HUNYUAN_RESULT "))
            except json.JSONDecodeError:
                return {}
    return {}


def _run_hunyuan(db, job, project, strategy_key: str = "ai_multiview"):
    python, generator = _find_hunyuan_runtime()
    if not python or not generator:
        raise RuntimeError("O motor generativo Hunyuan3D não está instalado ou não está pronto.")

    workspace = settings.storage_root / project.id / "reconstruction" / job.id
    images_dir = workspace / "images"
    masks_dir = settings.storage_root / project.id / "segmentation"
    artifacts_dir = settings.storage_root / project.id / "artifacts"
    for directory in (workspace, images_dir, masks_dir, artifacts_dir):
        directory.mkdir(parents=True, exist_ok=True)
    stages = sorted(job.stages, key=lambda value: value.order)
    log_path = workspace / "hunyuan.log"
    job.logs_path = str(log_path)

    _advance(db, job, stages[0], 15, "A preparar as melhores vistas para a IA…")
    image_count = _prepare_images(project, images_dir)
    if image_count < MINIMUM_AI_IMAGES:
        raise RuntimeError(f"São necessárias pelo menos {MINIMUM_AI_IMAGES} fotografias utilizáveis.")
    mask_count = _prepare_object_masks(images_dir, masks_dir)
    _advance(db, job, stages[0], 100, f"{image_count} imagens e {mask_count} máscaras preparadas")

    candidates = sorted(images_dir.glob("image-*.jpg"))
    selected = _select_conditioning_views(candidates, masks_dir, 4)
    selected_masks = [masks_dir / f"{image.stem}.mask.png" for image in selected]
    if any(not mask.is_file() for mask in selected_masks):
        raise RuntimeError("Não foi possível segmentar vistas suficientes para a reconstrução por IA.")
    _advance(db, job, stages[1], 100, f"{len(selected)} vistas complementares selecionadas")
    _advance(db, job, stages[2], 100, "A IA vai estimar câmaras e superfícies ocultas")
    _advance(db, job, stages[3], 100, "Nuvem clássica substituída por representação generativa")

    raw_output = workspace / "hunyuan-raw.glb"
    model_cache = _resolved_tool_root(settings.hunyuan_model_cache)
    model_cache.mkdir(parents=True, exist_ok=True)
    generated_candidates = 4 if image_count <= 10 else 2
    command = [
        str(python), str(generator),
        "--repo", str(_resolved_tool_root(settings.hunyuan_root)),
        "--output", str(raw_output),
        "--cache", str(model_cache),
        # 256 keeps the multiview model comfortably inside an 8 GB GPU.
        # Extra photographs improve view selection and confidence; they do not
        # need a larger diffusion grid to provide that benefit.
        "--resolution", "256",
        "--candidates", str(generated_candidates),
        "--target-faces", "60000",
        "--images", *[str(image) for image in selected],
        "--masks", *[str(mask) for mask in selected_masks],
    ]
    job.configuration = {
        **(job.configuration or {}),
        "engine": "Hunyuan3D-2mv Turbo",
        "strategy_key": strategy_key,
        "conditioning_views": [image.name for image in selected],
        "candidate_count": generated_candidates,
        "target_faces": 60000,
        "generative_ai": True,
    }
    db.commit()
    with log_path.open("w", encoding="utf-8") as log:
        _run_stage_command(
            db,
            job,
            stages[4],
            command,
            "A gerar e verificar a geometria multivista com IA…",
            log,
            workspace,
            timeout_seconds=settings.reconstruction_timeout_hours * 3600,
        )
    if not raw_output.is_file() or raw_output.stat().st_size < 10_000:
        raise RuntimeError("A IA terminou sem produzir uma malha 3D utilizável.")
    worker_result = _read_hunyuan_result(log_path)
    _advance(db, job, stages[5], 100, "Material cerâmico PBR aplicado sem projeção fotográfica falsa")

    _advance(db, job, stages[6], 20, "A normalizar e exportar o GLB…")
    glb_path = artifacts_dir / f"{job.id}.glb"
    geometry = _convert_to_glb(raw_output, glb_path)
    if geometry["vertices"] < 500 or geometry["triangles"] < 1_000:
        glb_path.unlink(missing_ok=True)
        raise RuntimeError("A IA produziu geometria insuficiente; adiciona vistas mais distintas do objeto.")
    _advance(db, job, stages[6], 100, "GLB generativo criado e verificado")

    trackability = photogrammetry_trackability(project.images)
    estimates = capture_metrics(image_count, project.validation_score, trackability["level"])
    confidence = estimates["geometric_confidence_estimate"]
    if strategy_key == "hybrid_fallback":
        confidence = max(35, confidence - 10)
    _finish(
        db,
        job,
        project,
        glb_path,
        {
            "cameras": len(selected),
            "input_images": image_count,
            "points": 0,
            **geometry,
            "simulated": False,
            "generative_ai": True,
            "visual_fidelity": estimates["visual_fidelity_estimate"],
            "geometric_confidence": confidence,
            "observed_coverage": estimates["observed_coverage_estimate"],
            "candidates_generated": int(worker_result.get("candidate_count", generated_candidates)),
            "selected_candidate": int(worker_result.get("selected_candidate", 1)),
            "candidate_score": float(worker_result.get("candidate_score", 0)),
            "handle_expected": bool(worker_result.get("handle_expected", False)),
            "handle_preserved": bool(worker_result.get("handle_preserved", False)),
            "triangles_before_optimization": int(worker_result.get("faces_before_optimization", geometry["triangles"])),
            "texture_mode": "PBR base · sem projeção da fotografia",
            "photogrammetry_trackability": trackability["score"],
            "quality_score": estimates["visual_fidelity_estimate"],
        },
        {
            "simulated": False,
            "displayable": True,
            "generative_ai": True,
            "engine": "Hunyuan3D-2mv Turbo multi-candidato + PBR",
            "strategy": strategy_key,
            "estimated_geometry": True,
            "conditioning_views": len(selected),
            "candidates_generated": int(worker_result.get("candidate_count", generated_candidates)),
            "selected_candidate": int(worker_result.get("selected_candidate", 1)),
            "material": "PBR uniforme estimado das vistas",
            "texture_projection": False,
            "optimized_target_faces": 60000,
            "source_format": ".glb",
        },
    )


def _run_colmap(db, job, project):
    colmap = _find_colmap_executable()
    interface = _find_openmvs_executable("InterfaceCOLMAP")
    densify = _find_openmvs_executable("DensifyPointCloud")
    reconstruct = _find_openmvs_executable("ReconstructMesh")
    refine = _find_openmvs_executable("RefineMesh")
    texture = _find_openmvs_executable("TextureMesh")
    if not colmap or not all((interface, densify, reconstruct, texture)):
        raise RuntimeError("COLMAP 4.0.1 e OpenMVS 2.4 não estão instalados no diretório tools.")

    workspace = settings.storage_root / project.id / "reconstruction" / job.id
    images_dir = workspace / "images"
    masks_dir = settings.storage_root / project.id / "segmentation"
    sparse_dir = workspace / "sparse"
    dense_dir = workspace / "dense"
    text_model = workspace / "model-text"
    artifacts_dir = settings.storage_root / project.id / "artifacts"
    for directory in (workspace, sparse_dir, text_model, artifacts_dir):
        directory.mkdir(parents=True, exist_ok=True)
    database = workspace / "database.db"
    log_path = workspace / "reconstruction.log"
    job.logs_path = str(log_path)
    job.configuration = {
        **(job.configuration or {}),
        "engine": "COLMAP 4.0.1 + OpenMVS 2.4",
        "segmentation": settings.segmentation_model if settings.enable_object_segmentation else None,
        "camera_model": "PINHOLE",
    }
    db.commit()
    stages = sorted(job.stages, key=lambda value: value.order)
    _advance(db, job, stages[0], 10, "A normalizar imagens sem perder resolução…")
    camera_count = _prepare_images(project, images_dir)
    if camera_count < 20:
        raise RuntimeError("O modo fotogramétrico precisa de pelo menos 20 fotografias válidas; com menos imagens usa a reconstrução por IA.")
    _advance(db, job, stages[0], 35, "A isolar a chávena do fundo com segmentação automática…")
    mask_count = _prepare_object_masks(images_dir, masks_dir)
    _advance(db, job, stages[0], 100, f"{camera_count} imagens e {mask_count} máscaras preparadas")

    colmap_env = _colmap_environment(colmap)
    models_root = colmap.parent.parent
    with log_path.open("w", encoding="utf-8") as log:
        feature_command = [
            str(colmap), "feature_extractor",
            "--database_path", str(database),
            "--image_path", str(images_dir),
            "--ImageReader.camera_model", "PINHOLE",
            "--ImageReader.single_camera", "1",
            "--FeatureExtraction.type", "ALIKED_N16ROT",
            "--FeatureExtraction.use_gpu", "0",
            "--FeatureExtraction.max_image_size", "2048",
            "--AlikedExtraction.max_num_features", "4096",
            "--AlikedExtraction.min_score", "0.1",
            "--AlikedExtraction.n16rot_model_path", str(models_root / "aliked-n16rot.onnx"),
        ]
        if mask_count:
            feature_command.extend(["--ImageReader.mask_path", str(masks_dir)])
        _run_stage_command(db, job, stages[1], feature_command, "A extrair detalhes visuais do objeto…", log, workspace, colmap_env)
        _run_stage_command(
            db, job, stages[1],
            [
                str(colmap), "exhaustive_matcher", "--database_path", str(database),
                "--FeatureMatching.type", "ALIKED_LIGHTGLUE", "--FeatureMatching.use_gpu", "0",
                "--FeatureMatching.max_num_matches", "8192",
                "--AlikedMatching.lightglue_min_score", "0.05",
                "--AlikedMatching.lightglue_model_path", str(models_root / "aliked-lightglue.onnx"),
            ],
            "A comparar todos os pares de fotografias…", log, workspace, colmap_env,
        )
        _run_stage_command(
            db, job, stages[2],
            [
                str(colmap), "mapper", "--database_path", str(database), "--image_path", str(images_dir),
                "--output_path", str(sparse_dir), "--Mapper.min_model_size", "8",
                "--Mapper.init_min_num_inliers", "30", "--Mapper.abs_pose_min_num_inliers", "20",
                "--Mapper.ba_refine_principal_point", "1", "--Mapper.max_num_models", "1",
            ],
            "A estimar posições de câmara e geometria esparsa…", log, workspace, colmap_env,
        )
        model_dir = sparse_dir / "0"
        if not model_dir.is_dir():
            raise RuntimeError(
                "Não foi possível alinhar as fotografias da chávena. O flash, as superfícies brancas e a mudança entre posição direita/invertida impediram correspondências suficientes."
            )
        _run_stage_command(
            db, job, stages[2],
            [str(colmap), "model_converter", "--input_path", str(model_dir), "--output_path", str(text_model), "--output_type", "TXT"],
            "A verificar câmaras reconstruídas…", log, workspace, colmap_env,
        )
        registered, sparse_points = _colmap_model_stats(text_model)
        minimum_registered = max(16, int(np.ceil(camera_count * 0.7)))
        if registered < minimum_registered:
            raise RuntimeError(f"Só {registered} de {camera_count} fotografias foram alinhadas. Faz uma nova captura sem flash e com 70–80% de sobreposição.")
        _run_stage_command(
            db, job, stages[3],
            [
                str(colmap), "image_undistorter", "--image_path", str(images_dir), "--input_path", str(model_dir),
                "--output_path", str(dense_dir), "--output_type", "COLMAP", "--max_image_size", "2400",
            ],
            "A preparar imagens e câmaras para densificação…", log, workspace, colmap_env,
        )
        _copy_openmvs_masks(masks_dir, dense_dir / "images")
        _apply_dense_masks(masks_dir, dense_dir / "images")
        scene = workspace / "scene.mvs"
        scene_dense = workspace / "scene_dense.mvs"
        scene_mesh = workspace / "scene_mesh.mvs"
        scene_refined = workspace / "scene_mesh_refined.mvs"
        _run_stage_command(
            db, job, stages[3],
            [str(interface), "-i", str(dense_dir), "-o", str(scene), "--image-folder", str(dense_dir / "images"), "--archive-type", "1"],
            "A transferir a reconstrução para OpenMVS…", log, workspace,
        )
        densify_command = [
            str(densify), "-i", str(scene), "-o", str(scene_dense), "-w", str(workspace),
            "--resolution-level", "1", "--number-views", "5", "--number-views-fuse", "2",
            "--postprocess-dmaps", "7", "--archive-type", "1",
        ]
        if mask_count:
            densify_command.extend(["--mask-path", str(masks_dir), "--ignore-mask-label", "0"])
        _run_stage_command(db, job, stages[3], densify_command, "A calcular uma nuvem de pontos densa…", log, workspace)
        _run_stage_command(
            db, job, stages[4],
            [
                str(reconstruct), "-i", str(scene_dense), "-o", str(scene_mesh), "-w", str(workspace),
                "--remove-spurious", "4", "--close-holes", "40", "--smooth", "2", "--archive-type", "1",
            ],
            "A reconstruir e limpar a superfície…", log, workspace,
        )
        mesh_for_texture = scene_mesh
        if refine:
            try:
                _run_stage_command(
                    db, job, stages[4],
                    [str(refine), "-i", str(scene_mesh), "-o", str(scene_refined), "-w", str(workspace), "--resolution-level", "1", "--archive-type", "1"],
                    "A refinar os detalhes da mesh…", log, workspace,
                )
                mesh_for_texture = scene_refined
            except RuntimeError as refinement_error:
                log.write(f"Refinement warning: {refinement_error}\n")
        textured_scene = workspace / "textured.mvs"
        _run_stage_command(
            db, job, stages[5],
            [
                str(texture), "-i", str(mesh_for_texture), "-o", str(textured_scene), "-w", str(workspace),
                "--export-type", "obj", "--max-texture-size", "8192", "--ignore-mask-label", "0", "--archive-type", "1",
            ],
            "A projetar as fotografias sobre a mesh…", log, workspace,
        )

    source = _best_mesh_source(workspace, workspace)
    if source is None or source.suffix.lower() not in {".obj", ".gltf", ".glb"}:
        raise RuntimeError("O pipeline terminou sem produzir uma mesh texturizada utilizável.")
    _advance(db, job, stages[6], 20, f"A converter {source.suffix.upper()} para GLB…")
    glb_path = artifacts_dir / f"{job.id}.glb"
    geometry = _convert_to_glb(source, glb_path)
    if geometry["vertices"] < 1_000 or geometry["triangles"] < 2_000:
        glb_path.unlink(missing_ok=True)
        raise RuntimeError(
            "A geometria produzida é demasiado incompleta para ser apresentada como reconstrução. "
            "Adiciona vistas intermédias sem flash, em passos pequenos, mantendo 70–80% de sobreposição."
        )
    _advance(db, job, stages[6], 100, "GLB criado e verificado")
    quality = min(96, round(30 + registered / camera_count * 25 + min(camera_count, 50) * 0.6 + min(geometry["triangles"], 500_000) / 30_000))
    _finish(
        db, job, project, glb_path,
        {"cameras": registered, "points": sparse_points, **geometry, "simulated": False, "quality_score": quality},
        {
            "simulated": False, "displayable": True, "engine": "COLMAP 4.0.1 + ALIKED/LightGlue + OpenMVS 2.4",
            "segmentation": settings.segmentation_model, "source_format": source.suffix.lower(),
        },
    )
