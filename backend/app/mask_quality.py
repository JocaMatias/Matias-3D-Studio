from __future__ import annotations

import numpy as np
from PIL import Image
from scipy import ndimage


def analyse_mask(mask: Image.Image, object_profile: str = "auto") -> dict:
    foreground = np.asarray(mask.convert("L")) > 127
    height, width = foreground.shape
    coverage = float(foreground.mean())
    labels, count = ndimage.label(foreground)
    components = []
    for index in range(1, count + 1):
        area = int(np.sum(labels == index))
        if area:
            components.append(area)
    components.sort(reverse=True)
    largest_ratio = components[0] / max(1, int(foreground.sum())) if components else 0.0
    ys, xs = np.where(foreground)
    if len(xs):
        x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
        bbox_area = max(1, (x1 - x0 + 1) * (y1 - y0 + 1))
        rectangularity = float(foreground.sum() / bbox_area)
        bbox_width_ratio = (x1 - x0 + 1) / max(width, 1)
        centroid = [round(float(xs.mean() / max(width - 1, 1)), 4), round(float(ys.mean() / max(height - 1, 1)), 4)]
    else:
        x0 = x1 = y0 = y1 = 0
        rectangularity = 0.0
        bbox_width_ratio = 0.0
        centroid = [0.5, 0.5]
    touches = {
        "top": bool(foreground[0].any()),
        "bottom": bool(foreground[-1].any()),
        "left": bool(foreground[:, 0].any()),
        "right": bool(foreground[:, -1].any()),
    }
    touch_count = sum(touches.values())
    bottom_band = foreground[int(height * 0.88) :, :]
    bottom_band_ratio = float(bottom_band.mean()) if bottom_band.size else 0.0

    inverse_labels, inverse_count = ndimage.label(~foreground)
    border_labels = set(np.unique(np.concatenate((inverse_labels[0], inverse_labels[-1], inverse_labels[:, 0], inverse_labels[:, -1]))).tolist())
    holes = sum(index not in border_labels for index in range(1, inverse_count + 1))

    warnings: list[str] = []
    blocking: list[str] = []
    if coverage < 0.01 or coverage > 0.85:
        blocking.append("A cobertura da máscara está fora do intervalo seguro (1%–85%).")
    if touch_count >= 4 and coverage > 0.42:
        blocking.append("A máscara toca todas as margens e provavelmente inclui o fundo.")
    elif touch_count >= 3:
        warnings.append("A máscara toca várias margens; confirma se o objeto está cortado.")
    if largest_ratio < (0.45 if object_profile in {"thin_parts", "mechanical", "multi_component"} else 0.68):
        warnings.append("A máscara está muito fragmentada.")
    likely_base_plane = (
        object_profile != "architecture"
        and bottom_band_ratio > 0.72
        and bbox_width_ratio > 0.72
        and rectangularity > 0.42
        and coverage > 0.16
    )
    if likely_base_plane:
        blocking.append("A máscara parece incluir uma superfície larga do fundo junto à base.")

    confidence = 100
    confidence -= len(warnings) * 14
    confidence -= len(blocking) * 42
    confidence -= int(max(0.0, 0.55 - largest_ratio) * 35)
    confidence = max(0, min(100, confidence))
    return {
        "coverage": round(coverage, 5),
        "bounding_box": [x0, y0, x1, y1],
        "bbox_width_ratio": round(bbox_width_ratio, 5),
        "centroid": centroid,
        "touches": touches,
        "touch_count": touch_count,
        "component_count": len(components),
        "largest_component_ratio": round(largest_ratio, 5),
        "rectangularity": round(rectangularity, 5),
        "bottom_band_ratio": round(bottom_band_ratio, 5),
        "holes": holes,
        "likely_base_plane": likely_base_plane,
        "confidence": confidence,
        "warnings": warnings,
        "blocking_issues": blocking,
        "status": "invalid" if blocking else "warning" if warnings else "approved",
    }
