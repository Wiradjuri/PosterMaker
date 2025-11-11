from enum import Enum

class QualityPreset(Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    HIGHEST = "Highest"

class FitMode(Enum):
    FIT = "Fit"         # keep aspect ratio, pad to size
    FILL = "Fill"       # cover then crop center
    STRETCH = "Stretch" # direct resize (Advanced only)

class ExportFormat(Enum):
    PNG = "PNG"
    TIFF = "TIFF"
    JPEG = "JPEG"
