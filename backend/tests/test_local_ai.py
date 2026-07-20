import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw
import trimesh

import pytest

import app.local_ai as local_ai
from app.local_ai import analyse_candidate, prepare_transparent_input


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
