from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from luma import APP_NAME, img
from luma.batch import ExportWorker
from luma.store import (
    BitDepth,
    Choice,
    ColorSpace,
    ColorSpaceOp,
    DpiOp,
    ExportProfile,
    ImageFormat,
    Store,
)
from luma.theme import set_role

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
MAX_PIXELS = 1_000_000
MAX_DPI = 100_000
RUN_HINT = "Add source files, an export format and an output folder first"


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def label(text: str, role: str = "") -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    return widget


def separator() -> QFrame:
    line = QFrame()
    line.setProperty("role", "separator")
    line.setFixedHeight(1)
    return line


def spin_box(minimum: int, maximum: int) -> QSpinBox:
    box = QSpinBox()
    box.setRange(minimum, maximum)
    box.setMinimumWidth(140)
    return box


class Section(QWidget):
    def __init__(self, title: str):
        super().__init__()
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setProperty("role", "section")
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.toggle.toggled.connect(self.expand)

        self.body = QWidget()
        self.form = QFormLayout(self.body)
        self.form.setContentsMargins(8, 4, 8, 8)
        self.form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint
        )
        self.body.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.toggle)
        layout.addWidget(self.body)

    def expand(self, expanded: bool) -> None:
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.body.setVisible(expanded)

    def row(self, text: str, field: QWidget) -> None:
        self.form.addRow(text, field)


class ChoiceGroup(QWidget):
    changed = Signal(int)

    def __init__(self, choices: type[Choice]):
        super().__init__()
        self.group = QButtonGroup(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        for choice in choices:
            button = QRadioButton(choice.label)
            self.group.addButton(button, choice.value)
            layout.addWidget(button)
        layout.addStretch()
        self.group.idClicked.connect(self.changed)

    def set_value(self, value: int) -> None:
        self.group.button(int(value)).setChecked(True)


class EntryRow(QWidget):
    def __init__(self, text: str, on_remove: Callable[[], None], tooltip: str = ""):
        super().__init__()
        self.remove_button = QToolButton()
        self.remove_button.setText("×")
        self.remove_button.setProperty("role", "remove")
        self.remove_button.clicked.connect(lambda: on_remove())

        self.name = QLabel(text)
        self.name.setToolTip(tooltip)
        self.status = QLabel()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.remove_button)
        layout.addWidget(self.name, 1)
        layout.addWidget(self.status)

    def set_result(self, result: img.ExportResult | None) -> None:
        if result is None:
            self.status.clear()
            self.status.setToolTip("")
        elif result.error:
            self.status.setText("failed")
            self.status.setToolTip(result.error)
            set_role(self.status, "error")
        else:
            self.status.setText("done")
            self.status.setToolTip("")
            set_role(self.status, "dim")


class EntryList(QWidget):
    def __init__(self, empty_text: str):
        super().__init__()
        self.rows: list[EntryRow] = []
        self.empty = label(empty_text, "dim")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.empty)
        layout.addStretch()

    def set_entries(self, entries: list[tuple[str, Callable[[], None], str]]) -> None:
        layout = self.layout()

        if not layout:
            return

        for row in self.rows:
            layout.removeWidget(row)
            row.deleteLater()

        self.rows = [
            EntryRow(text, on_remove, tooltip) for text, on_remove, tooltip in entries
        ]
        for row in self.rows:
            layout.insertWidget(layout.count() - 1, row)
        self.empty.setVisible(not self.rows)


class MainWindow(QMainWindow):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.profiles: list[ExportProfile] = []
        self.profile = ExportProfile()
        self.sources: list[Path] = []
        self.results: list[img.ExportResult] = []
        self.total = 0
        self.output_dir = ""
        self.message = ""
        self.worker: ExportWorker | None = None
        self.loading = False

        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)
        self.setAcceptDrops(True)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(8)
        content_layout.addLayout(self.build_header())
        content_layout.addWidget(separator())
        content_layout.addWidget(self.build_body(), 1)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(content, 1)
        root_layout.addWidget(self.build_status())
        self.setCentralWidget(root)

        self.reload_profiles(0)

    def build_header(self) -> QHBoxLayout:
        width = self.fontMetrics().height() * 12

        new_button = QPushButton("New Profile")
        new_button.clicked.connect(self.new_profile)
        save_button = QPushButton("Save Profile")
        save_button.clicked.connect(self.save_profile)
        delete_button = QPushButton("Delete Profile")
        delete_button.clicked.connect(self.delete_profile)

        self.profile_combo = QComboBox()
        self.profile_combo.setPlaceholderText("Unsaved profile")
        self.profile_combo.setFixedWidth(width)
        self.profile_combo.activated.connect(self.select_profile)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Profile name")
        self.name_edit.setFixedWidth(width)
        self.name_edit.textEdited.connect(lambda text: self.edit("name", text))

        self.run_button = QPushButton("Run Batch")
        self.run_button.setProperty("role", "accent")
        self.run_button.clicked.connect(self.start_batch)

        header = QHBoxLayout()
        header.setSpacing(8)
        for widget in (
            new_button,
            save_button,
            delete_button,
            self.profile_combo,
            self.name_edit,
            self.run_button,
        ):
            header.addWidget(widget)
        header.addStretch()
        return header

    def build_body(self) -> QSplitter:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.build_sources())
        splitter.addWidget(self.build_pipeline())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([400, 800])
        return splitter

    def build_sources(self) -> QWidget:
        self.clear_button = QPushButton("Clear")
        self.clear_button.setProperty("role", "small")
        self.clear_button.clicked.connect(self.clear_sources)

        top = QHBoxLayout()
        top.addWidget(label("Files", "title"))
        top.addWidget(self.clear_button)
        top.addStretch()

        self.source_list = EntryList("Drop images or folders onto the window.")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.source_list)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 8, 12, 0)
        layout.addLayout(top)
        layout.addWidget(separator())
        layout.addWidget(scroll, 1)
        return panel

    def build_pipeline(self) -> QWidget:
        description = label(
            "Every file in the batch runs through these stages in order. "
            "The line tracks what each stage leaves behind.",
            "dim",
        )
        description.setWordWrap(True)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 8, 12, 0)
        layout.setSpacing(8)
        layout.addWidget(label("Pipeline", "title"))
        layout.addWidget(description)
        layout.addWidget(self.build_color())
        layout.addWidget(self.build_bit_depth())
        layout.addWidget(self.build_resolution())
        layout.addWidget(self.build_dpi())
        layout.addWidget(self.build_write())
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def build_color(self) -> Section:
        self.color_enabled = QCheckBox()
        self.color_enabled.toggled.connect(
            lambda v: self.edit("color_space_enabled", v)
        )

        self.color_space = QComboBox()
        self.color_space.setMinimumWidth(140)
        for space in ColorSpace:
            self.color_space.addItem(space.label)
        self.color_space.currentIndexChanged.connect(
            lambda i: self.edit("color_space", ColorSpace(i))
        )

        self.color_op = ChoiceGroup(ColorSpaceOp)
        self.color_op.changed.connect(
            lambda v: self.edit("color_space_op", ColorSpaceOp(v))
        )

        self.embed = QCheckBox("Embed ICC Profile")
        self.embed.toggled.connect(lambda v: self.edit("embed", v))

        section = Section("Color")
        section.row("Enabled", self.color_enabled)
        section.row("Color Profile", self.color_space)
        section.row("Handling", self.color_op)
        section.row("Embed", self.embed)
        return section

    def build_bit_depth(self) -> Section:
        self.bit_depth_enabled = QCheckBox()
        self.bit_depth_enabled.toggled.connect(
            lambda v: self.edit("bit_depth_enabled", v)
        )

        self.bit_depth = ChoiceGroup(BitDepth)
        self.bit_depth.changed.connect(lambda v: self.edit("bit_depth", BitDepth(v)))

        self.keep_alpha = QCheckBox("Keep Alpha Channel")
        self.keep_alpha.toggled.connect(lambda v: self.edit("keep_alpha", v))

        section = Section("Bit Depth")
        section.row("Enabled", self.bit_depth_enabled)
        section.row("Bit Depth", self.bit_depth)
        section.row("Alpha", self.keep_alpha)
        return section

    def build_resolution(self) -> Section:
        self.resolution_enabled = QCheckBox()
        self.resolution_enabled.toggled.connect(
            lambda v: self.edit("resolution_enabled", v)
        )

        self.width_spin = spin_box(0, MAX_PIXELS)
        self.width_spin.valueChanged.connect(lambda v: self.edit("width", v))
        self.height_spin = spin_box(0, MAX_PIXELS)
        self.height_spin.valueChanged.connect(lambda v: self.edit("height", v))

        hint = label(
            "Fits inside the box, keeping the aspect ratio. 0 leaves a side unconstrained.",
            "dim",
        )
        hint.setWordWrap(True)

        section = Section("Resolution")
        section.row("Enabled", self.resolution_enabled)
        section.row("Width", self.width_spin)
        section.row("Height", self.height_spin)
        section.row("", hint)
        return section

    def build_dpi(self) -> Section:
        self.dpi_enabled = QCheckBox()
        self.dpi_enabled.toggled.connect(lambda v: self.edit("dpi_enabled", v))

        self.dpi_spin = spin_box(1, MAX_DPI)
        self.dpi_spin.valueChanged.connect(lambda v: self.edit("dpi", v))

        self.dpi_op = ChoiceGroup(DpiOp)
        self.dpi_op.changed.connect(lambda v: self.edit("dpi_op", DpiOp(v)))

        section = Section("DPI")
        section.row("Enabled", self.dpi_enabled)
        section.row("DPI", self.dpi_spin)
        section.row("Handling", self.dpi_op)
        return section

    def build_write(self) -> Section:
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Folder for the exported files")
        self.output_edit.setMinimumWidth(360)
        self.output_edit.textEdited.connect(self.set_output_dir)

        self.format_list = EntryList("No export formats")
        formats = QFrame()
        formats.setProperty("role", "panel")
        formats.setMinimumWidth(240)
        formats_layout = QVBoxLayout(formats)
        formats_layout.setContentsMargins(6, 6, 6, 6)
        formats_layout.addWidget(self.format_list)

        self.format_combo = QComboBox()
        self.format_combo.setMinimumWidth(140)
        for fmt in ImageFormat:
            self.format_combo.addItem(fmt.label)
        self.format_combo.currentIndexChanged.connect(self.update_controls)

        self.add_format_button = QPushButton("Add")
        self.add_format_button.clicked.connect(self.add_format)

        add_row = QWidget()
        add_layout = QHBoxLayout(add_row)
        add_layout.setContentsMargins(0, 0, 0, 0)
        add_layout.addWidget(self.format_combo)
        add_layout.addWidget(self.add_format_button)

        section = Section("Write")
        section.row("Output Folder", self.output_edit)
        section.row("Exports", formats)
        section.row("Export Format", add_row)
        return section

    def build_status(self) -> QFrame:
        self.message_label = QLabel()

        self.progress = QProgressBar()
        self.progress.setFixedWidth(self.fontMetrics().height() * 10)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_batch)
        self.summary_label = QLabel()

        bar = QFrame()
        bar.setProperty("role", "status")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.addWidget(self.message_label)
        layout.addStretch()
        layout.addWidget(self.progress)
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.summary_label)
        return bar

    def running(self) -> bool:
        return self.worker is not None

    def edit(self, field: str, value: Any) -> None:
        if not self.loading:
            setattr(self.profile, field, value)

    def load_profile(self, profile: ExportProfile) -> None:
        self.profile = profile.copy()
        p = self.profile

        self.loading = True
        self.name_edit.setText(p.name)
        self.color_enabled.setChecked(p.color_space_enabled)
        self.color_space.setCurrentIndex(p.color_space)
        self.color_op.set_value(p.color_space_op)
        self.embed.setChecked(p.embed)
        self.bit_depth_enabled.setChecked(p.bit_depth_enabled)
        self.bit_depth.set_value(p.bit_depth)
        self.keep_alpha.setChecked(p.keep_alpha)
        self.resolution_enabled.setChecked(p.resolution_enabled)
        self.width_spin.setValue(p.width)
        self.height_spin.setValue(p.height)
        self.dpi_enabled.setChecked(p.dpi_enabled)
        self.dpi_spin.setValue(p.dpi)
        self.dpi_op.set_value(p.dpi_op)
        self.loading = False

        index = next(
            (i for i, saved in enumerate(self.profiles) if p.id and saved.id == p.id),
            -1,
        )
        self.profile_combo.setCurrentIndex(index)
        self.refresh_formats()

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
        self.update_status()

    def refresh_formats(self) -> None:
        self.format_list.set_entries(
            [
                (fmt.label, lambda i=i: self.remove_format(i), "")
                for i, fmt in enumerate(self.profile.formats)
            ]
        )
        self.update_controls()

    def add_format(self) -> None:
        fmt = ImageFormat(self.format_combo.currentIndex())
        if fmt not in self.profile.formats:
            self.profile.formats.append(fmt)
            self.refresh_formats()

    def remove_format(self, index: int) -> None:
        del self.profile.formats[index]
        self.refresh_formats()

    def set_output_dir(self, text: str) -> None:
        self.output_dir = text
        self.update_controls()

    def add_source(self, path: Path) -> None:
        if path in self.sources:
            return

        if not self.output_dir:
            self.output_dir = str(path.parent / "export")
            self.output_edit.setText(self.output_dir)
        self.sources.append(path)

    def add_dropped(self, path: Path) -> None:
        if not path.is_dir():
            self.add_source(path)
            return

        try:
            files = sorted(
                entry for entry in path.iterdir() if entry.is_file() and is_image(entry)
            )
        except OSError:
            return

        for file in files:
            self.add_source(file)

    def refresh_sources(self) -> None:
        self.source_list.set_entries(
            [
                (path.name, lambda i=i: self.remove_source(i), str(path))
                for i, path in enumerate(self.sources)
            ]
        )
        for row, result in zip(self.source_list.rows, self.results):
            row.set_result(result)
        self.update_controls()

    def remove_source(self, index: int) -> None:
        del self.sources[index]
        if index < len(self.results):
            del self.results[index]
        self.refresh_sources()

    def clear_sources(self) -> None:
        self.sources.clear()
        self.results.clear()
        self.refresh_sources()

    def start_batch(self) -> None:
        self.results.clear()
        self.total = len(self.sources)
        self.worker = ExportWorker(
            list(self.sources), self.profile.copy(), Path(self.output_dir), self
        )
        self.worker.exported.connect(self.on_exported)
        self.worker.finished.connect(self.on_batch_finished)
        self.cancel_button.setEnabled(True)

        for row in self.source_list.rows:
            row.set_result(None)
        self.worker.start()
        self.update_controls()

    def cancel_batch(self) -> None:
        if self.worker:
            self.worker.requestInterruption()
            self.cancel_button.setEnabled(False)

    def on_exported(self, result: img.ExportResult) -> None:
        self.results.append(result)
        index = len(self.results) - 1
        if index < len(self.source_list.rows):
            self.source_list.rows[index].set_result(result)
        self.update_status()

    def on_batch_finished(self) -> None:
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
        self.update_controls()

    def update_controls(self) -> None:
        running = self.running()
        can_run = (
            not running
            and bool(self.sources)
            and bool(self.profile.formats)
            and bool(self.output_dir)
        )
        self.run_button.setEnabled(can_run)
        self.run_button.setToolTip("" if can_run or running else RUN_HINT)

        self.clear_button.setEnabled(not running and bool(self.sources))
        for row in self.source_list.rows:
            row.remove_button.setEnabled(not running)

        selected = ImageFormat(max(self.format_combo.currentIndex(), 0))
        self.add_format_button.setEnabled(selected not in self.profile.formats)
        self.update_status()

    def update_status(self) -> None:
        self.message_label.setText(
            self.message or f"{len(self.profile.formats)} export format(s)"
        )

        running = self.running()
        done = len(self.results)
        failed = sum(1 for r in self.results if r.error)

        self.progress.setVisible(running)
        self.cancel_button.setVisible(running)
        self.summary_label.setVisible(not running)

        if running:
            self.progress.setRange(0, max(self.total, 1))
            self.progress.setValue(done)
            self.progress.setFormat(f"Exporting {done}/{self.total}")
            return

        if done == 0:
            text = "Ready"
        elif failed:
            text = f"{done - failed} exported, {failed} failed"
        else:
            text = f"{done} exported"
        self.summary_label.setText(text)
        set_role(self.summary_label, "error" if failed else "")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.add_dropped(Path(url.toLocalFile()))
        event.acceptProposedAction()
        self.refresh_sources()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker:
            self.worker.requestInterruption()
            self.worker.wait()
        event.accept()
