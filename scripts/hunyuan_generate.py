"""Isolated, GPU-efficient Hunyuan3D multiview shape and texture worker.

The worker keeps the diffusion model loaded while it generates multiple shape
candidates.  It scores their proportions against the input silhouettes, keeps
the best one, decimates it for real-time display, and exports an honest PBR
material. When enabled, Hunyuan Paint creates a coherent UV texture from the
selected views; if its native CUDA rasterizer is unavailable, a portable
multiview UV baker preserves the observed appearance without pasting a
rectangular photograph onto the mesh.
"""

import argparse
import gc
import json
import os
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--images", nargs="+")
    parser.add_argument("--masks", nargs="+")
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--candidates", type=int, default=3)
    parser.add_argument("--target-faces", type=int, default=60000)
    parser.add_argument("--category", default="generic")
    parser.add_argument("--object-profile", default="auto")
    parser.add_argument("--texture", action="store_true")
    parser.add_argument("--texture-model")
    parser.add_argument("--project-colors", action="store_true")
    return parser.parse_args()


args = parse_args()
os.environ.setdefault("HF_HOME", str(Path(args.cache).resolve()))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HY3DGEN_MODELS", str((Path(args.cache) / "models").resolve()))
sys.path.insert(0, str(Path(args.repo).resolve()))

import numpy as np
import torch
import trimesh
from PIL import Image, ImageDraw
from scipy.ndimage import label

from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
from mesh_recovery import (
    is_usable_topology,
    repair_candidate,
    sanitize_mesh,
    topology_report,
)
from mesh_texturing import (
    apply_multiview_uv_texture,
    apply_multiview_vertex_colours,
    apply_pbr_material,
    estimate_base_colour,
)


def foreground_image(image_path: str, mask_path: str) -> Image.Image:
    image = Image.open(image_path).convert("RGB")
    mask = Image.open(mask_path).convert("L")
    if mask.size != image.size:
        mask = mask.resize(image.size, Image.Resampling.NEAREST)
    rgba = image.convert("RGBA")
    rgba.putalpha(mask)
    return rgba


def load_inputs() -> tuple[list[str], list[str], list[list[int]], list[list[str]]]:
    """Load all validation views plus four-slot conditioning groups."""
    if args.manifest:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        image_paths = [str(value) for value in manifest.get("images", [])]
        mask_paths = [str(value) for value in manifest.get("masks", [])]
        raw_groups = manifest.get("view_groups", [])
        group_names = manifest.get("view_group_names", [])
    else:
        image_paths = [str(value) for value in (args.images or [])]
        mask_paths = [str(value) for value in (args.masks or [])]
        raw_groups = [list(range(min(4, len(image_paths))))]
        group_names = [[Path(image_paths[index]).name for index in raw_groups[0]]] if image_paths else []
    if not image_paths or len(image_paths) != len(mask_paths):
        raise RuntimeError("O manifesto multivista não contém pares imagem/máscara válidos.")
    groups: list[list[int]] = []
    for raw in raw_groups:
        group = [int(index) for index in raw if 0 <= int(index) < len(image_paths)][:4]
        if group and len(group) == len(set(group)) and group not in groups:
            groups.append(group)
    if not groups:
        groups = [list(range(min(4, len(image_paths))))]
    if not group_names:
        group_names = [[Path(image_paths[index]).name for index in group] for group in groups]
    return image_paths, mask_paths, groups, group_names


def silhouette_profile(image: Image.Image) -> np.ndarray:
    alpha = np.asarray(image.getchannel("A").resize((64, 64), Image.Resampling.NEAREST)) > 127
    return alpha.mean(axis=1)


def normalize_orientations(images: list[Image.Image]) -> list[Image.Image]:
    reference = silhouette_profile(images[0])
    normalized = [images[0]]
    for image in images[1:]:
        profile = silhouette_profile(image)
        normal_error = float(np.mean(np.abs(profile - reference)))
        rotated_error = float(np.mean(np.abs(profile[::-1] - reference)))
        normalized.append(image.rotate(180, expand=False) if rotated_error + 0.025 < normal_error else image)
    return normalized


def expected_silhouette_aspect(images: list[Image.Image]) -> float:
    aspects = []
    for image in images:
        alpha = np.asarray(image.getchannel("A")) > 127
        ys, xs = np.where(alpha)
        if len(xs):
            points = np.column_stack((xs - xs.mean(), ys - ys.mean()))
            axis = np.linalg.eigh(np.cov(points, rowvar=False))[1][:, -1]
            across = np.array([-axis[1], axis[0]])
            major = np.ptp(points @ axis)
            minor = np.ptp(points @ across)
            aspects.append(max(major, minor) / max(min(major, minor), 1.0))
    return float(np.median(aspects)) if aspects else 1.0


def expects_handle_topology(images: list[Image.Image]) -> bool:
    """Detect a repeated off-centre silhouette hole, such as a cup handle."""
    handle_views = 0
    for image in images:
        alpha = np.asarray(image.getchannel("A").resize((128, 128), Image.Resampling.NEAREST)) > 127
        ys, xs = np.where(alpha)
        if not len(xs):
            continue
        crop = alpha[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        components, count = label(~crop)
        border = set(components[0, :]) | set(components[-1, :]) | set(components[:, 0]) | set(components[:, -1])
        found = False
        for component in range(1, count + 1):
            if component in border:
                continue
            hole_y, hole_x = np.where(components == component)
            area = len(hole_x) / max(crop.size, 1)
            offset = float(hole_x.mean()) / crop.shape[1] - 0.5 if len(hole_x) else 0.0
            vertical = float(hole_y.mean()) / crop.shape[0] - 0.5 if len(hole_y) else 1.0
            if area >= 0.006 and abs(offset) >= 0.16 and abs(vertical) <= 0.34:
                found = True
                break
        handle_views += int(found)
    return handle_views >= 2


def normalized_observed_mask(image: Image.Image, size: int = 128) -> np.ndarray:
    alpha = np.asarray(image.getchannel("A")) > 127
    ys, xs = np.where(alpha)
    canvas = Image.new("L", (size, size), 0)
    if not len(xs):
        return np.asarray(canvas) > 127
    crop = Image.fromarray((alpha[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1] * 255).astype(np.uint8))
    crop.thumbnail((size - 12, size - 12), Image.Resampling.NEAREST)
    canvas.paste(crop, ((size - crop.width) // 2, (size - crop.height) // 2))
    return np.asarray(canvas) > 127


def _validation_mesh(mesh: trimesh.Trimesh, target_faces: int = 24000) -> trimesh.Trimesh:
    if len(mesh.faces) <= target_faces:
        return mesh
    try:
        simplified = mesh.simplify_quadric_decimation(face_count=target_faces)
        if len(simplified.faces) >= target_faces * 0.55:
            return simplified
    except Exception:
        pass
    return mesh


def rasterized_mesh_silhouettes(mesh: trimesh.Trimesh, size: int = 128) -> dict[str, np.ndarray]:
    """Render canonical silhouettes without an OpenGL dependency."""
    probe = _validation_mesh(mesh)
    vertices = np.asarray(probe.vertices, dtype=np.float64)
    faces = np.asarray(probe.faces, dtype=np.int64)
    if not len(vertices) or not len(faces):
        empty = np.zeros((size, size), dtype=bool)
        return {name: empty for name in ("front", "left", "back", "right", "top", "bottom")}
    projections = {
        "front": vertices[:, [0, 1]] * np.array([1.0, 1.0]),
        "left": vertices[:, [2, 1]] * np.array([1.0, 1.0]),
        "back": vertices[:, [0, 1]] * np.array([-1.0, 1.0]),
        "right": vertices[:, [2, 1]] * np.array([-1.0, 1.0]),
        # Top/base photographs must validate the generated shape without being
        # misused as one of the four lateral diffusion conditions.
        "top": vertices[:, [0, 2]] * np.array([1.0, 1.0]),
        "bottom": vertices[:, [0, 2]] * np.array([-1.0, 1.0]),
    }
    rendered: dict[str, np.ndarray] = {}
    for name, points in projections.items():
        low = points.min(axis=0)
        span = np.maximum(points.max(axis=0) - low, 1e-8)
        scale = (size - 12) / float(max(span))
        screen = (points - low) * scale
        screen += (np.array([size, size]) - span * scale) / 2
        screen[:, 1] = size - 1 - screen[:, 1]
        canvas = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(canvas)
        for triangle in screen[faces]:
            draw.polygon([(float(x), float(y)) for x, y in triangle], fill=255)
        rendered[name] = np.asarray(canvas) > 127
    return rendered


def silhouette_similarity(observed: np.ndarray, rendered: np.ndarray) -> float:
    union = np.logical_or(observed, rendered).sum()
    if not union:
        return 0.0
    iou = float(np.logical_and(observed, rendered).sum() / union)
    observed_rows = observed.mean(axis=1)
    rendered_rows = rendered.mean(axis=1)
    observed_cols = observed.mean(axis=0)
    rendered_cols = rendered.mean(axis=0)
    profile_error = (
        float(np.mean(np.abs(observed_rows - rendered_rows)))
        + float(np.mean(np.abs(observed_cols - rendered_cols)))
    ) / 2
    return float(np.clip(iou * 0.76 + (1.0 - profile_error) * 0.24, 0.0, 1.0))


def silhouette_overlap(observed: np.ndarray, rendered: np.ndarray) -> dict[str, float]:
    """Report asymmetric support so excess geometry cannot hide behind IoU."""
    intersection = float(np.logical_and(observed, rendered).sum())
    observed_area = float(observed.sum())
    rendered_area = float(rendered.sum())
    return {
        "similarity": silhouette_similarity(observed, rendered),
        "precision": intersection / max(rendered_area, 1.0),
        "recall": intersection / max(observed_area, 1.0),
        "area_ratio": rendered_area / max(observed_area, 1.0),
    }


def multiview_silhouette_evidence(
    mesh: trimesh.Trimesh,
    group_images: list[Image.Image],
    all_images: list[Image.Image],
) -> dict[str, float]:
    rendered = rasterized_mesh_silhouettes(mesh)
    slots = ["front", "left", "back", "right"]
    ordered_metrics = [
        silhouette_overlap(normalized_observed_mask(image), rendered[slot])
        for image, slot in zip(group_images, slots)
    ]
    variants = []
    angles = range(0, 180, 15) if len(all_images) == 1 else (0,)
    for mask in rendered.values():
        source = Image.fromarray((mask * 255).astype(np.uint8))
        for angle in angles:
            rotated = np.asarray(
                source.rotate(angle, resample=Image.Resampling.NEAREST, expand=False)
            ) > 127
            variants.extend((rotated, np.fliplr(rotated)))
    coverage_metrics = []
    for image in all_images:
        observed = normalized_observed_mask(image)
        coverage_metrics.append(max(
            (silhouette_overlap(observed, candidate) for candidate in variants),
            key=lambda metric: metric["similarity"],
        ))
    coverage_scores = [metric["similarity"] for metric in coverage_metrics]
    ordered_scores = [metric["similarity"] for metric in ordered_metrics]
    ordered = (
        max(coverage_scores)
        if len(group_images) == 1 and coverage_scores
        else float(np.mean(ordered_scores)) if ordered_scores else 0.0
    )
    coverage = float(np.mean(coverage_scores)) if coverage_scores else ordered
    selected_metrics = coverage_metrics or ordered_metrics
    return {
        "ordered_silhouette": ordered,
        "all_view_silhouette": coverage,
        "silhouette_evidence": ordered * 0.62 + coverage * 0.38,
        "silhouette_precision": float(np.mean([metric["precision"] for metric in selected_metrics])) if selected_metrics else 0.0,
        "silhouette_recall": float(np.mean([metric["recall"] for metric in selected_metrics])) if selected_metrics else 0.0,
        "silhouette_area_ratio": float(np.mean([metric["area_ratio"] for metric in selected_metrics])) if selected_metrics else 0.0,
    }


def orient_single_view_for_display(
    mesh: trimesh.Trimesh,
    image: Image.Image,
) -> tuple[trimesh.Trimesh, str, float]:
    """Choose the lateral pose that exposes the most reference-supported detail."""
    observed = normalized_observed_mask(image)
    rendered = rasterized_mesh_silhouettes(mesh)
    best = (float("-inf"), "front")
    for slot in ("front", "left", "back", "right"):
        source = Image.fromarray((rendered[slot] * 255).astype(np.uint8))
        score = max(
            silhouette_similarity(
                observed,
                np.asarray(source.rotate(angle, resample=Image.Resampling.NEAREST)) > 127,
            )
            for angle in range(0, 180, 15)
        )
        if score > best[0]:
            best = (score, slot)
    yaw = {"front": 0.0, "left": 90.0, "back": 180.0, "right": -90.0}[best[1]]
    radians = np.deg2rad(yaw)
    cosine, sine = np.cos(radians), np.sin(radians)
    transform = np.eye(4)
    transform[:3, :3] = np.array(
        [[cosine, 0.0, sine], [0.0, 1.0, 0.0], [-sine, 0.0, cosine]]
    )
    oriented = mesh.copy()
    oriented.apply_transform(transform)
    return oriented, best[1], float(best[0])


def candidate_score(
    mesh,
    expected_aspect: float,
    handle_expected: bool,
    evidence: dict[str, float] | None = None,
) -> tuple[float, dict]:
    face_count = int(len(mesh.faces))
    vertices = np.asarray(mesh.vertices, dtype=float)
    if face_count == 0 or vertices.ndim != 2 or len(vertices) < 4:
        details = {
            "score": 0.0,
            "expected_aspect": round(expected_aspect, 4),
            "generated_aspect": 0.0,
            "faces": face_count,
            "euler_number": 2,
            "watertight": False,
            "handle_expected": handle_expected,
            "object_profile": args.object_profile,
            "handle_topology": False,
            "main_face_ratio": 0.0,
            "significant_components": 999,
            "secondary_planar_component": False,
            "dominant_sheet_ratio": 0.0,
            "ordered_silhouette": 0.0,
            "all_view_silhouette": 0.0,
            "silhouette_evidence": 0.0,
            "silhouette_precision": 0.0,
            "silhouette_recall": 0.0,
            "silhouette_area_ratio": 0.0,
        }
        return -100.0, details
    extents = np.sort(np.maximum(np.asarray(mesh.extents, dtype=float), 1e-6))
    generated_aspect = float(extents[2] / extents[1])
    volumetric_depth_ratio = float(extents[0] / extents[1])
    aspect_error = abs(float(np.log(generated_aspect / max(expected_aspect, 1e-6))))
    finite = bool(np.isfinite(mesh.vertices).all())
    report = topology_report(mesh, args.object_profile)
    euler_number = report.euler_number
    watertight = report.watertight
    main_face_ratio = report.main_face_ratio
    significant_components = report.significant_components
    secondary_planar = report.secondary_planar_component
    dominant_sheet_ratio = report.dominant_sheet_ratio
    # Leave headroom for evidence bonuses.  The previous 100-point starting
    # value made merely plausible candidates display a misleading perfect
    # score after clamping, even with only ~60% silhouette support.
    score = 88.0 - min(75.0, aspect_error * 62.0)
    if not finite or face_count < 1000:
        score -= 80
    if generated_aspect < 1.0 or generated_aspect > 12.0:
        score -= 20
    minimum_volume = 0.06 if args.object_profile == "thin_parts" else 0.10
    if volumetric_depth_ratio < minimum_volume:
        score -= 70.0 * (1.0 - volumetric_depth_ratio / minimum_volume)
    score += (main_face_ratio - 0.70) * 45
    score -= max(0, significant_components - 6) * 1.6
    if secondary_planar:
        score -= 35
    if dominant_sheet_ratio >= 0.20 and args.object_profile != "thin_parts":
        score -= min(75.0, 40.0 + (dominant_sheet_ratio - 0.20) * 180.0)
    # A handle is topological, not merely a wide silhouette.  Prefer a genus-1
    # candidate when multiple photographs clearly show its enclosed opening.
    # This stops a broad handle-less body from winning on aspect ratio alone.
    handle_topology = watertight and euler_number <= 0
    if handle_expected:
        score += 9 if handle_topology else -28
    # Prefer the simplest topology that explains the observed openings.  A
    # handled watertight object normally needs genus 1 (Euler 0); an extra
    # tunnel is usually a diffusion artefact even when its silhouette is close.
    # The penalty is deliberately modest so clearly observed complex objects
    # can still win through stronger multiview evidence.
    if watertight:
        expected_euler = 0 if handle_expected else 2
        score -= min(15.0, abs(euler_number - expected_euler) * 2.5)
    if evidence:
        silhouette_evidence = float(evidence.get("silhouette_evidence", 0.0))
        score += (silhouette_evidence - 0.58) * 105
        silhouette_precision = float(evidence.get("silhouette_precision", 0.0))
        silhouette_recall = float(evidence.get("silhouette_recall", 0.0))
        area_ratio = float(evidence.get("silhouette_area_ratio", 1.0))
        # Precision answers the crucial question IoU alone misses: how much of
        # the generated silhouette is actually supported by the photograph?
        # Large invented wings/floors now lose decisively against a cleaner
        # candidate even when both explain the main body.
        score += (silhouette_precision - 0.72) * 82
        score += (silhouette_recall - 0.68) * 24
        if silhouette_precision < 0.58:
            score -= (0.58 - silhouette_precision) * 120
        if area_ratio > 1.45:
            score -= min(32.0, (area_ratio - 1.45) * 28.0)
        if float(evidence.get("all_view_silhouette", 0.0)) < 0.48:
            score -= 24
    else:
        evidence = {
            "ordered_silhouette": 0.0,
            "all_view_silhouette": 0.0,
            "silhouette_evidence": 0.0,
            "silhouette_precision": 0.0,
            "silhouette_recall": 0.0,
            "silhouette_area_ratio": 0.0,
        }
    details = {
        "score": round(max(0.0, score), 2),
        "expected_aspect": round(expected_aspect, 4),
        "generated_aspect": round(generated_aspect, 4),
        "volumetric_depth_ratio": round(volumetric_depth_ratio, 4),
        "faces": face_count,
        "euler_number": euler_number,
        "watertight": watertight,
        "handle_expected": handle_expected,
        "handle_topology": handle_topology,
        "main_face_ratio": round(main_face_ratio, 4),
        "significant_components": significant_components,
        "secondary_planar_component": secondary_planar,
        "dominant_sheet_ratio": round(dominant_sheet_ratio, 4),
        "ordered_silhouette": round(float(evidence.get("ordered_silhouette", 0.0)), 4),
        "all_view_silhouette": round(float(evidence.get("all_view_silhouette", 0.0)), 4),
        "silhouette_evidence": round(float(evidence.get("silhouette_evidence", 0.0)), 4),
        "silhouette_precision": round(float(evidence.get("silhouette_precision", 0.0)), 4),
        "silhouette_recall": round(float(evidence.get("silhouette_recall", 0.0)), 4),
        "silhouette_area_ratio": round(float(evidence.get("silhouette_area_ratio", 0.0)), 4),
    }
    return score, details


def optimize_mesh(mesh, target_faces: int):
    original_faces = int(len(mesh.faces))
    try:
        mesh.update_faces(mesh.unique_faces())
        mesh.update_faces(mesh.nondegenerate_faces())
        mesh.remove_unreferenced_vertices()
    except Exception:
        pass
    if len(mesh.faces) > target_faces:
        try:
            simplified = mesh.simplify_quadric_decimation(face_count=target_faces)
            if len(simplified.faces) >= target_faces * 0.65:
                mesh = simplified
        except Exception as error:
            print(f"HUNYUAN_OPTIMIZATION_WARNING {error}", flush=True)
    mesh.remove_unreferenced_vertices()
    return mesh, original_faces


def refine_surface(
    mesh: trimesh.Trimesh,
    expected_aspect: float,
    handle_expected: bool,
    group_images: list[Image.Image],
    all_images: list[Image.Image],
    category: str,
) -> tuple[trimesh.Trimesh, bool, dict]:
    """Remove diffusion noise only when geometric evidence is preserved.

    A tiny Taubin pass makes manufactured and organic surfaces less lumpy.  It
    is accepted only if topology remains safe and silhouette support does not
    regress, so detailed or thin objects keep their unsmoothed geometry.
    """
    profile_iterations = {
        "thin_parts": 3,
        "mechanical": 5,
        "multi_component": 3,
        "architecture": 1,
        "organic": 7,
        "compact": 5,
        "handled_container": 4,
        "auto": 4,
    }
    category_iterations = {
        "product": 5,
        "character": 7,
        "generic": 4,
        "other": 4,
        "vehicle": 5,
        "furniture": 3,
        "architecture": 1,
    }
    iterations = profile_iterations.get(args.object_profile, category_iterations.get(category, 4))
    baseline_evidence = multiview_silhouette_evidence(mesh, group_images, all_images)
    baseline_score, baseline_details = candidate_score(
        mesh, expected_aspect, handle_expected, baseline_evidence
    )
    if iterations <= 0:
        return mesh, False, baseline_details
    try:
        refined = mesh.copy()
        trimesh.smoothing.filter_taubin(
            refined,
            lamb=0.38,
            nu=0.40,
            iterations=iterations,
        )
        trimesh.repair.fix_normals(refined, multibody=True)
        refined_evidence = multiview_silhouette_evidence(refined, group_images, all_images)
        refined_score, refined_details = candidate_score(
            refined, expected_aspect, handle_expected, refined_evidence
        )
        evidence_ok = (
            float(refined_evidence.get("all_view_silhouette", 0.0))
            >= float(baseline_evidence.get("all_view_silhouette", 0.0)) - 0.012
        )
        precision_ok = (
            float(refined_evidence.get("silhouette_precision", 0.0))
            >= float(baseline_evidence.get("silhouette_precision", 0.0)) - 0.01
        )
        if evidence_ok and precision_ok and refined_score >= baseline_score - 2.0 and is_usable_topology(
            refined_details, refined_score, args.object_profile
        ):
            return refined, True, refined_details
    except Exception as error:
        print(f"HUNYUAN_SMOOTHING_WARNING {error}", flush=True)
    return mesh, False, baseline_details


def main():
    if not torch.cuda.is_available():
        raise RuntimeError("Hunyuan3D requer CUDA; PyTorch não detetou a GPU NVIDIA.")
    image_paths, mask_paths, view_groups, view_group_names = load_inputs()
    images = normalize_orientations(
        [foreground_image(image, mask) for image, mask in zip(image_paths, mask_paths)]
    )
    view_names = ["front", "left", "back", "right"]
    conditioning_indices = sorted({index for group in view_groups for index in group})
    conditioning_images = [images[index] for index in conditioning_indices]
    expected_aspect = expected_silhouette_aspect(conditioning_images)
    handle_expected = args.object_profile == "handled_container" and expects_handle_topology(images)
    base_colour = estimate_base_colour(images)

    single_image_mode = len(images) == 1
    model_id = "tencent/Hunyuan3D-2mini" if single_image_mode else "tencent/Hunyuan3D-2mv"
    model_subfolder = (
        "hunyuan3d-dit-v2-mini-turbo"
        if single_image_mode
        else "hunyuan3d-dit-v2-mv-turbo"
    )
    pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        model_id,
        subfolder=model_subfolder,
        variant="fp16",
        device="cuda",
    )
    pipeline.enable_flashvdm(mc_algo="mc")

    best_mesh = None
    best_score = float("-inf")
    best_details = {}
    candidate_count = max(1, min(args.candidates, 8))
    maximum_attempts = min(8, candidate_count + 2)
    generated_count = 0
    attempted_count = 0
    candidate_errors = []
    for index in range(maximum_attempts):
        # Extra seeds are recovery attempts and only run when the normal budget
        # failed to produce a safe topology.
        if index >= candidate_count and best_mesh is not None and is_usable_topology(best_details, best_score, args.object_profile):
            break
        group_index = index % len(view_groups)
        group = view_groups[group_index]
        group_images = [images[image_index] for image_index in group]
        conditions = (
            group_images[0]
            if single_image_mode
            else {name: image for name, image in zip(view_names, group_images)}
        )
        group_aspect = expected_silhouette_aspect(group_images)
        seed = args.seed + index * 7919
        attempted_count += 1
        resolution = args.resolution if index < candidate_count else max(128, args.resolution // 2)
        try:
            raw_mesh = pipeline(
                image=conditions,
                num_inference_steps=5,
                octree_resolution=resolution,
                num_chunks=8000,
                generator=torch.manual_seed(seed),
                output_type="trimesh",
            )[0]
        except Exception as error:
            candidate_errors.append(str(error)[:280])
            print(
                f"HUNYUAN_CANDIDATE_ERROR {json.dumps({'index': index + 1, 'seed': seed, 'error': str(error)[:280]}, separators=(',', ':'))}",
                flush=True,
            )
            gc.collect()
            torch.cuda.empty_cache()
            continue

        cleaned_mesh = sanitize_mesh(raw_mesh)
        raw_evidence = multiview_silhouette_evidence(cleaned_mesh, group_images, images)
        raw_score, raw_details = candidate_score(cleaned_mesh, group_aspect, handle_expected, raw_evidence)
        repaired_mesh, repair = repair_candidate(cleaned_mesh, object_profile=args.object_profile)
        if repair["changed"]:
            repaired_evidence = multiview_silhouette_evidence(repaired_mesh, group_images, images)
        else:
            repaired_evidence = raw_evidence
        repaired_score, repaired_details = candidate_score(
            repaired_mesh,
            group_aspect,
            handle_expected,
            repaired_evidence,
        )
        use_repaired = bool(
            repair["changed"]
            and (
                repaired_score > raw_score + 2
                or (
                    not is_usable_topology(raw_details, raw_score, args.object_profile)
                    and is_usable_topology(repaired_details, repaired_score, args.object_profile)
                )
            )
        )
        if use_repaired:
            mesh, score, details = repaired_mesh, repaired_score, repaired_details
            candidate_recovery = "mesh_repair"
            del cleaned_mesh
        else:
            mesh, score, details = cleaned_mesh, raw_score, raw_details
            candidate_recovery = "retry_seed" if index >= candidate_count else "none"
            del repaired_mesh
        del raw_mesh
        details.update(
            {
                "index": index + 1,
                "seed": seed,
                "resolution": resolution,
                "view_group": group_index + 1,
                "conditioning_views": view_group_names[group_index] if group_index < len(view_group_names) else group,
                "recovery_mode": candidate_recovery,
                "repair": repair,
            }
        )
        generated_count += 1
        print(f"HUNYUAN_CANDIDATE {json.dumps(details, separators=(',', ':'))}", flush=True)
        if score > best_score:
            if best_mesh is not None:
                del best_mesh
            best_mesh = mesh
            best_score = score
            best_details = details
        else:
            del mesh
        gc.collect()
        torch.cuda.empty_cache()
        # Do not stop before every angular set has produced evidence.  Different
        # subsets can expose missing backs, bases and thin attachments even when
        # an early candidate looks topologically valid.

    result_tier = "ai_assisted"
    recovery_mode = str(best_details.get("recovery_mode", "none"))
    recovery_warnings = []
    if best_mesh is None or not is_usable_topology(best_details, best_score, args.object_profile):
        raise RuntimeError(
            "Nenhuma hipótese produziu geometria 3D volumétrica coerente. "
            "Adiciona uma vista frontal ou lateral; o Studio não vai criar uma placa ou proxy."
        )
    elif recovery_mode == "mesh_repair":
        recovery_warnings.append(
            "A geometria gerada foi soldada e foram removidas pequenas superfícies isoladas."
        )
    elif int(best_details.get("index", 0)) > candidate_count:
        recovery_mode = "retry_seed"
        recovery_warnings.append("O modelo foi recuperado automaticamente com uma semente adicional.")

    best_mesh, original_faces = optimize_mesh(best_mesh, max(10000, args.target_faces))
    best_group_index = max(0, int(best_details.get("view_group", 1)) - 1) % len(view_groups)
    best_texture_images = [images[index] for index in view_groups[best_group_index]]
    best_mesh, surface_smoothed, refined_details = refine_surface(
        best_mesh,
        expected_aspect,
        handle_expected,
        best_texture_images,
        images,
        args.category,
    )
    # Keep candidate identity/recovery metadata while reporting final geometry.
    best_details = {**best_details, **refined_details}
    canonical_view = "multiview"
    canonical_view_score = 0.0
    if len(images) == 1:
        best_mesh, canonical_view, canonical_view_score = orient_single_view_for_display(
            best_mesh,
            images[0],
        )
    optimized_components = best_mesh.split(only_watertight=False)
    optimized_main = max(optimized_components, key=lambda component: len(component.faces))
    handle_preserved = bool(optimized_main.is_watertight and optimized_main.euler_number <= 0)
    material_mode = "pbr_uniform"
    if args.texture:
        try:
            if not args.texture_model:
                raise RuntimeError("O modelo local de textura não foi indicado.")
            del pipeline
            gc.collect()
            torch.cuda.empty_cache()
            from hy3dgen.texgen import Hunyuan3DPaintPipeline

            paint = Hunyuan3DPaintPipeline.from_pretrained(
                args.texture_model,
                subfolder="hunyuan3d-paint-v2-0-turbo",
            )
            # Texture generation normally targets 16 GB VRAM. Sequential CPU
            # offload keeps it viable on common 8 GB laptop GPUs at the cost of
            # additional time, while the surrounding worker remains responsive.
            paint.enable_model_cpu_offload()
            best_mesh = paint(best_mesh, image=best_texture_images)
            material_mode = "hunyuan_paint_multiview"
            del paint
            gc.collect()
            torch.cuda.empty_cache()
        except Exception as error:
            print(f"HUNYUAN_TEXTURE_WARNING {error}", flush=True)
            try:
                best_mesh = apply_multiview_uv_texture(
                    best_mesh, best_texture_images, base_colour, texture_size=1024
                )
                material_mode = "multiview_uv_texture"
            except Exception as bake_error:
                print(f"HUNYUAN_UV_TEXTURE_WARNING {bake_error}", flush=True)
                best_mesh = apply_multiview_vertex_colours(best_mesh, best_texture_images, base_colour)
                material_mode = "multiview_vertex_color"
    elif args.project_colors:
        try:
            best_mesh = apply_multiview_uv_texture(
                best_mesh, best_texture_images, base_colour, texture_size=1024
            )
            material_mode = "multiview_uv_texture"
        except Exception as error:
            print(f"HUNYUAN_UV_TEXTURE_WARNING {error}", flush=True)
            best_mesh = apply_multiview_vertex_colours(best_mesh, best_texture_images, base_colour)
            material_mode = "multiview_vertex_color"
    else:
        best_mesh = apply_pbr_material(best_mesh, base_colour)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    best_mesh.export(output)
    result = {
        "vertices": int(len(best_mesh.vertices)),
        "faces": int(len(best_mesh.faces)),
        "faces_before_optimization": original_faces,
        "candidate_count": generated_count,
        "attempted_candidates": attempted_count,
        "selected_candidate": best_details.get("index", 1),
        "candidate_score": round(min(100.0, max(0.0, best_score)), 2),
        "result_tier": result_tier,
        "recovery_mode": recovery_mode,
        "recovery_warnings": recovery_warnings,
        "candidate_errors": candidate_errors,
        "estimated_geometry": result_tier == "estimated",
        "inferred_geometry": True,
        "object_profile": args.object_profile,
        "shape_model": model_id,
        "handle_expected": handle_expected,
        "handle_preserved": handle_preserved,
        "surface_smoothed": surface_smoothed,
        "canonical_view": canonical_view,
        "canonical_view_score": round(canonical_view_score, 4),
        "main_face_ratio": best_details.get("main_face_ratio", 0),
        "significant_components": best_details.get("significant_components", 0),
        "secondary_planar_component": best_details.get("secondary_planar_component", False),
        "dominant_sheet_ratio": best_details.get("dominant_sheet_ratio", 0),
        "volumetric_depth_ratio": best_details.get("volumetric_depth_ratio", 0),
        "silhouette_evidence": best_details.get("silhouette_evidence", 0),
        "ordered_silhouette": best_details.get("ordered_silhouette", 0),
        "all_view_silhouette": best_details.get("all_view_silhouette", 0),
        "silhouette_precision": best_details.get("silhouette_precision", 0),
        "silhouette_recall": best_details.get("silhouette_recall", 0),
        "silhouette_area_ratio": best_details.get("silhouette_area_ratio", 0),
        "view_groups": len(view_groups),
        "validation_views": len(images),
        "base_color": [int(value) for value in base_colour],
        "material": material_mode,
        "texture_visibility_aware": material_mode == "multiview_uv_texture",
        "texture_source_views": len(best_texture_images),
        "output": str(output),
    }
    print(f"HUNYUAN_RESULT {json.dumps(result, separators=(',', ':'))}", flush=True)


if __name__ == "__main__":
    main()
