from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QIcon,
    QMouseEvent,
    QPixmap,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from clex import img
from clex.store import Choice
from clex.theme import repolish, set_role

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
IMAGE_FILTER = "Images (*.jpg *.jpeg *.png *.tif *.tiff)"


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def image_files(paths: list[Path]) -> list[Path]:
    """The images among `paths`, with the images directly inside dropped folders."""
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            try:
                files.extend(sorted(p for p in path.iterdir() if p.is_file()))
            except OSError:
                continue
        else:
            files.append(path)
    return [p for p in files if is_image(p)]


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


def button(text: str, role: str = "") -> QPushButton:
    widget = QPushButton(text)
    if role:
        widget.setProperty("role", role)
    return widget


def card() -> tuple[QFrame, QVBoxLayout]:
    """A rounded panel, the main building block of the window."""
    frame = QFrame()
    frame.setProperty("role", "card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 14, 16, 16)
    layout.setSpacing(12)
    return frame, layout


def spin_box(minimum: int, maximum: int) -> QSpinBox:
    box = QSpinBox()
    box.setRange(minimum, maximum)
    box.setMinimumWidth(140)
    return box


def double_spin_box(
    minimum: float, maximum: float, step: float, value: float
) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(minimum, maximum)
    box.setDecimals(2)
    box.setSingleStep(step)
    box.setValue(value)
    box.setMinimumWidth(140)
    return box


class FolderField(QWidget):
    """A folder path with a browse button."""

    edited = Signal(str)

    def __init__(self, placeholder: str):
        super().__init__()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setMinimumWidth(260)
        self.edit.textEdited.connect(self.edited)

        browse = button("…", "square")
        browse.setFixedWidth(34)
        browse.clicked.connect(self.browse)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit, 1)
        layout.addWidget(browse)

    def text(self) -> str:
        return self.edit.text().strip()

    def set_text(self, text: str) -> None:
        self.edit.setText(text)

    def browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Choose output folder", self.text()
        )
        if folder:
            self.edit.setText(folder)
            self.edited.emit(folder)


class DropSlot(QFrame):
    """A slot in a file row that takes one dropped image, or browses on a click."""

    dropped = Signal(Path)
    clicked = Signal()
    cleared = Signal()

    WIDTH = 150

    def __init__(self, kind: str, file: Path | None):
        super().__init__()
        self.setProperty("role", "dropslot")
        self.setProperty("empty", file is None)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(self.WIDTH)
        self.idle_text = file.name if file else f"Drop {kind}"
        self.release_text = f"Release to set {kind}"
        if file:
            self.setToolTip(f"{kind.capitalize()}: {file}\nDrop or click to replace it")
        else:
            self.setToolTip(f"Drop the {kind} image here, or click to choose one")

        # parented right away: shown without a parent, it flashes up as a window
        self.text = QLabel(self)
        clear = QToolButton(self)
        clear.setText("×")
        clear.setProperty("role", "remove")
        clear.setToolTip(f"Remove the {kind}")
        clear.setVisible(file is not None)
        clear.clicked.connect(self.cleared)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 1, 1, 1)
        layout.setSpacing(0)
        layout.addWidget(self.text, 1)
        layout.addWidget(clear)
        self.text_width = self.WIDTH - 12 - (clear.sizeHint().width() if file else 0)
        self.show_text(self.idle_text)

    def show_text(self, text: str) -> None:
        metrics = self.text.fontMetrics()
        elided = metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, self.text_width)
        self.text.setText(elided)

    def set_hover(self, hover: bool) -> None:
        """Highlights the slot while an image is dragged over it."""
        self.setProperty("hover", hover)
        self.show_text(self.release_text if hover else self.idle_text)
        # the label is styled by the slot's state, so it restyles with it
        repolish(self)
        repolish(self.text)

    def image(self, event: QDragEnterEvent | QDropEvent) -> Path | None:
        """The first local image among the dragged files."""
        paths = (
            Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()
        )
        return next((p for p in paths if p.is_file() and is_image(p)), None)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self.isEnabled() and self.image(event):
            event.acceptProposedAction()
            self.set_hover(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self.set_hover(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self.set_hover(False)
        if image := self.image(event):
            event.acceptProposedAction()
            self.dropped.emit(image)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


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
        self.form.setContentsMargins(12, 6, 8, 10)
        self.form.setHorizontalSpacing(16)
        self.form.setVerticalSpacing(10)
        self.form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
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

    def switch(self, enabled: QCheckBox) -> None:
        """Adds the stage's Enabled checkbox and shows its state on the header."""
        self.row("Enabled", enabled)

        self.badge = QLabel()
        self.badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        header = QHBoxLayout(self.toggle)
        header.setContentsMargins(0, 0, 12, 0)
        header.addStretch()
        header.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)

        enabled.toggled.connect(self.set_active)
        self.set_active(enabled.isChecked())

    def set_active(self, active: bool) -> None:
        self.toggle.setProperty("active", active)
        repolish(self.toggle)
        self.badge.setText("On" if active else "Off")
        set_role(self.badge, "badge-on" if active else "badge-off")


class ChoiceGroup(QWidget):
    changed = Signal(int)

    def __init__(self, choices: type[Choice]):
        super().__init__()
        self.group = QButtonGroup(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        for choice in choices:
            radio = QRadioButton(choice.label)
            self.group.addButton(radio, choice.value)
            layout.addWidget(radio)
        layout.addStretch()
        self.group.idClicked.connect(self.changed)

    def value(self) -> int:
        return self.group.checkedId()

    def set_value(self, value: int) -> None:
        self.group.button(int(value)).setChecked(True)


class ColorButton(QPushButton):
    changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(140)
        self.color = QColor("#ffffff")
        self.clicked.connect(self.pick)

    def set_value(self, value: str) -> None:
        color = QColor(value)
        self.color = color if color.isValid() else QColor("#ffffff")
        swatch = QPixmap(14, 14)
        swatch.fill(self.color)
        self.setIcon(QIcon(swatch))
        self.setText(self.color.name())

    def pick(self) -> None:
        color = QColorDialog.getColor(self.color, self, "Background Color")
        if color.isValid():
            self.set_value(color.name())
            self.changed.emit(color.name())


type Entry = (
    tuple[str, Callable[[], None], str] | tuple[str, Callable[[], None], str, QWidget]
)


class EntryRow(QWidget):
    def __init__(
        self,
        text: str,
        on_remove: Callable[[], None],
        tooltip: str = "",
        extra: QWidget | None = None,
    ):
        super().__init__()
        self.remove_button = QToolButton()
        self.remove_button.setText("×")
        self.remove_button.setProperty("role", "remove")
        self.remove_button.clicked.connect(lambda: on_remove())

        self.name = QLabel(text)
        self.name.setToolTip(tooltip)
        self.status = QLabel()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 4, 2)
        layout.addWidget(self.remove_button)
        layout.addWidget(self.name, 1)
        if extra:
            layout.addWidget(extra)
        layout.addWidget(self.status)

    def set_result(self, result: img.ExportResult | None) -> None:
        if result is None:
            self.status.clear()
            self.status.setToolTip("")
        elif result.error:
            self.status.setText("Failed")
            self.status.setToolTip(result.error)
            set_role(self.status, "error")
        else:
            self.status.setText("Done")
            self.status.setToolTip("\n".join(str(o) for o in result.outputs))
            set_role(self.status, "success")


class EntryList(QWidget):
    def __init__(self, empty_text: str):
        super().__init__()
        self.rows: list[EntryRow] = []
        self.empty = label(empty_text, "muted")
        self.empty.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.empty)
        layout.addStretch()

    def set_entries(self, entries: list[Entry]) -> None:
        layout = self.layout()

        if not layout:
            return

        for row in self.rows:
            layout.removeWidget(row)
            row.hide()
            row.deleteLater()

        self.rows = [EntryRow(*entry) for entry in entries]
        for row in self.rows:
            layout.insertWidget(layout.count() - 1, row)
        self.empty.setVisible(not self.rows)
