from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple
from .enums import QualityPreset, FitMode, ExportFormat

@dataclass(frozen=True)
class RunSettings:
    width_mm: float
    height_mm: float
    dpi: int
    quality: QualityPreset
    fit_mode: FitMode
    export_format: ExportFormat
    output_dir: Path
    keep_metadata: bool = False
    jpeg_quality: int = 95
    background_opaque: bool = True
    pad_color_rgba: Tuple[int, int, int, int] = (0, 0, 0, 255)
    stop_on_first_error: bool = False
