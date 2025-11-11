from __future__ import annotations
from pathlib import Path
from typing import List
from app.models.settings import RunSettings
from app.models.enums import ExportFormat
from app.workers.upscale_worker import UpscaleWorker

def default_output_namer(p: Path, settings: RunSettings) -> Path:
    base = p.stem
    ext = settings.export_format.value.lower()
    tw = settings.dpi
    out = settings.output_dir / f"{base}__{settings.width_mm:.0f}x{settings.height_mm:.0f}mm_{tw}dpi.{ext}"
    i = 1
    while out.exists():
        out = settings.output_dir / f"{base}__{settings.width_mm:.0f}x{settings.height_mm:.0f}mm_{tw}dpi_{i}.{ext}"
        i += 1
    return out

class JobController:
    def __init__(self, ui, logger):
        self.ui = ui
        self.logger = logger
        self.worker: UpscaleWorker | None = None

    def start(self, files: List[Path], settings: RunSettings):
        if self.worker and self.worker.isRunning():
            return
        self.worker = UpscaleWorker(files, settings, default_output_namer)
        self._wire_worker(self.worker)
        self.worker.start()

    def cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()

    def _wire_worker(self, w: UpscaleWorker):
        w.file_started.connect(lambda f: self.ui.on_file_started(f))
        w.file_progress.connect(lambda f, p: self.ui.on_file_progress(f, p))
        w.file_done.connect(lambda f: self.ui.on_file_done(f))
        w.error.connect(lambda msg: self.ui.on_error(msg))
        w.all_done.connect(lambda: self.ui.on_all_done())
        w.log_line.connect(lambda line: self.ui.append_log(line))
