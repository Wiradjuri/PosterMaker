# # app/gui.py
from __future__ import annotations

import sys
from PySide6.QtWidgets import QApplication
from app.ui_main_window import MainWindow

def main():
    app = QApplication(sys.argv)

    win = MainWindow()
    win.show()

    return app.exec()

if __name__ == "__main__":
    sys.exit(main())
# app/gui.py
# Thin wrapper so you can still do: python -m app.gui


import sys
from PySide6.QtWidgets import QApplication
from app.ui_main_window import MainWindow

def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())
