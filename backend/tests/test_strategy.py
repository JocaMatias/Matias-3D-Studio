from pathlib import Path
import sys
from types import SimpleNamespace

from PIL import Image, ImageDraw
import numpy as np
import trimesh

from app.config import PROJECT_ROOT
from app.reconstruction import (
    _convert_to_glb,
    _fast_uniform_background_mask,
    _select_conditioning_view_sets,
    _select_conditioning_views,
    _semantic_handle_order,
)
from app.strategy import capture_metrics, strategy_for_images, strategy_for_project
from app.validation import photogrammetry_trackability

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from mesh_texturing import apply_multiview_vertex_colours


def test_public_strategy_has_two_clear_modes():
    assert strategy_for_images(0).key == "insufficient"
    assert strategy_for_images(1).key == "ai_generation"
    assert strategy_for_images(19).key == "ai_generation"
    assert strategy_for_images(20, "high").key == "reality_scan"


def test_explicit_modes_enforce_their_own_minimums_and_legacy_aliases():
    assert strategy_for_project("ai_generation", 1).key == "ai_generation"
    assert strategy_for_project("ai_multiview", 1).key == "ai_generation"
    assert strategy_for_project("reality_scan", 19).key == "insufficient"
    assert strategy_for_project("precision_scan", 20).key == "reality_scan"


def test_extra_ai_references_do_not_inflate_single_image_confidence():
    one = capture_metrics(1, 70, project_type="ai_generation")
    ten = capture_metrics(10, 70, project_type="ai_generation")
    scan = capture_metrics(20, 70, "high", "reality_scan")
    assert one["geometric_confidence_estimate"] == ten["geometric_confidence_estimate"]
    assert one["observed_coverage_estimate"] == 35
    assert scan["geometric_confidence_estimate"] > one["geometric_confidence_estimate"]


def test_reality_scan_remains_photogrammetry_only():
    images = [SimpleNamespace(blur_score=22.0, validation_status="approved") for _ in range(24)]
    trackability = photogrammetry_trackability(images)
    strategy = strategy_for_images(len(images), trackability["level"])
    assert strategy.key == "reality_scan"
    assert strategy.uses_photogrammetry is True
    assert strategy.uses_generative_ai is False



def test_handle_views_are_put_in_opposite_multiview_slots(tmp_path: Path):
    images = [tmp_path / f"image-{index:04d}.jpg" for index in range(4)]
    for image in images:
        Image.new("RGB", (120, 100), "white").save(image)

    def mask(index: int, side: str | None = None):
        value = Image.new("L", (120, 100), 0)
        draw = ImageDraw.Draw(value)
        draw.rectangle((30, 25, 89, 80), fill=255)
        if side == "left":
            draw.ellipse((8, 38, 42, 70), fill=255)
            draw.ellipse((15, 44, 32, 64), fill=0)
        elif side == "right":
            draw.ellipse((78, 38, 112, 70), fill=255)
            draw.ellipse((88, 44, 105, 64), fill=0)
        value.save(tmp_path / f"image-{index:04d}.mask.png")

    mask(0)
    mask(1, "left")
    mask(2)
    mask(3, "right")
    selected = _semantic_handle_order(images, tmp_path)
    assert selected == images


def test_uniform_studio_background_uses_fast_local_mask(tmp_path: Path):
    image_path = tmp_path / "studio.jpg"
    image = Image.new("RGB", (900, 900), (190, 190, 190))
    draw = ImageDraw.Draw(image)
    draw.ellipse((220, 190, 680, 690), fill=(239, 236, 232))
    draw.rounded_rectangle((650, 360, 790, 500), radius=35, fill=(236, 233, 229))
    image.save(image_path)
    mask = _fast_uniform_background_mask(image_path)
    assert mask is not None
    assert 0.15 < float(np.mean(np.asarray(mask) > 127)) < 0.5


def test_conditioning_views_keep_the_dominant_lateral_orbit(tmp_path: Path):
    images = [tmp_path / f"image-{index:04d}.jpg" for index in range(13)]
    lateral = {0, 1, 2, 3, 4, 5, 9}
    for index, image in enumerate(images):
        image.touch()
        mask = Image.new("L", (100, 100), 0)
        draw = ImageDraw.Draw(mask)
        if index in lateral:
            draw.rectangle((25, 35, 74, 64), fill=255)
        elif index < 10:
            draw.rectangle((25, 20, 74, 74), fill=255)
        else:
            draw.rectangle((28, 15, 72, 79), fill=255)
        mask.save(tmp_path / f"{image.stem}.mask.png")

    selected = _select_conditioning_views(images, tmp_path, 4)
    assert [image.name for image in selected] == [
        "image-0000.jpg",
        "image-0002.jpg",
        "image-0004.jpg",
        "image-0009.jpg",
    ]


def test_conditioning_view_sets_use_distinct_parts_of_a_full_orbit(tmp_path: Path):
    images = [tmp_path / f"image-{index:04d}.jpg" for index in range(16)]
    for index, image in enumerate(images):
        Image.new("RGB", (96, 96), (180 + index, 180, 180)).save(image)
        mask = Image.new("L", (96, 96), 0)
        ImageDraw.Draw(mask).ellipse((18 + index % 3, 20, 76, 78), fill=255)
        mask.save(tmp_path / f"{image.stem}.mask.png")

    groups = _select_conditioning_view_sets(images, tmp_path, set_count=3, limit=4)

    assert len(groups) == 3
    assert all(len(set(group)) == 4 for group in groups)
    assert len({tuple(group) for group in groups}) == 3
    assert len({image for group in groups for image in group}) >= 8


def test_multiview_colours_survive_glb_normalization(tmp_path: Path):
    mesh = trimesh.creation.icosphere(subdivisions=2)
    views = [
        Image.new("RGBA", (64, 64), color)
        for color in ("red", "green", "blue", "gold")
    ]
    apply_multiview_vertex_colours(
        mesh,
        views,
        np.array([220, 220, 220, 255], dtype=np.uint8),
    )
    source = tmp_path / "coloured-source.glb"
    output = tmp_path / "coloured-normalized.glb"
    mesh.export(source)
    _convert_to_glb(source, output)

    scene = trimesh.load(output, force="scene", process=False)
    colours = np.concatenate(
        [geometry.visual.vertex_colors[:, :3] for geometry in scene.geometry.values()],
        axis=0,
    )
    assert len(np.unique(colours, axis=0)) >= 3
    assert not np.all(colours == 255)
