import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from tracey import APP_NAME, APP_VERSION, img, theme
from tracey.store import Store
from tracey.ui import MainWindow

DATABASE_PATH = Path("tracey.db")
OLD_DATABASE_PATH = Path("clex.db")  # from before the rename to Tracey

log = logging.getLogger(__name__)


def adopt_old_database() -> None:
    """Keeps the saved profiles from when the app was called Clex."""
    if DATABASE_PATH.exists() or not OLD_DATABASE_PATH.exists():
        return
    try:
        OLD_DATABASE_PATH.rename(DATABASE_PATH)
        log.info("renamed %s to %s", OLD_DATABASE_PATH, DATABASE_PATH)
    except OSError:
        log.exception("failed to rename %s", OLD_DATABASE_PATH)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s][%(name)s][%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M",
    )
    img.init()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    theme.setup(app)

    adopt_old_database()
    store = Store(DATABASE_PATH)
    log.info("starting application")

    window = MainWindow(store)
    window.show()
    exitcode = app.exec()

    log.info("closing application")
    return exitcode
