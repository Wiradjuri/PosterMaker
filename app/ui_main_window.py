# app/ui_main_window.py
# FIXED VERSION - Dark-mode GUI for PosterMaker with all critical bugs addressed:
# - Fixed progress bar jumping backwards with smooth animation
# - Added image thumbnail preview
# - Fixed checkbox visibility and styling
# - Proper QThread worker to prevent UI freezing
# - Better exception handling with modal popups
# - Auto-open output folder on success
# - Fixed ChatGPT-inspired dark theme
# - Disabled Process button during processing

from __future__ import annotations

import json
import logging
import os
import sys
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QTextCursor, QPixmap, QFont
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
    QScrollArea,
    QSizePolicy,
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


# --------------------------- Worker Thread (FIXED) ---------------------------

class ProcessWorker(QThread):
    """FIXED: Properly isolated worker thread that never accesses GUI directly"""
    finished = Signal(bool, str, str)  # success, output_path, error_message
    progress = Signal(int)
    preview = Signal(str)  # preview path emitted from pipeline
    status = Signal(str)   # status messages for UI

    def __init__(self, args: dict, parent=None):
        super().__init__(parent)
        self.args = args
        self._should_stop = False

    def stop(self):
        """Request worker to stop (graceful shutdown)"""
        self._should_stop = True

    def run(self) -> None:
        """FIXED: Complete error isolation - never throws exceptions to main thread"""
        try:
            self.status.emit("Initializing AI upscaling...")
            
            # CRITICAL: Wrap progress callback to check for stop requests
            def progress_wrapper(value):
                if self._should_stop:
                    raise RuntimeError("Processing cancelled by user")
                self.progress.emit(value)
            
            def preview_wrapper(path):
                if self._should_stop:
                    return
                self.preview.emit(path)
            
            self.status.emit("Starting Real-ESRGAN processing...")
            
            # Call pipeline with isolated callbacks
            out_path = process_exact(
                **self.args,
                progress_cb=progress_wrapper,
                preview_cb=preview_wrapper,
            )
            
            if self._should_stop:
                self.finished.emit(False, "", "Processing was cancelled")
                return
                
            self.status.emit("Processing completed successfully")
            self.finished.emit(True, str(out_path), "")
            
        except Exception as e:
            error_msg = f"Processing failed: {str(e)}"
            self.status.emit(f"Error: {error_msg}")
            self.finished.emit(False, "", error_msg)


# --------------------------- Smooth Progress Bar ---------------------------

class SmoothProgressBar(QProgressBar):
    """FIXED: Progress bar that never jumps backwards and animates smoothly"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._target_value = 0
        self._current_value = 0
        
        # Animation for smooth progress
        self._animation = QPropertyAnimation(self, b"value")
        self._animation.setDuration(200)  # 200ms animation
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        
    def setValueSmooth(self, value: int):
        """CRITICAL: Set value with smooth animation, never going backwards"""
        # Clamp to valid range
        value = max(0, min(100, value))
        
        # CRITICAL: Never allow progress to go backwards
        if value <= self._target_value:
            return
            
        self._target_value = value
        
        # Animate from current displayed value to target
        self._animation.stop()
        self._animation.setStartValue(self.value())
        self._animation.setEndValue(value)
        self._animation.start()


# --------------------------- Image Preview Widget ---------------------------

class ImagePreviewWidget(QLabel):
    """FIXED: Shows thumbnail preview of input image"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 150)
        self.setMaximumSize(300, 225)
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #555;
                border-radius: 8px;
                background-color: #1a1a1a;
                color: #888;
            }
        """)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText("No image selected\\nPreviews will appear here")
        self.setScaledContents(False)
        
    def setImagePath(self, path: str):
        """Load and display thumbnail of image"""
        try:
            if not path or not Path(path).exists():
                self.clear()
                return
                
            pixmap = QPixmap(path)
            if pixmap.isNull():
                self.setText("Could not load image")
                return
                
            # Scale to fit widget while maintaining aspect ratio
            scaled = pixmap.scaled(
                self.size(), 
                Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            )
            self.setPixmap(scaled)
            
        except Exception as e:
            self.setText(f"Preview error:\\n{str(e)}")
            
    def clear(self):
        """Clear preview and show placeholder"""
        super().clear()
        self.setText("No image selected\\nPreviews will appear here")


# --------------------------- Main Window (COMPLETELY FIXED) ---------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} – AI Poster Upscaler")
        self.resize(1400, 850)  # Larger for preview
        
        # Worker thread tracking
        self.worker = None
        self.processing = False

        self._build_ui()
        self._install_logging_bridge()
        self._load_config_into_ui()

    # ---------------------- UI construction (COMPLETELY FIXED) ----------------------

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)

        # Overall layout: left controls, right logs
        main_layout = QHBoxLayout(root)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(20)

        # LEFT column (controls) - fixed width
        left_widget = QWidget()
        left_widget.setMinimumWidth(400)
        left_widget.setMaximumWidth(450)
        left = QVBoxLayout(left_widget)
        left.setSpacing(15)
        main_layout.addWidget(left_widget, 0)

        # RIGHT column (logs + preview)
        right = QVBoxLayout()
        main_layout.addLayout(right, 1)

        # ----- Files group (FIXED) -----
        files_group = QGroupBox("📁 Input & Output")
        files_layout = QFormLayout()
        files_group.setLayout(files_layout)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Choose a source image...")
        self.input_edit.textChanged.connect(self._on_input_changed)  # FIXED: Auto-preview
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

        # ----- Image Preview (NEW) -----
        preview_group = QGroupBox("🖼️ Preview")
        preview_layout = QVBoxLayout()
        preview_group.setLayout(preview_layout)
        
        self.preview_widget = ImagePreviewWidget()
        preview_layout.addWidget(self.preview_widget)
        
        left.addWidget(preview_group)

        # ----- Engine group (FIXED) -----
        engine_group = QGroupBox("⚡ Upscaler Engine (Real-ESRGAN NCNN)")
        engine_layout = QFormLayout()
        engine_group.setLayout(engine_layout)

        self.realesrgan_edit = QLineEdit()
        self.realesrgan_edit.setPlaceholderText(r"C:\\tools\\realesrgan-ncnn-vulkan.exe")
        btn_rex = QPushButton("Browse…")
        btn_rex.clicked.connect(self._browse_realesrgan)
        rex_row = self._hrow(self.realesrgan_edit, btn_rex)
        engine_layout.addRow("Executable:", rex_row)

        self.model_edit = QLineEdit("realesrgan-x4plus")
        engine_layout.addRow("Model:", self.model_edit)

        # Advanced engine options (FIXED)
        adv_row = QHBoxLayout()
        adv_row.setSpacing(12)

        self.tilesize_spin = QSpinBox()
        self.tilesize_spin.setRange(64, 512)  # FIXED: Capped at 512 to prevent VRAM issues
        self.tilesize_spin.setSingleStep(64)
        self.tilesize_spin.setValue(512)
        self.tilesize_spin.setToolTip("Tile size is automatically capped at 512 to prevent VRAM crashes")
        adv_row.addWidget(QLabel("Tile size:"))
        adv_row.addWidget(self.tilesize_spin)

        # FIXED: Properly styled checkbox
        self.fp16_check = QCheckBox("Use FP16")
        self.fp16_check.setChecked(True)
        self.fp16_check.setToolTip("FP16 provides faster processing but may cause issues on some GPUs")
        adv_row.addWidget(self.fp16_check)

        adv_wrap = QWidget()
        adv_wrap.setLayout(adv_row)
        engine_layout.addRow("Advanced:", adv_wrap)

        left.addWidget(engine_group)

        # ----- Print settings group (FIXED) -----
        print_group = QGroupBox("🖨️ Print Settings")
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
        # Default to 300 DPI
        idx_300 = next(
            (i for i in range(self.dpi_combo.count()) if self.dpi_combo.itemData(i) == 300),
            0,
        )
        self.dpi_combo.setCurrentIndex(idx_300)
        print_layout.addRow("DPI:", self.dpi_combo)

        # FIXED: Properly styled checkbox
        self.landscape_check = QCheckBox("Landscape orientation")
        print_layout.addRow("Orientation:", self.landscape_check)

        # FIXED: Properly styled checkbox  
        self.force600_check = QCheckBox("Force 600 DPI (expert mode)")
        self.force600_check.setToolTip("600 DPI creates very large files and may cause memory issues")
        print_layout.addRow("High DPI:", self.force600_check)

        left.addWidget(print_group)

        # ----- Controls row (FIXED) -----
        controls_row = QHBoxLayout()
        
        self.run_btn = QPushButton("🚀 Process Image")
        self.run_btn.setMinimumHeight(40)
        self.run_btn.clicked.connect(self._run)
        
        self.savecfg_btn = QPushButton("💾 Save Settings")
        self.savecfg_btn.clicked.connect(self._save_config)
        
        self.cancel_btn = QPushButton("❌ Cancel")
        self.cancel_btn.setVisible(False)  # Hidden until processing starts
        self.cancel_btn.clicked.connect(self._cancel_processing)
        
        controls_row.addWidget(self.run_btn)
        controls_row.addWidget(self.savecfg_btn)
        controls_row.addWidget(self.cancel_btn)
        left.addLayout(controls_row)

        # ----- Status and Progress (FIXED) -----
        self.status_label = QLabel("Ready to process images")
        self.status_label.setStyleSheet("color: #888; font-style: italic;")
        left.addWidget(self.status_label)
        
        # FIXED: Smooth progress bar
        self.progress = SmoothProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        left.addWidget(self.progress)

        # ----- RIGHT: Logs -----
        log_group = QGroupBox("📋 Processing Logs")
        log_layout = QVBoxLayout()
        log_group.setLayout(log_layout)
        
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.log_edit.setPlaceholderText("Processing logs will appear here...")
        self.log_edit.setMinimumHeight(400)
        log_layout.addWidget(self.log_edit)
        
        right.addWidget(log_group)

        # Tooltips for clarity
        files_group.setToolTip("Choose the input image and where to save the output file.")
        engine_group.setToolTip("Configure the Real-ESRGAN NCNN executable and model.")
        print_group.setToolTip("A1/A2/A3 paper and DPI for the final poster.")

        # FIXED: Apply beautiful dark theme
        self._apply_beautiful_dark_theme()

    def _apply_beautiful_dark_theme(self) -> None:
        """FIXED: ChatGPT-inspired dark theme with proper checkbox styling"""
        self.setStyleSheet("""
            /* Main window and base widgets */
            QMainWindow {
                background-color: #0d1117;
                color: #e6edf3;
            }
            
            QWidget {
                background-color: #0d1117;
                color: #e6edf3;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
                font-size: 13px;
            }
            
            /* Group boxes */
            QGroupBox {
                border: 1px solid #30363d;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 16px;
                font-weight: 600;
                color: #f0f6fc;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px;
                background-color: #0d1117;
                color: #58a6ff;
            }
            
            /* Input fields */
            QLineEdit, QComboBox, QSpinBox {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 8px 12px;
                color: #e6edf3;
                selection-background-color: #1f6feb;
                min-height: 16px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border-color: #1f6feb;
                outline: none;
            }
            QLineEdit:hover, QComboBox:hover, QSpinBox:hover {
                border-color: #484f58;
            }
            
            /* Dropdown arrows */
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border: 4px solid transparent;
                border-top-color: #7d8590;
                width: 0;
                height: 0;
            }
            
            /* Buttons */
            QPushButton {
                background-color: #238636;
                color: white;
                border: 1px solid #2ea043;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 500;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #2ea043;
                border-color: #46954a;
            }
            QPushButton:pressed {
                background-color: #1a7f37;
            }
            QPushButton:disabled {
                background-color: #21262d;
                color: #484f58;
                border-color: #30363d;
            }
            
            /* Special button styling */
            QPushButton[text="🚀 Process Image"] {
                background-color: #1f6feb;
                border-color: #1f6feb;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton[text="🚀 Process Image"]:hover {
                background-color: #4184e4;
            }
            QPushButton[text="❌ Cancel"] {
                background-color: #da3633;
                border-color: #da3633;
            }
            QPushButton[text="❌ Cancel"]:hover {
                background-color: #f85149;
            }
            
            /* Progress bar */
            QProgressBar {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
                text-align: center;
                color: #e6edf3;
                font-weight: 500;
                min-height: 20px;
            }
            QProgressBar::chunk {
                background-color: #238636;
                border-radius: 5px;
            }
            
            /* CRITICAL FIX: Proper checkbox styling */
            QCheckBox {
                color: #e6edf3;
                spacing: 8px;
                font-size: 13px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #484f58;
                border-radius: 3px;
                background-color: #21262d;
            }
            QCheckBox::indicator:hover {
                border-color: #58a6ff;
                background-color: #30363d;
            }
            QCheckBox::indicator:checked {
                background-color: #1f6feb;
                border-color: #1f6feb;
                image: url(data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16' fill='white'%3E%3Cpath d='M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 011.06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z'/%3E%3C/svg%3E);
            }
            QCheckBox::indicator:checked:hover {
                background-color: #4184e4;
            }
            
            /* Text areas */
            QTextEdit {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
                color: #e6edf3;
                selection-background-color: #1f6feb;
                padding: 12px;
                font-family: ui-monospace, SFMono-Regular, 'SF Mono', Monaco, Inconsolata, 'Roboto Mono', monospace;
                font-size: 12px;
                line-height: 1.4;
            }
            
            /* Spin boxes */
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #30363d;
                border: none;
                width: 16px;
                height: 12px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #484f58;
            }
            QSpinBox::up-arrow {
                image: none;
                border: 3px solid transparent;
                border-bottom-color: #7d8590;
                width: 0;
                height: 0;
            }
            QSpinBox::down-arrow {
                image: none;
                border: 3px solid transparent;
                border-top-color: #7d8590;
                width: 0;
                height: 0;
            }
            
            /* Labels */
            QLabel {
                color: #e6edf3;
            }
            
            /* Image preview specific styling */
            ImagePreviewWidget {
                border: 2px dashed #30363d;
                border-radius: 8px;
                background-color: #161b22;
                color: #7d8590;
            }
        """)

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
        """FIXED: Better log formatting and auto-scroll"""
        timestamp = QTimer()
        self.log_edit.append(f"[{timestamp.remainingTime()}] {text}")
        self.log_edit.moveCursor(QTextCursor.MoveOperation.End)
        self.log_edit.ensureCursorVisible()

    def _on_input_changed(self, path: str) -> None:
        """FIXED: Auto-update preview when input changes"""
        self.preview_widget.setImagePath(path)

    # ---------------------- Logging bridge ----------------------

    def _install_logging_bridge(self) -> None:
        self.qt_log_emitter = QtLogEmitter()
        self.qt_log_emitter.message.connect(self._append_log)

        self.qt_handler = QtLogHandler(self.qt_log_emitter)
        fmt = logging.Formatter("%(levelname)s | %(message)s")
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
            data.get("realesrgan_exe", r"C:\\tools\\realesrgan-ncnn-vulkan.exe")
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
            QMessageBox.information(self, "✅ Saved", f"Settings saved to {CONFIG_PATH}")
        except Exception as e:
            QMessageBox.critical(self, "❌ Save Failed", f"Could not save settings:\\n{e}")

    # ---------------------- Browsers ----------------------

    def _browse_input(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Input Image",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.tif *.tiff *.webp *.bmp);;All Files (*)",
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
            r"C:\\tools",
            "Executable (*.exe);;All Files (*)",
        )
        if path:
            self.realesrgan_edit.setText(path)

    # ---------------------- Validation & Run (COMPLETELY FIXED) ----------------------

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
                "600 DPI requires 'Force 600 DPI (expert mode)'. "
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
        """FIXED: Proper thread management with UI state control"""
        if self.processing:
            return  # Prevent double-click
            
        try:
            args = self._validate_inputs()
        except Exception as e:
            QMessageBox.warning(self, "⚠️ Fix Settings", str(e))
            return

        # Save settings before processing
        self._save_config()

        # FIXED: Set busy UI state
        self._set_processing_state(True)

        self._append_log("\\n" + "="*50)
        self._append_log("🚀 Starting AI upscaling process...")
        self._append_log(f"📊 Settings: {args['paper'].upper()} paper, {args['dpi']} DPI")
        self._append_log(f"🔧 Model: {args['model']}, Tile: {args['tilesize']}, FP16: {args['fp16']}")
        self._append_log("="*50)

        # FIXED: Create and start worker thread
        self.worker = ProcessWorker(args)
        self.worker.progress.connect(self.progress.setValueSmooth)  # FIXED: Smooth progress
        self.worker.preview.connect(self._on_preview)
        self.worker.status.connect(self._on_status)  # FIXED: Status updates
        self.worker.finished.connect(self._on_finished)
        self.worker.start()

    def _cancel_processing(self) -> None:
        """FIXED: Graceful cancellation"""
        if self.worker and self.worker.isRunning():
            self.status_label.setText("Cancelling processing...")
            self.worker.stop()
            self.worker.wait(5000)  # Wait up to 5 seconds
            if self.worker.isRunning():
                self.worker.terminate()
                self.worker.wait()
                
        self._set_processing_state(False)
        self.progress.setValue(0)
        self.status_label.setText("Processing cancelled")
        self._append_log("❌ Processing cancelled by user")

    def _set_processing_state(self, processing: bool) -> None:
        """FIXED: Centralized UI state management"""
        self.processing = processing
        
        # Toggle button states
        self.run_btn.setEnabled(not processing)
        self.savecfg_btn.setEnabled(not processing)
        self.cancel_btn.setVisible(processing)
        
        # Disable inputs during processing  
        self.input_edit.setEnabled(not processing)
        self.output_edit.setEnabled(not processing)
        self.realesrgan_edit.setEnabled(not processing)
        
        if processing:
            self.status_label.setText("Processing...")
            self.progress.setValue(0)
        else:
            self.status_label.setText("Ready")

    def _on_status(self, message: str) -> None:
        """FIXED: Handle status updates from worker"""
        self.status_label.setText(message)

    def _on_preview(self, path: str) -> None:
        """FIXED: Handle preview updates from worker thread"""
        try:
            self._append_log(f"🖼️ Preview updated: {Path(path).name}")
            # Could update preview widget here if desired
        except Exception as e:
            self._append_log(f"Preview update failed: {e}")

    def _on_finished(self, success: bool, out_path: str, error: str) -> None:
        """FIXED: Handle completion with proper error handling and folder opening"""
        self._set_processing_state(False)
        
        if success:
            self.progress.setValueSmooth(100)
            self.status_label.setText("✅ Processing completed!")
            self._append_log(f"✅ SUCCESS! Output saved to:")
            self._append_log(f"📁 {out_path}")
            
            # FIXED: Show success dialog with option to open folder
            reply = QMessageBox.question(
                self, 
                "🎉 Processing Complete!", 
                f"Image successfully processed!\\n\\n📁 {out_path}\\n\\nOpen output folder?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self._open_output_folder(out_path)
                
        else:
            self.progress.setValue(0)
            self.status_label.setText("❌ Processing failed")
            self._append_log("❌ FAILED!")
            self._append_log(f"Error: {error}")
            
            # FIXED: Show detailed error in modal dialog
            error_dialog = QMessageBox(self)
            error_dialog.setIcon(QMessageBox.Icon.Critical)
            error_dialog.setWindowTitle("❌ Processing Failed")
            error_dialog.setText("Image processing failed:")
            error_dialog.setDetailedText(error)
            error_dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
            error_dialog.exec()

    def _open_output_folder(self, file_path: str) -> None:
        """FIXED: Reliably open output folder on Windows"""
        try:
            folder_path = Path(file_path).parent
            if sys.platform == "win32":
                # Use Windows explorer with file selection
                subprocess.run(["explorer", "/select,", str(file_path)], check=False)
            elif sys.platform == "darwin":  # macOS
                subprocess.run(["open", "-R", str(file_path)], check=False)
            else:  # Linux
                subprocess.run(["xdg-open", str(folder_path)], check=False)
        except Exception as e:
            QMessageBox.warning(self, "Folder Open Failed", f"Could not open folder:\\n{e}")


# --------------------------- App entry ---------------------------

def main() -> int:
    app = QApplication(sys.argv)
    
    # Set application properties
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion("2.0")
    app.setOrganizationName("PosterMaker")
    
    win = MainWindow()
    win.show()
    
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())