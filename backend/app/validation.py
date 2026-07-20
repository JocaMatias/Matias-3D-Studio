from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, ImageStat
from sqlalchemy.orm import Session

from .config import PROJECT_ROOT
from .models import Project
from .strategy import (
    capture_metrics,
    minimum_images_for_mode,
    next_capture_suggestion,
    normalize_generation_mode,
    recommended_images_for_mode,
)


def _difference_hash(image: Image.Image) -> int:
    pixels = np.asarray(image.convert("L").resize((9, 8)), dtype=np.int16)
    bits = (pixels[:, 1:] > pixels[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def _hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def photogrammetry_trackability(images) -> dict:
    """Estimate whether local feature matching is appropriate for this set."""
    values = [
        float(item.blur_score)
        for item in images
        if item.blur_score is not None and item.validation_status != "rejected"
    ]
    if not values:
        return {
            "level": "unknown",
            "score": 0,
            "label": "Ainda não analisada",
            "reason": "Valida as imagens para medir detalhe repetível.",
        }
    median_detail = float(np.median(values))
    score = int(np.clip(round((median_detail - 15) / 0.75), 0, 100))
    if score >= 45:
        level, label = "high", "Alta"
        reason = "O objeto contém detalhe visual repetível suficiente para tentar fotogrametria."
    elif score >= 20:
        level, label = "medium", "Média"
        reason = "Há algum detalhe; a reconstrução híbrida é mais robusta do que forçar o alinhamento clássico."
    else:
        level, label = "low", "Baixa"
        reason = "A superfície é lisa ou uniforme; a IA será usada se a fotogrametria não recuperar câmaras suficientes."
    return {"level": level, "score": score, "label": label, "reason": reason}


def validate_project(db: Session, project: Project) -> dict:
    mode = normalize_generation_mode(project.project_type)
    minimum_images = minimum_images_for_mode(mode)
    recommended_images = recommended_images_for_mode(mode)
    hashes: list[tuple[str, int]] = []
    signatures: list[tuple[object, np.ndarray]] = []
    approved = warnings = rejected = 0
    flash_count = background_dominant_count = 0

    for item in project.images:
        messages: list[str] = []
        item.duplicate_group = None
        try:
            path = Path(item.storage_path)
            if not path.is_absolute() and not path.exists():
                path = PROJECT_ROOT / "backend" / path
            with Image.open(path) as source:
                rgb = ImageOps.exif_transpose(source).convert("RGB")
                width, height = rgb.size
                gray_image = rgb.convert("L")
                gray = np.asarray(gray_image, dtype=np.float32)
                center = gray[height // 5 : height * 4 // 5, width // 5 : width * 4 // 5]
                mean = ImageStat.Stat(gray_image).mean[0]
                laplacian = (
                    -4 * gray
                    + np.roll(gray, 1, axis=0)
                    + np.roll(gray, -1, axis=0)
                    + np.roll(gray, 1, axis=1)
                    + np.roll(gray, -1, axis=1)
                )
                blur = float(laplacian[2:-2, 2:-2].var())
                highlight_ratio = float(np.mean(center > 248))
                vertical_edges = np.abs(np.diff(gray, axis=0, prepend=gray[:1]))
                horizontal_edges = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
                edge_energy = vertical_edges + horizontal_edges
                center_edges = edge_energy[height // 5 : height * 4 // 5, width // 5 : width * 4 // 5]
                center_energy = float(center_edges.mean())
                strong_edge = float(np.percentile(center_edges, 99))
                border_mask = np.ones_like(edge_energy, dtype=bool)
                border_mask[height // 5 : height * 4 // 5, width // 5 : width * 4 // 5] = False
                border_energy = float(edge_energy[border_mask].mean())
                digest = _difference_hash(rgb)

                signature_parts = []
                center_rgb = np.asarray(rgb, dtype=np.uint8)[
                    height // 6 : height * 5 // 6,
                    width // 6 : width * 5 // 6,
                ]
                for channel in range(3):
                    histogram, _ = np.histogram(
                        center_rgb[:, :, channel], bins=16, range=(0, 256), density=True
                    )
                    signature_parts.append(histogram)
                signature = np.concatenate(signature_parts).astype(np.float32)
                signature /= max(float(np.linalg.norm(signature)), 1e-8)
                signatures.append((item, signature))

                item.blur_score = round(blur, 2)
                item.exposure_score = round(max(0, 100 - abs(mean - 127.5) / 1.275), 2)
                if min(width, height) < 900:
                    messages.append("Resolução baixa; recomenda-se pelo menos 900 px no lado menor.")
                if blur < 8 and strong_edge < 35:
                    messages.append("O contorno parece desfocado; estabiliza a câmara e volta a fotografar.")
                if mean < 30 or mean > 242:
                    messages.append("A exposição parece demasiado escura ou clara.")
                if highlight_ratio > 0.18 and float(np.percentile(center, 20)) < 150:
                    messages.append("Há realces estourados; evita flash e reflexos diretos no objeto.")
                    flash_count += 1
                if border_energy > center_energy * 1.35:
                    background_dominant_count += 1

                duplicate = next(
                    ((image_id, value) for image_id, value in hashes if _hamming(digest, value) <= 3),
                    None,
                )
                if duplicate:
                    item.duplicate_group = duplicate[0]
                    messages.append("Imagem duplicada ou quase duplicada detetada.")
                else:
                    hashes.append((item.id, digest))

                if item.duplicate_group:
                    item.validation_status = "rejected"
                    rejected += 1
                elif messages:
                    item.validation_status = "warning"
                    warnings += 1
                else:
                    item.validation_status = "approved"
                    approved += 1
        except Exception:
            item.validation_status = "rejected"
            messages = ["Não foi possível ler a imagem."]
            rejected += 1
        item.validation_messages = messages

    consistency_estimate = 0
    if signatures:
        primary = next(
            (signature for item, signature in signatures if item.is_primary),
            signatures[0][1],
        )
        scores = []
        for item, signature in signatures:
            consistency = int(np.clip(round(float(np.dot(primary, signature)) * 100), 0, 100))
            item.consistency_score = consistency
            scores.append(consistency)
            if mode == "reality_scan" and consistency < 38 and item.validation_status == "approved":
                item.validation_status = "warning"
                item.validation_messages = [
                    *item.validation_messages,
                    "Esta vista difere muito da referência principal; confirma forma, cores e detalhes.",
                ]
                approved -= 1
                warnings += 1
        consistency_estimate = round(float(np.mean(scores)))

    count = len(project.images)
    usable = approved + warnings
    quantity_target = 1 if mode == "ai_generation" else 24
    quantity_score = min(100, round(usable / quantity_target * 100))
    technical_score = round((approved + warnings * 0.72) / max(1, count) * 100)
    capture_penalty = min(20, round(flash_count / max(1, count) * 16))
    score = max(0, round(quantity_score * 0.52 + technical_score * 0.48 - capture_penalty))
    project.validation_score = score
    project.status = "ready" if usable >= minimum_images else "draft"
    db.commit()

    trackability = photogrammetry_trackability(project.images)
    global_warnings: list[str] = []
    if usable < minimum_images:
        global_warnings.append(
            f"São necessárias pelo menos {minimum_images} imagens utilizáveis para o modo escolhido."
        )
    elif mode == "ai_generation":
        global_warnings.append(
            "A IA local usa apenas a imagem principal; as zonas invisíveis serão estimadas."
        )
    elif mode == "reality_scan" and trackability["level"] != "high":
        global_warnings.append(
            "A digitalização real pode falhar em superfícies lisas, transparentes ou refletoras."
        )
    if trackability["level"] == "low":
        global_warnings.append("Objeto liso detetado: a fotogrametria pode ter poucas correspondências visuais.")
    if flash_count:
        global_warnings.append(f"Flash/reflexos fortes detetados em {flash_count} imagem(ns).")
    if background_dominant_count > count * 0.35:
        global_warnings.append("O fundo tem mais detalhe do que o objeto; a segmentação automática irá isolá-lo.")
    if mode == "reality_scan" and consistency_estimate < 58:
        global_warnings.append(
            "As referências têm baixa consistência visual. Confirma que representam o mesmo objeto e define a vista principal."
        )

    diversity_values = [
        _hamming(left[1], right[1])
        for index, left in enumerate(hashes)
        for right in hashes[index + 1 :]
    ]
    view_diversity = int(
        np.clip(
            round((float(np.median(diversity_values)) if diversity_values else 0) / 24 * 100),
            0,
            100,
        )
    )

    return {
        "score": score,
        "capture_preparation_score": score,
        "input_quality_score": technical_score,
        "structural_consistency_estimate": consistency_estimate,
        "view_diversity_estimate": view_diversity,
        "approved": approved,
        "warnings": warnings,
        "rejected": rejected,
        "messages": global_warnings,
        "recommended_images": recommended_images,
        "minimum_images": minimum_images,
        "real_reconstruction_ready": usable >= minimum_images,
        "next_capture_suggestion": next_capture_suggestion(usable, mode),
        "photogrammetry_trackability": trackability,
        **capture_metrics(usable, score, trackability["level"], mode),
    }
