from dataclasses import asdict, dataclass

AI_GENERATION_MIN_IMAGES = 1
REALITY_SCAN_MIN_IMAGES = 20

MINIMUM_AI_IMAGES = AI_GENERATION_MIN_IMAGES
RECOMMENDED_AI_IMAGES = "1 imagem principal"

GENERATION_MODES = {
    "ai_generation": {
        "label": "Criar com IA",
        "minimum": AI_GENERATION_MIN_IMAGES,
        "recommended": "1 imagem principal",
    },
    "reality_scan": {
        "label": "Digitalizar objeto real",
        "minimum": REALITY_SCAN_MIN_IMAGES,
        "recommended": "20+ fotografias reais",
    },
}

LEGACY_MODE_ALIASES = {
    "ai_references": "ai_generation",
    "ai_multiview": "ai_generation",
    "hybrid": "ai_generation",
    "real_photos": "reality_scan",
    "precision_scan": "reality_scan",
}


def normalize_generation_mode(value: str) -> str:
    return LEGACY_MODE_ALIASES.get(value, value if value in GENERATION_MODES else "ai_generation")


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
        f"{info['label']} · faltam imagens",
        f"Adiciona pelo menos {missing} imagem(ns) utilizável(eis) para este modo.",
        normalized == "ai_generation",
        normalized == "reality_scan",
        minimum,
        str(info["recommended"]),
    )


def strategy_for_images(usable_images: int, photogrammetry_trackability: str = "unknown") -> ReconstructionStrategy:
    if usable_images < AI_GENERATION_MIN_IMAGES:
        return _insufficient("ai_generation", usable_images)
    if usable_images >= REALITY_SCAN_MIN_IMAGES:
        return strategy_for_project("reality_scan", usable_images, photogrammetry_trackability)
    return strategy_for_project("ai_generation", usable_images, photogrammetry_trackability)


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

    if mode == "reality_scan":
        return ReconstructionStrategy(
            "reality_scan",
            "Digitalizar objeto real",
            "Fotogrametria baseada em fotografias reais. As zonas não observadas não são apresentadas como medidas.",
            False,
            True,
            minimum,
            recommended,
        )

    return ReconstructionStrategy(
        "ai_generation",
        "Criar com IA · imagem única",
        "A imagem principal define a identidade. O motor local gera uma malha completa e estima as zonas invisíveis.",
        True,
        False,
        minimum,
        recommended,
    )


def capture_metrics(
    usable_images: int,
    validation_score: int | None,
    photogrammetry_trackability: str = "unknown",
    project_type: str = "ai_generation",
) -> dict:
    strategy = strategy_for_project(project_type, usable_images, photogrammetry_trackability)
    technical = int(validation_score or 0)
    mode = normalize_generation_mode(project_type)

    if mode == "ai_generation":
        observed_coverage = 35 if usable_images else 0
        confidence = min(45, round(technical * 0.28 + observed_coverage * 0.42))
        fidelity = min(55, round(technical * 0.34 + observed_coverage * 0.50))
    else:
        observed_coverage = min(97, 72 + max(0, usable_images - 20))
        confidence = min(95, round(technical * 0.36 + observed_coverage * 0.58))
        fidelity = min(95, round(technical * 0.40 + observed_coverage * 0.54))

    return {
        "pipeline": strategy.as_dict(),
        "visual_fidelity_estimate": int(max(0, fidelity)),
        "geometric_confidence_estimate": int(max(0, confidence)),
        "observed_coverage_estimate": int(max(0, observed_coverage)),
    }


def next_capture_suggestion(usable_images: int, project_type: str = "ai_generation") -> str:
    if normalize_generation_mode(project_type) == "ai_generation":
        if usable_images <= 0:
            return "Carrega uma imagem a 30–45°, com o objeto inteiro, fundo simples e boa luz."
        return "A imagem principal será a única usada para gerar a geometria nesta versão."
    if usable_images < 20:
        return "Completa uma volta lateral e outra superior com 70–80% de sobreposição."
    return "Acrescenta apenas base, topo, cavidades ou zonas ainda sem cobertura."
