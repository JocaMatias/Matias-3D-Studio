from pathlib import Path

from app.reconstruction import (
    _colmap_matching_command,
    _elapsed_label,
    _estimated_stage_progress,
)


def test_native_progress_is_time_based_and_never_claims_completion():
    assert _estimated_stage_progress(0, 300) == 5
    assert _estimated_stage_progress(30, 300) < _estimated_stage_progress(180, 300)
    assert _estimated_stage_progress(300, 300) == 85
    assert _estimated_stage_progress(3_000, 300) == 85
    assert _elapsed_label(125, 300) == "2:05 min; limite 5 min"


def test_precision_scan_uses_bounded_sequential_gpu_matching():
    command = _colmap_matching_command(
        Path("colmap.exe"),
        Path("database.db"),
        Path("models"),
        camera_count=27,
        use_gpu=True,
    )
    assert command[1] == "sequential_matcher"
    assert "exhaustive_matcher" not in command
    assert command[command.index("--FeatureMatching.use_gpu") + 1] == "1"
    assert command[command.index("--FeatureMatching.type") + 1] == "SIFT_BRUTEFORCE"
    assert command[command.index("--SequentialMatching.overlap") + 1] == "7"
    assert command[command.index("--FeatureMatching.max_num_matches") + 1] == "4096"


def test_cpu_matching_keeps_aliked_lightglue_as_fallback():
    command = _colmap_matching_command(
        Path("colmap.exe"), Path("database.db"), Path("models"), 27, False
    )
    assert command[command.index("--FeatureMatching.type") + 1] == "ALIKED_LIGHTGLUE"
    assert command[command.index("--FeatureMatching.use_gpu") + 1] == "0"
    assert command[command.index("--FeatureMatching.max_num_matches") + 1] == "2048"
