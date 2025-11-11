from pathlib import Path
from PIL import Image
from app.imaging.pipeline import process_exact
from app.models.settings import RunSettings
from app.models.enums import QualityPreset, FitMode, ExportFormat

tmp = Path('C:/Temp/poster_test')
tmp.mkdir(parents=True, exist_ok=True)
src = tmp / 'in.png'
Image.new('RGB',(200,200),(128,128,128)).save(src)

settings = RunSettings(
    width_mm=148, height_mm=210, dpi=150,
    quality=QualityPreset.MEDIUM, fit_mode=FitMode.FIT,
    export_format=ExportFormat.PNG, output_dir=tmp
)

img = process_exact(src, settings)
print('Saved:', img.size)
