from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw
import numpy as np

from app.reconstruction import _fast_uniform_background_mask, _select_conditioning_views, _semantic_handle_order
from app.strategy import capture_metrics, strategy_for_images
from app.validation import photogrammetry_trackability


def test_progressive_strategy_thresholds():
    assert strategy_for_images(4).key == "insufficient"
    assert strategy_for_images(5).key == "ai_multiview"
    assert strategy_for_images(10).key == "ai_multiview"
    assert strategy_for_images(11).key == "ai_refined"
    assert strategy_for_images(19).key == "ai_refined"
    assert strategy_for_images(20).key == "ai_refined"
    assert strategy_for_images(20, "low").key == "ai_refined"
    assert strategy_for_images(20, "high").key == "hybrid"


def test_more_images_raise_geometric_confidence():
    five = capture_metrics(5, 70)
    ten = capture_metrics(10, 70)
    nineteen = capture_metrics(19, 70)
    assert five["geometric_confidence_estimate"] < ten["geometric_confidence_estimate"]
    assert ten["geometric_confidence_estimate"] < nineteen["geometric_confidence_estimate"]
    assert five["visual_fidelity_estimate"] < ten["visual_fidelity_estimate"] < 90


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


def test_smooth_object_stays_on_ai_even_with_many_images():
    images = [SimpleNamespace(blur_score=22.0, validation_status="approved") for _ in range(24)]
    trackability = photogrammetry_trackability(images)
    assert trackability["level"] == "low"
    assert strategy_for_images(len(images), trackability["level"]).key == "ai_refined"


def test_detailed_object_can_enable_hybrid_pipeline():
    images = [SimpleNamespace(blur_score=65.0, validation_status="approved") for _ in range(24)]
    trackability = photogrammetry_trackability(images)
    assert trackability["level"] == "high"
    assert strategy_for_images(len(images), trackability["level"]).key == "hybrid"


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
