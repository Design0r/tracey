import logging
import sqlite3
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from tracey import APP_NAME, APP_VERSION, img, theme
from tracey.config import default_database_path, load_config
from tracey.store import Store
from tracey.ui import MainWindow

log = logging.getLogger(__name__)


def open_store() -> Store:
    database = load_config().database_path()
    try:
        return Store(database)
    except (sqlite3.Error, OSError) as error:
        log.exception("failed to open database %s", database)
        fallback = default_database_path()
        QMessageBox.warning(
            None,
            APP_NAME,
            f"Could not open the database at\n{database}\n\n{error}\n\n"
            f"Using the default database at\n{fallback}\ninstead.",
        )
        return Store(fallback)


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

    store = open_store()
    log.info("starting application")

    window = MainWindow(store)
    window.show()
    exitcode = app.exec()

    log.info("closing application")
    return exitcode
