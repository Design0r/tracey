import logging
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import pyvips

from clex import paths, psd
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

log = logging.getLogger(__name__)

MM_PER_INCH = 25.4
UNTAGGED_DPI = 72.0
JPEG_QUALITY = 92
ICC_PROFILE = "icc-profile-data"
PHOTOSHOP_DATA = "photoshop-data"

PROFILE_DIR = Path(__file__).parent / "profiles"
BUILTIN_PROFILES = {ColorSpace.SRGB: "srgb", ColorSpace.CMYK: "cmyk"}
PROFILE_FILES = {
    ColorSpace.ECI_RGB: "eciRGB_v2.icc",
    ColorSpace.ISO_COATED: "ISOcoated_v2_300_eci.icc",
}
DEPTH_FORMATS = {
    BitDepth.BPC_8: "uchar",
    BitDepth.BPC_16: "ushort",
    BitDepth.BPC_32: "float",
}
DEPTH_MAX = {BitDepth.BPC_8: 255.0, BitDepth.BPC_16: 65535.0, BitDepth.BPC_32: 1.0}
EXTENSIONS = {
    ImageFormat.JPEG: ".jpg",
    ImageFormat.PNG: ".png",
    ImageFormat.TIFF: ".tif",
    ImageFormat.PSD: ".psd",
}
TIFF_COMPRESSION = {TiffCompression.NONE: "none", TiffCompression.LZW: "lzw"}


class ExportError(Exception):
    pass


@dataclass
class ExportResult:
    source: Path
    outputs: list[Path] = field(default_factory=list)
    error: str = ""


Progress = Callable[[ExportResult], bool]


@dataclass
class Document:
    image: pyvips.Image
    background: list[float] | None = None
    path: paths.TracedPath | None = None  # traced by the path stage
    path_size: tuple[int, int] = (0, 0)  # of the bitmap the path was traced from

    def composite(self) -> pyvips.Image:
        if self.background is None:
            return self.image
        return drop_alpha(self.image, self.background)

    def layers(self) -> list[psd.Layer]:
        if self.background is not None:
            fill = self.image.new_from_image(self.background)
            return [
                psd.Layer("Background", fill, background=True),
                psd.Layer("Layer 1", self.image),
            ]
        if self.image.hasalpha():
            return [psd.Layer("Layer 0", self.image)]
        return []


def init() -> None:
    pyvips.cache_set_max(0)


def error_message(error: Exception) -> str:
    if isinstance(error, pyvips.Error):
        return (error.detail or error.message).strip()
    return str(error)


def format_max(image: pyvips.Image) -> float:
    match image.format:
        case "uchar" | "char":
            return 255.0
        case "float" | "double":
            return 1.0
        case _:
            return 65535.0


def color_bands(image: pyvips.Image) -> int:
    return image.bands - (1 if image.hasalpha() else 0)


def is_deep(image: pyvips.Image) -> bool:
    return image.format not in ("uchar", "char")


def depth_interpretation(image: pyvips.Image, depth: BitDepth) -> str:
    if image.interpretation == "cmyk":
        return "cmyk"
    if color_bands(image) < 3:
        return "grey16" if depth == BitDepth.BPC_16 else "b-w"
    return "rgb16" if depth == BitDepth.BPC_16 else "srgb"


def to_depth(image: pyvips.Image, depth: BitDepth) -> pyvips.Image:
    if image.interpretation == "scrgb" and depth != BitDepth.BPC_32:
        image = image.colourspace("rgb16")

    if image.format == DEPTH_FORMATS[depth]:
        return image

    offset = 0.0 if depth == BitDepth.BPC_32 else 0.5
    image = image.linear(DEPTH_MAX[depth] / format_max(image), offset).cast(
        DEPTH_FORMATS[depth]
    )
    return image.copy(interpretation=depth_interpretation(image, depth))


def drop_alpha(
    image: pyvips.Image, background: list[float] | None = None
) -> pyvips.Image:
    if not image.hasalpha():
        return image

    fmt = image.format
    maximum = format_max(image)
    if background is None:
        background = [0.0 if image.interpretation == "cmyk" else maximum]
    return image.flatten(background=background, max_alpha=maximum).cast(fmt)


def resize(image: pyvips.Image, hscale: float, vscale: float) -> pyvips.Image:
    if hscale == 1.0 and vscale == 1.0:
        return image

    if not image.hasalpha():
        return image.resize(hscale, vscale=vscale)

    fmt = image.format
    maximum = format_max(image)
    return (
        image.premultiply(max_alpha=maximum)
        .resize(hscale, vscale=vscale)
        .unpremultiply(max_alpha=maximum)
        .cast(fmt)
    )


def profile_path(space: ColorSpace) -> str:
    if space in BUILTIN_PROFILES:
        return BUILTIN_PROFILES[space]

    path = PROFILE_DIR / PROFILE_FILES[space]
    if not path.is_file():
        raise ExportError(f"{space.label} profile not found: {path}")
    return str(path)


def load_profile(space: ColorSpace) -> bytes:
    if space in BUILTIN_PROFILES:
        return pyvips.Operation.call("profile_load", BUILTIN_PROFILES[space])
    return Path(profile_path(space)).read_bytes()


def assign_profile(image: pyvips.Image, space: ColorSpace) -> pyvips.Image:
    expected = 4 if space.is_cmyk else 3
    bands = color_bands(image)
    if bands != expected:
        raise ExportError(
            f"cannot assign a {space.label} profile to an image with {bands} color channels"
        )

    profile = load_profile(space)

    if space.is_cmyk:
        interpretation = "cmyk"
    elif is_deep(image):
        interpretation = "rgb16"
    else:
        interpretation = "srgb"

    image = image.copy(interpretation=interpretation)
    image.set_type(pyvips.GValue.blob_type, ICC_PROFILE, profile)
    return image


def icc_convert(image: pyvips.Image, profile: str, depth: int) -> pyvips.Image:
    if not image.hasalpha():
        return image.icc_transform(profile, embedded=True, depth=depth)

    # libvips leaves alpha in 8-bit range for 16-bit CMYK output, so carry it ourselves
    bands = color_bands(image)
    alpha = image.extract_band(bands)
    image = image.extract_band(0, n=bands).icc_transform(
        profile, embedded=True, depth=depth
    )
    alpha = alpha.linear(format_max(image) / format_max(alpha), 0.5).cast(image.format)
    return image.bandjoin(alpha)


def color_stage(image: pyvips.Image, p: ExportProfile) -> pyvips.Image:
    if p.color_space_op == ColorSpaceOp.CONVERT:
        deep = is_deep(image)

        if color_bands(image) < 3 and image.get_typeof(ICC_PROFILE) == 0:
            image = image.colourspace("rgb16" if deep else "srgb")

        image = icc_convert(image, profile_path(p.color_space), 16 if deep else 8)
    else:
        image = assign_profile(image, p.color_space)

    if not p.embed:
        image = image.copy()
        image.remove(ICC_PROFILE)

    return image


def bit_depth_stage(image: pyvips.Image, p: ExportProfile) -> pyvips.Image:
    # with a background stage the alpha is flattened onto its color instead of white
    if not p.keep_alpha and not p.background_enabled:
        image = drop_alpha(image)
    return to_depth(image, p.bit_depth)


def resolution_stage(image: pyvips.Image, p: ExportProfile) -> pyvips.Image:
    width = float(image.width)
    height = float(image.height)
    sx = p.width / width if p.width > 0 else 0.0
    sy = p.height / height if p.height > 0 else 0.0

    if sx == 0.0 and sy == 0.0:
        raise ExportError("resolution needs a width or a height")

    scale = min(sx, sy) if sx > 0.0 and sy > 0.0 else max(sx, sy)

    target_w = max(1.0, round(width * scale))
    target_h = max(1.0, round(height * scale))
    return resize(image, target_w / width, target_h / height)


def source_dpi(pixels_per_mm: float) -> float:
    return pixels_per_mm * MM_PER_INCH if pixels_per_mm > 1.0 else UNTAGGED_DPI


def dpi_stage(image: pyvips.Image, p: ExportProfile) -> pyvips.Image:
    if p.dpi <= 0:
        raise ExportError(f"invalid DPI {p.dpi}")

    if p.dpi_op == DpiOp.RESAMPLE:
        image = resize(
            image, p.dpi / source_dpi(image.xres), p.dpi / source_dpi(image.yres)
        )

    pixels_per_mm = p.dpi / MM_PER_INCH
    return image.copy(xres=pixels_per_mm, yres=pixels_per_mm)


def parse_color(text: str) -> list[int]:
    value = text.removeprefix("#")
    try:
        if len(value) != 6:
            raise ValueError
        return [int(value[i : i + 2], 16) for i in (0, 2, 4)]
    except ValueError:
        raise ExportError(f"invalid background color {text}") from None


def match_color(
    rgb: list[int], image: pyvips.Image, profile: str | None
) -> list[float]:
    """Converts an sRGB color into the color space and value range of image."""
    if profile is None and image.get_typeof(ICC_PROFILE) != 0:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "embedded.icc"
            path.write_bytes(image.get(ICC_PROFILE))
            return match_color(rgb, image, str(path))

    if profile is None and image.interpretation == "cmyk":
        profile = BUILTIN_PROFILES[ColorSpace.CMYK]

    pixel = (pyvips.Image.black(1, 1) + rgb).cast("uchar").copy(interpretation="srgb")
    if profile is not None:
        values = pixel.icc_transform(profile, input_profile="srgb", depth=16).getpoint(
            0, 0
        )
        scale = 65535.0
    elif image.interpretation == "scrgb":
        values, scale = pixel.colourspace("scrgb").getpoint(0, 0), 1.0
    elif color_bands(image) < 3:
        values, scale = pixel.colourspace("b-w").getpoint(0, 0), 255.0
    else:
        values, scale = [float(v) for v in rgb], 255.0

    if len(values) != color_bands(image):
        raise ExportError(
            f"background color has {len(values)} channels, the image has {color_bands(image)}"
        )

    maximum = format_max(image)
    values = [v / scale * maximum for v in values]
    if image.format in ("float", "double"):
        return values
    return [float(round(v)) for v in values]


def background_stage(
    image: pyvips.Image, p: ExportProfile, profile: str | None
) -> Document:
    color = match_color(parse_color(p.background_color), image, profile)

    if p.bit_depth_enabled and not p.keep_alpha:
        image = drop_alpha(image, color)

    if p.background_op == BackgroundOp.MERGE:
        return Document(drop_alpha(image, color))
    return Document(image, color)


def trace_settings(p: ExportProfile) -> paths.TraceSettings:
    return paths.TraceSettings(
        threshold=p.path_blacklevel / 100,
        alphamax=p.path_smoothness,
        tolerance=p.path_simplify,
        turdsize=p.path_speckle_size,
        invert=p.path_invert,
    )


def path_stage(
    image: pyvips.Image,
    p: ExportProfile,
    mask: Path | None,
    cancelled: Callable[[], bool],
) -> tuple[paths.TracedPath, tuple[int, int]]:
    """Traces the path from the untouched source, at its full resolution.

    Photoshop stores paths as fractions of the image size, so the path still fits
    after the later stages have resized the image.
    """
    if p.path_source == PathSource.MASK_FILE:
        if mask is None:
            raise ExportError("no mask file found for this image")
        mask_image = pyvips.Image.new_from_file(str(mask)).autorot()
        paths.check_aspect(image, mask_image)
    else:
        if not image.hasalpha():
            raise ExportError("the image has no alpha channel to trace a path from")
        mask_image = image

    plist = paths.trace_image(mask_image, trace_settings(p), cancelled=cancelled)
    return plist, (mask_image.width, mask_image.height)


def process(
    source: Path,
    p: ExportProfile,
    mask: Path | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> Document:
    image = pyvips.Image.new_from_file(str(source)).autorot()

    # keep the source's saved paths, its other Photoshop resources describe its
    # layers and resolution, not ours
    if image.get_typeof(PHOTOSHOP_DATA) != 0:
        kept = paths.keep_paths(bytes(image.get(PHOTOSHOP_DATA)))
        image = image.copy()
        image.remove(PHOTOSHOP_DATA)
        if kept:
            image.set_type(pyvips.GValue.blob_type, PHOTOSHOP_DATA, kept)

    traced = path_stage(image, p, mask, cancelled) if p.path_enabled else None

    profile = None
    if p.color_space_enabled:
        image = color_stage(image, p)
        profile = profile_path(p.color_space)
    if p.bit_depth_enabled:
        image = bit_depth_stage(image, p)
    if p.resolution_enabled:
        image = resolution_stage(image, p)
    if p.dpi_enabled:
        image = dpi_stage(image, p)
    doc = (
        background_stage(image, p, profile) if p.background_enabled else Document(image)
    )

    if traced:
        plist, size = traced
        doc.image = paths.embed_path(
            doc.image, plist, size=size, offset=p.path_offset, clipping=p.path_clipping
        )
        doc.path, doc.path_size = plist, size
    return doc


def photoshop_depth(doc: Document) -> Document:
    if doc.image.format in ("uchar", "ushort"):
        return doc

    background = doc.background
    if background is not None:
        scale = DEPTH_MAX[BitDepth.BPC_16] / format_max(doc.image)
        background = [float(round(v * scale)) for v in background]
    return replace(
        doc, image=to_depth(doc.image, BitDepth.BPC_16), background=background
    )


def save(doc: Document, fmt: ImageFormat, path: Path, p: ExportProfile) -> None:
    image = doc.composite()

    match fmt:
        case ImageFormat.JPEG:
            to_depth(drop_alpha(image), BitDepth.BPC_8).jpegsave(
                str(path), Q=JPEG_QUALITY
            )
            # libvips leaves Photoshop resources out of JPEGs, paths go in like Photoshop's
            if image.get_typeof(PHOTOSHOP_DATA) != 0:
                psd.embed_jpeg_resources(path, bytes(image.get(PHOTOSHOP_DATA)))

        case ImageFormat.PNG:
            if image.interpretation == "cmyk":
                raise ExportError("PNG cannot store CMYK")
            if image.format not in ("uchar", "ushort"):
                image = to_depth(image, BitDepth.BPC_16)
            image.pngsave(str(path))

        case ImageFormat.TIFF:
            if doc.background is not None and image.format not in ("uchar", "ushort"):
                raise ExportError("Photoshop layers need 8 or 16-bit images")
            image.tiffsave(str(path), compression=TIFF_COMPRESSION[p.tiff_compression])
            if doc.background is not None:
                psd.embed_tiff_layers(path, doc.layers())

        case ImageFormat.PSD:
            doc = photoshop_depth(doc)
            psd.save_psd(path, doc.composite(), doc.layers())


def same_file(a: Path, b: Path) -> bool:
    try:
        return b.exists() and a.samefile(b)
    except OSError:
        return False


def export_file(
    p: ExportProfile,
    output_dir: Path,
    result: ExportResult,
    mask: Path | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> None:
    try:
        doc = process(result.source, p, mask, cancelled)
        if len(p.formats) > 1:
            doc.image = doc.image.copy_memory()
    except InterruptedError:
        result.error = "cancelled"
        return
    except (pyvips.Error, ExportError, paths.TraceError, OSError) as e:
        result.error = error_message(e)
        return

    for fmt in p.formats:
        out = output_dir / (result.source.stem + EXTENSIONS[fmt])

        if same_file(result.source, out):
            result.error = f"{fmt.label} would overwrite the source file"
            return

        try:
            save(doc, fmt, out, p)
        except (pyvips.Error, ExportError, psd.PsdError, OSError) as e:
            result.error = f"{fmt.label}: {error_message(e)}"
            return

        result.outputs.append(out)

    if doc.path and p.path_svg:
        out = output_dir / (result.source.stem + ".svg")
        if same_file(result.source, out):
            result.error = "SVG would overwrite the source file"
            return
        try:
            paths.write_svg(
                doc.path,
                doc.image.width,
                doc.image.height,
                out,
                p.path_offset,
                view=doc.path_size,
            )
        except OSError as e:
            result.error = f"SVG: {error_message(e)}"
            return
        result.outputs.append(out)


def execute_profile(
    files: Sequence[Path],
    profile: ExportProfile,
    output_dir: Path,
    progress: Progress | None = None,
    masks: Mapping[Path, Path] | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> list[ExportResult]:
    results: list[ExportResult] = []

    directory_error = ""
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        directory_error = f"cannot create {output_dir}: {e.strerror or e}"

    for file in files:
        result = ExportResult(file)
        results.append(result)

        if directory_error:
            result.error = directory_error
        elif not profile.formats:
            result.error = "profile has no export formats"
        else:
            mask = masks.get(file) if masks else None
            export_file(profile, output_dir, result, mask, cancelled)

        if result.error:
            log.warning("failed to export %s: %s", file, result.error)
        else:
            log.info("exported %s", file)

        if progress and not progress(result):
            break

    return results
