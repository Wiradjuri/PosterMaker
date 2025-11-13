# app/ui_main_window.py
# Dark-mode GUI for PosterMaker with controls on the left and logs on the right.
# Entry point is main() at the bottom; can be run via:
#   python -m app.ui_main_window

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

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
)

from app.imaging.pipeline import process_exact, A_SIZES_MM

APP_NAME = "PosterMaker"
CONFIG_PATH = Path.home() / ".poster_maker_config.json"


# --------------------------- Logging bridge ---------------------------

class QtLogEmitter(QObject):
    message = Signal(str)


class QtLogHandler(logging.Handler):
    """Routes logging records to a Qt signal so we can append to the UI."""

    def __init__(self, emitter: QtLogEmitter):
        super().__init__()
        self.emitter = emitter

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        self.emitter.message.emit(msg)


# --------------------------- Worker Thread ---------------------------

class ProcessWorker(QThread):
    finished = Signal(bool, str, str)  # success, output_path, error_message
    progress = Signal(int)
    preview = Signal(str)  # not used for now, but kept for compatibility

    def __init__(self, args: dict, parent=None):
        super().__init__(parent)
        self.args = args

    def run(self) -> None:
        try:
            # Call pipeline with progress callback wired into this thread
            out_path = process_exact(
                **self.args,
                progress_cb=self.progress.emit,
                preview_cb=self.preview.emit,
            )
            self.finished.emit(True, str(out_path), "")
        except Exception as e:
            self.finished.emit(False, "", str(e))


# --------------------------- Main Window ---------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} – AI Poster Upscaler")
        self.resize(1200, 750)

        self._build_ui()
        self._install_logging_bridge()
        self._load_config_into_ui()

    # ---------------------- UI construction ----------------------

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        # Overall layout: left controls, right logs
        main_layout = QHBoxLayout(root)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # LEFT column (controls)
        left = QVBoxLayout()
        left.setSpacing(10)
        main_layout.addLayout(left, 0)

        # RIGHT column (logs)
        right = QVBoxLayout()
        main_layout.addLayout(right, 1)

        # ----- Files group -----
        files_group = QGroupBox("Files")
        files_layout = QFormLayout()
        files_group.setLayout(files_layout)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Choose a source image...")
        btn_in = QPushButton("Browse…")
        btn_in.clicked.connect(self._browse_input)
        in_row = self._hrow(self.input_edit, btn_in)
        files_layout.addRow("Input image:", in_row)

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Choose an output folder…")
        btn_out = QPushButton("Browse…")
        btn_out.clicked.connect(self._browse_output)
        out_row = self._hrow(self.output_edit, btn_out)
        files_layout.addRow("Output folder:", out_row)

        left.addWidget(files_group)

        # ----- Engine group -----
        engine_group = QGroupBox("Upscaler Engine (Real-ESRGAN NCNN)")
        engine_layout = QFormLayout()
        engine_group.setLayout(engine_layout)

        self.realesrgan_edit = QLineEdit()
        self.realesrgan_edit.setPlaceholderText(r"C:\tools\realesrgan-ncnn-vulkan.exe")
        btn_rex = QPushButton("Browse…")
        btn_rex.clicked.connect(self._browse_realesrgan)
        rex_row = self._hrow(self.realesrgan_edit, btn_rex)
        engine_layout.addRow("Executable:", rex_row)

        self.model_edit = QLineEdit("realesrgan-x4plus")
        engine_layout.addRow("Model:", self.model_edit)

        # Advanced engine options
        adv_row = QHBoxLayout()
        adv_row.setSpacing(8)

        self.tilesize_spin = QSpinBox()
        self.tilesize_spin.setRange(64, 2048)
        self.tilesize_spin.setSingleStep(64)
        self.tilesize_spin.setValue(512)
        adv_row.addWidget(QLabel("Tile size:"))
        adv_row.addWidget(self.tilesize_spin)

        self.fp16_check = QCheckBox("Use FP16")
        self.fp16_check.setChecked(True)
        adv_row.addWidget(self.fp16_check)

        adv_wrap = QWidget()
        adv_wrap.setLayout(adv_row)
        engine_layout.addRow("Advanced:", adv_wrap)

        left.addWidget(engine_group)

        # ----- Print settings group -----
        print_group = QGroupBox("Print Settings")
        print_layout = QFormLayout()
        print_group.setLayout(print_layout)

        self.paper_combo = QComboBox()
        for key in ("a1", "a2", "a3"):
            self.paper_combo.addItem(key.upper(), key)
        self.paper_combo.setCurrentIndex(0)
        print_layout.addRow("Paper:", self.paper_combo)

        self.dpi_combo = QComboBox()
        for val in [150, 200, 240, 300, 450, 600]:
            self.dpi_combo.addItem(f"{val} DPI", val)
        # default to 300
        idx_300 = next(
            (i for i in range(self.dpi_combo.count()) if self.dpi_combo.itemData(i) == 300),
            0,
        )
        self.dpi_combo.setCurrentIndex(idx_300)

        self.landscape_check = QCheckBox("Landscape")
        print_layout.addRow("Orientation:", self.landscape_check)

        self.force600_check = QCheckBox("Force 600 DPI (expert)")
        print_layout.addRow("600 DPI:", self.force600_check)

        left.addWidget(print_group)

        # ----- Controls row -----
        controls_row = QHBoxLayout()
        self.run_btn = QPushButton("Process")
        self.run_btn.clicked.connect(self._run)
        self.savecfg_btn = QPushButton("Save Settings")
        self.savecfg_btn.clicked.connect(self._save_config)
        controls_row.addWidget(self.run_btn)
        controls_row.addWidget(self.savecfg_btn)
        left.addLayout(controls_row)

        # ----- Progress bar -----
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        left.addWidget(self.progress)

        # ----- Logs on the right -----
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setLineWrapMode(QTextEdit.NoWrap)
        self.log_edit.setPlaceholderText("Logs will appear here…")
        right.addWidget(self.log_edit)

        # Tooltips for clarity
        files_group.setToolTip("Choose the input image and where to save the output file.")
        engine_group.setToolTip("Configure the Real-ESRGAN NCNN executable and model.")
        print_group.setToolTip("A1/A2/A3 paper and DPI for the final poster.")

        # Simple dark style
        self._apply_dark_style()

    def _apply_dark_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #121212;
                color: #e0e0e0;
            }
            QWidget {
                background-color: #121212;
                color: #e0e0e0;
                font-size: 11pt;
            }
            QGroupBox {
                border: 1px solid #333;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px;
                color: #bbbbbb;
            }
            QLineEdit, QComboBox, QTextEdit, QSpinBox {
                background-color: #1e1e1e;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 4px;
                selection-background-color: #2979ff;
            }
            QPushButton {
                background-color: #2979ff;
                color: white;
                border-radius: 4px;
                padding: 6px 10px;
            }
            QPushButton:hover {
                background-color: #448aff;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
            QProgressBar {
                background-color: #1e1e1e;
                border: 1px solid #444;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #00c853;
            }
            """
        )

    # ---------------------- Helpers ----------------------

    def _hrow(self, *widgets: QWidget) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        for wid in widgets:
            lay.addWidget(wid)
        return w

    def _append_log(self, text: str) -> None:
        self.log_edit.append(text)
        self.log_edit.moveCursor(QTextCursor.End)
        self.log_edit.ensureCursorVisible()

    # ---------------------- Logging bridge ----------------------

    def _install_logging_bridge(self) -> None:
        self.qt_log_emitter = QtLogEmitter()
        self.qt_log_emitter.message.connect(self._append_log)

        self.qt_handler = QtLogHandler(self.qt_log_emitter)
        fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")
        self.qt_handler.setFormatter(fmt)

        # Attach to the pipeline logger only
        self.pipeline_logger = logging.getLogger("poster-pipeline")
        self.pipeline_logger.setLevel(logging.INFO)
        if not any(isinstance(h, QtLogHandler) for h in self.pipeline_logger.handlers):
            self.pipeline_logger.addHandler(self.qt_handler)

        # Do NOT propagate to root to avoid duplicate console logs
        self.pipeline_logger.propagate = False

    # ---------------------- Config ----------------------

    def _load_config_into_ui(self) -> None:
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        else:
            data = {}

        self.realesrgan_edit.setText(
            data.get("realesrgan_exe", r"C:\tools\realesrgan-ncnn-vulkan.exe")
        )

        if "last_input" in data:
            self.input_edit.setText(data["last_input"])
        if "last_output" in data:
            self.output_edit.setText(data["last_output"])

        paper = data.get("paper", "a1")
        idx_paper = max(0, self.paper_combo.findData(paper))
        self.paper_combo.setCurrentIndex(idx_paper)

        dpi_val = data.get("dpi", 300)
        idx_dpi = next(
            (i for i in range(self.dpi_combo.count()) if self.dpi_combo.itemData(i) == dpi_val),
            self.dpi_combo.currentIndex(),
        )
        self.dpi_combo.setCurrentIndex(idx_dpi)

        self.landscape_check.setChecked(bool(data.get("landscape", False)))
        self.force600_check.setChecked(bool(data.get("force_600dpi", False)))
        self.tilesize_spin.setValue(int(data.get("tilesize", 512)))
        self.fp16_check.setChecked(bool(data.get("fp16", True)))
        self.model_edit.setText(data.get("model", "realesrgan-x4plus"))

    def _save_config(self) -> None:
        data = {
            "realesrgan_exe": self.realesrgan_edit.text().strip(),
            "last_input": self.input_edit.text().strip(),
            "last_output": self.output_edit.text().strip(),
            "paper": self.paper_combo.currentData(),
            "dpi": self.dpi_combo.currentData(),
            "landscape": self.landscape_check.isChecked(),
            "force_600dpi": self.force600_check.isChecked(),
            "tilesize": self.tilesize_spin.value(),
            "fp16": self.fp16_check.isChecked(),
            "model": self.model_edit.text().strip() or "realesrgan-x4plus",
        }
        try:
            CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
            QMessageBox.information(self, "Saved", f"Settings saved to {CONFIG_PATH}")
        except Exception as e:
            QMessageBox.critical(self, "Save Failed", f"Could not save settings:\n{e}")

    # ---------------------- Browsers ----------------------

    def _browse_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Input Image",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.tif *.tiff *.webp);;All Files (*)",
        )
        if path:
            self.input_edit.setText(path)

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose Output Folder", str(Path.home())
        )
        if path:
            self.output_edit.setText(path)

    def _browse_realesrgan(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Locate realesrgan-ncnn-vulkan.exe",
            r"C:\tools",
            "Executable (*.exe);;All Files (*)",
        )
        if path:
            self.realesrgan_edit.setText(path)

    # ---------------------- Validation & Run ----------------------

    def _validate_inputs(self) -> dict:
        inp = self.input_edit.text().strip()
        outd = self.output_edit.text().strip()
        rex = self.realesrgan_edit.text().strip()

        if not inp or not Path(inp).exists():
            raise ValueError("Please choose a valid input image.")
        if not outd:
            raise ValueError("Please choose an output folder.")
        Path(outd).mkdir(parents=True, exist_ok=True)

        if not rex or not Path(rex).exists():
            raise ValueError("Please set a valid path to realesrgan-ncnn-vulkan.exe.")

        dpi = int(self.dpi_combo.currentData())
        if dpi == 600 and not self.force600_check.isChecked():
            raise ValueError(
                "600 DPI requires 'Force 600 DPI (expert)'. "
                "Either lower DPI or enable the checkbox."
            )

        args = {
            "input_path": inp,
            "output_dir": outd,
            "paper": self.paper_combo.currentData(),  # 'a1' | 'a2' | 'a3'
            "dpi": dpi,
            "portrait": not self.landscape_check.isChecked(),
            "exe_path": rex,
            "model": self.model_edit.text().strip() or "realesrgan-x4plus",
            "tilesize": int(self.tilesize_spin.value()),
            "fp16": bool(self.fp16_check.isChecked()),
            "force_600dpi": bool(self.force600_check.isChecked()),
            "keep_native_if_larger": False,
        }
        return args

    def _run(self) -> None:
        try:
            args = self._validate_inputs()
        except Exception as e:
            QMessageBox.warning(self, "Fix settings", str(e))
            return

        self._save_config()

        # Busy UI state
        self.run_btn.setEnabled(False)
        self.savecfg_btn.setEnabled(False)
        self.progress.setValue(0)

        self._append_log("\n======================================================================")
        self._append_log("Starting processing…")
        self._append_log(
            f"Settings: paper={args['paper'].upper()}  dpi={args['dpi']}  "
            f"landscape={args['portrait'] is False}  model={args['model']}  "
            f"tilesize={args['tilesize']}  fp16={args['fp16']}"
        )
        self._append_log("======================================================================")

        self.worker = ProcessWorker(args)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _on_finished(self, success: bool, out_path: str, error: str) -> None:
        self.run_btn.setEnabled(True)
        self.savecfg_btn.setEnabled(True)

        if success:
            self._append_log(f"✅ Done. Output: {out_path}")
            self.progress.setValue(100)
            QMessageBox.information(self, "Done", f"Saved:\n{out_path}")
        else:
            self._append_log("❌ Failed.")
            self._append_log(error)
            QMessageBox.critical(self, "Processing Failed", error)


# --------------------------- App entry ---------------------------

def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
