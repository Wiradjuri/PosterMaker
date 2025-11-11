from __future__ import annotations
from typing import Dict, Tuple, List
from app.models.enums import QualityPreset

QUALITY_TO_DPI: Dict[QualityPreset, int] = {
    QualityPreset.LOW: 150,
    QualityPreset.MEDIUM: 200,
    QualityPreset.HIGH: 300,
    QualityPreset.HIGHEST: 600,
}

DPI_CHOICES: List[Tuple[int, str]] = [
    (150, "Good at distance (fast, smaller files)"),
    (200, "Better detail, moderate size"),
    (240, "Fine posters, closer viewing"),
    (300, "Pro print standard"),
    (360, "High detail inkjet workflows"),
    (600, "Ultra fine detail; huge files"),
    (720, "Specialist workflows only"),
]

def default_dpi_for(q: QualityPreset) -> int:
    return QUALITY_TO_DPI[q]
