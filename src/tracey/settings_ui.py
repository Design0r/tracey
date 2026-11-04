import logging
import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from tracey.config import Config, config_path, default_database_path, save_config
from tracey.store import Store
from tracey.widgets import button, card, label, separator

DATABASE_FILTER = "SQLite database (*.db *.sqlite *.sqlite3);;All files (*)"

log = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    def __init__(self, database: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.store: Store | None = None
        self.setWindowTitle("Settings")
        self.setMinimumWidth(560)

        self.database_edit = QLineEdit(str(database))
        self.database_edit.setPlaceholderText(str(default_database_path()))
        self.database_edit.textEdited.connect(lambda _: self.error.hide())

        browse = button("…", "square")
        browse.setFixedWidth(34)
        browse.setToolTip("Choose an existing database or a new file")
        browse.clicked.connect(self.browse)

        reset = button("Default", "ghost")
        reset.setToolTip(f"Use {default_database_path()}")
        reset.clicked.connect(self.reset)

        database_field = QWidget()
        database_row = QHBoxLayout(database_field)
        database_row.setContentsMargins(0, 0, 0, 0)
        database_row.addWidget(self.database_edit, 1)
        database_row.addWidget(browse)
        database_row.addWidget(reset)

        hint = label(
            "Profiles are stored in this SQLite file. A missing file is created,"
            " an existing one is used as it is.",
            "muted",
        )
        hint.setWordWrap(True)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        form.addRow("Location", database_field)
        form.addRow("", hint)

        location = label(f"Settings are saved to {config_path()}", "muted")
        location.setWordWrap(True)
        location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        panel, panel_layout = card()
        panel_layout.addWidget(label("Database", "section"))
        panel_layout.addLayout(form)
        panel_layout.addWidget(separator())
        panel_layout.addWidget(location)

        self.error = label("", "error")
        self.error.setWordWrap(True)
        self.error.hide()

        cancel = button("Cancel")
        cancel.clicked.connect(self.reject)
        save = button("Save", "accent")
        save.setDefault(True)
        save.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(panel)
        layout.addWidget(self.error)
        layout.addLayout(buttons)

    def database(self) -> Path:
        text = self.database_edit.text().strip()
        return Path(text).expanduser() if text else default_database_path()

    def browse(self) -> None:
        current = self.database()
        name, _ = QFileDialog.getSaveFileName(
            self,
            "Choose database",
            str(current),
            DATABASE_FILTER,
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if name:
            self.database_edit.setText(str(Path(name)))
            self.error.hide()

    def reset(self) -> None:
        self.database_edit.setText(str(default_database_path()))
        self.error.hide()

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    def accept(self) -> None:
        database = self.database()
        if database.is_dir():
            self.show_error(f"{database} is a folder, choose a file")
            return

        try:
            store = Store(database)
        except (sqlite3.Error, OSError) as error:
            log.exception("failed to open database %s", database)
            self.show_error(f"Could not open the database: {error}")
            return

        try:
            custom = database if database != default_database_path() else None
            save_config(Config(database=custom))
        except OSError as error:
            log.exception("failed to save config")
            self.show_error(f"Could not save the settings: {error}")
            return

        self.store = store
        super().accept()
