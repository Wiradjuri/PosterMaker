from __future__ import annotations
from pathlib import Path
from typing import List
from PySide6.QtCore import QObject, Signal, QThread
from app.models.settings import RunSettings
from app.imaging.pipeline import process_and_save

class UpscaleWorker(QThread):
    file_started = Signal(str)
    file_progress = Signal(str, int)
    file_done = Signal(str)
    error = Signal(str)
    all_done = Signal()
    log_line = Signal(str)

    def __init__(self, files: List[Path], settings: RunSettings, output_namer):
        super().__init__()
        self._files = files
        self._settings = settings
        self._cancel = False
        self._output_namer = output_namer

    def cancel(self):
        self._cancel = True

    def run(self):
        total = len(self._files)
        for idx, f in enumerate(self._files, 1):
            if self._cancel:
                break
            try:
                self.file_started.emit(str(f))
                out_path = self._output_namer(f, self._settings)
                # Wire progress and preview callbacks into signals
                def _progress(p: int, fname=str(f)):
                    try:
                        self.file_progress.emit(str(fname), int(p))
                    except Exception:
                        pass

                def _preview(p: str):
                    try:
                        self.log_line.emit(f"Preview: {p}")
                    except Exception:
                        pass

                process_and_save(
                    f,
                    out_path,
                    self._settings,
                    progress_cb=_progress,
                    preview_cb=_preview,
                )
                self.file_progress.emit(str(f), int(idx * 100 / total))
                self.file_done.emit(str(out_path))
            except Exception as e:
                self.error.emit(f"{Path(f).name}: {e}")
        self.all_done.emit()
