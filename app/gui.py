from __future__ import annotations
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt
from app.ui_main_window import MainWindow
from app.utils.logging_utils import build_logger, QtTailHandler, log_section
from app.controllers.job_controller import JobController

def main():
    app = QApplication(sys.argv)

    logger = build_logger("poster_maker")
    win = MainWindow(logger)
    controller = JobController(win, logger)

    # Stream logs to GUI
    tail = QtTailHandler(win.append_log_signal.emit)
    logger.addHandler(tail)

    # Wire start/cancel actions
    def on_start():
        files = win.gather_files()
        if not files:
            QMessageBox.warning(win, "No files", "Please add at least one JPG/JPEG/PNG.")
            return
        settings = win.gather_settings()
        with log_section("Poster Maker :: Start", logger):
            controller.start(files, settings)

    def on_cancel():
        controller.cancel()

    win.start_btn.clicked.connect(on_start)
    win.cancel_btn.clicked.connect(on_cancel)

    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
