"""A window that traces the path of one file and draws it over the image."""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pyvips
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QCloseEvent,
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QProgressBar,
)

from tracey import img, paths
from tracey.store import ExportProfile, PathSource
from tracey.widgets import button, card, label

if TYPE_CHECKING:
    from tracey.export_ui import ExportPage, TraceFields

DISPLAY_SIZE = 4096  # longest side of the shown image, the path stays exact
RETRACE_DELAY = 250  # ms of quiet after the last edit before tracing again
PATH_COLOR = QColor("#22d3ee")
ZOOM_STEP = 1.25


@dataclass
class Traced:
    plist: paths.TracedPath
    size: tuple[int, int]  # of the traced mask
    seconds: float


def to_qimage(image: pyvips.Image) -> QImage:
    data = image.write_to_memory()
    stride = image.width * 4
    return QImage(
        data, image.width, image.height, stride, QImage.Format.Format_RGBA8888
    ).copy()  # owns its pixels once `data` is gone


def display_image(source: Path, mask: Path | None) -> QImage:
    """The source scaled down for display, or its mask as grey when given one.

    `mask` is the source itself to show its alpha channel.
    """
    path = mask or source
    image = pyvips.Image.thumbnail(str(path), DISPLAY_SIZE, size="down")
    if mask is None:
        image = image.colourspace("srgb")
        if not image.hasalpha():
            image = image.bandjoin(255)
        return to_qimage(image.cast("uchar"))

    # the same band the tracer looks at, see paths.load_mask
    if image.hasalpha():
        band = image.extract_band(image.bands - 1)
    elif image.bands == 1:
        band = image
    else:
        band = image.colourspace("b-w").extract_band(0)
    grey = (band * (255 / img.format_max(band))).cast("uchar")
    return to_qimage(grey.bandjoin([grey, grey, 255]))


class LoadJob(QThread):
    loaded = Signal(object, object)  # key, QImage or error message

    def __init__(self, key: tuple[Path, Path | None], parent: QObject):
        super().__init__(parent)
        self.key = key

    def run(self) -> None:
        try:
            self.loaded.emit(self.key, display_image(*self.key))
        except pyvips.Error as e:
            self.loaded.emit(self.key, img.error_message(e))


class TraceJob(QThread):
    progress = Signal(float)
    traced = Signal(object)  # Traced or an error message

    def __init__(
        self,
        key: tuple[object, ...],
        source: Path,
        image: pyvips.Image | None,
        profile: ExportProfile,
        mask: Path | None,
        parent: QObject,
    ):
        super().__init__(parent)
        self.key = key  # the inputs it traces, see PathPreview.trace_key
        self.source = source
        self.image = image  # the decoded source when tracing its alpha
        self.profile = profile
        self.mask = mask

    def run(self) -> None:
        started = time.perf_counter()
        try:
            image = self.image
            if image is None:
                image = pyvips.Image.new_from_file(str(self.source)).autorot()
                if self.profile.path_source == PathSource.ALPHA:
                    image = image.copy_memory()  # traced again on the next edit
                self.image = image
            plist, size = img.path_stage(
                image,
                self.profile,
                self.mask,
                self.isInterruptionRequested,
                self.progress.emit,
            )
        except InterruptedError:
            return
        except (pyvips.Error, img.ExportError, paths.TraceError, OSError) as e:
            self.traced.emit(img.error_message(e))
            return
        self.traced.emit(Traced(plist, size, time.perf_counter() - started))


class PathView(QGraphicsView):
    """The image with the path on top, zoomed with the wheel and dragged to pan."""

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setBackgroundBrush(QColor("#0b0d11"))
        self.setFrameShape(QGraphicsView.Shape.NoFrame)

        self.checker = QGraphicsRectItem()
        self.checker.setBrush(QBrush(checkerboard()))
        self.checker.setPen(Qt.PenStyle.NoPen)
        self.pixmap = QGraphicsPixmapItem()
        self.pixmap.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.outline = QGraphicsPathItem()  # dark edge, keeps the path readable
        self.outline.setPen(cosmetic_pen(QColor(0, 0, 0, 150), 4))
        self.line = QGraphicsPathItem()
        self.line.setPen(cosmetic_pen(PATH_COLOR, 2))
        for item in (self.checker, self.pixmap, self.outline, self.line):
            self.scene().addItem(item)

        self.anchors: list[QPointF] = []
        self.show_anchors = True
        self._size = (0, 0)
        self.image: QImage | None = None

    def set_image(self, image: QImage | None, size: tuple[int, int]) -> None:
        """Shows `image` stretched over a source of `size` pixels."""
        if image is self.image and size == self._size:
            return  # converting to a pixmap again is slow for large images
        width, height = size
        resized = size != self._size
        self._size, self.image = size, image
        self.scene().setSceneRect(QRectF(0, 0, width, height))
        self.checker.setRect(QRectF(0, 0, width, height))
        if image is None:
            self.pixmap.setPixmap(QPixmap())
        else:
            self.pixmap.setPixmap(QPixmap.fromImage(image))
            self.pixmap.setScale(width / image.width())
        if resized:
            self.fit()

    def set_path(self, path: QPainterPath, anchors: list[QPointF]) -> None:
        self.outline.setPath(path)
        self.line.setPath(path)
        self.anchors = anchors
        self.viewport().update()

    def set_show_anchors(self, show: bool) -> None:
        self.show_anchors = show
        self.viewport().update()

    def fit(self) -> None:
        self.fitInView(self.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = ZOOM_STEP ** (event.angleDelta().y() / 120)
        zoom = self.transform().m11() * factor
        if 0.01 < zoom < 64:
            self.scale(factor, factor)

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        if not self.show_anchors or not self.anchors:
            return
        # markers keep their screen size at every zoom
        transform = painter.transform()
        painter.resetTransform()
        painter.setPen(QPen(QColor(0, 0, 0, 200), 1))
        painter.setBrush(QColor("#ffffff"))
        for point in self.anchors:
            if rect.contains(point):
                p = transform.map(point)
                painter.drawRect(QRectF(p.x() - 2.5, p.y() - 2.5, 5, 5))
        painter.setTransform(transform)


def cosmetic_pen(color: QColor, width: float) -> QPen:
    pen = QPen(color, width)
    pen.setCosmetic(True)  # the same width at every zoom
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def checkerboard() -> QPixmap:
    tile = QPixmap(16, 16)
    tile.fill(QColor("#cfd2d8"))
    painter = QPainter(tile)
    painter.fillRect(0, 0, 8, 8, QColor("#f2f3f5"))
    painter.fillRect(8, 8, 8, 8, QColor("#f2f3f5"))
    painter.end()
    return tile


def painter_path(
    subpaths: list[paths.Subpath], scale: float
) -> tuple[QPainterPath, list[QPointF]]:
    """The knots as a QPainterPath and its anchor points, scaled to the source."""

    def point(xy: paths.XY) -> QPointF:
        return QPointF(xy[0] * scale, xy[1] * scale)

    path = QPainterPath()
    anchors: list[QPointF] = []
    for knots in subpaths:
        path.moveTo(point(knots[0][1]))
        # each knot pair is a cubic, see paths.write_svg
        for (_, _, out), (into, anchor, _) in zip(
            knots, knots[1:] + knots[:1], strict=True
        ):
            path.cubicTo(point(out), point(into), point(anchor))
        path.closeSubpath()
        anchors.extend(point(knot[1]) for knot in knots)
    return path, anchors


class PathPreview(QDialog):
    """Traces one file with the profile's settings and draws the path over it.

    The settings are the profile's own: tuning them here tunes the export.
    """

    def __init__(self, page: ExportPage):
        super().__init__(page)
        self.page = page
        self.setWindowTitle("Path Preview")
        self.resize(1180, 780)

        self.job: TraceJob | None = None
        self.loads: list[LoadJob] = []
        self.retrace = False  # trace again once the running job stops
        self.traced: Traced | None = None
        self.traced_key: tuple[object, ...] | None = None  # inputs of `traced`
        self.images: dict[tuple[Path, Path | None], QImage | str] = {}
        self.decoded: tuple[Path, pyvips.Image] | None = None  # for alpha tracing
        self.sizes: dict[Path, tuple[int, int]] = {}
        self.message = ""

        self.view = PathView()
        self.files = QComboBox()
        self.files.currentIndexChanged.connect(lambda _: self.update_preview())
        self.fields: TraceFields = page.trace_fields()
        self.anchors = QCheckBox("Show anchor points")
        self.anchors.setChecked(True)
        self.anchors.toggled.connect(self.view.set_show_anchors)
        self.show_mask = QCheckBox("Show mask instead of image")
        self.show_mask.toggled.connect(lambda _: self.update_image())
        fit = button("Fit to window", "ghost")
        fit.clicked.connect(self.view.fit)
        self.info = label("", "muted")
        self.info.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        form.addRow("File", self.files)
        for text, field in self.fields.tuning_rows():
            form.addRow(text, field)
        form.addRow("", self.anchors)
        form.addRow("", self.show_mask)

        hint = label(
            "These are the profile's settings, the export uses what you set here."
            " Scroll to zoom, drag to pan.",
            "muted",
        )
        hint.setWordWrap(True)

        panel, side = card()
        panel.setFixedWidth(340)
        side.addWidget(label("Path", "section"))
        side.addLayout(form)
        side.addWidget(fit, 0, Qt.AlignmentFlag.AlignLeft)
        side.addStretch()
        side.addWidget(self.progress)
        side.addWidget(self.info)
        side.addWidget(hint)

        viewer, viewer_layout = card()
        viewer_layout.setContentsMargins(1, 1, 1, 1)
        viewer_layout.addWidget(self.view)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addWidget(viewer, 1)
        layout.addWidget(panel)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(RETRACE_DELAY)
        self.timer.timeout.connect(self.update_preview)

        page.changed.connect(self.sync_files)
        page.trace_changed.connect(self.on_trace_changed)
        self.fields.sync(page.profile())
        self.sync_files()

    # --- inputs --------------------------------------------------------------

    def source(self) -> Path | None:
        index = self.files.currentIndex()
        sources = self.page.sources
        return sources[index] if 0 <= index < len(sources) else None

    def select(self, source: Path | None) -> None:
        if source in self.page.sources:
            self.files.setCurrentIndex(self.page.sources.index(source))

    def sync_files(self) -> None:
        names = [p.name for p in self.page.sources]
        if names != [self.files.itemText(i) for i in range(self.files.count())]:
            current = self.source()
            self.files.blockSignals(True)
            self.files.clear()
            self.files.addItems(names)
            self.files.blockSignals(False)
            self.select(current)
        if self.isVisible():
            self.update_preview()  # the mask slot or mode may have changed

    def on_trace_changed(self, origin: object) -> None:
        if origin is not self.fields:
            self.fields.sync(self.page.profile())
        if self.isVisible():
            self.timer.start()

    def mask_path(self, source: Path) -> Path | None:
        if self.page.profile().path_source == PathSource.MASK_FILE:
            return self.page.masks.get(source)
        return source

    def trace_key(self, source: Path) -> tuple[object, ...]:
        p = self.page.profile()
        return (
            source,
            p.path_source,
            self.mask_path(source),
            p.path_blacklevel,
            p.path_invert,
            p.path_smoothness,
            p.path_simplify,
            p.path_speckle_size,
        )

    # --- work ------------------------------------------------------------------

    def update_preview(self) -> None:
        """Shows the current file, traces it if its inputs changed."""
        if not self.isVisible():
            return
        self.update_image()
        source = self.source()
        if source is None:
            self.show_message("Add files to preview their path.")
            return
        if self.mask_path(source) is None:  # mask file mode, none dropped yet
            self.show_message("Drop a mask on this file's Mask slot to trace it.")
            return
        key = self.trace_key(source)
        if self.job:
            if self.job.key != key:  # outdated: stop it, trace again after
                self.retrace = True
                self.job.requestInterruption()
            self.update_path()
            return
        if key == self.traced_key:
            self.update_path()  # only the offset changed
            return
        self.start_trace(source, key)

    def show_message(self, message: str) -> None:
        """Shows `message` instead of a path, nothing is traced now."""
        if self.job:
            self.job.requestInterruption()
        self.retrace = False
        self.traced, self.traced_key, self.message = None, None, message
        self.update_path()

    def start_trace(self, source: Path, key: tuple[object, ...]) -> None:
        p = self.page.profile()
        cached = None
        if p.path_source == PathSource.ALPHA and self.decoded:
            cached = self.decoded[1] if self.decoded[0] == source else None
        self.job = TraceJob(
            key, source, cached, p.copy(), self.page.masks.get(source), self
        )
        self.job.progress.connect(lambda v: self.progress.setValue(round(v * 100)))
        self.job.traced.connect(self.on_traced)
        self.job.finished.connect(self.on_job_finished)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.info.setText(f"Tracing {source.name}…")
        self.job.start()

    def on_traced(self, result: Traced | str) -> None:
        job = self.job
        if job is None:
            return
        if job.profile.path_source == PathSource.ALPHA:
            self.decoded = (job.source, job.image)
        source = self.source()
        if source is None or job.key != self.trace_key(source):
            return  # outdated, what is current now runs or shows after the job
        self.traced_key = job.key
        if isinstance(result, str):
            self.traced, self.message = None, f"Cannot trace: {result}"
        else:
            self.traced, self.message = result, ""
        self.update_path()

    def on_job_finished(self) -> None:
        if self.job:
            self.job.deleteLater()
        self.job = None
        self.progress.setVisible(False)
        if self.retrace:
            self.retrace = False
            self.update_preview()

    def update_image(self) -> None:
        source = self.source()
        if source is None:
            self.view.set_image(None, (1, 1))
            return
        key = (source, self.mask_path(source) if self.show_mask.isChecked() else None)
        if key[1] is None and self.show_mask.isChecked():
            key = (source, source)  # no mask file yet: its alpha, if any
        size = self.source_size(source)
        cached = self.images.get(key)
        if isinstance(cached, QImage):
            self.view.set_image(cached, size)
        elif cached is None and not any(job.key == key for job in self.loads):
            self.view.set_image(None, size)
            job = LoadJob(key, self)
            job.loaded.connect(self.on_loaded)
            job.finished.connect(lambda job=job: self.loads.remove(job))
            self.loads.append(job)
            job.start()

    def on_loaded(self, key: tuple[Path, Path | None], image: QImage | str) -> None:
        self.images[key] = image
        if isinstance(image, str):
            self.message = f"Cannot show the image: {image}"
            self.update_path()
        self.update_image()

    def source_size(self, source: Path) -> tuple[int, int]:
        if source not in self.sizes:
            try:
                image = pyvips.Image.new_from_file(str(source)).autorot()
                self.sizes[source] = (image.width, image.height)
            except pyvips.Error:
                self.sizes[source] = (1, 1)
        return self.sizes[source]

    def update_path(self) -> None:
        traced = self.traced
        source = self.source()
        if traced is None or source is None:
            self.view.set_path(QPainterPath(), [])
            self.info.setText(self.message)
            return
        offset = self.page.profile().path_offset
        subpaths = paths.subpaths(traced.plist, offset)
        scale = self.source_size(source)[0] / traced.size[0]
        path, anchors = painter_path(subpaths, scale)
        self.view.set_path(path, anchors)
        count = len(subpaths)
        self.info.setText(
            f"{count} subpath{'s' * (count != 1)}, {len(anchors)} anchor points"
            f" · traced in {traced.seconds:.1f} s"
        )

    # --- window ----------------------------------------------------------------

    def open_for(self, source: Path | None) -> None:
        self.select(source)
        self.show()
        self.raise_()
        self.activateWindow()
        self.update_preview()

    def stop(self) -> None:
        self.timer.stop()
        self.retrace = False
        if self.job:
            self.job.requestInterruption()
            self.job.wait()

        for job in self.loads:
            job.requestInterruption()
            job.wait()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.stop()
        self.decoded = None  # a decoded source can be large
        super().closeEvent(event)
