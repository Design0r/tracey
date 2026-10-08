import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from tracey import APP_NAME, APP_VERSION, img, theme
from tracey.store import Store
from tracey.ui import MainWindow

DATABASE_PATH = Path("tracey.db")

log = logging.getLogger(__name__)


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

    store = Store(DATABASE_PATH)
    log.info("starting application")

    window = MainWindow(store)
    window.show()
    exitcode = app.exec()

    log.info("closing application")
    return exitcode
