from pathlib import Path
import sys

import numpy as np
import trimesh


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from mesh_recovery import (  # noqa: E402
    build_estimated_proxy,
    is_usable_topology,
    repair_candidate,
    sanitize_mesh,
    topology_report,
)


def test_sanitize_welds_coincident_vertices_into_one_component():
    box = trimesh.creation.box()
    duplicated = trimesh.Trimesh(
        vertices=box.vertices[box.faces].reshape((-1, 3)),
        faces=np.arange(len(box.faces) * 3).reshape((-1, 3)),
        process=False,
    )

    cleaned = sanitize_mesh(duplicated)
    report = topology_report(cleaned)

    assert len(cleaned.vertices) == len(box.vertices)
    assert report.main_face_ratio == 1.0
    assert report.significant_components == 1


def test_repair_removes_small_floating_islands():
    main = trimesh.creation.icosphere(subdivisions=3)
    islands = []
    for index in range(16):
        island = trimesh.creation.box(extents=(0.02, 0.02, 0.02))
        island.apply_translation((3 + index * 0.1, 0, 0))
        islands.append(island)
    fragmented = trimesh.util.concatenate([main, *islands])

    repaired, details = repair_candidate(fragmented)
    report = topology_report(repaired)

    assert details["changed"] is True
    assert report.main_face_ratio > 0.99
    assert report.significant_components == 1


def test_estimated_proxy_is_dense_watertight_and_usable():
    fragments = []
    for index in range(12):
        fragment = trimesh.creation.icosphere(subdivisions=1, radius=0.12)
        fragment.apply_translation((index * 0.18, (index % 3) * 0.1, 0))
        fragments.append(fragment)
    source = trimesh.util.concatenate(fragments)

    proxy, mode = build_estimated_proxy(source, expected_aspect=1.7)
    report = topology_report(proxy)

    assert mode == "convex_hull_proxy"
    assert len(proxy.faces) >= 1200
    assert proxy.is_watertight
    assert report.main_face_ratio == 1.0
    assert is_usable_topology(report.as_dict(), 60)


def test_estimated_proxy_falls_back_without_source_geometry():
    proxy, mode = build_estimated_proxy(None, expected_aspect=1.4)

    assert mode == "ellipsoid_proxy"
    assert len(proxy.faces) >= 1000
    assert proxy.is_watertight


def test_topology_report_detects_a_large_ground_sheet():
    body = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    sheet = trimesh.creation.box(extents=(2.4, 0.04, 2.4))
    sheet.apply_translation((0.0, -0.52, 0.0))
    contaminated = trimesh.util.concatenate([body, sheet])

    report = topology_report(contaminated)

    assert report.dominant_sheet_ratio >= 0.20
    assert not is_usable_topology(report.as_dict(), 90)


def test_topology_report_does_not_call_a_regular_box_a_sheet():
    report = topology_report(trimesh.creation.box(extents=(1.0, 1.0, 1.0)))

    assert report.dominant_sheet_ratio < 0.20


def test_volumetric_gate_rejects_a_card_thin_result_even_for_thin_parts():
    details = topology_report(
        trimesh.creation.box(extents=(1.0, 0.25, 0.008)),
        "thin_parts",
    ).as_dict()
    details["volumetric_depth_ratio"] = 0.032

    assert not is_usable_topology(details, 95, "thin_parts")


def test_texture_depth_buffer_rejects_an_occluded_surface():
    from scripts.mesh_texturing import _rasterized_view_depth, _visible_in_view

    vertices = np.array(
        [
            [0.0, 0.0, 0.2], [1.0, 0.0, 0.2], [1.0, 1.0, 0.2], [0.0, 1.0, 0.2],
            [0.0, 0.0, 0.8], [1.0, 0.0, 0.8], [1.0, 1.0, 0.8], [0.0, 1.0, 0.8],
        ],
        dtype=np.float32,
    )
    faces = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]], dtype=np.int64)
    direction = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    depth = _rasterized_view_depth(vertices, faces, direction, 0, False, 96)
    samples = np.array([[0.5, 0.5, 0.2], [0.5, 0.5, 0.8]], dtype=np.float32)

    visible = _visible_in_view(samples, direction, 0, False, depth)

    assert visible.tolist() == [False, True]


def test_texture_alpha_removes_white_backdrop_and_soft_shadow():
    from scripts.mesh_texturing import _texture_subject_alpha

    rgba = np.full((80, 100, 4), 255, dtype=np.uint8)
    rgba[48:66, 20:80, :3] = 220  # permissive geometry mask includes a cast shadow
    rgba[20:48, 34:66, :3] = [190, 35, 28]

    subject = _texture_subject_alpha(rgba)

    assert subject[30, 50]
    assert not subject[5, 5]
    assert not subject[60, 50]
