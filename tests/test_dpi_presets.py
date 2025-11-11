from app.imaging.dpi_presets import default_dpi_for
from app.models.enums import QualityPreset

def test_default_dpi():
    assert default_dpi_for(QualityPreset.HIGH) == 300
