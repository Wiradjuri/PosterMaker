# app/ui_main_window.py
# PosterMaker — modern dark UI (ChatGPT-like) with right-side log pane
# - Works when run as a module OR as a script (adds project root to sys.path)
# - QSplitter: controls on the left, logs on the right
# - Visible checkboxes, clean theme
# - “Keep native pixels (no shrink)”
# - No duplicate log propagation

from __future__ import annotations

import json
import logging
import sys
import traceback
from pathlib import Path

# Path bootstrap: ensure package imports work when running as a module or script
# Insert project root into sys.path so `import app.*` resolves correctly.
_THIS = Path(__file__).resolve()
_ROOT = _THIS.parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QFileDialog,
    QTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QSplitter,
)

# Import pipeline after path bootstrap
try:
    from app.imaging.pipeline import process_exact
except Exception as e:
    raise RuntimeError(f"Failed to import pipeline: {e}")

APP_NAME = "PosterMaker"
CONFIG_PATH = Path.home() / ".poster_maker_config.json"

# ====================== Theme (ChatGPT-like dark) ======================
DARK_QSS = """
* { font-family: "Segoe UI", "Inter", "Segoe UI Variable", Arial, sans-serif; }
QWidget { background: #0E0F13; color: #E6E8EE; }
QToolTip { background: #1F2330; color: #E6E8EE; border: 1px solid #2A2D37; padding: 6px 8px; border-radius: 8px; }
#TitleLabel { font-size: 22px; font-weight: 700; letter-spacing: 0.2px; }
#SubtitleLabel { font-size: 12px; color: #B7BECC; }
QGroupBox { margin-top: 14px; border: 1px solid #2A2D37; border-radius: 12px; background: #1A1C23; padding-top: 12px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 12px; top: 6px; padding: 0 6px; color: #DDE2EC; }
QLabel { color: #D5DBE8; }
QLineEdit, QComboBox, QTextEdit, QSpinBox { background: #12141A; border: 1px solid #2A2D37; border-radius: 10px; padding: 8px; selection-background-color: #2AB691; selection-color: #0B0C10; }
QLineEdit:hover, QComboBox:hover, QTextEdit:hover, QSpinBox:hover { border-color: #3A3F4E; }
QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QSpinBox:focus { border-color: #10A37F; box-shadow: 0 0 0 1px #10A37F; }
QCheckBox { color: #E6E8EE; spacing: 10px; }
QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #2A2D37; border-radius: 5px; background: #0E0F13; }
QCheckBox::indicator:hover { border-color: #3A3F4E; }
QCheckBox::indicator:checked { background: #10A37F; border: 1px solid #10A37F; image: url(); }
QCheckBox::indicator:checked:hover { background: #2AB691; border-color: #2AB691; }
QPushButton { background: #222632; border: 1px solid #2E3342; border-radius: 12px; padding: 10px 14px; font-weight: 600; color: #E6E8EE; }
QPushButton:hover { background: #2A2F3D; border-color: #3B4153; }
QPushButton:pressed { background: #202431; }
QPushButton#PrimaryButton { background: #10A37F; border: 1px solid #10A37F; color: #0B0C10; }
QPushButton#PrimaryButton:hover { background: #2AB691; border-color: #2AB691; }
QPushButton#PrimaryButton:disabled { background: #1E2230; color: #8A93A6; }
QProgressBar { border: 1px solid #2A2D37; border-radius: 10px; background: #12141A; height: 10px; text-align: center; }
QProgressBar::chunk { background: #10A37F; border-radius: 9px; }
QTextEdit { background: #0E1016; border: 1px solid #2A2D37; border-radius: 12px; }
"""

# ====================== Logging bridge ======================
class QtLogEmitter(QObject):
    message = Signal(str)

class QtLogHandler(logging.Handler):
    def __init__(self, emitter: QtLogEmitter):
        super().__init__()
        self.emitter = emitter
        self.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S"))
    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        self.emitter.message.emit(msg)

class ProcessWorker(QThread):
    finished = Signal(bool, str, str)
    def __init__(self, args: dict, parent=None):
        super().__init__(parent)
        self.args = args
    def run(self):
        try:
            out_path = process_exact(**self.args)
            self.finished.emit(True, str(out_path), "")
        except Exception as e:
            tb = traceback.format_exc()
            self.finished.emit(False, "", f"{e}\n\n{tb}")

# ====================== Main Window ======================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — A1 Poster Upscaler")
        self.resize(1200, 780)
        self.setStyleSheet(DARK_QSS)

        # Splitter: left controls | right log
        splitter = QSplitter(Qt.Horizontal, self)
        self.setCentralWidget(splitter)

        # Left panel (controls)
        left = QWidget(); splitter.addWidget(left)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(16, 14, 16, 14)
        left_layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("PosterMaker"); title.setObjectName("TitleLabel")
        subtitle = QLabel("Ultra-high-definition poster export • Real-ESRGAN"); subtitle.setObjectName("SubtitleLabel")
        lbox = QVBoxLayout(); lbox.addWidget(title); lbox.addWidget(subtitle)
        header.addLayout(lbox); header.addStretch(1)
        left_layout.addLayout(header)

        left_layout.addWidget(self._files_card())
        left_layout.addWidget(self._engine_card())
        left_layout.addWidget(self._print_card())

        controls = QHBoxLayout()
        self.run_btn = QPushButton("▶  Process"); self.run_btn.setObjectName("PrimaryButton")
        self.run_btn.clicked.connect(self._run)
        self.save_btn = QPushButton("💾  Save Settings"); self.save_btn.clicked.connect(self._save_config)
        controls.addWidget(self.run_btn); controls.addWidget(self.save_btn); controls.addStretch(1)
        left_layout.addLayout(controls)

        self.progress = QProgressBar(); self.progress.setRange(0, 1); self.progress.setValue(0)
        left_layout.addWidget(self.progress)

        # Right panel (log)
        right = QWidget(); splitter.addWidget(right)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 14, 16, 14)
        right_layout.setSpacing(10)
        log_label = QLabel("Logs"); log_label.setObjectName("SubtitleLabel")
        self.log_edit = QTextEdit(); self.log_edit.setReadOnly(True); self.log_edit.setPlaceholderText("Logs will appear here…")
        right_layout.addWidget(log_label); right_layout.addWidget(self.log_edit, 1)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([560, 640])

        # Logging bridge
        self._install_logging_bridge()
        # Load config
        self._load_config_into_ui()

    # ---------- Cards ----------
    def _files_card(self) -> QGroupBox:
        gb = QGroupBox("Files")
        form = QFormLayout(gb)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Choose a source image…")
        self.input_edit.setToolTip("Pick the photo you want to turn into a print-ready poster (JPG/PNG/TIFF).")
        b_in = QPushButton("Browse…"); b_in.clicked.connect(self._browse_input)
        form.addRow("Input image:", self._row(self.input_edit, b_in))

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Choose an output folder…")
        self.output_edit.setToolTip("Folder where the processed poster image will be saved.")
        b_out = QPushButton("Browse…"); b_out.clicked.connect(self._browse_output)
        form.addRow("Output folder:", self._row(self.output_edit, b_out))
        return gb

    def _engine_card(self) -> QGroupBox:
        gb = QGroupBox("Upscaler Engine (Real-ESRGAN NCNN)")
        form = QFormLayout(gb)

        self.realesrgan_edit = QLineEdit()
        self.realesrgan_edit.setPlaceholderText(r"C:\tools\realesrgan-ncnn-vulkan\realesrgan-ncnn-vulkan.exe")
        self.realesrgan_edit.setToolTip("Full path to realesrgan-ncnn-vulkan.exe. No fallback is used.")
        b_rex = QPushButton("Browse…"); b_rex.clicked.connect(self._browse_realesrgan)
        form.addRow("Executable:", self._row(self.realesrgan_edit, b_rex))

        self.model_edit = QLineEdit("realesrgan-x4plus")
        self.model_edit.setToolTip("Model name. Ensure matching *.param and *.bin exist in the 'models' folder.")
        form.addRow("Model:", self.model_edit)

        adv = QHBoxLayout()
        self.tilesize_spin = QSpinBox(); self.tilesize_spin.setRange(64, 2048); self.tilesize_spin.setSingleStep(64); self.tilesize_spin.setValue(512)
        self.tilesize_spin.setToolTip("Tile size. Lower if you run out of VRAM; higher may be faster.")
        self.fp16_check = QCheckBox("Use FP16"); self.fp16_check.setChecked(True)
        self.fp16_check.setToolTip("Half-precision for speed. Disable if the driver/device crashes.")
        adv.addWidget(QLabel("Tile size:")); adv.addWidget(self.tilesize_spin); adv.addSpacing(16); adv.addWidget(self.fp16_check)
        w = QWidget(); w.setLayout(adv)
        form.addRow("Advanced:", w)
        return gb

    def _print_card(self) -> QGroupBox:
        gb = QGroupBox("Print Settings")
        form = QFormLayout(gb)

        self.paper_combo = QComboBox()
        for key in ("a1", "a2", "a3"):
            self.paper_combo.addItem(key.upper(), key)
        self.paper_combo.setToolTip("Paper size (A1 = 594×841 mm).")

        self.dpi_combo = QComboBox()
        for val in [150, 200, 240, 300, 450, 600]:
            self.dpi_combo.addItem(f"{val} DPI", val)
        self._select_combo_value(self.dpi_combo, 300)
        self.dpi_combo.currentIndexChanged.connect(self._on_dpi_changed)
        self.dpi_combo.setToolTip("Print resolution. 300–450 DPI is typical; 600 DPI is very large.")

        orow = QHBoxLayout()
        self.landscape_check = QCheckBox("Landscape")
        orow.addWidget(self.landscape_check)
        orient = QWidget(); orient.setLayout(orow)

        self.force600_check = QCheckBox("Force 600 DPI (expert)")
        self.force600_check.setChecked(False)
        self.force600_check.setToolTip("Required when choosing 600 DPI to avoid accidental giant images.")

        self.keepnative_check = QCheckBox("Keep native pixels (no shrink)")
        self.keepnative_check.setToolTip("If source ≥ target, keep full native pixels and only set the DPI tag.")

        form.addRow("Paper:", self.paper_combo)
        form.addRow("Resolution:", self._row(self.dpi_combo, self.force600_check))
        form.addRow("Orientation:", orient)
        form.addRow("", self.keepnative_check)
        return gb

    # ---------- Helpers ----------
    def _row(self, *widgets) -> QWidget:
        w = QWidget(); h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0); h.setSpacing(8)
        for wid in widgets: h.addWidget(wid)
        h.addStretch(1); return w

    def _append_log(self, text: str):
        self.log_edit.append(text)
        self.log_edit.moveCursor(QTextCursor.End)
        self.log_edit.ensureCursorVisible()

    def _install_logging_bridge(self):
        self.qt_emitter = QtLogEmitter()
        self.qt_emitter.message.connect(self._append_log)
        self.qt_handler = QtLogHandler(self.qt_emitter)
        self.pipeline_logger = logging.getLogger("poster-pipeline")
        self.pipeline_logger.setLevel(logging.INFO)
        self.pipeline_logger.propagate = False
        if not any(isinstance(h, QtLogHandler) for h in self.pipeline_logger.handlers):
            self.pipeline_logger.addHandler(self.qt_handler)

    def _select_combo_value(self, combo: QComboBox, value):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i); return

    # ---------- Config ----------
    def _load_config_into_ui(self):
        data = {}
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                data = {}

        self.realesrgan_edit.setText(data.get("realesrgan_exe", ""))
        if "last_input" in data:  self.input_edit.setText(data["last_input"])
        if "last_output" in data: self.output_edit.setText(data["last_output"])

        paper = data.get("paper", "a1")
        idx = max(0, self.paper_combo.findData(paper))
        self.paper_combo.setCurrentIndex(idx)

        self._select_combo_value(self.dpi_combo, data.get("dpi", 300))
        self.landscape_check.setChecked(bool(data.get("landscape", False)))
        self.force600_check.setChecked(bool(data.get("force_600dpi", False)))
        self.keepnative_check.setChecked(bool(data.get("keep_native_if_larger", False)))
        self.tilesize_spin.setValue(int(data.get("tilesize", 512)))
        self.fp16_check.setChecked(bool(data.get("fp16", True)))
        self.model_edit.setText(data.get("model", "realesrgan-x4plus"))

    def _save_config(self):
        data = {
            "realesrgan_exe": self.realesrgan_edit.text().strip(),
            "last_input": self.input_edit.text().strip(),
            "last_output": self.output_edit.text().strip(),
            "paper": self.paper_combo.currentData(),
            "dpi": self.dpi_combo.currentData(),
            "landscape": self.landscape_check.isChecked(),
            "force_600dpi": self.force600_check.isChecked(),
            "keep_native_if_larger": self.keepnative_check.isChecked(),
            "tilesize": self.tilesize_spin.value(),
            "fp16": self.fp16_check.isChecked(),
            "model": self.model_edit.text().strip() or "realesrgan-x4plus",
        }
        try:
            CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
            QMessageBox.information(self, "Saved", f"Settings saved to {CONFIG_PATH}")
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", f"Could not save settings:\n{e}")

    # ---------- Browse ----------
    def _browse_input(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose Input Image", str(Path.home()),
                                              "Images (*.png *.jpg *.jpeg *.tif *.tiff *.webp);;All Files (*)")
        if path: self.input_edit.setText(path)

    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(self, "Choose Output Folder", str(Path.home()))
        if path: self.output_edit.setText(path)

    def _browse_realesrgan(self):
        path, _ = QFileDialog.getOpenFileName(self, "Locate realesrgan-ncnn-vulkan.exe", str(Path.home()),
                                              "Executable (*.exe);;All Files (*)")
        if path: self.realesrgan_edit.setText(path)

    # ---------- Interactions ----------
    def _on_dpi_changed(self):
        dpi = self.dpi_combo.currentData()
        if dpi == 600 and not self.force600_check.isChecked():
            self._append_log("⚠️  600 DPI selected. Tick 'Force 600 DPI (expert)' to proceed, otherwise use 300–450 DPI.")

    # ---------- Run ----------
    def _validate_inputs(self):
        inp = self.input_edit.text().strip()
        outd = self.output_edit.text().strip()
        rex = self.realesrgan_edit.text().strip()

        if not inp or not Path(inp).exists():
            raise ValueError("Please choose a valid input image.")
        if not outd:
            raise ValueError("Please choose an output folder.")
        Path(outd).mkdir(parents=True, exist_ok=True)
        if not rex or not Path(rex).exists():
            raise ValueError("Please set a valid path to realesrgan-ncnn-vulkan.exe (no fallback is used).")

        dpi = int(self.dpi_combo.currentData())
        if dpi == 600 and not self.force600_check.isChecked():
            raise ValueError("600 DPI requires 'Force 600 DPI (expert)'. Untick 600 DPI or enable the checkbox.")

        return {
            "input_path": inp,
            "output_dir": outd,
            "paper": self.paper_combo.currentData(),
            "dpi": dpi,
            "portrait": not self.landscape_check.isChecked(),
            "exe_path": rex,
            "model": self.model_edit.text().strip() or "realesrgan-x4plus",
            "tilesize": int(self.tilesize_spin.value()),
            "fp16": bool(self.fp16_check.isChecked()),
            "force_600dpi": bool(self.force600_check.isChecked()),
            "keep_native_if_larger": bool(self.keepnative_check.isChecked()),
        }

    def _run(self):
        try:
            args = self._validate_inputs()
        except Exception as e:
            QMessageBox.warning(self, "Fix settings", str(e)); return

        self._save_config()

        self.run_btn.setEnabled(False); self.save_btn.setEnabled(False)
        self.progress.setRange(0, 0)
        self._append_log("\n" + "=" * 70)
        self._append_log("Starting processing…")
        self._append_log(f"Settings: paper={args['paper'].upper()}  dpi={args['dpi']}  "
                         f"landscape={not args['portrait']}  keep_native={args['keep_native_if_larger']}  "
                         f"model={args['model']}  tilesize={args['tilesize']}  fp16={args['fp16']}")
        self._append_log("=" * 70)

        self.worker = ProcessWorker(args)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_finished(self, success: bool, out_path: str, error: str):
        self.progress.setRange(0, 1); self.progress.setValue(0)
        self.run_btn.setEnabled(True); self.save_btn.setEnabled(True)
        if success:
            self._append_log(f"✅ Done. Output: {out_path}")
            QMessageBox.information(self, "Done", f"Saved:\n{out_path}")
        else:
            self._append_log("❌ Failed.\n" + error)
            QMessageBox.critical(self, "Processing Failed", error)

# --------------------------- App entry ---------------------------
def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())
