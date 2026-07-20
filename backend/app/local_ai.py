from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import trimesh
from PIL import Image, ImageDraw

from .config import PROJECT_ROOT, settings


@dataclass(frozen=True)
class LocalAIEngine:
    key: str
    label: str
    python: Path
    repo: Path
    available: bool
    reason: str
    low_vram: bool = False

    def public(self) -> dict:
        value = asdict(self)
        value["python"] = str(self.python)
        value["repo"] = str(self.repo)
        return value


def _resolved(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def discover_local_ai_engines() -> list[LocalAIEngine]:
    runtime = settings.local_ai_runtime.strip().lower()
    if runtime == "wsl":
        marker = PROJECT_ROOT / "tools" / "wsl-ai-install.json"
        manifest: dict = {}
        try:
            manifest = json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else {}
        except (OSError, json.JSONDecodeError):
            manifest = {}
        wsl_available = shutil.which("wsl.exe") is not None
        correct_distro = manifest.get("distro") == settings.local_ai_wsl_distro
        engine_states = manifest.get("engines") if isinstance(manifest.get("engines"), dict) else {}

        def state(key: str) -> tuple[bool, str]:
            installed = isinstance(engine_states.get(key), dict) and engine_states[key].get("ready") is True
            available = bool(wsl_available and correct_distro and installed)
            if available:
                return True, "Pronto via WSL2"
            if not wsl_available:
                return False, "WSL2 não está disponível"
            if not correct_distro:
                return False, f"Distro {settings.local_ai_wsl_distro} não instalada"
            return False, "Instalação do motor incompleta"

        spar_available, spar_reason = state("spar3d")
        sf3d_available, sf3d_reason = state("stable_fast_3d")
        return [
            LocalAIEngine(
                "spar3d",
                "SPAR3D Low VRAM (WSL2)",
                Path("wsl.exe"),
                Path("/opt/matias-ai/stable-point-aware-3d"),
                spar_available,
                spar_reason,
                True,
            ),
            LocalAIEngine(
                "stable_fast_3d",
                "Stable Fast 3D (WSL2)",
                Path("wsl.exe"),
                Path("/opt/matias-ai/stable-fast-3d"),
                sf3d_available,
                sf3d_reason,
                False,
            ),
        ]

    definitions = [
        (
            "spar3d",
            "SPAR3D Low VRAM",
            _resolved(settings.spar3d_python),
            _resolved(settings.spar3d_root),
            "spar3d",
            True,
        ),
        (
            "stable_fast_3d",
            "Stable Fast 3D",
            _resolved(settings.sf3d_python),
            _resolved(settings.sf3d_root),
            "sf3d",
            False,
        ),
    ]
    engines: list[LocalAIEngine] = []
    for key, label, python, repo, module_dir, low_vram in definitions:
        available = python.is_file() and repo.is_dir() and (repo / module_dir).is_dir()
        if available:
            reason = "Pronto"
        elif not python.is_file():
            reason = "Ambiente Python não instalado"
        elif not repo.is_dir():
            reason = "Código do motor não instalado"
        else:
            reason = "Instalação incompleta"
        engines.append(LocalAIEngine(key, label, python, repo, available, reason, low_vram))
    return engines


def local_ai_engine_status() -> dict:
    engines = discover_local_ai_engines()
    available = [engine for engine in engines if engine.available]
    selected = available[0] if available else None
    return {
        "available": bool(selected),
        "selected": selected.key if selected else None,
        "selected_label": selected.label if selected else None,
        "engines": [engine.public() for engine in engines],
        "message": (
            f"{selected.label} pronto. O modelo é gerado localmente e sem créditos."
            if selected
            else "Executa install_matias_local_ai_wsl_final.ps1 para instalar os motores locais."
        ),
    }


def prepare_transparent_input(image_path: Path, mask_path: Path, output_path: Path) -> Path:
    with Image.open(image_path) as source, Image.open(mask_path) as mask_source:
        image = source.convert("RGBA")
        mask = mask_source.convert("L")
        if mask.size != image.size:
            mask = mask.resize(image.size, Image.Resampling.NEAREST)
        image.putalpha(mask)
        alpha = np.asarray(mask) > 16
        ys, xs = np.where(alpha)
        if len(xs):
            margin_x = max(8, round((xs.max() - xs.min() + 1) * 0.08))
            margin_y = max(8, round((ys.max() - ys.min() + 1) * 0.08))
            box = (
                max(0, int(xs.min()) - margin_x),
                max(0, int(ys.min()) - margin_y),
                min(image.width, int(xs.max()) + margin_x + 1),
                min(image.height, int(ys.max()) + margin_y + 1),
            )
            image = image.crop(box)
        side = max(image.size)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.alpha_composite(image, ((side - image.width) // 2, (side - image.height) // 2))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(output_path)
    return output_path


def _wsl_path(path: Path) -> str:
    command = [
        "wsl.exe",
        "-d",
        settings.local_ai_wsl_distro,
        "--",
        "wslpath",
        "-a",
        str(path.resolve()),
    ]
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return completed.stdout.strip()


def _terminate_process(
    process: subprocess.Popen,
    *,
    wsl_distro: str | None = None,
    wsl_pid_file: Path | None = None,
    wsl_run_id: str | None = None,
) -> None:
    """Terminate the worker and its process tree, including its WSL process group."""
    if wsl_distro and wsl_pid_file:
        deadline = time.monotonic() + 5
        while not wsl_pid_file.is_file() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
    if wsl_distro and wsl_pid_file and wsl_pid_file.is_file():
        pid = wsl_pid_file.read_text(encoding="ascii", errors="ignore").strip()
        if pid.isdigit():
            def group_exists() -> bool:
                check = subprocess.run(
                    ["wsl.exe", "-d", wsl_distro, "--", "/usr/bin/kill", "-0", "--", f"-{pid}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=15,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                return check.returncode == 0

            for signal, grace_seconds in (("TERM", 5), ("KILL", 3)):
                subprocess.run(
                    ["wsl.exe", "-d", wsl_distro, "--", "/usr/bin/kill", f"-{signal}", "--", f"-{pid}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=15,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                grace_deadline = time.monotonic() + grace_seconds
                while group_exists() and time.monotonic() < grace_deadline:
                    time.sleep(0.2)
                if not group_exists():
                    break
    if wsl_distro and wsl_run_id:
        def run_exists() -> bool:
            check = subprocess.run(
                ["wsl.exe", "-d", wsl_distro, "--", "/usr/bin/pgrep", "-f", "--", wsl_run_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            return check.returncode == 0

        for signal, grace_seconds in (("TERM", 5), ("KILL", 3)):
            subprocess.run(
                ["wsl.exe", "-d", wsl_distro, "--", "/usr/bin/pkill", f"-{signal}", "-f", "--", wsl_run_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            grace_deadline = time.monotonic() + grace_seconds
            while run_exists() and time.monotonic() < grace_deadline:
                time.sleep(0.2)
            if not run_exists():
                break
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _run_logged_process(
    command: list[str],
    *,
    log_path: Path,
    timeout_seconds: float,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    cancel_check: Callable[[], None] | None = None,
    wsl_distro: str | None = None,
    wsl_pid_file: Path | None = None,
    wsl_run_id: str | None = None,
) -> tuple[int, float]:
    started = time.monotonic()
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    if os.name == "nt":
        creation_flags |= subprocess.CREATE_NEW_PROCESS_GROUP
    with log_path.open("a", encoding="utf-8") as log:
        log.write("\n$ " + " ".join(command) + "\n")
        log.flush()
        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
            text=True,
        )
        try:
            while process.poll() is None:
                if cancel_check:
                    cancel_check()
                if time.monotonic() - started > timeout_seconds:
                    raise TimeoutError(f"O motor excedeu o limite de {round(timeout_seconds)} segundos.")
                time.sleep(1)
        finally:
            _terminate_process(
                process,
                wsl_distro=wsl_distro,
                wsl_pid_file=wsl_pid_file,
                wsl_run_id=wsl_run_id,
            )
    return process.returncode, time.monotonic() - started


def _failure_detail(engine: LocalAIEngine, log_path: Path) -> RuntimeError:
    tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-25:])
    if "out of memory" in tail.lower() or ("cuda" in tail.lower() and "memory" in tail.lower()):
        return RuntimeError(f"{engine.label} ficou sem memória GPU. Fecha outras aplicações e usa o perfil rápido.")
    return RuntimeError(f"{engine.label} falhou. Detalhe técnico: {tail[-1800:]}")


def _run_wsl_local_ai_candidate(
    engine: LocalAIEngine,
    *,
    input_path: Path,
    output_path: Path,
    cache_dir: Path,
    seed: int,
    texture_resolution: int,
    timeout_seconds: float,
    log_path: Path,
    cancel_check: Callable[[], None] | None,
) -> dict:
    distro = settings.local_ai_wsl_distro
    repo = (
        "/opt/matias-ai/stable-point-aware-3d"
        if engine.key == "spar3d"
        else "/opt/matias-ai/stable-fast-3d"
    )
    python = (
        "/opt/matias-ai/spar3d-env/bin/python"
        if engine.key == "spar3d"
        else "/opt/matias-ai/sf3d-env/bin/python"
    )
    worker = "/opt/matias-ai/local_ai_worker.py"
    input_linux = _wsl_path(input_path)
    output_linux = _wsl_path(output_path)
    pid_file = output_path.with_suffix(output_path.suffix + ".pid")
    pid_linux = _wsl_path(pid_file)
    cache_linux = "/opt/matias-ai/model-cache"
    run_id = f"matias-{uuid.uuid4().hex}"

    worker_args = [
        python,
        worker,
        "--engine",
        engine.key,
        "--repo",
        repo,
        "--input",
        input_linux,
        "--output",
        output_linux,
        "--cache",
        cache_linux,
        "--seed",
        str(seed),
        "--texture-resolution",
        str(texture_resolution),
        "--run-id",
        run_id,
    ]
    if engine.low_vram:
        worker_args.append("--low-vram")

    worker_command = " ".join(shlex.quote(value) for value in worker_args)
    grouped_worker = (
        f"printf '%s' \"$$\" > {shlex.quote(pid_linux)}; "
        f"exec {worker_command}"
    )
    shell_command = (
        f"cd {shlex.quote(repo)} && "
        f"export HF_HOME={shlex.quote(cache_linux)}; "
        f"export ALPHA_CLIP_PATH={shlex.quote(cache_linux + '/alpha-clip')}; "
        f"export HF_HUB_OFFLINE=1; "
        f"export SPAR3D_LOW_VRAM={'1' if engine.low_vram else '0'}; "
        f"exec setsid --wait bash -c {shlex.quote(grouped_worker)}"
    )
    command = [
        "wsl.exe",
        "-d",
        distro,
        "--",
        "bash",
        "-lc",
        shell_command,
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    output_path.with_suffix(".partial.glb").unlink(missing_ok=True)
    try:
        returncode, duration = _run_logged_process(
            command,
            log_path=log_path,
            timeout_seconds=timeout_seconds,
            cancel_check=cancel_check,
            wsl_distro=distro,
            wsl_pid_file=pid_file,
            wsl_run_id=run_id,
        )
    finally:
        pid_file.unlink(missing_ok=True)
    if returncode != 0:
        raise _failure_detail(engine, log_path)
    if not output_path.is_file() or output_path.stat().st_size < 10_000:
        raise RuntimeError(f"{engine.label} terminou sem produzir um GLB utilizável.")
    return {
        "engine": engine.key,
        "engine_label": engine.label,
        "seed": seed,
        "duration_seconds": round(duration, 2),
    }


def run_local_ai_candidate(
    engine: LocalAIEngine,
    *,
    input_path: Path,
    output_path: Path,
    cache_dir: Path,
    seed: int,
    texture_resolution: int,
    timeout_seconds: float,
    log_path: Path,
    cancel_check: Callable[[], None] | None = None,
) -> dict:
    if settings.local_ai_runtime.strip().lower() == "wsl":
        return _run_wsl_local_ai_candidate(
            engine,
            input_path=input_path,
            output_path=output_path,
            cache_dir=cache_dir,
            seed=seed,
            texture_resolution=texture_resolution,
            timeout_seconds=timeout_seconds,
            log_path=log_path,
            cancel_check=cancel_check,
        )

    worker = PROJECT_ROOT / "scripts" / "local_ai_worker.py"
    if not worker.is_file():
        raise RuntimeError("O worker local de IA não foi encontrado.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    output_path.with_suffix(".partial.glb").unlink(missing_ok=True)
    command = [
        str(engine.python),
        str(worker),
        "--engine",
        engine.key,
        "--repo",
        str(engine.repo),
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--cache",
        str(cache_dir),
        "--seed",
        str(seed),
        "--texture-resolution",
        str(texture_resolution),
    ]
    if engine.low_vram:
        command.append("--low-vram")
    env = os.environ.copy()
    env["HF_HOME"] = str(cache_dir)
    env["ALPHA_CLIP_PATH"] = str(cache_dir / "alpha-clip")
    env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    env["SPAR3D_LOW_VRAM"] = "1" if engine.low_vram else "0"
    returncode, duration = _run_logged_process(
        command,
        log_path=log_path,
        timeout_seconds=timeout_seconds,
        cwd=engine.repo,
        env=env,
        cancel_check=cancel_check,
    )
    if returncode != 0:
        raise _failure_detail(engine, log_path)
    if not output_path.is_file() or output_path.stat().st_size < 10_000:
        raise RuntimeError(f"{engine.label} terminou sem produzir um GLB utilizável.")
    return {
        "engine": engine.key,
        "engine_label": engine.label,
        "seed": seed,
        "duration_seconds": round(duration, 2),
    }


def _as_mesh(source: Path) -> tuple[trimesh.Scene, trimesh.Trimesh]:
    loaded = trimesh.load(source, force="scene", process=False)
    scene = loaded if isinstance(loaded, trimesh.Scene) else trimesh.Scene(loaded)
    geometries = [geometry.copy() for geometry in scene.geometry.values() if len(geometry.faces)]
    mesh = trimesh.util.concatenate(geometries) if geometries else trimesh.Trimesh()
    try:
        mesh.remove_infinite_values()
        mesh.update_faces(mesh.nondegenerate_faces())
        mesh.remove_unreferenced_vertices()
        mesh.merge_vertices()
    except Exception:
        pass
    return scene, mesh


def _normalised_observed_mask(mask_path: Path, size: int = 160) -> np.ndarray:
    with Image.open(mask_path) as source:
        mask = np.asarray(source.convert("L")) > 127
    ys, xs = np.where(mask)
    canvas = Image.new("L", (size, size), 0)
    if not len(xs):
        return np.asarray(canvas) > 127
    crop = Image.fromarray((mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1] * 255).astype(np.uint8))
    crop.thumbnail((size - 14, size - 14), Image.Resampling.NEAREST)
    canvas.paste(crop, ((size - crop.width) // 2, (size - crop.height) // 2))
    return np.asarray(canvas) > 127


def _render_silhouette(mesh: trimesh.Trimesh, yaw: float, pitch: float, size: int = 160) -> np.ndarray:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if len(vertices) == 0 or len(faces) == 0:
        return np.zeros((size, size), dtype=bool)
    if len(faces) > 45_000:
        step = max(1, len(faces) // 45_000)
        faces = faces[::step]
    center = (vertices.min(axis=0) + vertices.max(axis=0)) / 2
    vertices = vertices - center
    extent = max(float(np.ptp(vertices, axis=0).max()), 1e-8)
    vertices /= extent
    cy, sy = np.cos(yaw), np.sin(yaw)
    cp, sp = np.cos(pitch), np.sin(pitch)
    rotate_y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rotate_x = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    projected = (vertices @ (rotate_x @ rotate_y).T)[:, :2]
    low = projected.min(axis=0)
    span = np.maximum(projected.max(axis=0) - low, 1e-8)
    scale = (size - 14) / float(max(span))
    screen = (projected - low) * scale + (np.array([size, size]) - span * scale) / 2
    screen[:, 1] = size - 1 - screen[:, 1]
    canvas = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(canvas)
    for triangle in screen[faces]:
        draw.polygon([(float(x), float(y)) for x, y in triangle], fill=255)
    return np.asarray(canvas) > 127


def _silhouette_similarity(observed: np.ndarray, rendered: np.ndarray) -> float:
    union = np.logical_or(observed, rendered).sum()
    if not union:
        return 0.0
    iou = float(np.logical_and(observed, rendered).sum() / union)
    row_error = float(np.mean(np.abs(observed.mean(axis=1) - rendered.mean(axis=1))))
    col_error = float(np.mean(np.abs(observed.mean(axis=0) - rendered.mean(axis=0))))
    return float(np.clip(iou * 0.78 + (1 - (row_error + col_error) / 2) * 0.22, 0, 1))


def _material_capabilities(scene: trimesh.Scene) -> dict:
    has_texture = False
    has_vertex_colors = False
    has_material = False
    for geometry in scene.geometry.values():
        visual = getattr(geometry, "visual", None)
        if visual is None:
            continue
        kind = str(getattr(visual, "kind", ""))
        has_vertex_colors = has_vertex_colors or kind == "vertex"
        material = getattr(visual, "material", None)
        has_material = has_material or material is not None
        image = getattr(material, "image", None) if material is not None else None
        has_texture = has_texture or image is not None
    mode = "uv_texture" if has_texture else "vertex_colors" if has_vertex_colors else "pbr_uniform" if has_material else "none"
    return {
        "has_texture": has_texture,
        "has_vertex_colors": has_vertex_colors,
        "has_pbr_material": has_material,
        "texture_mode": mode,
        "texture_quality_score": 90 if has_texture else 70 if has_vertex_colors else 35 if has_material else 0,
    }


def analyse_candidate(source: Path, mask_path: Path) -> dict:
    scene, mesh = _as_mesh(source)
    if len(mesh.faces) < 500 or len(mesh.vertices) < 250 or not np.isfinite(mesh.vertices).all():
        return {"score": 0.0, "usable": False, "reason": "geometria insuficiente"}
    try:
        components = list(mesh.split(only_watertight=False)) or [mesh]
    except Exception:
        components = [mesh]
    components.sort(key=lambda value: len(value.faces), reverse=True)
    face_counts = [len(value.faces) for value in components]
    total_faces = max(1, sum(face_counts))
    main_ratio = face_counts[0] / total_faces
    significant = sum(count >= max(80, total_faces * 0.002) for count in face_counts)
    observed = _normalised_observed_mask(mask_path)
    silhouette_scores = []
    for pitch_deg in (-18, 0, 18):
        for yaw_deg in range(0, 360, 20):
            rendered = _render_silhouette(mesh, np.deg2rad(yaw_deg), np.deg2rad(pitch_deg))
            silhouette_scores.append(_silhouette_similarity(observed, rendered))
            silhouette_scores.append(_silhouette_similarity(observed, np.fliplr(rendered)))
    silhouette = max(silhouette_scores) if silhouette_scores else 0.0
    materials = _material_capabilities(scene)
    component_score = max(0.0, 1.0 - max(0, significant - 8) / 28)
    geometry_score = float(np.clip(main_ratio * 72 + component_score * 28, 0, 100))
    score = float(np.clip(silhouette * 55 + geometry_score * 0.30 + materials["texture_quality_score"] * 0.15, 0, 100))
    return {
        "score": round(score, 2),
        "usable": score >= 35 and main_ratio >= 0.35,
        "vertices": int(len(mesh.vertices)),
        "triangles": int(len(mesh.faces)),
        "main_component_ratio": round(float(main_ratio), 4),
        "significant_components": int(significant),
        "visual_match_score": round(float(silhouette * 100), 1),
        "geometry_quality_score": round(geometry_score, 1),
        **materials,
    }


def select_best_candidate(candidates: list[dict], mask_path: Path) -> tuple[dict, list[dict]]:
    reports = []
    for candidate in candidates:
        report = {**candidate, **analyse_candidate(Path(candidate["path"]), mask_path)}
        reports.append(report)
    usable = [report for report in reports if report.get("usable")]
    pool = usable or reports
    if not pool:
        raise RuntimeError("Nenhum motor local produziu candidatos.")
    selected = max(pool, key=lambda value: float(value.get("score", 0)))
    if float(selected.get("score", 0)) < 20:
        raise RuntimeError("Os motores locais não produziram uma geometria suficientemente coerente.")
    return selected, reports
