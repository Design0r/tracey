import logging
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
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
    RenderingIntent,
    ShadowOp,
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
INTENTS = {
    RenderingIntent.PERCEPTUAL: "perceptual",
    RenderingIntent.RELATIVE: "relative",
}
TIFF_COMPRESSION = {TiffCompression.NONE: "none", TiffCompression.LZW: "lzw"}
K_RAMP_STEPS = 256  # K-only inks measured to match lightness
LUT_STEPS = 1000  # L* steps the lightness → K table resolves


class ExportError(Exception):
    pass


@dataclass
class ExportResult:
    source: Path
    outputs: list[Path] = field(default_factory=list[Path])
    error: str = ""


Progress = Callable[[ExportResult], bool]


@dataclass
class Document:
    image: pyvips.Image
    background: list[float] | None = None
    merge: bool = False  # flatten onto the background instead of layering
    shadow: pyvips.Image | None = None  # float coverage 0..1, at the image's size
    shadow_color: list[float] | None = None
    shadow_opacity: float = 1.0
    path: paths.TracedPath | None = None  # traced by the path stage
    path_size: tuple[int, int] = (0, 0)  # of the bitmap the path was traced from

    def composite(self) -> pyvips.Image:
        if self.shadow is not None and self.shadow_color is not None:
            shadow = self.shadow * self.shadow_opacity
            return composite_shadow(
                self.image, shadow, self.shadow_color, self.background
            )
        if self.background is None:
            return self.image
        return drop_alpha(self.image, self.background)

    def layered(self) -> bool:
        """Whether TIFF exports carry Photoshop layers."""
        return not self.merge and (
            self.background is not None or self.shadow is not None
        )

    def layers(self) -> list[psd.Layer]:
        if self.merge:
            return []
        layers = []
        if self.background is not None:
            fill = self.image.new_from_image(self.background)
            layers.append(psd.Layer("Background", fill, background=True))
        if self.shadow is not None and self.shadow_color is not None:
            alpha = cast_rounded(
                self.shadow * format_max(self.image), self.image.format
            )
            fill = self.image.new_from_image(self.shadow_color).bandjoin(alpha)
            opacity = round(self.shadow_opacity * 255)
            layers.append(psd.Layer("Shadow", fill, opacity=opacity))
        if layers:
            return [*layers, psd.Layer("Layer 1", self.image)]
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


def cast_rounded(image: pyvips.Image, fmt: str) -> pyvips.Image:
    if fmt in ("float", "double"):
        return image.cast(fmt)
    return (image + 0.5).cast(fmt)


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


def icc_convert(
    image: pyvips.Image, profile: str, depth: int, p: ExportProfile
) -> pyvips.Image:
    options = conversion(p)
    if not image.hasalpha():
        return image.icc_transform(profile, embedded=True, depth=depth, **options)

    # libvips leaves alpha in 8-bit range for 16-bit CMYK output, so carry it ourselves
    bands = color_bands(image)
    alpha = image.extract_band(bands)
    image = image.extract_band(0, n=bands).icc_transform(
        profile, embedded=True, depth=depth, **options
    )
    alpha = alpha.linear(format_max(image) / format_max(alpha), 0.5).cast(image.format)
    return image.bandjoin(alpha)


def conversion(p: ExportProfile) -> dict[str, Any]:
    """icc_transform options for converting colors the way the profile says."""
    return {"intent": INTENTS[p.intent], "black_point_compensation": p.bpc}


def color_stage(image: pyvips.Image, p: ExportProfile) -> pyvips.Image:
    if p.color_space_op == ColorSpaceOp.CONVERT:
        deep = is_deep(image)

        if color_bands(image) < 3 and image.get_typeof(ICC_PROFILE) == 0:
            image = image.colourspace("rgb16" if deep else "srgb")

        image = icc_convert(image, profile_path(p.color_space), 16 if deep else 8, p)
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
    rgb: list[int],
    image: pyvips.Image,
    profile: str | None,
    p: ExportProfile | None = None,
) -> list[float]:
    """Converts an sRGB color into the color space and value range of image."""
    if profile is None and image.get_typeof(ICC_PROFILE) != 0:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "embedded.icc"
            path.write_bytes(image.get(ICC_PROFILE))
            return match_color(rgb, image, str(path), p)

    if profile is None and image.interpretation == "cmyk":
        profile = BUILTIN_PROFILES[ColorSpace.CMYK]

    pixel = (pyvips.Image.black(1, 1) + rgb).cast("uchar").copy(interpretation="srgb")
    if profile is not None:
        options = conversion(p) if p else {}
        values = pixel.icc_transform(
            profile, input_profile="srgb", depth=16, **options
        ).getpoint(0, 0)
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
    color = match_color(parse_color(p.background_color), image, profile, p)

    if p.bit_depth_enabled and not p.keep_alpha:
        image = drop_alpha(image, color)

    return Document(image, color, merge=p.background_op == BackgroundOp.MERGE)


def load_coverage(
    path: Path, image: pyvips.Image, kind: str, dark: bool
) -> pyvips.Image:
    """How much of each pixel of `image` a `kind` file covers (0..1).

    The file's alpha channel if it has one, otherwise its brightness, or its
    darkness with `dark`. Stretched to the size of `image`.
    """
    file = pyvips.Image.new_from_file(str(path)).autorot()
    paths.check_aspect(image, file, kind)
    if file.hasalpha():
        coverage = file.extract_band(file.bands - 1)
    else:
        if file.bands > 1:
            file = file.colourspace("grey16" if is_deep(file) else "b-w")
            file = file.extract_band(0)
        coverage = file.invert() if dark else file
    coverage = coverage.cast("float") / format_max(coverage)
    coverage = coverage.resize(
        image.width / coverage.width, vscale=image.height / coverage.height
    )
    # resizing can land a pixel off and overshoot on hard edges
    coverage = coverage.embed(0, 0, image.width, image.height, extend="copy")
    return coverage.clamp(min=0, max=1)


def load_shadow(path: Path, image: pyvips.Image) -> pyvips.Image:
    """How much shadow falls on each pixel of `image` (0..1): black is full shadow."""
    return load_coverage(path, image, "shadow", dark=True)


def k_lightness_lut(
    ink: pyvips.Image, profile: str | None, maximum: float
) -> pyvips.Image:
    """Maps L* (in LUT_STEPS per 100) to the K-only ink, 0..`maximum`, as light.

    Measures a K ramp through the same CMYK profile as `ink`.
    """
    ink_max = format_max(ink)
    dtype = np.uint8 if ink.format == "uchar" else np.uint16
    ramp_k = np.round(np.linspace(0, ink_max, K_RAMP_STEPS)).astype(dtype)
    ramp = np.zeros((1, K_RAMP_STEPS, 4), dtype)
    ramp[..., 3] = ramp_k
    ramp_image = pyvips.Image.new_from_array(ramp, interpretation="cmyk").copy()
    if ink.get_typeof(ICC_PROFILE) != 0:
        ramp_image.set_type(pyvips.GValue.blob_type, ICC_PROFILE, ink.get(ICC_PROFILE))

    lightness = cmyk_lightness(ramp_image, profile).numpy().ravel()
    # more ink is never lighter, and np.interp wants rising lightness
    lightness = np.minimum.accumulate(lightness)[::-1]
    k = (ramp_k.astype(np.float64) / ink_max * maximum)[::-1]
    axis = np.arange(LUT_STEPS + 1) * (100 / LUT_STEPS)
    return pyvips.Image.new_from_array(np.interp(axis, lightness, k).reshape(1, -1))


def cmyk_lightness(image: pyvips.Image, profile: str | None) -> pyvips.Image:
    """L* of CMYK `image`, through its embedded profile, `profile` or the builtin."""
    fallback = profile or BUILTIN_PROFILES[ColorSpace.CMYK]
    return image.icc_import(input_profile=fallback, embedded=True).extract_band(0)


def grade_k(
    image: pyvips.Image, weight: pyvips.Image, profile: str | None
) -> pyvips.Image:
    """Moves CMYK `image` onto black ink alone where `weight` (0..1) is 1.

    The K-only ink is as light as the original pixel under its CMYK profile, so
    the graded area keeps its tone and loses its color.
    """
    if image.interpretation != "cmyk":
        raise ExportError("grading to black ink needs a CMYK image")

    fmt = image.format
    maximum = format_max(image)
    bands = color_bands(image)
    pixels = image.extract_band(0, n=bands)
    ink = pixels  # the profile works on 8 or 16-bit ink
    if fmt not in ("uchar", "ushort"):
        ink = cast_rounded(pixels * (65535.0 / maximum), "ushort")

    lut = k_lightness_lut(ink, profile, maximum)
    index = (cmyk_lightness(ink, profile) * (LUT_STEPS / 100) + 0.5).clamp(
        min=0, max=LUT_STEPS
    )
    k_only = index.cast("ushort").maplut(lut)

    keep = 1 - weight
    result = (pixels.extract_band(0, n=3) * keep).bandjoin(
        pixels.extract_band(3) * keep + k_only * weight
    )
    if image.hasalpha():
        result = result.bandjoin(image.extract_band(bands))
    return cast_rounded(result, fmt).copy(interpretation=image.interpretation)


def shadow_stage(
    doc: Document,
    p: ExportProfile,
    shadow: Path | None,
    profile: str | None,
    mask: Path | None,
) -> None:
    if p.shadow_grade_k and mask is not None:
        # everything outside the mask's shape goes onto the K plate
        inside = load_coverage(mask, doc.image, "mask", dark=False)
        doc.image = grade_k(doc.image, 1 - inside, profile)
    if shadow is None:
        return  # only grading

    coverage = load_shadow(shadow, doc.image)
    if p.shadow_k_only and doc.image.interpretation == "cmyk":
        # pure black ink, no CMY, instead of the profile's rich black
        color = [0.0, 0.0, 0.0, format_max(doc.image)]
    else:
        color = match_color([0, 0, 0], doc.image, profile, p)
    opacity = p.shadow_opacity / 100
    if p.shadow_op == ShadowOp.MERGE:
        # the shadow becomes part of the image layer, above any background
        doc.image = composite_shadow(doc.image, coverage * opacity, color, None)
        return
    doc.shadow, doc.shadow_color, doc.shadow_opacity = coverage, color, opacity


def composite_shadow(
    image: pyvips.Image,
    shadow: pyvips.Image,
    color: list[float],
    background: list[float] | None,
) -> pyvips.Image:
    """`image` over a `color` shadow (coverage 0..1), over `background` if given.

    Matches the black Shadow layer in Normal mode, at the shadow's opacity.
    """
    if not image.hasalpha():
        return image  # the shadow is underneath, hidden

    fmt = image.format
    maximum = format_max(image)
    bands = color_bands(image)
    pixels = image.extract_band(0, n=bands).cast("float")
    alpha = image.extract_band(bands).cast("float") / maximum

    if background is not None:
        base = (1 - shadow) * background + shadow * color
        result = pixels * alpha + base * (1 - alpha)
    else:
        below = shadow * (1 - alpha)
        coverage = alpha + below
        result = (pixels * alpha + below * color) / (coverage == 0).ifthenelse(
            1, coverage
        )
        result = result.bandjoin(coverage * maximum)
    return cast_rounded(result, fmt).copy(interpretation=image.interpretation)


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
    progress: Callable[[float], None] = lambda _: None,
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

    plist = paths.trace_image(
        mask_image, trace_settings(p), progress=progress, cancelled=cancelled
    )
    return plist, (mask_image.width, mask_image.height)


def process(
    source: Path,
    p: ExportProfile,
    mask: Path | None = None,
    cancelled: Callable[[], bool] = lambda: False,
    shadow: Path | None = None,
) -> Document:
    if p.shadow_enabled and not p.shadow_grade_k and shadow is None:
        raise ExportError("no shadow file found for this image")
    if p.shadow_enabled and p.shadow_grade_k and mask is None:
        raise ExportError("no mask file found for this image")
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
    if p.shadow_enabled:
        shadow_stage(doc, p, shadow, profile, mask)

    if traced:
        plist, size = traced
        doc.image = paths.embed_path(
            doc.image,
            plist,
            name=p.path_name.strip(),
            size=size,
            offset=p.path_offset,
            clipping=p.path_clipping,
        )
        doc.path, doc.path_size = plist, size
    return doc


def photoshop_depth(doc: Document) -> Document:
    if doc.image.format in ("uchar", "ushort"):
        return doc

    scale = DEPTH_MAX[BitDepth.BPC_16] / format_max(doc.image)

    def rescale(color: list[float] | None) -> list[float] | None:
        return None if color is None else [float(round(v * scale)) for v in color]

    return replace(
        doc,
        image=to_depth(doc.image, BitDepth.BPC_16),
        background=rescale(doc.background),
        shadow_color=rescale(doc.shadow_color),
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
            layered = doc.layered()
            if layered and image.format not in ("uchar", "ushort"):
                raise ExportError("Photoshop layers need 8 or 16-bit images")
            image.tiffsave(str(path), compression=TIFF_COMPRESSION[p.tiff_compression])
            if layered:
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
    shadow: Path | None = None,
) -> None:
    try:
        doc = process(result.source, p, mask, cancelled, shadow)
        if len(p.formats) > 1:
            doc.image = doc.image.copy_memory()
            if doc.shadow is not None:
                doc.shadow = doc.shadow.copy_memory()
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
    shadows: Mapping[Path, Path] | None = None,
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
            shadow = shadows.get(file) if shadows else None
            export_file(profile, output_dir, result, mask, cancelled, shadow)

        if result.error:
            log.warning("failed to export %s: %s", file, result.error)
        else:
            log.info("exported %s", file)

        if progress and not progress(result):
            break

    return results
