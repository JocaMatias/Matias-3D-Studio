from pathlib import Path
import sys

import numpy as np
import trimesh
from PIL import Image, ImageDraw

from app.image_consistency import describe_image, descriptor_similarity
from app.quality_control import inspect_model

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from mesh_recovery import repair_candidate, topology_report  # noqa: E402
from mesh_texturing import apply_pbr_material, estimate_base_colour  # noqa: E402


def _shape(kind: str, colour=(190, 40, 35), background=(245, 245, 245), light=1.0) -> Image.Image:
    image = Image.new("RGB", (256, 256), background)
    draw = ImageDraw.Draw(image)
    adjusted = tuple(min(255, round(channel * light)) for channel in colour)
    if kind == "circle":
        draw.ellipse((55, 45, 201, 211), fill=adjusted)
    elif kind == "wing":
        draw.polygon(((20, 120), (118, 82), (236, 120), (118, 147)), fill=adjusted)
        draw.rectangle((104, 72, 132, 205), fill=adjusted)
    else:
        draw.rectangle((68, 45, 188, 211), fill=adjusted)
    return image


def test_consistency_uses_shape_more_than_equal_colours():
    circle = describe_image(_shape("circle"))
    wing = describe_image(_shape("wing"))
    same_shape_new_light = describe_image(_shape("circle", light=0.72))

    assert descriptor_similarity(circle, same_shape_new_light) > 62
    assert descriptor_similarity(circle, wing) < descriptor_similarity(circle, same_shape_new_light) - 15


def test_base_colour_preserves_red_instead_of_white_highlights():
    image = Image.new("RGBA", (256, 256), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((30, 30, 226, 226), fill=(190, 45, 35, 255))
    draw.ellipse((70, 50, 135, 105), fill=(255, 245, 245, 255))

    colour = estimate_base_colour([image])

    assert int(colour[0]) > int(colour[1]) * 2
    assert int(colour[0]) > int(colour[2]) * 2
    assert int(colour[0]) < 235


def test_mechanical_repair_preserves_small_nearby_parts():
    body = trimesh.creation.box(extents=(1.0, 0.55, 0.45))
    wheel = trimesh.creation.icosphere(subdivisions=1, radius=0.09)
    wheel.apply_translation((0.42, -0.34, 0.22))
    remote_noise = trimesh.creation.box(extents=(0.02, 0.02, 0.02))
    remote_noise.apply_translation((4.0, 0.0, 0.0))
    source = trimesh.util.concatenate((body, wheel, remote_noise))

    repaired, details = repair_candidate(source, object_profile="mechanical")
    components = repaired.split(only_watertight=False)

    assert details["changed"] is True
    assert len(components) >= 2
    assert len(details["removed_components"]) == 1


def test_central_wing_is_not_classified_as_ground_sheet():
    fuselage = trimesh.creation.box(extents=(0.35, 1.3, 0.35))
    wing = trimesh.creation.box(extents=(2.4, 0.04, 0.75))
    wing.apply_translation((0.0, 0.1, 0.0))
    aircraft = trimesh.util.concatenate((fuselage, wing))

    report = topology_report(aircraft, object_profile="mechanical")

    assert report.dominant_sheet_ratio < 0.20


def test_quality_control_does_not_call_uniform_pbr_a_texture(tmp_path: Path):
    mesh = trimesh.creation.icosphere(subdivisions=2)
    apply_pbr_material(mesh, np.array([190, 45, 35, 255], dtype=np.uint8))
    output = tmp_path / "uniform.glb"
    output.write_bytes(mesh.export(file_type="glb"))

    report = inspect_model(output, {"candidate_score": 80}, "compact")

    capabilities = report["material_capabilities"]
    assert capabilities["has_pbr_material"] is True
    assert capabilities["has_texture"] is False
    assert capabilities["texture_mode"] == "pbr_uniform"
    assert report["texture_quality_score"] == 25

from app.mask_quality import analyse_mask  # noqa: E402


def test_mask_quality_blocks_wide_base_plane():
    mask = Image.new("L", (200, 200), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((65, 45, 135, 145), fill=255)
    draw.rectangle((10, 155, 190, 199), fill=255)

    report = analyse_mask(mask, "compact")

    assert report["status"] == "invalid"
    assert report["likely_base_plane"] is True


def test_mask_quality_allows_separate_mechanical_parts():
    mask = Image.new("L", (200, 200), 0)
    draw = ImageDraw.Draw(mask)
    draw.rectangle((55, 65, 145, 130), fill=255)
    draw.ellipse((48, 125, 72, 149), fill=255)
    draw.ellipse((128, 125, 152, 149), fill=255)

    report = analyse_mask(mask, "mechanical")

    assert report["status"] != "invalid"
