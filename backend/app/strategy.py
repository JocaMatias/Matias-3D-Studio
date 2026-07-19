from dataclasses import asdict, dataclass


AI_MULTIVIEW_MIN_IMAGES = 1
AI_MULTIVIEW_MAX_IMAGES = 4
HYBRID_MIN_IMAGES = 5
HYBRID_RECOMMENDED_MAX_IMAGES = 15
PRECISION_MIN_IMAGES = 20

# Backwards-compatible names used by the API and diagnostics.
MINIMUM_AI_IMAGES = AI_MULTIVIEW_MIN_IMAGES
RECOMMENDED_AI_IMAGES = "1–4"

GENERATION_MODES = {
    "ai_multiview": {
        "label": "IA Multivista",
        "minimum": AI_MULTIVIEW_MIN_IMAGES,
        "recommended": "1–4 imagens",
    },
    "hybrid": {
        "label": "Reconstrução híbrida",
        "minimum": HYBRID_MIN_IMAGES,
        "recommended": "5–15 imagens",
    },
    "precision_scan": {
        "label": "Digitalização precisa",
        "minimum": PRECISION_MIN_IMAGES,
        "recommended": "20+ imagens",
    },
}

LEGACY_MODE_ALIASES = {
    "ai_references": "ai_multiview",
    "real_photos": "hybrid",
}


def normalize_generation_mode(value: str) -> str:
    return LEGACY_MODE_ALIASES.get(value, value if value in GENERATION_MODES else "ai_multiview")


def minimum_images_for_mode(value: str) -> int:
    return int(GENERATION_MODES[normalize_generation_mode(value)]["minimum"])


def recommended_images_for_mode(value: str) -> str:
    return str(GENERATION_MODES[normalize_generation_mode(value)]["recommended"])


@dataclass(frozen=True)
class ReconstructionStrategy:
    key: str
    label: str
    description: str
    uses_generative_ai: bool
    uses_photogrammetry: bool
    minimum_images: int
    recommended_images: str

    def as_dict(self) -> dict:
        return asdict(self)


def _insufficient(mode: str, usable_images: int) -> ReconstructionStrategy:
    normalized = normalize_generation_mode(mode)
    info = GENERATION_MODES[normalized]
    minimum = int(info["minimum"])
    missing = max(0, minimum - usable_images)
    return ReconstructionStrategy(
        "insufficient",
        f"{info['label']} · faltam vistas",
        f"Adiciona pelo menos {missing} imagem(ns) utilizável(eis) para este modo.",
        normalized != "precision_scan",
        normalized == "precision_scan",
        minimum,
        str(info["recommended"]),
    )


def strategy_for_images(
    usable_images: int,
    photogrammetry_trackability: str = "unknown",
) -> ReconstructionStrategy:
    """Choose one of the three public pipelines from usable image coverage."""
    if usable_images < AI_MULTIVIEW_MIN_IMAGES:
        return _insufficient("ai_multiview", usable_images)
    if usable_images <= AI_MULTIVIEW_MAX_IMAGES:
        return strategy_for_project("ai_multiview", usable_images, photogrammetry_trackability)
    if usable_images < PRECISION_MIN_IMAGES:
        return strategy_for_project("hybrid", usable_images, photogrammetry_trackability)
    return strategy_for_project("precision_scan", usable_images, photogrammetry_trackability)


def strategy_for_project(
    project_type: str,
    usable_images: int,
    photogrammetry_trackability: str = "unknown",
) -> ReconstructionStrategy:
    mode = normalize_generation_mode(project_type)
    minimum = minimum_images_for_mode(mode)
    recommended = recommended_images_for_mode(mode)
    if usable_images < minimum:
        return _insufficient(mode, usable_images)

    if mode == "ai_multiview":
        return ReconstructionStrategy(
            "ai_multiview",
            "IA Multivista · 1–4 imagens",
            "A IA preserva as vistas observadas, infere superfícies ocultas e compara vários candidatos.",
            True,
            False,
            minimum,
            recommended,
        )
    if mode == "precision_scan":
        trackability_note = (
            "A textura visual é adequada para recuperar câmaras reais."
            if photogrammetry_trackability == "high"
            else "A fotogrametria será tentada e a IA mantém um fallback seguro se o alinhamento não for suficiente."
        )
        return ReconstructionStrategy(
            "precision_scan",
            "Digitalização precisa · 20+ imagens",
            f"COLMAP e OpenMVS usam todas as vistas para geometria e textura. {trackability_note}",
            True,
            True,
            minimum,
            recommended,
        )

    transition = (
        " Já tens cobertura elevada; com 20 imagens podes mudar para Digitalização precisa."
        if usable_images >= 16
        else ""
    )
    return ReconstructionStrategy(
        "hybrid",
        "Reconstrução híbrida · 5–15 imagens",
        "As vistas reais ancoram a forma e a IA completa zonas ocultas, gera candidatos e valida a malha." + transition,
        True,
        False,
        minimum,
        recommended,
    )


def capture_metrics(
    usable_images: int,
    validation_score: int | None,
    photogrammetry_trackability: str = "unknown",
    project_type: str = "ai_multiview",
) -> dict:
    strategy = strategy_for_project(project_type, usable_images, photogrammetry_trackability)
    technical = validation_score or 0
    mode = normalize_generation_mode(project_type)

    if usable_images <= 0:
        observed_coverage = 0
    elif mode == "ai_multiview":
        observed_coverage = min(58, 24 + (usable_images - 1) * 11)
    elif mode == "hybrid":
        observed_coverage = min(88, 52 + max(0, usable_images - 5) * 3)
    else:
        observed_coverage = min(97, 78 + max(0, usable_images - 20))

    # These are explicitly capture estimates. Final result confidence is capped
    # later by mesh integrity and candidate-validation metrics.
    confidence = round(technical * 0.32 + observed_coverage * 0.58)
    fidelity = round(technical * 0.45 + observed_coverage * 0.48)
    if strategy.uses_photogrammetry and photogrammetry_trackability == "high":
        confidence += 5
        fidelity += 4
    confidence = int(max(0, min(94, confidence)))
    fidelity = int(max(0, min(94, fidelity)))
    return {
        "pipeline": strategy.as_dict(),
        "visual_fidelity_estimate": fidelity,
        "geometric_confidence_estimate": confidence,
        "observed_coverage_estimate": observed_coverage,
    }


def next_capture_suggestion(usable_images: int) -> str:
    if usable_images <= 0:
        return "Começa por uma vista frontal a 45°, com o objeto completo e fundo simples."
    if usable_images == 1:
        return "Adiciona o lado oposto ou uma vista traseira para reduzir a geometria inventada."
    if usable_images < 4:
        return "Adiciona um ângulo complementar, evitando repetir quase a mesma vista."
    if usable_images < 5:
        return "Já podes usar IA Multivista; a quinta imagem desbloqueia a Reconstrução híbrida."
    if usable_images < 15:
        return "Fotografa cavidades, ligações finas e o lado menos observado do objeto."
    if usable_images < 20:
        return "Adiciona vistas intermédias até 20 para desbloquear a Digitalização precisa."
    return "Cobertura elevada: acrescenta apenas base, topo, cavidades ou zonas ainda ocultas."
