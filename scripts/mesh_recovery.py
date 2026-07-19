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


def _dominant_sheet_ratio(mesh: trimesh.Trimesh) -> float:
    """Detect a thin, connected ground sheet hidden inside one component.

    Component counting misses a generated floor when it touches the object.  A
    volumetric object should not devote two adjacent, opposite-facing planar
    layers to a large fraction of its complete surface area.  Thin legitimate
    objects are excluded by the extent-ratio guard.
    """
    if len(mesh.faces) < 12 or float(mesh.area) <= 1e-9:
        return 0.0
    extents = np.maximum(np.asarray(mesh.extents, dtype=float), 1e-9)
    centers = np.asarray(mesh.triangles_center, dtype=float)
    normals = np.asarray(mesh.face_normals, dtype=float)
    areas = np.asarray(mesh.area_faces, dtype=float)
    total_area = float(areas.sum())
    best = 0.0
    bins = 48
    for axis in range(3):
        if float(extents[axis] / extents.max()) < 0.25:
            continue
        aligned = np.abs(normals[:, axis]) >= 0.985
        if int(aligned.sum()) < 4:
            continue
        low, high = mesh.bounds[:, axis]
        if high - low <= 1e-9:
            continue
        histogram = np.histogram(
            centers[aligned, axis],
            bins=bins,
            range=(float(low), float(high)),
            weights=areas[aligned],
        )[0]
        positive = aligned & (normals[:, axis] > 0)
        negative = aligned & (normals[:, axis] < 0)
        positive_histogram = np.histogram(
            centers[positive, axis],
            bins=bins,
            range=(float(low), float(high)),
            weights=areas[positive],
        )[0]
        negative_histogram = np.histogram(
            centers[negative, axis],
            bins=bins,
            range=(float(low), float(high)),
            weights=areas[negative],
        )[0]
        for index in range(bins):
            front = float(positive_histogram[index] / total_area)
            back = float(negative_histogram[index] / total_area)
            if front >= 0.05 and back >= 0.05:
                best = max(best, front + back)
        for index in range(bins - 1):
            first = float(histogram[index] / total_area)
            second = float(histogram[index + 1] / total_area)
            if first >= 0.05 and second >= 0.05:
                best = max(best, first + second)
    return best


def topology_report(mesh: trimesh.Trimesh | trimesh.Scene) -> TopologyReport:
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
            dominant_sheet_ratio=_dominant_sheet_ratio(probe),
            euler_number=int(main.euler_number),
            watertight=bool(main.is_watertight),
        )
    except Exception:
        return TopologyReport(0.0, 999, False, 0.0, 2, False)


def repair_candidate(
    mesh: trimesh.Trimesh | trimesh.Scene,
    *,
    minimum_component_faces: int = 80,
    relative_component_size: float = 0.012,
    maximum_components: int = 32,
) -> tuple[trimesh.Trimesh, dict]:
    """Weld a candidate and remove tiny floating islands without hiding failure."""
    cleaned = sanitize_mesh(mesh)
    before = topology_report(cleaned)
    if not len(cleaned.faces):
        return cleaned, {"changed": False, "before": before.as_dict(), "after": before.as_dict()}
    if (
        before.main_face_ratio >= 0.92
        and before.significant_components <= 8
        and not before.secondary_planar_component
        and before.dominant_sheet_ratio < 0.20
    ):
        return cleaned, {"changed": False, "before": before.as_dict(), "after": before.as_dict()}

    try:
        components = list(cleaned.split(only_watertight=False))
        components.sort(key=lambda component: len(component.faces), reverse=True)
        largest_faces = max(1, len(components[0].faces))
        threshold = max(minimum_component_faces, int(largest_faces * relative_component_size))
        retained = [component for component in components if len(component.faces) >= threshold]
        retained = retained[:maximum_components] or components[:1]
        repaired = sanitize_mesh(trimesh.util.concatenate(retained))
        # Fill only small/simple boundary loops. trimesh's implementation will
        # leave complex openings untouched instead of inventing large surfaces.
        try:
            trimesh.repair.fill_holes(repaired)
            trimesh.repair.fix_normals(repaired, multibody=True)
        except Exception:
            pass
    except Exception:
        repaired = cleaned

    after = topology_report(repaired)
    return repaired, {
        "changed": bool(len(repaired.faces) != len(cleaned.faces) or after != before),
        "before": before.as_dict(),
        "after": after.as_dict(),
    }


def is_usable_topology(details: dict, score: float) -> bool:
    """Conservative acceptance rule shared by generation and recovery paths."""
    return not (
        score < 35
        or float(details.get("main_face_ratio", 0)) < 0.45
        or bool(details.get("secondary_planar_component", False))
        or float(details.get("dominant_sheet_ratio", 0.0)) >= 0.20
        or (
            int(details.get("significant_components", 999)) > 24
            and float(details.get("main_face_ratio", 0)) < 0.80
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
