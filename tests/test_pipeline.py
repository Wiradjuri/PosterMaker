from pathlib import Path
from PIL import Image
from app.imaging.pipeline import process_exact
from app.models.settings import RunSettings
from app.models.enums import QualityPreset, FitMode, ExportFormat

def test_process_exact_sizes(tmp_path: Path):
    # Make a tiny image and force upscaling to A5@150 just to sanity-check dimension math
    src = tmp_path / "in.png"
    Image.new("RGB", (200, 200), (128, 128, 128)).save(src)

    settings = RunSettings(
        width_mm=148, height_mm=210, dpi=150,
        quality=QualityPreset.MEDIUM, fit_mode=FitMode.FIT,
        export_format=ExportFormat.PNG, output_dir=tmp_path
    )
    img = process_exact(src, settings)
    assert img.size == (874, 1240)  # A5 @ 150 DPI
