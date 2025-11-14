# app/gui.py
# PRODUCTION READY - Clean entry point for PosterMaker GUI application
# - Proper error handling with modal dialogs
# - Application metadata setup
# - High DPI support
# - Clean shutdown handling
# - No heavy work in entry point

from __future__ import annotations

import sys
import traceback
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt


def main() -> int:
    """
    Main entry point for PosterMaker application.
    Creates Qt application, shows main window, and handles errors gracefully.
    """
    # Create application instance FIRST
    app = QApplication(sys.argv)
    
    # Set application metadata for OS integration
    app.setApplicationName("PosterMaker")
    app.setApplicationDisplayName("PosterMaker - AI Poster Upscaler")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("PosterMaker")
    app.setOrganizationDomain("postermaker.app")
    
    # Enable high DPI scaling for modern displays
    try:
        app.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
        app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    except AttributeError:
        # These attributes may not exist in all Qt versions
        pass
    
    try:
        # Import main window (deferred to catch import errors)
        from app.ui_main_window import MainWindow
        
        # Create and show main window
        window = MainWindow()
        window.show()
        
        # Run Qt event loop (blocks until app quits)
        return app.exec()
        
    except ImportError as e:
        # Handle missing dependencies gracefully
        error_text = (
            f"Failed to import required modules:\n\n"
            f"{str(e)}\n\n"
            f"Please ensure all dependencies are installed:\n"
            f"  pip install PySide6 Pillow\n\n"
            f"Or if using pipenv:\n"
            f"  pipenv install"
        )
        
        try:
            QMessageBox.critical(
                None,
                "❌ Import Error - PosterMaker",
                error_text
            )
        except Exception:
            # Fallback to console if message box fails
            print(f"FATAL ERROR:\n{error_text}", file=sys.stderr)
        
        return 1
        
    except Exception as e:
        # Handle any other startup errors
        error_text = (
            f"Application startup failed:\n\n"
            f"{str(e)}\n\n"
            f"Traceback:\n"
            f"{traceback.format_exc()}"
        )
        
        try:
            msg_box = QMessageBox()
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setWindowTitle("❌ Startup Error - PosterMaker")
            msg_box.setText("Application failed to start:")
            msg_box.setInformativeText(str(e))
            msg_box.setDetailedText(traceback.format_exc())
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg_box.exec()
        except Exception:
            # Fallback to console if message box fails
            print(f"FATAL ERROR:\n{error_text}", file=sys.stderr)
            
        return 1


if __name__ == "__main__":
    sys.exit(main())
