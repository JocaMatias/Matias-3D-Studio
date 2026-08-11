import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw
import trimesh

import pytest

import app.local_ai as local_ai
from app.local_ai import (
    analyse_candidate,
    apply_reference_texture,
    build_structure_preserving_candidate,
    prepare_transparent_input,
)
from app.reconstruction import (
    _effective_object_profile,
    _refine_studio_subject_mask,
    _stabilize_object_mask,
)


def test_prepare_transparent_input_uses_mask_and_square_canvas(tmp_path: Path):
    image_path = tmp_path / "source.png"
    mask_path = tmp_path / "mask.png"
    output_path = tmp_path / "prepared.png"

    Image.new("RGB", (160, 100), "white").save(image_path)
    mask = Image.new("L", (160, 100), 0)
    ImageDraw.Draw(mask).ellipse((45, 15, 115, 85), fill=255)
    mask.save(mask_path)

    prepare_transparent_input(image_path, mask_path, output_path)

    prepared = Image.open(output_path).convert("RGBA")
    alpha = np.asarray(prepared.getchannel("A"))
    assert prepared.width == prepared.height
    assert alpha[0, 0] == 0
    assert alpha.max() == 255
    assert 0.25 < float(np.mean(alpha > 127)) < 0.8


def test_candidate_analysis_accepts_a_coherent_mesh(tmp_path: Path):
    candidate = tmp_path / "candidate.glb"
    mask_path = tmp_path / "mask.png"
    trimesh.creation.icosphere(subdivisions=3).export(candidate)

    mask = Image.new("L", (180, 180), 0)
    ImageDraw.Draw(mask).ellipse((20, 20, 160, 160), fill=255)
    mask.save(mask_path)

    report = analyse_candidate(candidate, mask_path)

    assert report["usable"] is True
    assert report["main_component_ratio"] > 0.99
    assert report["geometry_quality_score"] >= 90
    assert report["texture_mode"] in {"none", "pbr_uniform", "vertex_colors", "uv_texture"}


def test_compact_profile_fills_reflection_holes_but_handle_profile_preserves_them():
    mask = np.zeros((100, 100), dtype=bool)
    mask[10:90, 25:75] = True
    mask[30:75, 38:62] = False

    compact = _stabilize_object_mask(mask, "compact")
    handled = _stabilize_object_mask(mask, "handled_container")

    assert compact[50, 50]
    assert not handled[50, 50]


def test_thin_parts_profile_does_not_close_identity_defining_gaps():
    mask = np.zeros((80, 80), dtype=bool)
    mask[35:45, 12:68] = True
    mask[18:36, 12:17] = True
    mask[18:36, 20:25] = True
    mask[18:36, 28:33] = True
    mask[18:36, 36:41] = True

    stabilized = _stabilize_object_mask(mask, "thin_parts")

    assert not stabilized[25, 18]
    assert not stabilized[25, 26]
    assert not stabilized[25, 34]


def test_studio_mask_rejects_soft_cast_shadow_without_losing_object(tmp_path: Path):
    image_path = tmp_path / "studio.png"
    pixels = np.full((180, 220, 3), 246, dtype=np.uint8)
    # Low-chroma, soft shadow deliberately touches the object mask.
    pixels[105:145, 45:190] = 210
    pixels[55:120, 65:165] = np.array([176, 38, 30], dtype=np.uint8)
    Image.fromarray(pixels).save(image_path)
    neural = np.zeros((180, 220), dtype=bool)
    neural[55:120, 65:165] = True
    neural[105:145, 45:190] = True

    refined = _refine_studio_subject_mask(image_path, neural)

    assert refined[80, 100]
    assert not refined[135, 175]
    assert refined.sum() < neural.sum() * 0.8


def test_studio_mask_keeps_neutral_object_with_strong_contrast(tmp_path: Path):
    image_path = tmp_path / "neutral.png"
    pixels = np.full((120, 120, 3), 245, dtype=np.uint8)
    pixels[30:90, 35:85] = 70
    Image.fromarray(pixels).save(image_path)
    neural = np.zeros((120, 120), dtype=bool)
    neural[30:90, 35:85] = True

    refined = _refine_studio_subject_mask(image_path, neural)

    assert refined[50, 50]
    assert refined.sum() >= neural.sum() * 0.95


def test_structural_score_penalises_a_solid_blade_that_replaces_fork_tines():
    fork = np.zeros((160, 160), dtype=bool)
    fork[76:86, 25:140] = True
    for start in (48, 57, 66, 75):
        fork[start:start + 5, 25:77] = True
    blade = np.zeros_like(fork)
    blade[76:86, 25:140] = True
    blade[48:80, 25:77] = True

    score, details = local_ai._structural_similarity(fork, blade)

    assert score < 0.7
    assert details["rendered_endpoints"] < details["observed_endpoints"]
    assert details["observed_cross_section_runs"] == 4
    assert details["rendered_cross_section_runs"] <= 2


def test_automatic_profile_recognises_solid_cutlery():
    project = type("Project", (), {
        "object_profile": "auto",
        "name": "Colher de aço",
        "description": "",
        "category": "generic",
    })()

    assert _effective_object_profile(project) == "compact"


def test_reference_projection_creates_embedded_texture(tmp_path: Path):
    candidate = tmp_path / "plain.glb"
    reference = tmp_path / "reference.png"
    output = tmp_path / "textured.glb"
    trimesh.creation.icosphere(subdivisions=2).export(candidate)
    image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((14, 14, 114, 114), fill=(34, 170, 130, 255))
    image.save(reference)

    report = apply_reference_texture(
        candidate,
        reference,
        output,
        yaw_deg=0,
        pitch_deg=0,
        material_hint="produto",
    )

    assert output.stat().st_size > 5_000
    assert report["has_texture"] is True
    assert report["texture_mode"] == "uv_texture"


def test_structure_recovery_preserves_four_tines_and_is_usable(tmp_path: Path):
    mask_path = tmp_path / "fork-mask.png"
    candidate = tmp_path / "fork-recovery.glb"
    mask = np.zeros((180, 280), dtype=np.uint8)
    mask[82:100, 70:250] = 255
    for start in (52, 66, 80, 94):
        mask[start:start + 8, 20:90] = 255
    Image.fromarray(mask).save(mask_path)

    build_structure_preserving_candidate(mask_path, candidate)
    report = analyse_candidate(candidate, mask_path, "thin_parts", 4)

    assert candidate.stat().st_size > 10_000
    assert report["watertight"] is True
    assert report["rendered_cross_section_runs"] >= 3
    assert report["usable"] is True


def test_wsl_manifest_controls_each_engine_independently(tmp_path: Path, monkeypatch):
    marker = tmp_path / "tools" / "wsl-ai-install.json"
    marker.parent.mkdir()
    marker.write_text(json.dumps({
        "distro": "MatiasAI",
        "engines": {
            "spar3d": {"ready": True},
            "stable_fast_3d": {"ready": False},
        },
    }), encoding="utf-8")
    monkeypatch.setattr(local_ai, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(local_ai.settings, "local_ai_runtime", "wsl")
    monkeypatch.setattr(local_ai.settings, "local_ai_wsl_distro", "MatiasAI")
    monkeypatch.setattr(local_ai.shutil, "which", lambda _name: "wsl.exe")

    spar3d, sf3d = local_ai.discover_local_ai_engines()

    assert spar3d.available is True
    assert sf3d.available is False


def test_logged_process_honours_cancellation(tmp_path: Path):
    checks = 0

    def cancel():
        nonlocal checks
        checks += 1
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        local_ai._run_logged_process(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            log_path=tmp_path / "cancel.log",
            timeout_seconds=30,
            cancel_check=cancel,
        )
    assert checks == 1


def test_logged_process_honours_timeout(tmp_path: Path):
    with pytest.raises(TimeoutError, match="excedeu o limite"):
        local_ai._run_logged_process(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            log_path=tmp_path / "timeout.log",
            timeout_seconds=0.05,
        )
