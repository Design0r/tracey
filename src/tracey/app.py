import logging
import sqlite3
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from tracey import APP_NAME, APP_VERSION, img, theme
from tracey.config import default_database_path, load_config, user_database_path
from tracey.store import Store
from tracey.ui import MainWindow

log = logging.getLogger(__name__)


def open_store() -> Store | None:
    database = load_config().database_path()
    try:
        return Store(database)
    except (sqlite3.Error, OSError) as error:
        log.exception("failed to open database %s", database)
        fallback = default_database_path()
        if fallback == database:
            fallback = user_database_path()
        QMessageBox.warning(
            None,
            APP_NAME,
            f"Could not open the database at\n{database}\n\n{error}\n\n"
            f"Using the default database at\n{fallback}\ninstead.",
        )

    try:
        return Store(fallback)
    except (sqlite3.Error, OSError) as error:
        log.exception("failed to open fallback database %s", fallback)
        QMessageBox.critical(
            None,
            APP_NAME,
            f"Could not open the database at\n{fallback}\n\n{error}",
        )
        return None


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
    if store is None:
        return 1
    log.info("starting application")

    window = MainWindow(store)
    window.show()
    exitcode = app.exec()

    log.info("closing application")
    return exitcode
