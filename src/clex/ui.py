from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from clex import APP_NAME, APP_VERSION, theme
from clex.export_ui import ExportPage
from clex.store import ExportProfile, Store
from clex.widgets import button, label


class MainWindow(QMainWindow):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.profiles: list[ExportProfile] = []
        self.profile = ExportProfile()
        self.message = ""
        self.loading = False

        self.setWindowTitle(APP_NAME)
        self.resize(1360, 860)
        self.setAcceptDrops(True)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)

        self.page = ExportPage(self.edit, lambda: self.profile)
        self.page.changed.connect(self.refresh)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.addWidget(self.page, 1)

        root = QWidget()
        root.setObjectName("root")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self.build_header())
        root_layout.addWidget(content, 1)
        root_layout.addWidget(self.build_footer())
        self.setCentralWidget(root)

        self.reload_profiles(0)

    def build_header(self) -> QFrame:
        logo = QLabel()
        logo.setPixmap(theme.logo(32, self.devicePixelRatioF()))

        width = self.fontMetrics().height() * 11
        self.profile_combo = QComboBox()
        self.profile_combo.setPlaceholderText("Unsaved profile")
        self.profile_combo.setFixedWidth(width)
        self.profile_combo.setToolTip("Saved profiles")
        self.profile_combo.activated.connect(self.select_profile)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Profile name")
        self.name_edit.setFixedWidth(width)
        self.name_edit.textEdited.connect(lambda text: self.edit("name", text))

        new_button = button("New", "ghost")
        new_button.setToolTip("Start a new profile with the default settings")
        new_button.clicked.connect(self.new_profile)
        save_button = button("Save", "ghost")
        save_button.setToolTip("Save the profile")
        save_button.clicked.connect(self.save_profile)
        delete_button = button("Delete", "ghost")
        delete_button.setToolTip("Delete the profile")
        delete_button.clicked.connect(self.delete_profile)

        divider = QFrame()
        divider.setProperty("role", "separator")
        divider.setFixedSize(1, 24)

        self.cancel_button = button("Cancel", "danger")
        self.cancel_button.clicked.connect(self.page.cancel)
        self.run_button = button("Run Batch", "accent")
        self.run_button.clicked.connect(self.run_batch)

        header = QFrame()
        header.setProperty("role", "topbar")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(10)
        layout.addWidget(logo)
        layout.addWidget(label(f"{APP_NAME} - {APP_VERSION}", "apptitle"))
        layout.addStretch()
        for widget in (
            self.profile_combo,
            self.name_edit,
            new_button,
            save_button,
            delete_button,
            divider,
            self.cancel_button,
            self.run_button,
        ):
            layout.addWidget(widget)
        return header

    def build_footer(self) -> QFrame:
        self.status = label("", "muted")
        self.status.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.overall = QProgressBar()
        self.overall.setRange(0, 100)
        self.overall.setFixedWidth(280)
        self.overall_label = label("", "muted")
        self.overall_label.setFixedWidth(36)
        self.overall_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        footer = QFrame()
        footer.setProperty("role", "footer")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(12)
        layout.addWidget(self.status, 1)
        layout.addWidget(self.overall)
        layout.addWidget(self.overall_label)
        return footer

    # --- batch ---------------------------------------------------------------

    def run_batch(self) -> None:
        self.message = ""
        self.page.start()

    def refresh(self) -> None:
        page = self.page
        running = page.running()
        self.run_button.setEnabled(page.can_run())
        self.run_button.setToolTip(page.run_hint())
        self.cancel_button.setVisible(running)
        self.cancel_button.setEnabled(not page.cancelling)
        self.status.setText(self.message or page.status())
        progress = page.progress()
        self.overall.setValue(progress)
        self.overall_label.setText(f"{progress}%")

    # --- profiles ------------------------------------------------------------

    def edit(self, field: str, value: Any) -> None:
        if not self.loading:
            setattr(self.profile, field, value)

    def load_profile(self, profile: ExportProfile) -> None:
        self.profile = profile.copy()
        p = self.profile

        self.loading = True
        self.name_edit.setText(p.name)
        self.page.load_profile(p)
        self.loading = False

        index = next(
            (i for i, saved in enumerate(self.profiles) if p.id and saved.id == p.id),
            -1,
        )
        self.profile_combo.setCurrentIndex(index)
        self.page.refresh_formats()

    def reload_profiles(self, select_id: int) -> None:
        self.profiles = self.store.get_profiles()

        self.profile_combo.clear()
        for p in self.profiles:
            self.profile_combo.addItem(p.name)

        selected = next((p for p in self.profiles if p.id == select_id), None)
        if selected is None:
            selected = self.profiles[0] if self.profiles else ExportProfile()
        self.load_profile(selected)

    def select_profile(self, index: int) -> None:
        self.message = ""
        self.load_profile(self.profiles[index])

    def new_profile(self) -> None:
        self.message = ""
        self.load_profile(ExportProfile())

    def save_profile(self) -> None:
        p = self.profile
        if not p.name:
            self.show_message("Name the profile before saving")
            return

        if p.id == 0:
            created = self.store.create_profile(p)
            if created == 0:
                self.show_message("Failed to save profile")
                return
            p.id = created
        elif not self.store.update_profile(p):
            self.show_message("Failed to save profile")
            return

        self.message = f'Saved "{p.name}"'
        self.reload_profiles(p.id)

    def delete_profile(self) -> None:
        p = self.profile
        if p.id != 0 and not self.store.delete_profile(p):
            self.show_message("Failed to delete profile")
            return

        self.message = f'Deleted "{p.name}"'
        self.reload_profiles(0)

    def show_message(self, message: str) -> None:
        self.message = message
        self.refresh()

    # --- window --------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        event.acceptProposedAction()
        self.message = ""
        self.page.add_dropped(paths)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.page.stop()
        event.accept()
