"""Defensive mesh cleanup and last-resort geometry recovery.

The reconstruction worker uses these helpers before it rejects a generative
candidate.  The operations are intentionally deterministic and independent of
the diffusion model so they can also be unit tested on machines without CUDA.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh


@dataclass(frozen=True)
class RepairPolicy:
    minimum_component_faces: int
    relative_component_size: float
    maximum_components: int
    nearby_gap_ratio: float
    fill_holes: bool
    penalize_ground_sheets: bool


def repair_policy(object_profile: str = "auto") -> RepairPolicy:
    policies = {
        "compact": RepairPolicy(50, 0.006, 24, 0.055, True, True),
        "handled_container": RepairPolicy(24, 0.0015, 64, 0.14, False, True),
        "thin_parts": RepairPolicy(8, 0.0002, 192, 0.32, False, True),
        "multi_component": RepairPolicy(8, 0.00015, 256, 0.38, False, True),
        "mechanical": RepairPolicy(16, 0.00025, 192, 0.34, False, True),
        "organic": RepairPolicy(24, 0.0012, 72, 0.15, False, True),
        "architecture": RepairPolicy(8, 0.00015, 256, 0.35, False, False),
        "auto": RepairPolicy(20, 0.0008, 96, 0.16, False, True),
    }
    return policies.get(object_profile, policies["auto"])


@dataclass(frozen=True)
class TopologyReport:
    main_face_ratio: float
    significant_components: int
    secondary_planar_component: bool
    dominant_sheet_ratio: float
    euler_number: int
    watertight: bool

    def as_dict(self) -> dict:
        return {
            "main_face_ratio": round(self.main_face_ratio, 4),
            "significant_components": self.significant_components,
            "secondary_planar_component": self.secondary_planar_component,
            "dominant_sheet_ratio": round(self.dominant_sheet_ratio, 4),
            "euler_number": self.euler_number,
            "watertight": self.watertight,
        }


def _as_mesh(mesh: trimesh.Trimesh | trimesh.Scene) -> trimesh.Trimesh:
    if isinstance(mesh, trimesh.Scene):
        geometries = [geometry for geometry in mesh.geometry.values() if len(geometry.faces)]
        if not geometries:
            return trimesh.Trimesh()
        return trimesh.util.concatenate(geometries)
    return mesh.copy()


def sanitize_mesh(mesh: trimesh.Trimesh | trimesh.Scene) -> trimesh.Trimesh:
    """Remove invalid geometry and weld coincident marching-cubes vertices."""
    cleaned = _as_mesh(mesh)
    if not len(cleaned.vertices) or not len(cleaned.faces):
        return cleaned
    try:
        cleaned.remove_infinite_values()
        cleaned.update_faces(cleaned.nondegenerate_faces())
        cleaned.update_faces(cleaned.unique_faces())
        cleaned.remove_unreferenced_vertices()
        # Hunyuan's marching-cubes output can contain coincident vertices that
        # make a continuous surface look like thousands of disconnected parts.
        cleaned.merge_vertices(merge_tex=True, merge_norm=True)
        cleaned.remove_unreferenced_vertices()
        trimesh.repair.fix_normals(cleaned, multibody=True)
    except Exception:
        # Cleanup is best-effort. The caller still validates the returned mesh.
        pass
    return cleaned


def _dominant_sheet_ratio(mesh: trimesh.Trimesh, object_profile: str = "auto") -> float:
    """Detect a likely generated floor near the lower Y boundary.

    A central thin surface can be a wing, shelf or architectural slab.  Only a
    broad, paired sheet near the lower boundary is treated as floor evidence.
    """
    if object_profile == "architecture" or len(mesh.faces) < 12 or float(mesh.area) <= 1e-9:
        return 0.0
    extents = np.maximum(np.asarray(mesh.extents, dtype=float), 1e-9)
    if float(extents[1] / extents.max()) < 0.12:
        return 0.0
    centers = np.asarray(mesh.triangles_center, dtype=float)
    normals = np.asarray(mesh.face_normals, dtype=float)
    areas = np.asarray(mesh.area_faces, dtype=float)
    total_area = float(areas.sum())
    low, high = mesh.bounds[:, 1]
    span = float(high - low)
    if span <= 1e-9:
        return 0.0
    aligned = np.abs(normals[:, 1]) >= 0.985
    lower = centers[:, 1] <= low + span * 0.18
    relevant = aligned & lower
    if int(relevant.sum()) < 4:
        return 0.0
    positive = relevant & (normals[:, 1] > 0)
    negative = relevant & (normals[:, 1] < 0)
    positive_area = float(areas[positive].sum() / total_area)
    negative_area = float(areas[negative].sum() / total_area)
    if positive_area >= 0.045 and negative_area >= 0.045:
        return positive_area + negative_area
    return 0.0


def topology_report(mesh: trimesh.Trimesh | trimesh.Scene, object_profile: str = "auto") -> TopologyReport:
    """Measure topology after welding, avoiding false fragmentation reports."""
    probe = sanitize_mesh(mesh)
    if not len(probe.faces):
        return TopologyReport(0.0, 999, False, 0.0, 2, False)
    try:
        if len(probe.faces) > 60_000:
            try:
                probe = sanitize_mesh(probe.simplify_quadric_decimation(face_count=40_000))
            except Exception:
                pass
        components = list(probe.split(only_watertight=False))
        if not components:
            components = [probe]
        components.sort(key=lambda component: len(component.faces), reverse=True)
        face_counts = [int(len(component.faces)) for component in components]
        total_faces = max(1, sum(face_counts))
        main = components[0]
        main_ratio = face_counts[0] / total_faces
        significant = max(1, sum(faces >= max(80, total_faces * 0.002) for faces in face_counts))
        secondary_planar = False
        for component in components[1:]:
            if len(component.faces) < total_faces * 0.025:
                continue
            extents = np.maximum(np.asarray(component.extents, dtype=float), 1e-6)
            if float(extents.min() / extents.max()) < 0.025:
                secondary_planar = True
                break
        return TopologyReport(
            main_face_ratio=float(main_ratio),
            significant_components=int(significant),
            secondary_planar_component=secondary_planar,
            dominant_sheet_ratio=_dominant_sheet_ratio(probe, object_profile),
            euler_number=int(main.euler_number),
            watertight=bool(main.is_watertight),
        )
    except Exception:
        return TopologyReport(0.0, 999, False, 0.0, 2, False)


def _bbox_gap(left: trimesh.Trimesh, right: trimesh.Trimesh) -> float:
    left_min, left_max = np.asarray(left.bounds[0]), np.asarray(left.bounds[1])
    right_min, right_max = np.asarray(right.bounds[0]), np.asarray(right.bounds[1])
    gap = np.maximum(0.0, np.maximum(left_min - right_max, right_min - left_max))
    return float(np.linalg.norm(gap))


def repair_candidate(
    mesh: trimesh.Trimesh | trimesh.Scene,
    *,
    object_profile: str = "auto",
    minimum_component_faces: int | None = None,
    relative_component_size: float | None = None,
    maximum_components: int | None = None,
) -> tuple[trimesh.Trimesh, dict]:
    """Weld a candidate and remove only unsupported, distant islands.

    Small components close to the main object are preserved for mechanical and
    thin-part profiles because they can be wheels, blades, bars or decorations.
    """
    policy = repair_policy(object_profile)
    minimum_component_faces = policy.minimum_component_faces if minimum_component_faces is None else minimum_component_faces
    relative_component_size = policy.relative_component_size if relative_component_size is None else relative_component_size
    maximum_components = policy.maximum_components if maximum_components is None else maximum_components
    cleaned = sanitize_mesh(mesh)
    before = topology_report(cleaned, object_profile)
    if not len(cleaned.faces):
        return cleaned, {"changed": False, "profile": object_profile, "removed_components": [], "before": before.as_dict(), "after": before.as_dict()}

    try:
        components = list(cleaned.split(only_watertight=False))
        components.sort(
            key=lambda component: (float(component.area), float(np.prod(np.maximum(component.extents, 1e-9))), len(component.faces)),
            reverse=True,
        )
        main = components[0]
        largest_faces = max(1, len(main.faces))
        threshold = max(minimum_component_faces, int(largest_faces * relative_component_size))
        diagonal = max(float(np.linalg.norm(main.extents)), 1e-8)
        retained = [main]
        removed = []
        for index, component in enumerate(components[1:], start=1):
            faces = int(len(component.faces))
            gap_ratio = _bbox_gap(main, component) / diagonal
            supported_by_size = faces >= threshold
            supported_by_proximity = gap_ratio <= policy.nearby_gap_ratio and faces >= minimum_component_faces
            if supported_by_size or supported_by_proximity:
                retained.append(component)
            else:
                removed.append({"index": index, "faces": faces, "gap_ratio": round(gap_ratio, 5), "reason": "small_and_distant"})
        retained = retained[:maximum_components]
        repaired = sanitize_mesh(trimesh.util.concatenate(retained))
        if policy.fill_holes:
            try:
                trimesh.repair.fill_holes(repaired)
                trimesh.repair.fix_normals(repaired, multibody=True)
            except Exception:
                pass
    except Exception:
        repaired = cleaned
        removed = []

    after = topology_report(repaired, object_profile)
    return repaired, {
        "changed": bool(len(repaired.faces) != len(cleaned.faces) or after != before),
        "profile": object_profile,
        "removed_components": removed,
        "before": before.as_dict(),
        "after": after.as_dict(),
    }


def is_usable_topology(details: dict, score: float, object_profile: str = "auto") -> bool:
    """Conservative acceptance rule shared by generation and recovery paths."""
    policy = repair_policy(object_profile)
    component_limit = policy.maximum_components
    sheet_failure = policy.penalize_ground_sheets and float(details.get("dominant_sheet_ratio", 0.0)) >= 0.20
    return not (
        score < 35
        or float(details.get("main_face_ratio", 0)) < (0.30 if object_profile in {"mechanical", "multi_component", "thin_parts", "architecture"} else 0.45)
        or (bool(details.get("secondary_planar_component", False)) and object_profile not in {"architecture", "mechanical", "thin_parts"})
        or sheet_failure
        or (
            int(details.get("significant_components", 999)) > component_limit
            and float(details.get("main_face_ratio", 0)) < 0.55
        )
    )


def _robust_vertices(mesh: trimesh.Trimesh | trimesh.Scene | None) -> np.ndarray:
    if mesh is None:
        return np.empty((0, 3), dtype=float)
    cleaned = sanitize_mesh(mesh)
    vertices = np.asarray(cleaned.vertices, dtype=float)
    vertices = vertices[np.isfinite(vertices).all(axis=1)]
    if len(vertices) < 8:
        return vertices
    low, high = np.percentile(vertices, [0.25, 99.75], axis=0)
    inside = np.logical_and(vertices >= low, vertices <= high).all(axis=1)
    trimmed = vertices[inside]
    return trimmed if len(trimmed) >= 8 else vertices


def build_estimated_proxy(
    mesh: trimesh.Trimesh | trimesh.Scene | None,
    expected_aspect: float,
) -> tuple[trimesh.Trimesh, str]:
    """Return a guaranteed renderable proxy when every generated mesh is unsafe.

    A convex hull preserves the candidate's overall occupied volume while
    removing floating sheets and self-intersections.  If even that cannot be
    built, an ellipsoid communicates the estimated bounding volume without
    pretending that unsupported detail was reconstructed.
    """
    vertices = _robust_vertices(mesh)
    if len(vertices) >= 8:
        try:
            proxy = sanitize_mesh(trimesh.convex.convex_hull(vertices))
            if len(proxy.faces) >= 12 and np.isfinite(proxy.vertices).all():
                while len(proxy.faces) < 1200:
                    subdivided_vertices, subdivided_faces = trimesh.remesh.subdivide(
                        proxy.vertices, proxy.faces
                    )
                    proxy = trimesh.Trimesh(
                        vertices=subdivided_vertices,
                        faces=subdivided_faces,
                        process=False,
                    )
                return sanitize_mesh(proxy), "convex_hull_proxy"
        except Exception:
            pass

    proxy = trimesh.creation.icosphere(subdivisions=4, radius=1.0)
    aspect = float(np.clip(expected_aspect, 0.45, 3.2))
    # Hunyuan uses Y as the upright axis. Preserve the expected silhouette
    # ratio while keeping a neutral depth for unknown views.
    width = max(0.55, aspect)
    proxy.apply_scale([width, 1.0, max(0.55, min(width, 1.15))])
    return sanitize_mesh(proxy), "ellipsoid_proxy"
