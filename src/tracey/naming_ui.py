from collections.abc import Callable

from PySide6.QtCore import QRegularExpression, Qt, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from tracey.naming import DATE_FORMATS, SAFE_TEXT, Kind, NamePattern, Token
from tracey.widgets import SpinBox, label

DATE_SOURCES = ("Export date", "File modified")
NONE_CHOICE = "—"
EDITOR_WIDTH = 120


def safe_validator(
    parent: QWidget, pattern: str = SAFE_TEXT
) -> QRegularExpressionValidator:
    return QRegularExpressionValidator(QRegularExpression(pattern), parent)


def text_edit(text: str, placeholder: str, tooltip: str) -> QLineEdit:
    edit = QLineEdit(text)
    edit.setPlaceholderText(placeholder)
    edit.setToolTip(tooltip)
    edit.setMinimumWidth(EDITOR_WIDTH)
    edit.setValidator(safe_validator(edit))
    return edit


def small_spin(minimum: int, maximum: int, value: int, prefix: str) -> SpinBox:
    box = SpinBox()
    box.setRange(minimum, maximum)
    box.setValue(value)
    box.setPrefix(prefix)
    return box


def icon_button(text: str, tooltip: str, role: str = "remove") -> QToolButton:
    widget = QToolButton()
    widget.setText(text)
    widget.setToolTip(tooltip)
    widget.setProperty("role", role)
    return widget


class TokenRow(QFrame):
    edited = Signal()
    relabeled = Signal(str, str)
    moved = Signal(int)
    removed = Signal()

    def __init__(self, token: Token, first: bool, last: bool):
        super().__init__()
        self.token = token
        self.setProperty("role", "panel")

        up = icon_button("↑", "Move this part earlier")
        up.setEnabled(not first)
        up.clicked.connect(lambda: self.moved.emit(-1))
        down = icon_button("↓", "Move this part later")
        down.setEnabled(not last)
        down.clicked.connect(lambda: self.moved.emit(1))
        remove = icon_button("×", "Remove this part")
        remove.clicked.connect(self.removed)

        header = QHBoxLayout()
        header.setSpacing(2)
        header.addWidget(label(token.kind.label, "fieldtitle"))
        header.addStretch()
        header.addWidget(up)
        header.addWidget(down)
        header.addWidget(remove)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 4, 4, 8)
        layout.setSpacing(4)
        layout.addLayout(header)

        editors = self.build_editors()
        if editors:
            body = QHBoxLayout()
            body.setContentsMargins(0, 0, 6, 0)
            body.setSpacing(6)
            for editor in editors:
                body.addWidget(editor)
            body.addStretch()
            layout.addLayout(body)

    def build_editors(self) -> list[QWidget]:
        token = self.token
        match token.kind:
            case Kind.TEXT:
                text = text_edit(token.text, "Fixed text", "Written as it is")
                text.textEdited.connect(lambda v: self.set("text", v))
                return [text]
            case Kind.SOURCE:
                return [label("The source file's name, without extension", "muted")]
            case Kind.FOLDER:
                return [label("The name of the folder the source is in", "muted")]
            case Kind.JOIN:
                return [
                    label(
                        "Joins the parts before and after it without the separator",
                        "muted",
                    )
                ]
            case Kind.COUNTER:
                return self.counter_editors()
            case Kind.DATE:
                return self.date_editors()
            case Kind.FIELD:
                return self.field_editors()
            case Kind.LIST:
                return self.list_editors()

    def counter_editors(self) -> list[QWidget]:
        token = self.token
        start = small_spin(0, 999_999, token.start, "Start ")
        start.valueChanged.connect(lambda v: self.set("start", v))
        step = small_spin(1, 1_000, token.step, "Step ")
        step.valueChanged.connect(lambda v: self.set("step", v))
        digits = small_spin(1, 10, token.digits, "Digits ")
        digits.setToolTip("Pads the number with leading zeros to this many digits")
        digits.valueChanged.connect(lambda v: self.set("digits", v))
        per_name = QCheckBox("Per name")
        per_name.setChecked(token.per_name)
        per_name.setToolTip(
            "Starts counting again for every distinct name, e.g. once per product"
            " ID, instead of numbering the whole batch through"
        )
        per_name.toggled.connect(lambda v: self.set("per_name", v))
        return [start, step, digits, per_name]

    def date_editors(self) -> list[QWidget]:
        token = self.token
        fmt = QComboBox()
        fmt.setEditable(True)
        fmt.addItems(DATE_FORMATS)
        fmt.setCurrentText(token.format)
        fmt.setMinimumWidth(EDITOR_WIDTH + 30)
        fmt.setToolTip(
            "YYYY year, YY short year, MM month, DD day, hh hour, mm minute,"
            " ss second; anything else is written as it is"
        )
        fmt.lineEdit().setValidator(safe_validator(fmt))
        fmt.currentTextChanged.connect(lambda v: self.set("format", v))
        source = QComboBox()
        source.addItems(DATE_SOURCES)
        source.setCurrentIndex(int(token.file_date))
        source.setToolTip(
            "Export date is the day the batch runs, File modified the source"
            " file's last change"
        )
        source.currentIndexChanged.connect(lambda i: self.set("file_date", i == 1))
        return [fmt, source]

    def field_editors(self) -> list[QWidget]:
        token = self.token
        name = self.label_edit()
        default = text_edit(
            token.default,
            "Default",
            "Used for files whose field is left empty; empty leaves the part out",
        )
        default.textEdited.connect(lambda v: self.set("default", v.strip()))
        return [name, default]

    def list_editors(self) -> list[QWidget]:
        token = self.token
        name = self.label_edit()
        options = text_edit(
            ", ".join(token.options),
            "front, back, side",
            "The values each file can pick from, separated by commas;"
            " files start on the first one",
        )
        options.setMinimumWidth(EDITOR_WIDTH + 60)
        options.textEdited.connect(
            lambda v: self.set("options", [o.strip() for o in v.split(",")])
        )
        return [name, options]

    def label_edit(self) -> QLineEdit:
        edit = text_edit(
            self.token.label,
            "Name",
            "Name of the input each file row shows; parts with the same name share"
            " one input",
        )
        edit.textEdited.connect(self.relabel)
        return edit

    def relabel(self, text: str) -> None:
        old = self.token.label
        self.token.label = text.strip()
        self.relabeled.emit(old, self.token.label)
        self.edited.emit()

    def set(self, name: str, value: object) -> None:
        setattr(self.token, name, value)
        self.edited.emit()


class NamingEditor(QWidget):
    changed = Signal(object)
    relabeled = Signal(str, str)
    rebuilt = Signal()

    def __init__(self):
        super().__init__()
        self.pattern = NamePattern()
        self.rows: list[TokenRow] = []

        self.separator = QLineEdit()
        self.separator.setMaxLength(3)
        self.separator.setFixedWidth(60)
        self.separator.setValidator(safe_validator(self.separator))
        self.separator.setToolTip(
            "Written between the parts; parts that come out empty are left out"
            " along with their separator"
        )
        self.separator.textEdited.connect(self.set_separator)

        self.parts = QWidget()
        self.parts_layout = QVBoxLayout(self.parts)
        self.parts_layout.setContentsMargins(0, 0, 0, 0)
        self.parts_layout.setSpacing(4)
        self.empty = label("No parts yet, the files keep their names", "muted")
        self.parts_layout.addWidget(self.empty)

        self.kind_combo = QComboBox()
        for kind in Kind:
            self.kind_combo.addItem(kind.label, kind)
        self.kind_combo.setMinimumWidth(140)
        add = QPushButton("Add")
        add.clicked.connect(self.add)
        self.add_row = QWidget()
        add_layout = QHBoxLayout(self.add_row)
        add_layout.setContentsMargins(0, 0, 0, 0)
        add_layout.addWidget(self.kind_combo)
        add_layout.addWidget(add)
        add_layout.addStretch()

        self.preview = label("", "")
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

    def rows_for(self) -> list[tuple[str | None, QWidget]]:
        hint = label(
            "Builds the names of the exports from these parts, in order. Input"
            " fields and choice lists show up on every file row, to type a product"
            " ID or pick a value per file. Counters number the files in list order."
            " A name typed into a file's name field overrides the pattern.",
            "muted",
        )
        hint.setWordWrap(True)
        return [
            ("Separator", self.separator),
            (None, self.parts),
            ("Add part", self.add_row),
            ("Preview", self.preview),
            ("", hint),
        ]

    def load(self, pattern: NamePattern) -> None:
        self.pattern = pattern.copy()
        self.separator.setText(self.pattern.separator)
        self.rebuild()

    def rebuild(self) -> None:
        for row in self.rows:
            self.parts_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        tokens = self.pattern.tokens
        self.rows = [
            TokenRow(token, i == 0, i == len(tokens) - 1)
            for i, token in enumerate(tokens)
        ]
        for index, row in enumerate(self.rows):
            row.edited.connect(self.emit_changed)
            row.relabeled.connect(self.relabeled)
            row.moved.connect(lambda by, index=index: self.move(index, by))
            row.removed.connect(lambda index=index: self.remove(index))
            self.parts_layout.addWidget(row)
        self.empty.setVisible(not self.rows)
        self.rebuilt.emit()

    def emit_changed(self) -> None:
        self.changed.emit(self.pattern.copy())

    def set_separator(self, text: str) -> None:
        self.pattern.separator = text
        self.emit_changed()

    def edit_structure(self, change: Callable[[list[Token]], None]) -> None:
        change(self.pattern.tokens)
        self.rebuild()
        self.emit_changed()

    def add(self) -> None:
        kind = Kind(self.kind_combo.currentData())
        token = Token.new(kind)
        if kind.per_file:
            taken = {t.label for t in self.pattern.tokens}
            base = token.label
            number = 2
            while token.label in taken:
                token.label = f"{base} {number}"
                number += 1
        self.edit_structure(lambda tokens: tokens.append(token))

    def move(self, index: int, by: int) -> None:
        target = index + by
        if not 0 <= target < len(self.pattern.tokens):
            return

        def swap(tokens: list[Token]) -> None:
            tokens[index], tokens[target] = tokens[target], tokens[index]

        self.edit_structure(swap)

    def remove(self, index: int) -> None:
        self.edit_structure(lambda tokens: tokens.pop(index))

    def set_preview(self, text: str) -> None:
        self.preview.setText(text)
