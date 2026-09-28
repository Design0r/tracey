import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pyvips

from luma.store import (
    BitDepth,
    ColorSpace,
    ColorSpaceOp,
    DpiOp,
    ExportProfile,
    ImageFormat,
)

log = logging.getLogger(__name__)

MM_PER_INCH = 25.4
UNTAGGED_DPI = 72.0
JPEG_QUALITY = 92
ICC_PROFILE = "icc-profile-data"

PROFILES = {ColorSpace.SRGB: "srgb", ColorSpace.CMYK: "cmyk"}
DEPTH_FORMATS = {BitDepth.BPC_8: "uchar", BitDepth.BPC_16: "ushort", BitDepth.BPC_32: "float"}
DEPTH_MAX = {BitDepth.BPC_8: 255.0, BitDepth.BPC_16: 65535.0, BitDepth.BPC_32: 1.0}
EXTENSIONS = {ImageFormat.JPEG: ".jpg", ImageFormat.PNG: ".png", ImageFormat.TIFF: ".tif"}


class ExportError(Exception):
    pass


@dataclass
class ExportResult:
    source: Path
    outputs: list[Path] = field(default_factory=list)
    error: str = ""


Progress = Callable[[ExportResult], bool]


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
    image = image.linear(DEPTH_MAX[depth] / format_max(image), offset).cast(DEPTH_FORMATS[depth])
    return image.copy(interpretation=depth_interpretation(image, depth))


def drop_alpha(image: pyvips.Image) -> pyvips.Image:
    if not image.hasalpha():
        return image

    fmt = image.format
    maximum = format_max(image)
    white = 0.0 if image.interpretation == "cmyk" else maximum
    return image.flatten(background=[white], max_alpha=maximum).cast(fmt)


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


def assign_profile(image: pyvips.Image, space: ColorSpace) -> pyvips.Image:
    expected = 4 if space == ColorSpace.CMYK else 3
    bands = color_bands(image)
    if bands != expected:
        raise ExportError(f"cannot assign a {space.label} profile to an image with {bands} color channels")

    profile = pyvips.Operation.call("profile_load", PROFILES[space])

    if space == ColorSpace.CMYK:
        interpretation = "cmyk"
    elif is_deep(image):
        interpretation = "rgb16"
    else:
        interpretation = "srgb"

    image = image.copy(interpretation=interpretation)
    image.set_type(pyvips.GValue.blob_type, ICC_PROFILE, profile)
    return image


def color_stage(image: pyvips.Image, p: ExportProfile) -> pyvips.Image:
    if p.color_space_op == ColorSpaceOp.CONVERT:
        deep = is_deep(image)

        if color_bands(image) < 3 and image.get_typeof(ICC_PROFILE) == 0:
            image = image.colourspace("rgb16" if deep else "srgb")

        image = image.icc_transform(PROFILES[p.color_space], embedded=True, depth=16 if deep else 8)
    else:
        image = assign_profile(image, p.color_space)

    if not p.embed:
        image = image.copy()
        image.remove(ICC_PROFILE)

    return image


def bit_depth_stage(image: pyvips.Image, p: ExportProfile) -> pyvips.Image:
    if not p.keep_alpha:
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
        image = resize(image, p.dpi / source_dpi(image.xres), p.dpi / source_dpi(image.yres))

    pixels_per_mm = p.dpi / MM_PER_INCH
    return image.copy(xres=pixels_per_mm, yres=pixels_per_mm)


def process(source: Path, p: ExportProfile) -> pyvips.Image:
    image = pyvips.Image.new_from_file(str(source)).autorot()

    if p.color_space_enabled:
        image = color_stage(image, p)
    if p.bit_depth_enabled:
        image = bit_depth_stage(image, p)
    if p.resolution_enabled:
        image = resolution_stage(image, p)
    if p.dpi_enabled:
        image = dpi_stage(image, p)

    return image


def save(image: pyvips.Image, fmt: ImageFormat, path: Path) -> None:
    match fmt:
        case ImageFormat.JPEG:
            to_depth(drop_alpha(image), BitDepth.BPC_8).jpegsave(str(path), Q=JPEG_QUALITY)

        case ImageFormat.PNG:
            if image.interpretation == "cmyk":
                raise ExportError("PNG cannot store CMYK")
            if image.format not in ("uchar", "ushort"):
                image = to_depth(image, BitDepth.BPC_16)
            image.pngsave(str(path))

        case ImageFormat.TIFF:
            image.tiffsave(str(path), compression="lzw")


def same_file(a: Path, b: Path) -> bool:
    try:
        return b.exists() and a.samefile(b)
    except OSError:
        return False


def export_file(p: ExportProfile, output_dir: Path, result: ExportResult) -> None:
    try:
        image = process(result.source, p)
        if len(p.formats) > 1:
            image = image.copy_memory()
    except (pyvips.Error, ExportError) as e:
        result.error = error_message(e)
        return

    for fmt in p.formats:
        out = output_dir / (result.source.stem + EXTENSIONS[fmt])

        if same_file(result.source, out):
            result.error = f"{fmt.label} would overwrite the source file"
            return

        try:
            save(image, fmt, out)
        except (pyvips.Error, ExportError) as e:
            result.error = f"{fmt.label}: {error_message(e)}"
            return

        result.outputs.append(out)


def execute_profile(
    files: Sequence[Path],
    profile: ExportProfile,
    output_dir: Path,
    progress: Progress | None = None,
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
            export_file(profile, output_dir, result)

        if result.error:
            log.warning("failed to export %s: %s", file, result.error)
        else:
            log.info("exported %s", file)

        if progress and not progress(result):
            break

    return results
