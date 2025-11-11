from __future__ import annotations
from typing import Tuple

MM_PER_INCH = 25.4

A_SERIES_MM = {
    "A0": (841, 1189),
    "A1": (594, 841),
    "A2": (420, 594),
    "A3": (297, 420),
    "A4": (210, 297),
    "A5": (148, 210),
}

def to_inches(mm: float) -> float:
    return mm / MM_PER_INCH

def target_pixels(width_mm: float, height_mm: float, dpi: int) -> Tuple[int, int]:
    w = max(1, round(to_inches(width_mm) * dpi))
    h = max(1, round(to_inches(height_mm) * dpi))
    return (w, h)
