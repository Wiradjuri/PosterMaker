# app/ui_main_window.py
# FULLY REWRITTEN - Modern dark-themed GUI for PosterMaker
# CRITICAL FIXES IMPLEMENTED:
# - QThread worker prevents UI freezing
# - Monotonic smooth progress bar (never goes backwards)
# - Image thumbnail preview
# - Proper button lockout during processing
# - Modal error dialogs with traceback
# - Auto-open output folder
# - Fixed checkbox visibility
# - Valid QSS only (no invalid CSS)
# - MAIN CONTENT WRAPPED IN QScrollArea (scrolls when window is small)

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject, QTimer
from PySide6.QtGui import QTextCursor, QPixmap
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
    QScrollArea,  # <-- added
)
from tomlkit import key

from app.imaging.pipeline import process_exact, A_SIZES_MM

APP_NAME = "PosterMaker"
CONFIG_PATH = Path.home() / ".poster_maker_config.json"


# --------------------------- Logging Bridge ---------------------------
class QtLogEmitter(QObject):
    """Signal emitter for logging to Qt UI"""

    message = Signal(str)


class QtLogHandler(logging.Handler):
    """Routes Python logging to Qt signal for UI display"""

    def __init__(self, emitter: QtLogEmitter):
        super().__init__()
        self.emitter = emitter

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = str(record.getMessage())
        self.emitter.message.emit(msg)


# --------------------------- Worker Thread ---------------------------
class ProcessWorker(QThread):
    """
    Background worker for AI upscaling.
    Never accesses GUI directly - all communication via signals.
    """

    finished = Signal(bool, str, str)  # success, output_path, error_message
    progress = Signal(int)  # progress percentage (0-100)
    preview = Signal(str)  # preview image path
    status = Signal(str)  # status messages

    def __init__(self, args: dict, parent=None):
        super().__init__(parent)
        self.args = args
        self._should_stop = False
        self._last_progress = 0  # Track to ensure monotonic

    def stop(self):
        """Request graceful shutdown"""
        self._should_stop = True

    def run(self) -> None:
        """
        Completely isolated from GUI.
        All communication via signals only.
        """
        try:
            self.status.emit("Starting AI upscaling...")
            self._emit_progress(0)

            # Define callbacks for pipeline
            def on_progress(pct: int):
                if self._should_stop:
                    raise RuntimeError("Processing cancelled by user")
                self._emit_progress(pct)

            def on_preview(path: str):
                if self._should_stop:
                    raise RuntimeError("Processing cancelled by user")
                self.preview.emit(path)

            # Execute pipeline
            output_path = process_exact(
                input_path=self.args["input_path"],
                output_dir=self.args["output_dir"],
                paper=self.args["paper"],
                dpi=self.args["dpi"],
                portrait=self.args["portrait"],
                exe_path=self.args["exe_path"],
                model=self.args["model"],
                tilesize=self.args["tilesize"],
                fp16=self.args["fp16"],
                force_600dpi=self.args["force_600dpi"],
                keep_native_if_larger=False,
                progress_cb=on_progress,
                preview_cb=on_preview,
            )

            # Ensure 100% progress on success
            self._emit_progress(100)
            self.status.emit("Processing complete!")

            # Emit success
            self.finished.emit(True, str(output_path), "")

        except Exception as e:
            # Capture full traceback
            error_msg = f"{str(e)}\n\n{traceback.format_exc()}"
            self.status.emit(f"Error: {str(e)}")
            self.finished.emit(False, "", error_msg)

    def _emit_progress(self, pct: int):
        """Ensure progress is monotonic (never decreasing)"""
        pct = max(self._last_progress, pct)
        self._last_progress = pct
        self.progress.emit(pct)


# --------------------------- Smooth Progress Bar ---------------------------
class SmoothProgressBar(QProgressBar):
    """
    Progress bar that smoothly animates and never goes backwards.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._target_value = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate_step)
        self._timer.setInterval(20)  # ~50 FPS

    def setValueSmooth(self, value: int):
        """
        Set value with smooth animation, never allowing backwards movement.
        """
        value = max(0, min(100, value))

        # Never go backwards
        if value <= self._target_value:
            return

        self._target_value = value

        if not self._timer.isActive():
            self._timer.start()

    def _animate_step(self):
        """Animate one step towards target"""
        current = self.value()
        target = self._target_value

        if current >= target:
            self._timer.stop()
            return

        diff = target - current
        step = max(1, diff // 10)
        new_val = min(current + step, target)

        self.setValue(new_val)


# --------------------------- Image Preview Widget ---------------------------
class ImagePreviewWidget(QLabel):
    """Thumbnail preview of input image"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(220, 160)
        self.setMaximumSize(380, 260)
        self.setStyleSheet(
            """
            QLabel {
                border: 2px dashed #555;
                border-radius: 8px;
                background-color: #1a1a1a;
                color: #888;
                padding: 10px;
            }
        """
        )
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText("No image selected\n\nPreview will appear here")
        self.setScaledContents(False)

    def setImagePath(self, path: str):
        """Load and display thumbnail"""
        try:
            if not path or not Path(path).exists():
                self.clear()
                return

            pixmap = QPixmap(path)
            if pixmap.isNull():
                self.setText("Failed to load image")
                return

            # Scale to fit while maintaining aspect ratio
            scaled = pixmap.scaled(
                self.maximumWidth() - 20,
                self.maximumHeight() - 20,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

            self.setPixmap(scaled)

        except Exception as e:
            self.setText(f"Preview error:\n{str(e)}")

    def clear(self):
        """Clear preview"""
        super().clear()
        self.setText("No image selected\n\nPreview will appear here")


# --------------------------- Main Window ---------------------------
class MainWindow(QMainWindow):
    """Main application window with all critical bugs fixed"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} – AI Poster Upscaler")
        self.resize(1400, 900)

        # Worker thread tracking
        self.worker = None
        self.processing = False

        self._build_ui()
        self._apply_dark_theme()
        self._install_logging_bridge()
        self._load_config()

    # ---------------------- UI Construction ----------------------
    def _build_ui(self) -> None:
        """Build the complete UI with scrollable content"""

        # Central widget that holds a scroll area
        central = QWidget()
        self.setCentralWidget(central)
        outer_layout = QVBoxLayout(central)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer_layout.addWidget(scroll)

        # Root widget inside the scroll area
        root = QWidget()
        scroll.setWidget(root)

        main_layout = QHBoxLayout(root)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(20)

        # LEFT: Controls (fixed-ish width)
        left_widget = QWidget()
        left_widget.setMinimumWidth(430)
        left_widget.setMaximumWidth(520)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(15)
        main_layout.addWidget(left_widget, 0)

        # RIGHT: Logs (expandable)
        right_layout = QVBoxLayout()
        main_layout.addLayout(right_layout, 1)

        # --- Files Group ---
        files_group = QGroupBox("📁 Input  Output")
        files_layout = QFormLayout()
        files_group.setLayout(files_layout)

        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Select source image...")
        self.input_edit.textChanged.connect(self._on_input_changed)
        btn_in = QPushButton("Browse...")
        btn_in.clicked.connect(self._browse_input)
        files_layout.addRow("Input image:", self._hbox(self.input_edit, btn_in))

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Select output folder...")
        btn_out = QPushButton("Browse...")
        btn_out.clicked.connect(self._browse_output)
        files_layout.addRow("Output folder:", self._hbox(self.output_edit, btn_out))

        left_layout.addWidget(files_group)

        # --- Preview Group ---
        preview_group = QGroupBox("🖼️ Preview")
        preview_layout = QVBoxLayout()
        preview_group.setLayout(preview_layout)

        self.preview_widget = ImagePreviewWidget()
        preview_layout.addWidget(self.preview_widget)

        left_layout.addWidget(preview_group)

        # --- Engine Group ---
        engine_group = QGroupBox("⚡ Upscaler Engine (Real-ESRGAN NCNN)")
        engine_layout = QFormLayout()
        engine_group.setLayout(engine_layout)

        self.realesrgan_edit = QLineEdit()
        self.realesrgan_edit.setPlaceholderText(r"C:\tools\realesrgan-ncnn-vulkan.exe")
        btn_rex = QPushButton("Browse...")
        btn_rex.clicked.connect(self._browse_realesrgan)
        engine_layout.addRow("Executable:", self._hbox(self.realesrgan_edit, btn_rex))

        self.model_edit = QLineEdit("realesrgan-x4plus")
        engine_layout.addRow("Model:", self.model_edit)

        # Advanced options
        adv_layout = QHBoxLayout()
        adv_layout.setSpacing(12)

        self.tilesize_spin = QSpinBox()
        self.tilesize_spin.setRange(64, 512)
        self.tilesize_spin.setSingleStep(64)
        self.tilesize_spin.setValue(512)
        self.tilesize_spin.setToolTip("Tile size (capped at 512 to prevent VRAM crashes)")
        adv_layout.addWidget(QLabel("Tile:"))
        adv_layout.addWidget(self.tilesize_spin)

        self.fp16_check = QCheckBox("FP16")
        self.fp16_check.setChecked(True)
        self.fp16_check.setToolTip("Use FP16 precision (faster, may fail on some GPUs)")
        adv_layout.addWidget(self.fp16_check)
        adv_layout.addStretch()

        engine_layout.addRow("Advanced:", self._widget_from_layout(adv_layout))

        left_layout.addWidget(engine_group)

        # --- Print Settings Group ---
        print_group = QGroupBox("🖨️ Print Settings")
        print_layout = QFormLayout()
        print_group.setLayout(print_layout)
        
        self.paper_combo = QComboBox()
        for key in ("a0", "a1", "a2", "a3", "a4"):
            w, h = A_SIZES_MM[key]
            self.paper_combo.addItem(f"{key.upper()} ({w}×{h} mm)", key)
        self.paper_combo.setCurrentIndex(0)
        print_layout.addRow("Paper:", self.paper_combo)

        self.dpi_combo = QComboBox()
        for val in [150, 200, 240, 300, 450, 600]:
            self.dpi_combo.addItem(f"{val} DPI", val)
        self.dpi_combo.setCurrentIndex(3)  # Default to 300 DPI
        print_layout.addRow("DPI:", self.dpi_combo)

        self.landscape_check = QCheckBox("Landscape orientation")
        print_layout.addRow("Orientation:", self.landscape_check)

        self.force600_check = QCheckBox("Force 600 DPI (expert mode)")
        self.force600_check.setToolTip("600 DPI creates very large files")
        print_layout.addRow("High DPI:", self.force600_check)

        left_layout.addWidget(print_group)

        # --- Control Buttons ---
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(10)

        self.run_btn = QPushButton("🚀 Process Image")
        self.run_btn.setMinimumHeight(40)
        self.run_btn.setObjectName("run_btn")
        self.run_btn.clicked.connect(self._run)
        controls_layout.addWidget(self.run_btn)

        self.save_btn = QPushButton("💾 Save Config")
        self.save_btn.clicked.connect(self._save_config)
        controls_layout.addWidget(self.save_btn)

        self.cancel_btn = QPushButton("❌ Cancel")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel)
        controls_layout.addWidget(self.cancel_btn)

        left_layout.addLayout(controls_layout)

        # --- Status & Progress ---
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #888; font-style: italic;")
        left_layout.addWidget(self.status_label)

        self.progress = SmoothProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        left_layout.addWidget(self.progress)

        left_layout.addStretch()

        # --- RIGHT: Logs ---
        log_group = QGroupBox("📋 Processing Logs")
        log_layout = QVBoxLayout()
        log_group.setLayout(log_layout)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.log_edit.setPlaceholderText("Processing logs will appear here...")
        self.log_edit.setMinimumHeight(500)
        log_layout.addWidget(self.log_edit)

        right_layout.addWidget(log_group)

    def _apply_dark_theme(self) -> None:
        """Apply production-ready dark theme (ChatGPT-inspired)"""
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #0d1117;
            }

            QWidget {
                background-color: #0d1117;
                color: #c9d1d9;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 10pt;
            }

            QGroupBox {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 16px;
                font-weight: 600;
                color: #c9d1d9;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 5px;
            }

            QLineEdit {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 6px 10px;
                color: #c9d1d9;
                selection-background-color: #1f6feb;
            }
            QLineEdit:focus {
                border: 1px solid #388bfd;
            }
            QLineEdit:disabled {
                background-color: #161b22;
                color: #6e7681;
            }

            QComboBox {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 6px 10px;
                color: #c9d1d9;
            }
            QComboBox:hover {
                border: 1px solid #388bfd;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid #c9d1d9;
                margin-right: 8px;
            }
            QComboBox QAbstractItemView {
                background-color: #161b22;
                border: 1px solid #30363d;
                selection-background-color: #1f6feb;
                color: #c9d1d9;
            }

            QSpinBox {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 4px 8px;
                color: #c9d1d9;
            }
            QSpinBox:focus {
                border: 1px solid #388bfd;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #21262d;
                border: none;
                width: 16px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #30363d;
            }

            /* Checkboxes with visible check state */
            QCheckBox {
                spacing: 8px;
                color: #c9d1d9;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #30363d;
                border-radius: 4px;
                background-color: #0d1117;
            }
            QCheckBox::indicator:hover {
                border-color: #388bfd;
            }
            QCheckBox::indicator:checked {
                background-color: #1f6feb;
                border-color: #1f6feb;
            }
            QCheckBox::indicator:disabled {
                background-color: #161b22;
                border-color: #21262d;
            }

            QPushButton {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 6px;
                padding: 6px 16px;
                color: #c9d1d9;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #30363d;
                border-color: #8b949e;
            }
            QPushButton:pressed {
                background-color: #161b22;
            }
            QPushButton:disabled {
                background-color: #161b22;
                color: #484f58;
                border-color: #21262d;
            }

            QPushButton#run_btn {
                background-color: #238636;
                border-color: #2ea043;
                color: white;
            }
            QPushButton#run_btn:hover {
                background-color: #2ea043;
            }
            QPushButton#run_btn:pressed {
                background-color: #1a7f37;
            }
            QPushButton#run_btn:disabled {
                background-color: #161b22;
                color: #484f58;
                border-color: #21262d;
            }

            QProgressBar {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
                text-align: center;
                color: #c9d1d9;
                height: 24px;
            }
            QProgressBar::chunk {
                background-color: #1f6feb;
                border-radius: 5px;
            }

            QTextEdit {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
                color: #c9d1d9;
                padding: 8px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 9pt;
            }

            QLabel {
                color: #c9d1d9;
                background: transparent;
            }

            QScrollBar:vertical {
                background: #0d1117;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #30363d;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background: #484f58;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                background: #0d1117;
                height: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                background: #30363d;
                border-radius: 6px;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #484f58;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """
        )

    # ---------------------- Helpers ----------------------
    def _hbox(self, *widgets: QWidget) -> QWidget:
        """Create horizontal box layout with widgets"""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for w in widgets:
            layout.addWidget(w)
        return container

    def _widget_from_layout(self, layout: QHBoxLayout) -> QWidget:
        """Wrap layout in widget"""
        widget = QWidget()
        widget.setLayout(layout)
        return widget

    def _append_log(self, text: str) -> None:
        """Append text to log widget"""
        self.log_edit.append(text)
        self.log_edit.moveCursor(QTextCursor.MoveOperation.End)

    def _on_input_changed(self, path: str) -> None:
        """Update preview when input changes"""
        self.preview_widget.setImagePath(path)

    # ---------------------- Logging Bridge ----------------------
    def _install_logging_bridge(self) -> None:
        """Connect Python logging to GUI"""
        emitter = QtLogEmitter()
        emitter.message.connect(self._append_log)

        handler = QtLogHandler(emitter)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )

        pipeline_logger = logging.getLogger("poster-pipeline")
        pipeline_logger.addHandler(handler)
        pipeline_logger.setLevel(logging.INFO)

    # ---------------------- Config ----------------------
    def _load_config(self) -> None:
        """Load saved configuration"""
        if not CONFIG_PATH.exists():
            return

        try:
            with open(CONFIG_PATH, "r") as f:
                cfg = json.load(f)

            self.input_edit.setText(cfg.get("input_path", ""))
            self.output_edit.setText(cfg.get("output_dir", ""))
            self.realesrgan_edit.setText(cfg.get("realesrgan_exe", ""))
            self.model_edit.setText(cfg.get("model", "realesrgan-x4plus"))

            paper_idx = self.paper_combo.findData(cfg.get("paper", "a1"))
            if paper_idx >= 0:
                self.paper_combo.setCurrentIndex(paper_idx)

            dpi_idx = self.dpi_combo.findData(cfg.get("dpi", 300))
            if dpi_idx >= 0:
                self.dpi_combo.setCurrentIndex(dpi_idx)

            self.landscape_check.setChecked(cfg.get("landscape", False))
            self.tilesize_spin.setValue(cfg.get("tilesize", 512))
            self.fp16_check.setChecked(cfg.get("fp16", True))
            self.force600_check.setChecked(cfg.get("force_600dpi", False))

            self._append_log("✓ Configuration loaded")

        except Exception as e:
            self._append_log(f"⚠ Could not load config: {e}")

    def _save_config(self) -> None:
        """Save current configuration"""
        try:
            cfg = {
                "input_path": self.input_edit.text(),
                "output_dir": self.output_edit.text(),
                "realesrgan_exe": self.realesrgan_edit.text(),
                "model": self.model_edit.text(),
                "paper": self.paper_combo.currentData(),
                "dpi": self.dpi_combo.currentData(),
                "landscape": self.landscape_check.isChecked(),
                "tilesize": self.tilesize_spin.value(),
                "fp16": self.fp16_check.isChecked(),
                "force_600dpi": self.force600_check.isChecked(),
            }

            with open(CONFIG_PATH, "w") as f:
                json.dump(cfg, f, indent=2)

            QMessageBox.information(
                self,
                "✓ Configuration Saved",
                f"Settings saved to:\n{CONFIG_PATH}",
            )

        except Exception as e:
            QMessageBox.warning(
                self,
                "⚠ Save Failed",
                f"Could not save configuration:\n{e}",
            )

    # ---------------------- Browsers ----------------------
    def _browse_input(self) -> None:
        """Browse for input image"""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Input Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All Files (*.*)",
        )
        if path:
            self.input_edit.setText(path)

    def _browse_output(self) -> None:
        """Browse for output directory"""
        path = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if path:
            self.output_edit.setText(path)

    def _browse_realesrgan(self) -> None:
        """Browse for Real-ESRGAN executable"""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Real-ESRGAN Executable",
            "",
            "Executable (*.exe);;All Files (*.*)",
        )
        if path:
            self.realesrgan_edit.setText(path)

    # ---------------------- Validation & Run ----------------------
    def _validate_inputs(self) -> dict:
        """Validate inputs and return arguments dict"""
        input_path = self.input_edit.text().strip()
        if not input_path:
            raise ValueError("Please select an input image")
        if not Path(input_path).exists():
            raise FileNotFoundError(f"Input file not found:\n{input_path}")

        output_dir = self.output_edit.text().strip()
        if not output_dir:
            raise ValueError("Please select an output folder")

        exe_path = self.realesrgan_edit.text().strip()
        if not exe_path:
            raise ValueError("Please specify the Real-ESRGAN executable path")
        if not Path(exe_path).exists():
            raise FileNotFoundError(f"Executable not found:\n{exe_path}")

        return {
            "input_path": input_path,
            "output_dir": output_dir,
            "paper": self.paper_combo.currentData(),
            "dpi": self.dpi_combo.currentData(),
            "portrait": not self.landscape_check.isChecked(),
            "exe_path": exe_path,
            "model": self.model_edit.text().strip() or "realesrgan-x4plus",
            "tilesize": self.tilesize_spin.value(),
            "fp16": self.fp16_check.isChecked(),
            "force_600dpi": self.force600_check.isChecked(),
        }

    def _run(self) -> None:
        """Start processing"""
        try:
            args = self._validate_inputs()

            self.worker = ProcessWorker(args, self)
            self.worker.progress.connect(self._on_progress)
            self.worker.status.connect(self._on_status)
            self.worker.preview.connect(self._on_preview)
            self.worker.finished.connect(self._on_finished)

            self._set_processing_state(True)

            self.log_edit.clear()
            self._append_log("=" * 70)
            self._append_log("Starting AI upscaling process...")
            self._append_log("=" * 70)

            self.progress.setValue(0)

            self.worker.start()

        except Exception as e:
            QMessageBox.critical(
                self,
                "❌ Validation Error",
                f"Cannot start processing:\n\n{str(e)}",
            )

    def _cancel(self) -> None:
        """Cancel processing"""
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(
                self,
                "Cancel Processing?",
                "Are you sure you want to cancel the current operation?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.worker.stop()
                self._append_log("\n⚠ Cancellation requested...")

    def _set_processing_state(self, processing: bool) -> None:
        """Update UI based on processing state"""
        self.processing = processing

        self.run_btn.setEnabled(not processing)
        self.input_edit.setEnabled(not processing)
        self.output_edit.setEnabled(not processing)
        self.realesrgan_edit.setEnabled(not processing)
        self.model_edit.setEnabled(not processing)
        self.paper_combo.setEnabled(not processing)
        self.dpi_combo.setEnabled(not processing)
        self.landscape_check.setEnabled(not processing)
        self.tilesize_spin.setEnabled(not processing)
        self.fp16_check.setEnabled(not processing)
        self.force600_check.setEnabled(not processing)
        self.save_btn.setEnabled(not processing)

        self.cancel_btn.setVisible(processing)

    def _on_progress(self, pct: int) -> None:
        """Handle progress update"""
        self.progress.setValueSmooth(pct)

    def _on_status(self, message: str) -> None:
        """Handle status update"""
        self.status_label.setText(message)

    def _on_preview(self, path: str) -> None:
        """Handle preview update"""
        self.preview_widget.setImagePath(path)

    def _on_finished(self, success: bool, out_path: str, error: str) -> None:
        """Handle processing completion"""
        self._set_processing_state(False)

        if success:
            self.progress.setValueSmooth(100)
            self.status_label.setText("✅ Processing completed!")
            self._append_log("\n✅ SUCCESS! Output saved to:")
            self._append_log(f"📁 {out_path}")

            reply = QMessageBox.question(
                self,
                "🎉 Processing Complete!",
                f"Image successfully processed!\n\n📁 {out_path}\n\nOpen output folder?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )

            if reply == QMessageBox.StandardButton.Yes:
                self._open_output_folder(out_path)

        else:
            self.progress.setValue(0)
            self.status_label.setText("❌ Processing failed")
            self._append_log("\n❌ FAILED!")

            error_dialog = QMessageBox(self)
            error_dialog.setIcon(QMessageBox.Icon.Critical)
            error_dialog.setWindowTitle("❌ Processing Failed")
            error_dialog.setText("Image processing failed:")
            error_dialog.setDetailedText(error)
            error_dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
            error_dialog.exec()

    def _open_output_folder(self, file_path: str) -> None:
        """Reliably open output folder on all OSes"""
        try:
            folder_path = Path(file_path).parent
            if sys.platform == "win32":
                subprocess.run(["explorer", "/select,", str(file_path)], check=False)
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", str(file_path)], check=False)
            else:
                subprocess.run(["xdg-open", str(folder_path)], check=False)
        except Exception as e:
            QMessageBox.warning(
                self,
                "Folder Open Failed",
                f"Could not open folder:\n{e}",
            )


# --------------------------- App entry ---------------------------


def main() -> int:
    app = QApplication(sys.argv)

    app.setApplicationName(APP_NAME)
    app.setApplicationVersion("2.0")
    app.setOrganizationName("PosterMaker")

    win = MainWindow()
    win.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
