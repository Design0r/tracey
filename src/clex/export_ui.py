from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QScrollArea,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from clex import img, paths
from clex.batch import ExportWorker
from clex.store import (
    BackgroundOp,
    BitDepth,
    ColorSpace,
    ColorSpaceOp,
    DpiOp,
    ExportProfile,
    ImageFormat,
    PathSource,
    TiffCompression,
)
from clex.theme import set_role
from clex.widgets import (
    IMAGE_FILTER,
    MASK_WORDS,
    ChoiceGroup,
    ColorButton,
    EntryList,
    FolderField,
    Section,
    button,
    card,
    double_spin_box,
    image_files,
    label,
    natural_key,
    spin_box,
)

MAX_PIXELS = 1_000_000
MAX_DPI = 100_000
RUN_HINT = "Add source files, an export format and an output folder first"


def pair_masks(files: list[Path]) -> tuple[list[Path], dict[Path, Path]]:
    """Splits off mask files: shot_mask.png is the mask of shot.tif next to it."""

    def key(path: Path) -> tuple[object, ...]:
        return (path.parent, *natural_key(path))

    images = {key(f): f for f in files if not MASK_WORDS.search(f.stem)}
    masks: dict[Path, Path] = {}
    for file in files:
        source = images.get(key(file)) if MASK_WORDS.search(file.stem) else None
        if source and source not in masks:
            masks[source] = file
    paired = set(masks.values())
    return [f for f in files if f not in paired], masks


class TraceFields:
    """The trace settings of the profile as widgets, for the path stage and page."""

    def __init__(self, edit: Callable[[str, Any], None]):
        self.blacklevel = spin_box(1, 99)
        self.blacklevel.setSuffix(" %")
        self.blacklevel.setToolTip(
            "Mask value at which a pixel counts as inside. On soft edges, lower"
            " values move the path outwards, higher ones inwards."
        )
        self.alphamax = double_spin_box(0, 1.34, 0.05, 0.5)
        self.alphamax.setToolTip(
            "Corner threshold: 0 gives a polygon, higher values smoother curves"
        )
        self.tolerance = double_spin_box(0, 1, 0.05, 0.2)
        self.tolerance.setToolTip(
            "How far joined curves may stray from the mask: higher values give"
            " fewer anchor points, 0 keeps every segment."
        )
        self.turdsize = spin_box(0, 10_000)
        self.turdsize.setSuffix(" px")
        self.turdsize.setToolTip("Specks up to this area are ignored")
        self.offset = double_spin_box(-25, 25, 0.25, 0)
        self.offset.setSuffix(" px")
        self.offset.setToolTip(
            "Moves the path outwards (positive) or inwards (negative), in mask"
            " pixels.\nKeep shrinking below the radius of the tightest curve."
        )
        self.invert = QCheckBox("Invert mask")
        self.clipping = QCheckBox("Mark as clipping path")
        self.clipping.setToolTip(
            f'Saves the path as "{paths.CLIPPING_PATH_NAME}" and makes it the'
            " clipping path of the image, so layout apps cut the image out."
        )
        self.svg = QCheckBox("Also write an SVG")

        self.blacklevel.valueChanged.connect(lambda v: edit("path_blacklevel", v))
        self.alphamax.valueChanged.connect(lambda v: edit("path_smoothness", v))
        self.tolerance.valueChanged.connect(lambda v: edit("path_simplify", v))
        self.turdsize.valueChanged.connect(lambda v: edit("path_speckle_size", v))
        self.offset.valueChanged.connect(lambda v: edit("path_offset", v))
        self.invert.toggled.connect(lambda v: edit("path_invert", v))
        self.clipping.toggled.connect(lambda v: edit("path_clipping", v))
        self.svg.toggled.connect(lambda v: edit("path_svg", v))

    def rows(self) -> list[tuple[str, QWidget]]:
        return [
            ("Blacklevel", self.blacklevel),
            ("Smoothness", self.alphamax),
            ("Simplify", self.tolerance),
            ("Speckle size", self.turdsize),
            ("Grow / shrink", self.offset),
            ("", self.invert),
            ("", self.clipping),
            ("", self.svg),
        ]

    def load(self, p: ExportProfile) -> None:
        self.blacklevel.setValue(p.path_blacklevel)
        self.alphamax.setValue(p.path_smoothness)
        self.tolerance.setValue(p.path_simplify)
        self.turdsize.setValue(p.path_speckle_size)
        self.offset.setValue(p.path_offset)
        self.invert.setChecked(p.path_invert)
        self.clipping.setChecked(p.path_clipping)
        self.svg.setChecked(p.path_svg)


class ExportPage(QWidget):
    """Runs every source file through the pipeline of the current profile."""

    changed = Signal()

    def __init__(
        self,
        edit: Callable[[str, Any], None],
        profile: Callable[[], ExportProfile],
    ):
        super().__init__()
        self.edit = edit
        self.profile = profile
        self.files: list[Path] = []  # everything dropped, sources and masks
        self.sources: list[Path] = []
        self.masks: dict[Path, Path] = {}  # source → mask file it is traced from
        self.chosen_masks: dict[Path, Path] = {}  # picked by hand, beats matching
        self.results: dict[Path, img.ExportResult] = {}
        self.total = 0
        self.output_dir = ""
        self.worker: ExportWorker | None = None
        self.cancelling = False

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(12)
        splitter.addWidget(self.build_sources())
        splitter.addWidget(self.build_pipeline())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1000, 1000])  # equal halves, scaled to the real width

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    # --- layout --------------------------------------------------------------

    def build_sources(self) -> QFrame:
        self.source_summary = label("", "muted")
        browse = button("Browse…", "ghost")
        browse.clicked.connect(self.browse_sources)
        self.clear_button = button("Clear", "ghost")
        self.clear_button.clicked.connect(self.clear_sources)

        top = QHBoxLayout()
        top.addWidget(label("Files", "section"))
        top.addWidget(self.source_summary)
        top.addStretch()
        top.addWidget(browse)
        top.addWidget(self.clear_button)

        self.source_list = EntryList(
            "Drop images or folders onto the window, or browse for them."
        )
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.source_list)

        panel, layout = card()
        panel.setMinimumWidth(320)
        layout.addLayout(top)
        layout.addWidget(scroll, 1)
        return panel

    def build_pipeline(self) -> QFrame:
        description = label(
            "Every file in the batch runs through these stages in order.", "muted"
        )
        description.setWordWrap(True)

        content = QWidget()
        stages = QVBoxLayout(content)
        stages.setContentsMargins(0, 0, 8, 0)
        stages.setSpacing(8)
        for section in (
            self.build_color(),
            self.build_bit_depth(),
            self.build_resolution(),
            self.build_dpi(),
            self.build_background(),
            self.build_path(),
            self.build_write(),
        ):
            stages.addWidget(section)
        stages.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)

        panel, layout = card()
        layout.addWidget(label("Pipeline", "section"))
        layout.addWidget(description)
        layout.addWidget(scroll, 1)
        return panel

    def build_color(self) -> Section:
        self.color_enabled = QCheckBox()
        self.color_enabled.toggled.connect(
            lambda v: self.edit("color_space_enabled", v)
        )

        self.color_space = QComboBox()
        self.color_space.setMinimumWidth(180)
        for space in ColorSpace:
            self.color_space.addItem(space.label)
        self.color_space.currentIndexChanged.connect(
            lambda i: self.edit("color_space", ColorSpace(i))
        )

        self.color_op = ChoiceGroup(ColorSpaceOp)
        self.color_op.changed.connect(
            lambda v: self.edit("color_space_op", ColorSpaceOp(v))
        )

        self.embed = QCheckBox("Embed ICC profile")
        self.embed.toggled.connect(lambda v: self.edit("embed", v))

        section = Section("Color")
        section.switch(self.color_enabled)
        section.row("Color profile", self.color_space)
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

        self.keep_alpha = QCheckBox("Keep alpha channel")
        self.keep_alpha.toggled.connect(lambda v: self.edit("keep_alpha", v))

        section = Section("Bit Depth")
        section.switch(self.bit_depth_enabled)
        section.row("Bit depth", self.bit_depth)
        section.row("Alpha", self.keep_alpha)
        return section

    def build_resolution(self) -> Section:
        self.resolution_enabled = QCheckBox()
        self.resolution_enabled.toggled.connect(
            lambda v: self.edit("resolution_enabled", v)
        )

        self.width_spin = spin_box(0, MAX_PIXELS)
        self.width_spin.setSuffix(" px")
        self.width_spin.valueChanged.connect(lambda v: self.edit("width", v))
        self.height_spin = spin_box(0, MAX_PIXELS)
        self.height_spin.setSuffix(" px")
        self.height_spin.valueChanged.connect(lambda v: self.edit("height", v))

        hint = label(
            "Fits inside the box, keeping the aspect ratio. 0 leaves a side"
            " unconstrained.",
            "muted",
        )
        hint.setWordWrap(True)

        section = Section("Resolution")
        section.switch(self.resolution_enabled)
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
        section.switch(self.dpi_enabled)
        section.row("DPI", self.dpi_spin)
        section.row("Handling", self.dpi_op)
        return section

    def build_background(self) -> Section:
        self.background_enabled = QCheckBox()
        self.background_enabled.toggled.connect(
            lambda v: self.edit("background_enabled", v)
        )

        self.background_color = ColorButton()
        self.background_color.changed.connect(
            lambda v: self.edit("background_color", v)
        )

        self.background_op = ChoiceGroup(BackgroundOp)
        self.background_op.changed.connect(
            lambda v: self.edit("background_op", BackgroundOp(v))
        )

        hint = label(
            "Separate Layer keeps the image above a colored Background layer in TIFF"
            " and PSD exports. Merge to Background flattens everything into a single"
            " Photoshop Background layer. Other formats get the merged result.",
            "muted",
        )
        hint.setWordWrap(True)

        section = Section("Background")
        section.switch(self.background_enabled)
        section.row("Color", self.background_color)
        section.row("Handling", self.background_op)
        section.row("", hint)
        return section

    def build_path(self) -> Section:
        self.path_enabled = QCheckBox()
        self.path_enabled.toggled.connect(lambda v: self.edit_files("path_enabled", v))

        self.path_source = ChoiceGroup(PathSource)
        self.path_source.changed.connect(
            lambda v: self.edit_files("path_source", PathSource(v))
        )

        self.trace = TraceFields(self.edit)

        hint = label(
            "Traces a Photoshop path from the source at full resolution, so it still"
            " fits after resizing. Alpha Channel traces the source's own"
            " transparency, Mask File a file named like it with mask, alpha or matte"
            " (shot.tif ← shot_mask.png), or the one picked in a file's Mask menu."
            " TIFF, PSD and JPEG carry the path, PNG has no place for it.",
            "muted",
        )
        hint.setWordWrap(True)

        section = Section("Path")
        section.switch(self.path_enabled)
        section.row("Trace", self.path_source)
        for text, field in self.trace.rows():
            section.row(text, field)
        section.row("", hint)
        return section

    def build_write(self) -> Section:
        self.output_field = FolderField("Folder for the exported files")
        self.output_field.edited.connect(self.set_output_dir)

        self.format_list = EntryList("No export formats yet")
        formats = QFrame()
        formats.setProperty("role", "panel")
        formats.setMinimumWidth(260)
        formats_layout = QVBoxLayout(formats)
        formats_layout.setContentsMargins(8, 6, 8, 6)
        formats_layout.addWidget(self.format_list)

        self.format_combo = QComboBox()
        self.format_combo.setMinimumWidth(140)
        for fmt in ImageFormat:
            self.format_combo.addItem(fmt.label)
        self.format_combo.currentIndexChanged.connect(lambda _: self.refresh())

        self.add_format_button = QPushButton("Add")
        self.add_format_button.clicked.connect(self.add_format)

        add_row = QWidget()
        add_layout = QHBoxLayout(add_row)
        add_layout.setContentsMargins(0, 0, 0, 0)
        add_layout.addWidget(self.format_combo)
        add_layout.addWidget(self.add_format_button)

        self.tiff_compression = ChoiceGroup(TiffCompression)
        self.tiff_compression.changed.connect(
            lambda v: self.edit("tiff_compression", TiffCompression(v))
        )

        section = Section("Write")
        section.row("Output folder", self.output_field)
        section.row("Exports", formats)
        section.row("Export format", add_row)
        section.row("TIFF compression", self.tiff_compression)
        section.toggle.setChecked(True)
        return section

    # --- profile ---------------------------------------------------------------

    def load_profile(self, p: ExportProfile) -> None:
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
        self.background_enabled.setChecked(p.background_enabled)
        self.background_color.set_value(p.background_color)
        self.background_op.set_value(p.background_op)
        self.tiff_compression.set_value(p.tiff_compression)
        self.path_enabled.setChecked(p.path_enabled)
        self.path_source.set_value(p.path_source)
        self.trace.load(p)
        self.refresh_sources()

    def edit_files(self, field: str, value: Any) -> None:
        """Edits a setting that decides which dropped files are masks."""
        self.edit(field, value)
        self.refresh_sources()

    def uses_mask_files(self) -> bool:
        p = self.profile()
        return p.path_enabled and p.path_source == PathSource.MASK_FILE

    def refresh_formats(self) -> None:
        self.format_list.set_entries(
            [
                (fmt.label, lambda i=i: self.remove_format(i), "")
                for i, fmt in enumerate(self.profile().formats)
            ]
        )
        self.refresh()

    def add_format(self) -> None:
        fmt = ImageFormat(self.format_combo.currentIndex())
        if fmt not in self.profile().formats:
            self.profile().formats.append(fmt)
            self.refresh_formats()

    def remove_format(self, index: int) -> None:
        del self.profile().formats[index]
        self.refresh_formats()

    # --- sources -------------------------------------------------------------

    def set_output_dir(self, text: str) -> None:
        self.output_dir = text.strip()
        self.refresh()

    def add_dropped(self, paths: list[Path]) -> None:
        if self.running():
            return
        for path in image_files(paths):
            if path in self.files:
                continue
            if not self.output_dir:
                self.output_dir = str(path.parent / "export")
                self.output_field.set_text(self.output_dir)
            self.files.append(path)
        self.refresh_sources()

    def browse_sources(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(
            self, "Choose source files", "", IMAGE_FILTER
        )
        self.add_dropped([Path(n) for n in names])

    def pair_sources(self) -> None:
        if not self.uses_mask_files():
            self.sources, self.masks = list(self.files), {}
            return

        # masks chosen by hand win over the ones matched by name, and are never
        # exported themselves
        chosen = {s: m for s, m in self.chosen_masks.items() if s in self.files}
        used = set(chosen.values())
        self.sources, matched = pair_masks([f for f in self.files if f not in used])
        self.masks = {}
        for source in self.sources:
            mask = chosen.get(source) or matched.get(source)
            if mask:
                self.masks[source] = mask

    def refresh_sources(self) -> None:
        if not self.running():  # the batch keeps the files it started with
            self.pair_sources()

        masked = self.uses_mask_files()
        entries = []
        for i, path in enumerate(self.sources):
            mask = self.masks.get(path)
            remove = lambda i=i: self.remove_source(i)
            if not masked:
                entries.append((path.name, remove, str(path)))
                continue
            chosen = path in self.chosen_masks
            how = "chosen" if chosen else "matched by name"
            text = (
                f"{path.name}  ←  {mask.name}" if mask else f"{path.name}  ←  no mask"
            )
            tooltip = f"{path}\nmask ({how}): {mask}" if mask else str(path)
            entries.append((text, remove, tooltip, self.mask_menu(path, chosen)))
        self.source_list.set_entries(entries)
        for row, path in zip(self.source_list.rows, self.sources):
            row.set_result(self.results.get(path))
            if masked and path not in self.masks:
                set_role(row.name, "muted")
        self.refresh()

    def mask_menu(self, source: Path, chosen: bool) -> QToolButton:
        menu_button = QToolButton()
        menu_button.setText("Mask")
        menu_button.setProperty("role", "mask")
        menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu_button.setEnabled(not self.running())
        menu = QMenu(menu_button)
        menu.addAction("Choose mask file…", lambda: self.choose_mask(source))
        auto = menu.addAction("Match by name", lambda: self.match_mask(source))
        auto.setEnabled(chosen)
        menu_button.setMenu(menu)
        return menu_button

    def choose_mask(self, source: Path) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self, f"Choose the mask for {source.name}", str(source.parent), IMAGE_FILTER
        )
        if name and Path(name) != source:
            self.chosen_masks[source] = Path(name)
            self.results.pop(source, None)
            self.refresh_sources()

    def match_mask(self, source: Path) -> None:
        self.chosen_masks.pop(source, None)
        self.results.pop(source, None)
        self.refresh_sources()

    def remove_source(self, index: int) -> None:
        source = self.sources[index]
        self.files.remove(source)
        mask = self.masks.get(source)
        if mask in self.files:
            self.files.remove(mask)
        self.chosen_masks.pop(source, None)
        self.results.pop(source, None)
        self.refresh_sources()

    def clear_sources(self) -> None:
        self.files.clear()
        self.chosen_masks.clear()
        self.results.clear()
        self.refresh_sources()

    # --- batch ---------------------------------------------------------------

    def running(self) -> bool:
        return self.worker is not None

    def can_run(self) -> bool:
        return (
            not self.running()
            and bool(self.sources)
            and bool(self.profile().formats)
            and bool(self.output_dir)
        )

    def run_hint(self) -> str:
        return "" if self.can_run() or self.running() else RUN_HINT

    def start(self) -> None:
        if not self.can_run():
            return
        self.results.clear()
        self.total = len(self.sources)
        self.cancelling = False
        self.worker = ExportWorker(
            list(self.sources),
            self.profile().copy(),
            Path(self.output_dir),
            dict(self.masks),
            self,
        )
        self.worker.exported.connect(self.on_exported)
        self.worker.finished.connect(self.on_batch_finished)

        for row in self.source_list.rows:
            row.set_result(None)
        self.worker.start()
        self.refresh()

    def cancel(self) -> None:
        if self.worker:
            self.cancelling = True
            self.worker.requestInterruption()
            self.refresh()

    def stop(self) -> None:
        if self.worker:
            self.worker.requestInterruption()
            self.worker.wait()

    def on_exported(self, result: img.ExportResult) -> None:
        self.results[result.source] = result
        if result.source in self.sources:
            index = self.sources.index(result.source)
            if index < len(self.source_list.rows):
                self.source_list.rows[index].set_result(result)
        self.refresh()

    def on_batch_finished(self) -> None:
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
        self.cancelling = False
        self.refresh_sources()  # settings may have changed during the batch

    # --- state ---------------------------------------------------------------

    def progress(self) -> int:
        if not self.total:
            return 0
        return len(self.results) * 100 // self.total

    def status(self) -> str:
        done = len(self.results)
        failed = sum(1 for r in self.results.values() if r.error)
        if self.running():
            verb = "Cancelling" if self.cancelling else "Exporting"
            current = min(done + 1, self.total)
            name = (
                self.sources[current - 1].name if current <= len(self.sources) else ""
            )
            return f"{verb} {current} of {self.total} — {name}"
        if done:
            verb = "Cancelled" if done < self.total else "Finished"
            return f"{verb}: {done - failed} of {self.total} exported" + (
                f", {failed} failed" if failed else ""
            )
        if not self.sources:
            return "Drop images or folders to get started."
        formats = len(self.profile().formats)
        paired = f", {len(self.masks)} with mask files" if self.masks else ""
        return (
            f"{len(self.sources)} file{'s' * (len(self.sources) != 1)} ready{paired},"
            f" {formats} export format{'s' * (formats != 1)}"
        )

    def refresh(self) -> None:
        running = self.running()
        count = len(self.sources)
        self.source_summary.setText(
            f"{count} file{'s' * (count != 1)}" if count else ""
        )
        self.clear_button.setEnabled(not running and bool(self.files))
        for row in self.source_list.rows:
            row.remove_button.setEnabled(not running)

        selected = ImageFormat(max(self.format_combo.currentIndex(), 0))
        self.add_format_button.setEnabled(selected not in self.profile().formats)
        self.changed.emit()
