from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh


def _scene_meshes(scene: trimesh.Scene) -> list[trimesh.Trimesh]:
    return [geometry for geometry in scene.geometry.values() if isinstance(geometry, trimesh.Trimesh) and len(geometry.faces)]


def _material_capabilities(scene: trimesh.Scene) -> dict:
    has_uv = False
    has_texture = False
    has_vertex_colors = False
    has_pbr_material = False
    modes: set[str] = set()
    for geometry in _scene_meshes(scene):
        visual = geometry.visual
        kind = getattr(visual, "kind", None)
        uv = getattr(visual, "uv", None)
        if uv is not None and len(uv) == len(geometry.vertices):
            has_uv = True
        colours = getattr(visual, "vertex_colors", None)
        if kind == "vertex" and colours is not None and len(colours) == len(geometry.vertices):
            has_vertex_colors = True
            modes.add("vertex_colors")
        material = getattr(visual, "material", None)
        if material is not None:
            has_pbr_material = True
            texture = getattr(material, "baseColorTexture", None) or getattr(material, "image", None)
            if texture is not None:
                has_texture = True
                modes.add("uv_texture")
            else:
                modes.add("pbr_uniform")
    if has_texture:
        texture_mode = "uv_texture"
    elif has_vertex_colors:
        texture_mode = "vertex_colors"
    elif has_pbr_material:
        texture_mode = "pbr_uniform"
    else:
        texture_mode = "none"
    return {
        "has_uv": has_uv,
        "has_texture": has_texture,
        "has_vertex_colors": has_vertex_colors,
        "has_pbr_material": has_pbr_material,
        "texture_coverage": 100 if has_texture and has_uv else (100 if has_vertex_colors else 0),
        "texture_mode": texture_mode,
        "detected_material_modes": sorted(modes),
    }


def _ground_sheet_ratio(mesh: trimesh.Trimesh, object_profile: str) -> float:
    if object_profile == "architecture" or len(mesh.faces) < 12 or float(mesh.area) <= 1e-9:
        return 0.0
    extents = np.maximum(np.asarray(mesh.extents, dtype=float), 1e-9)
    if float(extents[1] / extents.max()) < 0.12:
        return 0.0
    centers = np.asarray(mesh.triangles_center, dtype=float)
    normals = np.asarray(mesh.face_normals, dtype=float)
    areas = np.asarray(mesh.area_faces, dtype=float)
    low, high = mesh.bounds[:, 1]
    span = float(high - low)
    if span <= 1e-9:
        return 0.0
    relevant = (np.abs(normals[:, 1]) >= 0.985) & (centers[:, 1] <= low + span * 0.18)
    total = max(float(areas.sum()), 1e-9)
    up = float(areas[relevant & (normals[:, 1] > 0)].sum() / total)
    down = float(areas[relevant & (normals[:, 1] < 0)].sum() / total)
    return up + down if up >= 0.045 and down >= 0.045 else 0.0


def inspect_model(glb_path: Path, engine_metrics: dict | None = None, object_profile: str = "auto") -> dict:
    metrics = engine_metrics or {}
    warnings: list[str] = []
    blocking: list[str] = []
    try:
        scene = trimesh.load(str(glb_path), force="scene", process=False)
    except Exception as error:
        return {
            "quality_status": "quality_check_failed",
            "geometry_quality_score": 0,
            "visual_match_score": None,
            "texture_quality_score": None,
            "file_integrity_score": 0,
            "quality_score": 0,
            "warnings": [],
            "blocking_issues": [f"O GLB não pôde ser lido: {error}"],
            "material_capabilities": {
                "has_uv": False, "has_texture": False, "has_vertex_colors": False,
                "has_pbr_material": False, "texture_coverage": 0, "texture_mode": "none",
            },
        }

    geometries = _scene_meshes(scene)
    if not geometries:
        blocking.append("O GLB não contém uma mesh utilizável.")
        vertices = triangles = 0
        mesh = trimesh.Trimesh()
        components: list[trimesh.Trimesh] = []
    else:
        mesh = trimesh.util.concatenate(geometries)
        vertices = int(sum(len(value.vertices) for value in geometries))
        triangles = int(sum(len(value.faces) for value in geometries))
        try:
            components = list(mesh.split(only_watertight=False)) or [mesh]
        except Exception:
            components = [mesh]

    capabilities = _material_capabilities(scene)
    if not capabilities["has_texture"] and not capabilities["has_vertex_colors"]:
        warnings.append("Esta versão não contém textura fotográfica; usa apenas um material uniforme.")

    if vertices < 4 or triangles < 2:
        blocking.append("A geometria é insuficiente para representar um objeto 3D.")
    finite = bool(len(mesh.vertices) and np.isfinite(mesh.vertices).all())
    if not finite:
        blocking.append("A mesh contém coordenadas inválidas.")

    face_counts = sorted((int(len(component.faces)) for component in components), reverse=True)
    total_faces = max(1, sum(face_counts))
    main_ratio = face_counts[0] / total_faces if face_counts else 0.0
    significant_threshold = max(20, int(total_faces * (0.0003 if object_profile in {"mechanical", "thin_parts", "multi_component", "architecture"} else 0.002)))
    significant_components = sum(value >= significant_threshold for value in face_counts)
    sheet_ratio = _ground_sheet_ratio(mesh, object_profile) if len(mesh.faces) else 0.0
    if sheet_ratio >= 0.20:
        blocking.append("Foi detetada uma superfície larga e fina junto à base, semelhante a chão/fundo reconstruído.")
    if significant_components > (96 if object_profile in {"mechanical", "thin_parts", "multi_component", "architecture"} else 28) and main_ratio < 0.72:
        warnings.append("A mesh está muito fragmentada e deve ser revista.")

    geometry_score = 100.0
    geometry_score -= max(0.0, 0.82 - main_ratio) * (48 if object_profile not in {"mechanical", "multi_component", "thin_parts", "architecture"} else 24)
    geometry_score -= min(35.0, max(0, significant_components - 8) * (0.65 if object_profile in {"mechanical", "multi_component", "thin_parts", "architecture"} else 1.8))
    geometry_score -= min(55.0, sheet_ratio * 180.0)
    if triangles < 1000:
        geometry_score -= 35
    if not finite:
        geometry_score = 0
    geometry_score = int(np.clip(round(geometry_score), 0, 100))

    silhouette = metrics.get("silhouette_evidence")
    visual_match = None
    if isinstance(silhouette, (int, float)) and float(silhouette) > 0:
        visual_match = int(np.clip(round(float(silhouette) * 100), 0, 100))
    elif isinstance(metrics.get("candidate_score"), (int, float)):
        visual_match = int(np.clip(round(float(metrics["candidate_score"]) * 0.72), 0, 80))

    if capabilities["has_texture"]:
        texture_score = 90 if capabilities["has_uv"] else 70
    elif capabilities["has_vertex_colors"]:
        texture_score = 68
    elif capabilities["has_pbr_material"]:
        texture_score = 25
    else:
        texture_score = None

    file_integrity = 100 if finite and vertices >= 4 and triangles >= 2 else 0
    result_tier = str(metrics.get("result_tier", ""))
    if result_tier == "estimated":
        geometry_score = min(geometry_score, 35)
        if visual_match is not None:
            visual_match = min(visual_match, 35)
        warnings.append("A geometria é uma aproximação estimada, não uma reconstrução detalhada comprovada.")

    if blocking:
        status = "quality_check_failed"
    elif geometry_score < 45 or sheet_ratio >= 0.15 or (significant_components > 40 and main_ratio < 0.65):
        status = "review_required"
    elif warnings or geometry_score < 72 or texture_score in {None, 25}:
        status = "approved_with_warnings"
    else:
        status = "approved"

    scored = [geometry_score, file_integrity]
    weights = [0.48, 0.17]
    if visual_match is not None:
        scored.append(visual_match); weights.append(0.25)
    if texture_score is not None:
        scored.append(texture_score); weights.append(0.10)
    quality_score = int(round(sum(value * weight for value, weight in zip(scored, weights)) / sum(weights)))
    if status == "quality_check_failed":
        quality_score = min(quality_score, 25)
    elif status == "review_required":
        quality_score = min(quality_score, 55)
    if result_tier == "estimated":
        quality_score = min(quality_score, 35)

    return {
        "quality_status": status,
        "geometry_quality_score": geometry_score,
        "visual_match_score": visual_match,
        "texture_quality_score": texture_score,
        "file_integrity_score": file_integrity,
        "quality_score": quality_score,
        "warnings": warnings,
        "blocking_issues": blocking,
        "material_capabilities": capabilities,
        "mesh_analysis": {
            "vertices": vertices,
            "triangles": triangles,
            "main_component_ratio": round(main_ratio, 4),
            "significant_components": significant_components,
            "dominant_ground_sheet_ratio": round(sheet_ratio, 4),
            "object_profile": object_profile,
        },
    }
