from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QRegularExpression, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from tracey import img, paths
from tracey.batch import ExportWorker
from tracey.preview import PathPreview
from tracey.store import (
    BackgroundOp,
    BitDepth,
    ColorSpace,
    ColorSpaceOp,
    DpiOp,
    ExportProfile,
    ImageFormat,
    PathSource,
    RenderingIntent,
    ShadowOp,
    TiffCompression,
)
from tracey.theme import set_role
from tracey.widgets import (
    IMAGE_FILTER,
    ChoiceGroup,
    ColorButton,
    DropSlot,
    EntryList,
    FolderField,
    Section,
    button,
    card,
    double_spin_box,
    image_files,
    label,
    spin_box,
)

MAX_PIXELS = 1_000_000
MAX_DPI = 100_000
RUN_HINT = "Add source files, an export format and an output folder first"
DONE_HINT = "Every file is exported already, requeue them to export them again"
CURRENT_PROFILE = "Current profile"
OWN_SETTINGS = "Own settings"
OWN = -1  # assigned to a file that has settings of its own, no saved profile


def slot_row(slots: list[QWidget]) -> QWidget:
    if len(slots) == 1:
        return slots[0]
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    for slot in slots:
        layout.addWidget(slot)
    return row


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
            "Makes the path the clipping path of the image, so layout apps cut the"
            " image out."
        )
        self.name = QLineEdit()
        self.name.setMinimumWidth(140)
        self.name.setMaxLength(63)
        # Photoshop resource names are single byte strings, ASCII reads the same
        # on every system
        self.name.setValidator(
            QRegularExpressionValidator(QRegularExpression("[ -~]*"), self.name)
        )
        self.name.setToolTip(
            "Name of the path in Photoshop. A clipping path gets a number if the"
            " image already has a path of that name."
        )
        self.svg = QCheckBox("Also write an SVG")

        self.blacklevel.valueChanged.connect(lambda v: edit("path_blacklevel", v))
        self.alphamax.valueChanged.connect(lambda v: edit("path_smoothness", v))
        self.tolerance.valueChanged.connect(lambda v: edit("path_simplify", v))
        self.turdsize.valueChanged.connect(lambda v: edit("path_speckle_size", v))
        self.offset.valueChanged.connect(lambda v: edit("path_offset", v))
        self.invert.toggled.connect(lambda v: edit("path_invert", v))
        self.clipping.toggled.connect(lambda v: edit("path_clipping", v))
        self.clipping.toggled.connect(self.update_placeholder)
        self.name.textEdited.connect(lambda v: edit("path_name", v))
        self.svg.toggled.connect(lambda v: edit("path_svg", v))

    def tuning_rows(self) -> list[tuple[str, QWidget]]:
        """The settings that shape the path."""
        return [
            ("Blacklevel", self.blacklevel),
            ("Smoothness", self.alphamax),
            ("Simplify", self.tolerance),
            ("Speckle size", self.turdsize),
            ("Grow / shrink", self.offset),
            ("", self.invert),
        ]

    def rows(self) -> list[tuple[str, QWidget]]:
        return [
            *self.tuning_rows(),
            ("", self.clipping),
            ("Path name", self.name),
            ("", self.svg),
        ]

    def update_placeholder(self, clipping: bool) -> None:
        default = paths.CLIPPING_PATH_NAME if clipping else paths.PATH_NAME
        self.name.setPlaceholderText(default)

    def load(self, p: ExportProfile) -> None:
        self.blacklevel.setValue(p.path_blacklevel)
        self.alphamax.setValue(p.path_smoothness)
        self.tolerance.setValue(p.path_simplify)
        self.turdsize.setValue(p.path_speckle_size)
        self.offset.setValue(p.path_offset)
        self.invert.setChecked(p.path_invert)
        self.clipping.setChecked(p.path_clipping)
        self.update_placeholder(p.path_clipping)
        self.name.setText(p.path_name)
        self.svg.setChecked(p.path_svg)

    def sync(self, p: ExportProfile) -> None:
        """Loads `p` without reporting the values back as edits."""
        widgets = (
            self.blacklevel,
            self.alphamax,
            self.tolerance,
            self.turdsize,
            self.offset,
            self.invert,
            self.clipping,
            self.name,
            self.svg,
        )
        blockers = [QSignalBlocker(w) for w in widgets]
        self.load(p)
        del blockers


class ExportPage(QWidget):
    """Runs every source file through the pipeline of the current profile, or of
    the saved profile or own settings picked for it while per-file profiles are on.

    The pipeline shows the current profile, or the own settings of the file in
    `editing`.
    """

    changed = Signal()
    trace_changed = Signal(object)  # the TraceFields edited, None for a new profile

    def __init__(
        self,
        edit: Callable[[str, Any], None],
        profile: Callable[[], ExportProfile],
        saved: Callable[[], list[ExportProfile]],
    ):
        super().__init__()
        self.edit_current = edit
        self.current = profile
        self.saved = saved
        self.sources: list[Path] = []
        self.masks: dict[Path, Path] = {}  # source → mask file it is traced from
        self.shadows: dict[Path, Path] = {}  # source → its shadow file
        self.per_file = False  # off: every file uses the current profile
        self.assigned: dict[Path, int] = {}  # source → id of its saved profile, OWN
        self.own: dict[Path, ExportProfile] = {}  # source → its own settings
        self.editing: Path | None = None  # the file whose own settings are shown
        self.loading = False
        self.results: dict[Path, img.ExportResult] = {}
        self.queue: list[Path] = []  # the sources of the last or current batch
        self.cancelled = False  # the last batch stopped before its end
        self.output_dir = ""
        self.worker: ExportWorker | None = None
        self.cancelling = False

        self.trace_changed.connect(self.on_trace_changed)

        splitter = QSplitter()
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(12)
        splitter.addWidget(self.build_sources())
        splitter.addWidget(self.build_pipeline())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        # handle at three fifths, scaled to the real width
        splitter.setSizes([3000, 2000])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    # --- layout --------------------------------------------------------------

    def build_sources(self) -> QFrame:
        self.source_summary = label("", "muted")
        browse = button("Browse…", "ghost")
        browse.clicked.connect(self.browse_sources)
        self.requeue_button = button("Requeue", "ghost")
        self.requeue_button.setToolTip(
            "Queue the exported files again, so the next run exports them again"
        )
        self.requeue_button.clicked.connect(self.requeue_done)
        self.clear_button = button("Clear", "ghost")
        self.clear_button.clicked.connect(self.clear_sources)
        self.per_file_switch = QCheckBox("Per-file profiles")
        self.per_file_switch.setToolTip(
            "Off locks the batch to the profile above, for every file.\n"
            "On lets each file pick a saved profile or tune its own settings;"
            f" files left on {CURRENT_PROFILE} follow the one above."
        )
        self.per_file_switch.toggled.connect(self.set_per_file)

        top = QHBoxLayout()
        top.addWidget(label("Files", "section"))
        top.addWidget(self.source_summary)
        top.addStretch()
        top.addWidget(self.per_file_switch)
        top.addWidget(browse)
        top.addWidget(self.requeue_button)
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

        self.editing_label = label("", "")
        self.editing_label.setWordWrap(True)
        done = button("Done", "ghost")
        done.setToolTip("Show the profile above again")
        done.clicked.connect(lambda: self.edit_file(None))
        self.editing_banner = QFrame()
        self.editing_banner.setProperty("role", "panel")
        banner_layout = QHBoxLayout(self.editing_banner)
        banner_layout.setContentsMargins(10, 6, 6, 6)
        banner_layout.addWidget(self.editing_label, 1)
        banner_layout.addWidget(done)
        self.editing_banner.setVisible(False)

        content = QWidget()
        stages = QVBoxLayout(content)
        stages.setContentsMargins(0, 0, 8, 0)
        stages.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        def fit() -> None:
            # never narrower than the open sections, the splitter makes room
            bar = scroll.verticalScrollBar().sizeHint().width()
            width = content.minimumSizeHint().width() + bar + 2 * scroll.frameWidth()
            scroll.setMinimumWidth(width)

        for section in (
            self.build_color(),
            self.build_bit_depth(),
            self.build_resolution(),
            self.build_dpi(),
            self.build_background(),
            self.build_shadow(),
            self.build_path(),
            self.build_write(),
        ):
            stages.addWidget(section)
            section.toggle.toggled.connect(fit)
        stages.addStretch()
        scroll.setWidget(content)
        fit()

        panel, layout = card()
        layout.addWidget(label("Pipeline", "section"))
        layout.addWidget(description)
        layout.addWidget(self.editing_banner)
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

        self.intent = ChoiceGroup(RenderingIntent)
        self.intent.setToolTip(
            "Perceptual compresses the whole range into the profile, like a manual"
            " Photoshop conversion set to Perceptual; Relative Colorimetric keeps"
            " in-gamut colors exact and clips the rest"
        )
        self.intent.changed.connect(lambda v: self.edit("intent", RenderingIntent(v)))

        self.bpc = QCheckBox("Black point compensation")
        self.bpc.setToolTip(
            "Maps the source's black onto the profile's darkest ink, like Photoshop's"
            " default conversion, so shadows keep their detail instead of clipping"
        )
        self.bpc.toggled.connect(lambda v: self.edit("bpc", v))

        section = Section("Color")
        section.switch(self.color_enabled)
        section.row("Color profile", self.color_space)
        section.row("Handling", self.color_op)
        section.row("Embed", self.embed)
        section.row("Intent", self.intent)
        section.row("Black point", self.bpc)
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

    def build_shadow(self) -> Section:
        self.shadow_enabled = QCheckBox()
        self.shadow_enabled.toggled.connect(
            lambda v: self.edit_files("shadow_enabled", v)
        )

        self.shadow_opacity = spin_box(0, 100)
        self.shadow_opacity.setSuffix(" %")
        self.shadow_opacity.valueChanged.connect(
            lambda v: self.edit("shadow_opacity", v)
        )

        self.shadow_op = ChoiceGroup(ShadowOp)
        self.shadow_op.changed.connect(lambda v: self.edit("shadow_op", ShadowOp(v)))

        self.shadow_k_only = QCheckBox("Black ink only (K)")
        self.shadow_k_only.setToolTip(
            "In CMYK, the shadow is 0% C, M and Y and only K, instead of rich black"
        )
        self.shadow_k_only.toggled.connect(lambda v: self.edit("shadow_k_only", v))

        self.shadow_grade_k = QCheckBox("Grade outside the mask to black ink only")
        self.shadow_grade_k.setToolTip(
            "Moves the image outside the Mask slot's shape to 0% C, M and Y, with K"
            " as light as the original"
        )
        self.shadow_grade_k.toggled.connect(
            lambda v: self.edit_files("shadow_grade_k", v)
        )

        hint = label(
            "Puts a black shadow under the image, from the image dropped on a file's"
            " Shadow slot. Black is full shadow, white none; an image with an alpha"
            " channel uses that instead. Separate Layer keeps it as its own Shadow"
            " layer in TIFF and PSD exports, Merge into Image bakes it into the image"
            " layer. Other formats get the merged result. Black ink only keeps CMYK"
            " shadows on the K plate; RGB images ignore it. Grading outside the mask"
            " also moves the image itself onto the K plate wherever the file's Mask"
            " slot is black or transparent, e.g. a shadow photographed on white;"
            " it needs a CMYK image, and makes the Shadow slot optional.",
            "muted",
        )
        hint.setWordWrap(True)

        section = Section("Shadow")
        section.switch(self.shadow_enabled)
        section.row("Opacity", self.shadow_opacity)
        section.row("Handling", self.shadow_op)
        section.row("CMYK", self.shadow_k_only)
        section.row("", self.shadow_grade_k)
        section.row("", hint)
        return section

    def build_path(self) -> Section:
        self.path_enabled = QCheckBox()
        self.path_enabled.toggled.connect(lambda v: self.edit_files("path_enabled", v))

        self.path_source = ChoiceGroup(PathSource)
        self.path_source.changed.connect(
            lambda v: self.edit_files("path_source", PathSource(v))
        )

        self.trace = self.trace_fields()
        self.preview: PathPreview | None = None
        self.preview_button = button("Preview path…", "")
        self.preview_button.setToolTip(
            "Trace a file and see the path over it while tuning the settings"
        )
        self.preview_button.clicked.connect(self.open_preview)

        hint = label(
            "Traces a Photoshop path from the source at full resolution, so it still"
            " fits after resizing. Alpha Channel traces the source's own"
            " transparency, Mask File the image dropped on a file's Mask slot."
            " TIFF, PSD and JPEG carry the path, PNG has no place for it.",
            "muted",
        )
        hint.setWordWrap(True)

        section = Section("Path")
        section.switch(self.path_enabled)
        section.row("Trace", self.path_source)
        for text, field in self.trace.rows():
            section.row(text, field)
        section.row("", self.preview_button)
        section.row("", hint)
        return section

    def trace_fields(self) -> TraceFields:
        """Trace settings widgets that stay in step with every other set."""
        fields = TraceFields(lambda field, value: self.edit_trace(fields, field, value))
        return fields

    def edit_trace(self, origin: TraceFields, field: str, value: Any) -> None:
        self.edit(field, value)
        self.trace_changed.emit(origin)

    def on_trace_changed(self, origin: object) -> None:
        if origin is not self.trace:
            self.trace.sync(self.profile())

    def open_preview(self) -> None:
        if self.preview is None:
            self.preview = PathPreview(self)
        self.preview.open_for(self.sources[0] if self.sources else None)

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

    def profile(self) -> ExportProfile:
        """The profile the pipeline shows and edits."""
        if self.editing is not None:
            return self.own[self.editing]
        return self.current()

    def edit(self, field: str, value: Any) -> None:
        if self.loading:
            return
        if self.editing is not None:
            setattr(self.own[self.editing], field, value)
        else:
            self.edit_current(field, value)

    def load_profile(self, p: ExportProfile) -> None:
        """Shows the current profile, `p`, leaving a file's own settings."""
        self.editing = None
        self.show_profile(p)

    def edit_file(self, source: Path | None) -> None:
        """Shows the own settings of `source` in the pipeline, None the profile."""
        self.editing = source
        self.show_profile(self.profile())
        self.refresh_formats()

    def show_profile(self, p: ExportProfile) -> None:
        self.loading = True
        self.load_widgets(p)
        self.loading = False
        editing = self.editing is not None
        if editing:
            self.editing_label.setText(
                f"{OWN_SETTINGS} of {self.editing.name}: only this file exports"
                " with them, the profile above stays as it is."
            )
        self.editing_banner.setVisible(editing)
        self.refresh_sources()
        self.trace_changed.emit(None)

    def load_widgets(self, p: ExportProfile) -> None:
        self.color_enabled.setChecked(p.color_space_enabled)
        self.color_space.setCurrentIndex(p.color_space)
        self.color_op.set_value(p.color_space_op)
        self.embed.setChecked(p.embed)
        self.intent.set_value(p.intent)
        self.bpc.setChecked(p.bpc)
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
        self.shadow_enabled.setChecked(p.shadow_enabled)
        self.shadow_opacity.setValue(p.shadow_opacity)
        self.shadow_op.set_value(p.shadow_op)
        self.shadow_k_only.setChecked(p.shadow_k_only)
        self.shadow_grade_k.setChecked(p.shadow_grade_k)

    def edit_files(self, field: str, value: Any) -> None:
        """Edits a setting that decides which slots the file rows show."""
        self.edit(field, value)
        self.refresh_sources()

    def uses_mask_files(self, p: ExportProfile) -> bool:
        traced = p.path_enabled and p.path_source == PathSource.MASK_FILE
        return traced or (p.shadow_enabled and p.shadow_grade_k)

    def uses_shadows(self, p: ExportProfile) -> bool:
        return p.shadow_enabled

    def needs_shadows(self, p: ExportProfile) -> bool:
        """Whether a file without a shadow fails; grading to K works without one."""
        return p.shadow_enabled and not p.shadow_grade_k

    def profile_for(self, source: Path) -> ExportProfile:
        """The profile `source` exports with.

        The profile open above is used live, unsaved edits included, also by the
        files that picked it by name.
        """
        current = self.current()
        picked = self.assigned.get(source) if self.per_file else None
        if picked == OWN:
            return self.own[source]
        if picked is None or picked == current.id:
            return current
        return next((p for p in self.saved() if p.id == picked), current)

    def set_per_file(self, on: bool) -> None:
        self.per_file = on
        if not on and self.editing is not None:
            self.edit_file(None)
        else:
            self.refresh_sources()

    def assign(self, source: Path, index: int) -> None:
        """Picks the saved profile at `index` for `source`, 0 the current one and
        the one after the saved ones its own settings."""
        if self.running() or source not in self.sources:
            return
        saved = self.saved()
        if index > len(saved):
            if source not in self.own:
                # starts from the settings the file used so far
                own = self.profile_for(source).copy()
                own.id = 0
                own.name = OWN_SETTINGS
                self.own[source] = own
            self.assigned[source] = OWN
            self.results.pop(source, None)
            self.edit_file(source)
            return
        if index <= 0:
            self.assigned.pop(source, None)
        else:
            self.assigned[source] = saved[index - 1].id
        self.results.pop(source, None)  # it runs again, with the new profile
        if self.editing == source:
            self.edit_file(None)
        else:
            self.refresh_sources()

    def profile_picker(self, source: Path) -> QComboBox:
        combo = QComboBox()
        combo.setFixedWidth(DropSlot.WIDTH)
        combo.setToolTip(
            f"Profile this file exports with; {CURRENT_PROFILE} follows the one"
            f" above, {OWN_SETTINGS} tunes a copy for this file alone"
        )
        combo.addItem(CURRENT_PROFILE)
        saved = self.saved()
        for p in saved:
            combo.addItem(p.name)
        combo.addItem(OWN_SETTINGS)
        picked = self.assigned.get(source)
        if picked == OWN:
            index = len(saved) + 1
        else:
            index = next((i for i, p in enumerate(saved, 1) if p.id == picked), 0)
        combo.setCurrentIndex(index)
        combo.setEnabled(not self.running())
        combo.activated.connect(lambda i: self.assign(source, i))
        return combo

    def toggle_editing(self, source: Path) -> None:
        self.edit_file(None if source == self.editing else source)

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
        used = {*self.masks.values(), *self.shadows.values()}
        for path in image_files(paths):
            if path in self.sources or path in used:
                continue
            if not self.output_dir:
                self.output_dir = str(path.parent / "export")
                self.output_field.set_text(self.output_dir)
            self.sources.append(path)
        self.refresh_sources()

    def browse_sources(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(
            self, "Choose source files", "", IMAGE_FILTER
        )
        self.add_dropped([Path(n) for n in names])

    def refresh_sources(self) -> None:
        # a deleted profile hands its files back to the current one
        saved = {p.id for p in self.saved()} | {OWN}
        self.assigned = {s: i for s, i in self.assigned.items() if i in saved}

        entries: list[tuple[Any, ...]] = []
        incomplete: set[Path] = set()
        for i, path in enumerate(self.sources):
            remove = lambda i=i: self.remove_source(i)
            p = self.profile_for(path)
            kinds = [
                (kind, found, required)
                for kind, found, used, required in (
                    ("mask", self.masks, self.uses_mask_files(p), True),
                    (
                        "shadow",
                        self.shadows,
                        self.uses_shadows(p),
                        self.needs_shadows(p),
                    ),
                )
                if used
            ]
            slots: list[QWidget] = []
            if self.per_file:
                slots.append(self.profile_picker(path))
            for kind, found, required in kinds:
                if required and path not in found:
                    incomplete.add(path)
                slots.append(self.drop_slot(kind, path, found))
            if not slots:
                entries.append((path.name, remove, str(path)))
                continue
            entries.append((path.name, remove, str(path), slot_row(slots)))
        self.source_list.set_entries(entries)
        for row, path in zip(self.source_list.rows, self.sources):
            row.set_result(self.results.get(path))
            if path in incomplete:
                set_role(row.name, "muted")
            if self.per_file and self.assigned.get(path) == OWN:
                # a click shows the file's own settings in the pipeline
                row.name.set_selectable(True, path == self.editing)
                row.name.setToolTip(
                    f"{path}\nClick to show its {OWN_SETTINGS.lower()} in the pipeline"
                )
                row.name.clicked.connect(lambda path=path: self.toggle_editing(path))
        self.refresh()

    def drop_slot(self, kind: str, source: Path, found: dict[Path, Path]) -> DropSlot:
        slot = DropSlot(kind, found.get(source))
        slot.setEnabled(not self.running())
        slot.dropped.connect(lambda file: self.set_companion(found, source, file))
        slot.clicked.connect(lambda: self.browse_companion(kind, found, source))
        slot.cleared.connect(lambda: self.set_companion(found, source, None))
        return slot

    def browse_companion(
        self, kind: str, found: dict[Path, Path], source: Path
    ) -> None:
        current = found.get(source, source)
        name, _ = QFileDialog.getOpenFileName(
            self,
            f"Choose the {kind} for {source.name}",
            str(current.parent),
            IMAGE_FILTER,
        )
        if name:
            self.set_companion(found, source, Path(name))

    def set_companion(
        self, found: dict[Path, Path], source: Path, file: Path | None
    ) -> None:
        """Gives `source` another mask or shadow, `file`, or none; it runs again."""
        if self.running() or file == source or source not in self.sources:
            return
        if file is None:
            found.pop(source, None)
        else:
            found[source] = file
            if file in self.sources:  # a mask is no source
                self.forget(file)
        self.results.pop(source, None)
        self.refresh_sources()

    def forget(self, source: Path) -> None:
        self.sources.remove(source)
        self.masks.pop(source, None)
        self.shadows.pop(source, None)
        self.assigned.pop(source, None)
        self.own.pop(source, None)
        self.results.pop(source, None)
        if source in self.queue:
            self.queue.remove(source)
        if self.editing == source:
            self.edit_file(None)

    def remove_source(self, index: int) -> None:
        self.forget(self.sources[index])
        self.refresh_sources()

    def forget_saved_profiles(self) -> None:
        self.assigned = {s: i for s, i in self.assigned.items() if i == OWN}

    def clear_sources(self) -> None:
        self.sources.clear()
        self.masks.clear()
        self.shadows.clear()
        self.assigned.clear()
        self.own.clear()
        self.results.clear()
        self.queue.clear()
        if self.editing is not None:
            self.edit_file(None)
        else:
            self.refresh_sources()

    def done(self) -> list[Path]:
        """The sources the last runs exported without errors."""
        return [s for s in self.sources if (r := self.results.get(s)) and not r.error]

    def pending(self) -> list[Path]:
        """The sources the next run exports: new, failed and requeued ones."""
        done = set(self.done())
        return [s for s in self.sources if s not in done]

    def requeue_done(self) -> None:
        for source in self.done():
            self.results.pop(source)
        self.refresh_sources()

    # --- batch ---------------------------------------------------------------

    def running(self) -> bool:
        return self.worker is not None

    def can_run(self) -> bool:
        pending = self.pending()
        return (
            not self.running()
            and bool(pending)
            and all(self.profile_for(s).formats for s in pending)
            and bool(self.output_dir)
        )

    def run_hint(self) -> str:
        if self.can_run() or self.running():
            return ""
        return DONE_HINT if self.sources and not self.pending() else RUN_HINT

    def start(self) -> None:
        if not self.can_run():
            return
        self.queue = self.pending()
        for source in self.queue:
            self.results.pop(source, None)
        self.cancelling = False
        # one copy per profile, so edits during the batch leave it alone
        copies: dict[int, ExportProfile] = {}
        jobs: list[tuple[Path, ExportProfile]] = []
        for source in self.queue:
            p = self.profile_for(source)
            jobs.append((source, copies.setdefault(id(p), p.copy())))
        self.worker = ExportWorker(
            jobs,
            Path(self.output_dir),
            masks=dict(self.masks),
            shadows=dict(self.shadows),
            parent=self,
        )
        self.worker.exported.connect(self.on_exported)
        self.worker.finished.connect(self.on_batch_finished)

        for row, path in zip(self.source_list.rows, self.sources):
            if path in self.queue:
                row.set_result(None)

        self.worker.start()
        self.refresh()

    def cancel(self) -> None:
        if self.worker:
            self.cancelling = True
            self.worker.requestInterruption()
            self.refresh()

    def stop(self) -> None:
        if self.preview:
            self.preview.stop()
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
        self.cancelled = any(s not in self.results for s in self.queue)
        self.refresh_sources()  # settings may have changed during the batch

    # --- state ---------------------------------------------------------------

    def progress(self) -> int:
        if not self.queue:
            return 0
        done = sum(1 for s in self.queue if s in self.results)
        return done * 100 // len(self.queue)

    def status(self) -> str:
        if self.running():
            verb = "Cancelling" if self.cancelling else "Exporting"
            total = len(self.queue)
            current = min(sum(1 for s in self.queue if s in self.results) + 1, total)
            return f"{verb} {current} of {total} — {self.queue[current - 1].name}"
        exported = len(self.done())
        failed = sum(1 for s in self.sources if s in self.results) - exported
        if exported or failed:
            waiting = len(self.sources) - exported - failed
            verb = "Cancelled" if self.cancelled else "Finished"
            return (
                f"{verb}: {exported} of {len(self.sources)} exported"
                + (f", {failed} failed" if failed else "")
                + (f", {waiting} waiting" if waiting else "")
            )
        if not self.sources:
            return "Drop images or folders to get started."
        profiles = [self.profile_for(s) for s in self.sources]
        paired = ""
        if any(self.uses_mask_files(p) for p in profiles):
            paired += f", {len(self.masks)} with masks"
        if any(self.uses_shadows(p) for p in profiles):
            paired += f", {len(self.shadows)} with shadows"
        ready = (
            f"{len(self.sources)} file{'s' * (len(self.sources) != 1)} ready{paired}"
        )
        if self.per_file:
            used = len({id(p) for p in profiles})
            return f"{ready}, {used} profile{'s' * (used != 1)}"
        formats = len(self.profile().formats)
        return f"{ready}, {formats} export format{'s' * (formats != 1)}"

    def refresh(self) -> None:
        running = self.running()
        count = len(self.sources)
        self.source_summary.setText(
            f"{count} file{'s' * (count != 1)}" if count else ""
        )
        self.clear_button.setEnabled(not running and bool(self.sources))
        self.requeue_button.setEnabled(not running and bool(self.done()))
        self.per_file_switch.setEnabled(not running)
        for row in self.source_list.rows:
            row.remove_button.setEnabled(not running)
        for slot in self.source_list.findChildren(DropSlot):
            slot.setEnabled(not running)
        for picker in self.source_list.findChildren(QComboBox):
            picker.setEnabled(not running)

        selected = ImageFormat(max(self.format_combo.currentIndex(), 0))
        self.add_format_button.setEnabled(selected not in self.profile().formats)
        self.changed.emit()
