import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from clex import APP_NAME, APP_VERSION, img, theme
from clex.store import Store
from clex.ui import MainWindow

DATABASE_PATH = Path("test.db")

log = logging.getLogger(__name__)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    img.init()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    theme.setup(app)

    store = Store(DATABASE_PATH)
    log.info("starting application")

    window = MainWindow(store)
    window.show()
    code = app.exec()

    store.close()
    log.info("closing application")
    return code
