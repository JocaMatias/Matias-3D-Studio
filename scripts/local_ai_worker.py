"""Isolated single-image local AI worker for SPAR3D and Stable Fast 3D.

The backend launches this script in the engine-specific virtual environment so
CUDA dependencies cannot conflict with the FastAPI environment. The input is
already segmented and contains a real alpha channel.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import random
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["spar3d", "stable_fast_3d"], required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--texture-resolution", type=int, default=1024)
    parser.add_argument("--low-vram", action="store_true")
    parser.add_argument("--run-id", default="manual")
    return parser.parse_args()


args = parse_args()
os.environ.setdefault("HF_HOME", str(Path(args.cache).resolve()))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("SPAR3D_LOW_VRAM", "1" if args.low_vram else "0")
sys.path.insert(0, str(Path(args.repo).resolve()))

import numpy as np
import torch
from PIL import Image

random.seed(args.seed)
np.random.seed(args.seed)
torch.manual_seed(args.seed)
if torch.cuda.is_available():
    torch.cuda.manual_seed_all(args.seed)

if not torch.cuda.is_available():
    raise RuntimeError("O motor local requer uma GPU NVIDIA detetada pelo PyTorch CUDA.")

output = Path(args.output)
output.parent.mkdir(parents=True, exist_ok=True)
output.unlink(missing_ok=True)
partial_output = output.with_suffix(".partial.glb")
partial_output.unlink(missing_ok=True)
image = Image.open(args.input).convert("RGBA")
device = "cuda"
major, _minor = torch.cuda.get_device_capability()
amp_dtype = torch.bfloat16 if major >= 8 else torch.float16

if args.engine == "spar3d":
    from spar3d.system import SPAR3D
    from spar3d.utils import foreground_crop

    image = foreground_crop(image, 1.30)
    model = SPAR3D.from_pretrained(
        "stabilityai/stable-point-aware-3d",
        config_name="config.yaml",
        weight_name="model.safetensors",
        low_vram_mode=args.low_vram,
    )
    model.to(device)
    model.eval()
    with torch.no_grad(), torch.autocast(device_type="cuda", dtype=amp_dtype):
        mesh, _ = model.run_image(
            [image],
            bake_resolution=args.texture_resolution,
            remesh="none",
            vertex_count=-1,
            return_points=True,
        )
else:
    from sf3d.system import SF3D
    from sf3d.utils import resize_foreground

    image = resize_foreground(image, 0.85)
    model = SF3D.from_pretrained(
        "stabilityai/stable-fast-3d",
        config_name="config.yaml",
        weight_name="model.safetensors",
    )
    model.to(device)
    model.eval()
    with torch.no_grad(), torch.autocast(device_type="cuda", dtype=amp_dtype):
        mesh, _ = model.run_image(
            [image],
            bake_resolution=args.texture_resolution,
            remesh="none",
            vertex_count=-1,
        )

if isinstance(mesh, (list, tuple)):
    mesh = mesh[0]
mesh.export(partial_output, include_normals=True)
if not partial_output.is_file() or partial_output.stat().st_size < 10_000:
    raise RuntimeError("O motor terminou sem produzir um GLB válido.")
with partial_output.open("rb") as stream:
    if stream.read(4) != b"glTF":
        raise RuntimeError("O motor produziu um ficheiro que não é GLB.")
partial_output.replace(output)
peak = torch.cuda.max_memory_allocated() / 1024 / 1024
print(
    "LOCAL_AI_RESULT "
    + json.dumps(
        {
            "engine": args.engine,
            "seed": args.seed,
            "output": str(output),
            "peak_vram_mb": round(float(peak), 1),
        }
    ),
    flush=True,
)
del mesh, model
if torch.cuda.is_available():
    torch.cuda.empty_cache()
gc.collect()
