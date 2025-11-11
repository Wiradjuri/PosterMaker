from __future__ import annotations
import logging, sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True, parents=True)
LOG_FILE = LOG_DIR / "app.log"

BANNER = "=" * 75

def build_logger(name: str = "poster_maker") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    fh = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.INFO)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO)
    logger.addHandler(sh)
    return logger

class QtTailHandler(logging.Handler):
    def __init__(self, signal_emit):
        super().__init__()
        self.emit_to_gui = signal_emit
        self.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            self.emit_to_gui(line)
        except Exception:
            pass

class log_section:
    def __init__(self, title: str, logger: logging.Logger):
        self.title = title
        self.logger = logger

    def __enter__(self):
        self.logger.info("\n%s\n%s\n%s", BANNER, self.title, BANNER)

    def __exit__(self, exc_type, exc, tb):
        return False
