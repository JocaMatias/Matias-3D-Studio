from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy import ndimage


@dataclass(frozen=True)
class ImageDescriptor:
    mask: np.ndarray
    row_profile: np.ndarray
    column_profile: np.ndarray
    edge_histogram: np.ndarray
    colour_histogram: np.ndarray
    aspect: float
    coverage: float
    centroid: tuple[float, float]
    foreground_confidence: float


def _normalise_vector(value: np.ndarray) -> np.ndarray:
    vector = np.asarray(value, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 1e-8 else vector


def estimate_foreground_mask(image: Image.Image, size: int = 96) -> tuple[np.ndarray, float]:
    """Estimate a conservative object mask from border colour and centrality.

    It is deliberately lightweight and does not replace the reconstruction
    segmenter. Low-confidence masks reduce validation confidence instead of
    falsely proving structural consistency.
    """
    rgb = np.asarray(image.convert("RGB").resize((size, size), Image.Resampling.LANCZOS), dtype=np.float32)
    border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]), axis=0)
    background = np.median(border, axis=0)
    distance = np.linalg.norm(rgb - background[None, None, :], axis=2)
    border_noise = float(np.percentile(np.linalg.norm(border - background, axis=1), 85))
    threshold = max(14.0, border_noise * 2.4, float(np.percentile(distance, 58)) * 0.45)
    candidate = distance > threshold
    candidate = ndimage.binary_opening(candidate, structure=np.ones((2, 2), dtype=bool))
    candidate = ndimage.binary_closing(candidate, structure=np.ones((3, 3), dtype=bool))

    labels, count = ndimage.label(candidate)
    if count:
        yy, xx = np.mgrid[0:size, 0:size]
        centre = np.array([(size - 1) / 2, (size - 1) / 2])
        scored: list[tuple[float, int]] = []
        for index in range(1, count + 1):
            component = labels == index
            area = int(component.sum())
            if area < size * size * 0.002:
                continue
            cy = float(yy[component].mean())
            cx = float(xx[component].mean())
            centrality = 1.0 - min(1.0, np.linalg.norm(np.array([cy, cx]) - centre) / (size * 0.72))
            touches = float(
                component[0].mean() + component[-1].mean() + component[:, 0].mean() + component[:, -1].mean()
            )
            score = area * (0.55 + 0.45 * centrality) * max(0.15, 1.0 - touches * 1.8)
            scored.append((score, index))
        if scored:
            scored.sort(reverse=True)
            best_score = scored[0][0]
            selected = [index for score, index in scored if score >= best_score * 0.12]
            candidate = np.isin(labels, selected)

    coverage = float(candidate.mean())
    contrast = float(np.median(distance[candidate])) if candidate.any() else 0.0
    confidence = np.clip((contrast - border_noise) / 55.0, 0.0, 1.0)
    if coverage < 0.015 or coverage > 0.86:
        confidence *= 0.25
    elif coverage < 0.04 or coverage > 0.72:
        confidence *= 0.65
    return candidate.astype(bool), float(confidence)


def _normalised_mask(mask: np.ndarray, size: int = 48) -> tuple[np.ndarray, float, tuple[float, float]]:
    ys, xs = np.where(mask)
    canvas = Image.new("L", (size, size), 0)
    if not len(xs):
        return np.zeros((size, size), dtype=bool), 1.0, (0.5, 0.5)
    crop = Image.fromarray((mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1] * 255).astype(np.uint8))
    aspect = crop.width / max(crop.height, 1)
    crop.thumbnail((size - 6, size - 6), Image.Resampling.NEAREST)
    canvas.paste(crop, ((size - crop.width) // 2, (size - crop.height) // 2))
    centroid = (float(xs.mean() / max(mask.shape[1] - 1, 1)), float(ys.mean() / max(mask.shape[0] - 1, 1)))
    return np.asarray(canvas) > 127, float(aspect), centroid


def describe_image(image: Image.Image) -> ImageDescriptor:
    mask, confidence = estimate_foreground_mask(image)
    normalised, aspect, centroid = _normalised_mask(mask)
    row_profile = normalised.mean(axis=1).astype(np.float32)
    column_profile = normalised.mean(axis=0).astype(np.float32)

    gray = np.asarray(image.convert("L").resize((96, 96), Image.Resampling.LANCZOS), dtype=np.float32)
    gx = np.diff(gray, axis=1, prepend=gray[:, :1])
    gy = np.diff(gray, axis=0, prepend=gray[:1])
    magnitude = np.hypot(gx, gy)
    orientation = (np.arctan2(gy, gx) + np.pi) % np.pi
    foreground = mask & (magnitude >= np.percentile(magnitude[mask], 65) if mask.any() else False)
    edge_hist, _ = np.histogram(orientation[foreground], bins=12, range=(0, np.pi), weights=magnitude[foreground])

    rgb = np.asarray(image.convert("RGB").resize((96, 96), Image.Resampling.LANCZOS), dtype=np.uint8)
    pixels = rgb[mask] if mask.any() else rgb.reshape(-1, 3)
    colour_parts = [np.histogram(pixels[:, channel], bins=8, range=(0, 256))[0] for channel in range(3)]
    colour_hist = np.concatenate(colour_parts)
    return ImageDescriptor(
        mask=normalised,
        row_profile=_normalise_vector(row_profile),
        column_profile=_normalise_vector(column_profile),
        edge_histogram=_normalise_vector(edge_hist),
        colour_histogram=_normalise_vector(colour_hist),
        aspect=aspect,
        coverage=float(mask.mean()),
        centroid=centroid,
        foreground_confidence=confidence,
    )


def descriptor_similarity(left: ImageDescriptor, right: ImageDescriptor) -> float:
    union = np.logical_or(left.mask, right.mask).sum()
    iou = float(np.logical_and(left.mask, right.mask).sum() / union) if union else 0.0
    profiles = max(0.0, float(np.dot(left.row_profile, right.row_profile))) * 0.5
    profiles += max(0.0, float(np.dot(left.column_profile, right.column_profile))) * 0.5
    edges = max(0.0, float(np.dot(left.edge_histogram, right.edge_histogram)))
    colours = max(0.0, float(np.dot(left.colour_histogram, right.colour_histogram)))
    aspect = float(np.exp(-abs(np.log(max(left.aspect, 1e-4) / max(right.aspect, 1e-4)))))
    coverage = 1.0 - min(1.0, abs(left.coverage - right.coverage) / 0.55)
    centroid_distance = np.linalg.norm(np.asarray(left.centroid) - np.asarray(right.centroid))
    centroid = 1.0 - min(1.0, float(centroid_distance) / 0.55)
    structural = iou * 0.38 + profiles * 0.20 + edges * 0.17 + aspect * 0.12 + coverage * 0.08 + centroid * 0.05
    confidence = min(left.foreground_confidence, right.foreground_confidence)
    # Colour is deliberately capped at 15%; equal colours cannot make unlike
    # silhouettes look structurally consistent.
    score = structural * 0.85 + colours * 0.15
    score *= 0.58 + 0.42 * confidence
    return float(np.clip(score * 100.0, 0.0, 100.0))


def descriptor_vector(value: ImageDescriptor) -> np.ndarray:
    vector = np.concatenate(
        (
            value.mask.astype(np.float32).reshape(-1),
            value.row_profile * 4.0,
            value.column_profile * 4.0,
            value.edge_histogram * 2.0,
            np.array([np.log(max(value.aspect, 1e-4)), value.coverage, *value.centroid], dtype=np.float32) * 3.0,
        )
    )
    return _normalise_vector(vector)


def farthest_point_indices(descriptors: list[ImageDescriptor], limit: int, anchor: int = 0) -> list[int]:
    if not descriptors or limit <= 0:
        return []
    vectors = np.stack([descriptor_vector(value) for value in descriptors])
    anchor = min(max(anchor, 0), len(descriptors) - 1)
    chosen = [anchor]
    distances = 1.0 - vectors @ vectors[anchor]
    while len(chosen) < min(limit, len(descriptors)):
        distances[chosen] = -1.0
        next_index = int(np.argmax(distances))
        chosen.append(next_index)
        distances = np.minimum(distances, 1.0 - vectors @ vectors[next_index])
    return chosen
