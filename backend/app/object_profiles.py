from dataclasses import dataclass


OBJECT_PROFILES = {
    "auto",
    "compact",
    "thin_parts",
    "multi_component",
    "handled_container",
    "mechanical",
    "organic",
    "architecture",
}


PROFILE_LABELS = {
    "auto": "Automático (conservador)",
    "compact": "Objeto compacto",
    "thin_parts": "Partes finas",
    "multi_component": "Várias peças",
    "handled_container": "Recipiente com pega",
    "mechanical": "Mecânico / veículo",
    "organic": "Orgânico",
    "architecture": "Arquitetura",
}


def normalize_object_profile(value: str | None) -> str:
    return value if value in OBJECT_PROFILES else "auto"


@dataclass(frozen=True)
class RepairPolicy:
    minimum_component_faces: int
    relative_component_size: float
    maximum_components: int
    nearby_gap_ratio: float
    fill_holes: bool
    penalize_ground_sheets: bool


def repair_policy(value: str | None) -> RepairPolicy:
    profile = normalize_object_profile(value)
    policies = {
        "compact": RepairPolicy(50, 0.006, 24, 0.055, True, True),
        "handled_container": RepairPolicy(24, 0.0015, 64, 0.14, False, True),
        "thin_parts": RepairPolicy(8, 0.0002, 192, 0.32, False, True),
        "multi_component": RepairPolicy(8, 0.00015, 256, 0.38, False, True),
        "mechanical": RepairPolicy(16, 0.00025, 192, 0.34, False, True),
        "organic": RepairPolicy(24, 0.0012, 72, 0.15, False, True),
        "architecture": RepairPolicy(8, 0.00015, 256, 0.35, False, False),
        "auto": RepairPolicy(20, 0.0008, 96, 0.16, False, True),
    }
    return policies[profile]
