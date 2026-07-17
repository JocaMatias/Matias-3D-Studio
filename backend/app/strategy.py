from dataclasses import asdict, dataclass


MINIMUM_AI_IMAGES = 5
RECOMMENDED_AI_IMAGES = "5–10"


@dataclass(frozen=True)
class ReconstructionStrategy:
    key: str
    label: str
    description: str
    uses_generative_ai: bool
    uses_photogrammetry: bool

    def as_dict(self) -> dict:
        return asdict(self)


def strategy_for_images(
    usable_images: int,
    photogrammetry_trackability: str = "unknown",
) -> ReconstructionStrategy:
    """Choose a pipeline from both coverage and actual surface trackability.

    A high image count does not make a smooth or inconsistent object suitable
    for feature-based photogrammetry.  Five useful views therefore enable the
    generative path, while COLMAP is only selected when the object has enough
    repeatable visual detail as well as enough views.
    """
    if usable_images < MINIMUM_AI_IMAGES:
        return ReconstructionStrategy(
            "insufficient",
            "Faltam vistas",
            f"Adiciona pelo menos {MINIMUM_AI_IMAGES - usable_images} fotografia(s) de ângulos diferentes.",
            False,
            False,
        )
    if usable_images <= 10:
        return ReconstructionStrategy(
            "ai_multiview",
            "IA multivista · até 4 candidatos",
            "A IA cria várias formas a partir das melhores vistas e conserva automaticamente a mais consistente.",
            True,
            False,
        )
    if usable_images >= 20 and photogrammetry_trackability == "high":
        return ReconstructionStrategy(
            "hybrid",
            "Híbrido de alta precisão",
            "Há vistas e detalhe repetível suficientes: a fotogrametria preserva o observado e a IA serve de fallback.",
            True,
            True,
        )
    return ReconstructionStrategy(
        "ai_refined",
        "IA multivista reforçada",
        "As vistas extra melhoram a seleção; superfícies lisas continuam na IA para evitar falhas de alinhamento.",
        True,
        False,
    )


def capture_metrics(
    usable_images: int,
    validation_score: int | None,
    photogrammetry_trackability: str = "unknown",
) -> dict:
    strategy = strategy_for_images(usable_images, photogrammetry_trackability)
    technical = validation_score or 0
    if usable_images < MINIMUM_AI_IMAGES:
        confidence = min(28, usable_images * 6)
    elif usable_images <= 10:
        # Five views are a valid AI input, but the number remains honest about
        # unobserved surfaces.  Extra views improve it progressively.
        confidence = 46 + (usable_images - 5) * 5
    elif usable_images < 20:
        confidence = 73 + min(14, (usable_images - 11) * 2)
    else:
        confidence = min(94, 86 + (usable_images - 20) // 2)
    if strategy.uses_photogrammetry:
        confidence = min(96, confidence + 3)

    coverage = min(96, round(48 + max(0, usable_images - 5) * 6)) if usable_images >= 5 else usable_images * 9
    # Image cleanliness is not the same thing as 3D fidelity.  In particular,
    # pristine studio photos can still leave the back, base or cavity inferred.
    # Keep the displayed estimate deliberately conservative for the generative
    # path instead of rewarding exposure/sharpness as if they proved geometry.
    fidelity = min(90, round(technical * 0.42 + coverage * 0.52))
    if strategy.uses_photogrammetry:
        fidelity = min(94, fidelity + 4)
    return {
        "pipeline": strategy.as_dict(),
        "visual_fidelity_estimate": fidelity,
        "geometric_confidence_estimate": confidence,
        "observed_coverage_estimate": coverage,
    }


def next_capture_suggestion(usable_images: int) -> str:
    if usable_images < 5:
        return "Fotografa frente, traseira, lado esquerdo, lado direito e uma vista ligeiramente superior."
    if usable_images < 8:
        return "A próxima vista mais útil é um ângulo intermédio ou uma vista do lado da pega."
    if usable_images < 10:
        return "Adiciona uma vista superior oblíqua e uma vista da base, sem mudar a distância."
    if usable_images < 20:
        return "Já podes reconstruir; novas vistas melhoram sobretudo cavidades, pega e zonas ocultas."
    return "Cobertura elevada: acrescenta apenas vistas de cavidades, base ou zonas ainda ocultas."
