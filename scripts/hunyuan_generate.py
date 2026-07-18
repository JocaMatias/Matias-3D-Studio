"""Isolated, GPU-efficient Hunyuan3D multiview shape and texture worker.

The worker keeps the diffusion model loaded while it generates multiple shape
candidates.  It scores their proportions against the input silhouettes, keeps
the best one, decimates it for real-time display, and exports an honest PBR
material. When enabled, Hunyuan Paint creates a coherent UV texture from the
selected views; if the texture model is unavailable, a neutral PBR fallback is
exported without pasting a rectangular photograph onto the mesh.
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
    parser.add_argument("--images", nargs="+", required=True)
    parser.add_argument("--masks", nargs="+", required=True)
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--candidates", type=int, default=3)
    parser.add_argument("--target-faces", type=int, default=60000)
    parser.add_argument("--texture", action="store_true")
    parser.add_argument("--texture-model")
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
from PIL import Image
from scipy.ndimage import label

from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline


def foreground_image(image_path: str, mask_path: str) -> Image.Image:
    image = Image.open(image_path).convert("RGB")
    mask = Image.open(mask_path).convert("L")
    if mask.size != image.size:
        mask = mask.resize(image.size, Image.Resampling.NEAREST)
    rgba = image.convert("RGBA")
    rgba.putalpha(mask)
    return rgba


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
            aspects.append((xs.max() - xs.min() + 1) / max(ys.max() - ys.min() + 1, 1))
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


def candidate_score(mesh, expected_aspect: float, handle_expected: bool) -> tuple[float, dict]:
    extents = np.maximum(np.asarray(mesh.extents, dtype=float), 1e-6)
    # Hunyuan shape space uses Y as its upright axis.
    generated_aspect = float(max(extents[0], extents[2]) / extents[1])
    aspect_error = abs(float(np.log(generated_aspect / max(expected_aspect, 1e-6))))
    finite = bool(np.isfinite(mesh.vertices).all())
    face_count = int(len(mesh.faces))
    try:
        # Probe topology on a light copy.  Raw marching-cubes output contains
        # split vertices, while the 30k-face probe is welded by simplification
        # and makes a connected-component check inexpensive.
        probe = mesh.simplify_quadric_decimation(face_count=30000) if face_count > 45000 else mesh.copy()
        probe_components = probe.split(only_watertight=False)
        probe_main = max(probe_components, key=lambda component: len(component.faces))
        euler_number = int(probe_main.euler_number)
        watertight = bool(probe_main.is_watertight)
    except Exception:
        euler_number = 2
        watertight = False
    score = 100.0 - min(75.0, aspect_error * 62.0)
    if not finite or face_count < 1000:
        score -= 80
    if generated_aspect < 0.45 or generated_aspect > 3.2:
        score -= 20
    # A handle is topological, not merely a wide silhouette.  Prefer a genus-1
    # candidate when multiple photographs clearly show its enclosed opening.
    # This stops a broad handle-less body from winning on aspect ratio alone.
    handle_topology = watertight and euler_number <= 0
    if handle_expected:
        score += 9 if handle_topology else -28
    details = {
        "score": round(max(0.0, score), 2),
        "expected_aspect": round(expected_aspect, 4),
        "generated_aspect": round(generated_aspect, 4),
        "faces": face_count,
        "euler_number": euler_number,
        "watertight": watertight,
        "handle_expected": handle_expected,
        "handle_topology": handle_topology,
    }
    return score, details


def estimate_base_colour(images: list[Image.Image]) -> np.ndarray:
    samples = []
    for image in images:
        thumbnail = image.copy()
        thumbnail.thumbnail((384, 384), Image.Resampling.LANCZOS)
        rgba = np.asarray(thumbnail)
        pixels = rgba[rgba[:, :, 3] > 220, :3]
        if not len(pixels):
            continue
        luminance = pixels.mean(axis=1)
        low, high = np.percentile(luminance, [8, 97])
        neutral = pixels[(luminance >= low) & (luminance <= high)]
        samples.append(neutral[:: max(1, len(neutral) // 20000)])
    if not samples:
        return np.array([230, 230, 230, 255], dtype=np.uint8)
    # Estimate de-lit albedo from the bright side of the object instead of
    # baking photographed shadows into the material.
    rgb = np.percentile(np.concatenate(samples, axis=0), 90, axis=0)
    return np.r_[np.clip(np.rint(rgb), 0, 255).astype(np.uint8), 255]


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


def apply_pbr_material(mesh, base_colour: np.ndarray):
    material = trimesh.visual.material.PBRMaterial(
        name="AI PBR material",
        baseColorFactor=base_colour,
        metallicFactor=0.0,
        roughnessFactor=0.34,
    )
    # A constant UV is intentional: this is a coherent base material, not a
    # falsely calibrated photo projection.  A future texture model can replace it.
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=np.zeros((len(mesh.vertices), 2), dtype=np.float32),
        material=material,
    )
    return mesh


def main():
    if not torch.cuda.is_available():
        raise RuntimeError("Hunyuan3D requer CUDA; PyTorch não detetou a GPU NVIDIA.")
    images = normalize_orientations(
        [foreground_image(image, mask) for image, mask in zip(args.images, args.masks)]
    )
    view_names = ["front", "left", "back", "right"]
    conditions = {name: image for name, image in zip(view_names, images[:4])}
    expected_aspect = expected_silhouette_aspect(images)
    handle_expected = expects_handle_topology(images)
    base_colour = estimate_base_colour(images)

    pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        "tencent/Hunyuan3D-2mv",
        subfolder="hunyuan3d-dit-v2-mv-turbo",
        variant="fp16",
        device="cuda",
    )
    pipeline.enable_flashvdm(mc_algo="mc")

    best_mesh = None
    best_score = float("-inf")
    best_details = {}
    candidate_count = max(1, min(args.candidates, 4))
    generated_count = 0
    for index in range(candidate_count):
        seed = args.seed + index * 7919
        mesh = pipeline(
            image=conditions,
            num_inference_steps=5,
            octree_resolution=args.resolution,
            num_chunks=8000,
            generator=torch.manual_seed(seed),
            output_type="trimesh",
        )[0]
        score, details = candidate_score(mesh, expected_aspect, handle_expected)
        details.update({"index": index + 1, "seed": seed})
        generated_count += 1
        print(f"HUNYUAN_CANDIDATE {json.dumps(details, separators=(',', ':'))}", flush=True)
        if score > best_score:
            best_mesh = mesh
            best_score = score
            best_details = details
        else:
            del mesh
        gc.collect()
        torch.cuda.empty_cache()
        # A high-scoring genus-1 mesh already satisfies both the silhouette and
        # the observed handle constraint.  Further diffusion runs add latency
        # without a meaningful chance of improving this local result.
        if handle_expected and details["handle_topology"] and score >= 95:
            break

    if best_mesh is None:
        raise RuntimeError("Nenhum candidato 3D utilizável foi produzido.")
    best_mesh, original_faces = optimize_mesh(best_mesh, max(10000, args.target_faces))
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
            best_mesh = paint(best_mesh, image=images[:4])
            material_mode = "hunyuan_paint_multiview"
            del paint
            gc.collect()
            torch.cuda.empty_cache()
        except Exception as error:
            print(f"HUNYUAN_TEXTURE_WARNING {error}", flush=True)
            best_mesh = apply_pbr_material(best_mesh, base_colour)
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
        "selected_candidate": best_details.get("index", 1),
        "candidate_score": round(max(0.0, best_score), 2),
        "handle_expected": handle_expected,
        "handle_preserved": handle_preserved,
        "base_color": [int(value) for value in base_colour],
        "material": material_mode,
        "output": str(output),
    }
    print(f"HUNYUAN_RESULT {json.dumps(result, separators=(',', ':'))}", flush=True)


if __name__ == "__main__":
    main()
