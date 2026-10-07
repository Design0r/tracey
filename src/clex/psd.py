import struct
import sys
import zlib
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import pyvips

SIGNATURE = b"8BIM"
TIFF_LAYER_HEADER = b"Adobe Photoshop Document Data Block\0"
TIFF_LAYER_TAG = 37724
TIFF_UNDEFINED = 7
MAX_PSD_SIZE = 30000
MM_PER_INCH = 25.4
UNTAGGED_DPI = 72.0

BLEND_RANGES = b"\x00\x00\xff\xff" * 10
FLAG_PROTECT_TRANSPARENCY = 0x01
FLAG_PS5 = 0x08
COMPRESSION_RAW = 0
COMPRESSION_ZIP = 2

RESOURCE_RESOLUTION = 1005
RESOURCE_ICC = 1039
ICC_PROFILE = "icc-profile-data"
PHOTOSHOP_DATA = "photoshop-data"
JPEG_PHOTOSHOP = b"Photoshop 3.0\0"
JPEG_SEGMENT_MAX = 65533  # payload of a JPEG segment, after its length field

DEPTHS = {"uchar": 8, "ushort": 16}
MODE_GRAYSCALE = 1
MODE_RGB = 3
MODE_CMYK = 4


class PsdError(Exception):
    pass


@dataclass
class Layer:
    name: str
    image: pyvips.Image
    background: bool = False
    opacity: int = 255


class Encoder:
    def __init__(self, little_endian: bool):
        self.little_endian = little_endian
        self.order = "<" if little_endian else ">"

    def pack(self, fmt: str, *values: int) -> bytes:
        return struct.pack(self.order + fmt, *values)

    def key(self, key: bytes) -> bytes:
        return key[::-1] if self.little_endian else key


def pad(data: bytes, multiple: int) -> bytes:
    return data + b"\0" * (-len(data) % multiple)


def color_bands(image: pyvips.Image) -> int:
    return image.bands - (1 if image.hasalpha() else 0)


def depth(image: pyvips.Image) -> int:
    if image.format not in DEPTHS:
        raise PsdError("Photoshop layers need 8 or 16-bit images")
    return DEPTHS[image.format]


def mode(image: pyvips.Image) -> int:
    match color_bands(image):
        case 1:
            return MODE_GRAYSCALE
        case 3 if image.interpretation != "cmyk":
            return MODE_RGB
        case 4 if image.interpretation == "cmyk":
            return MODE_CMYK
    raise PsdError(f"Photoshop export does not support {image.interpretation} images")


def plane(image: pyvips.Image, band: int, invert: bool, encoder: Encoder) -> bytes:
    channel = image.extract_band(band)
    if invert:
        maximum = 255 if image.format == "uchar" else 65535
        channel = channel.linear(-1, maximum).cast(image.format)

    data = channel.write_to_memory()
    # samples stay big-endian even inside little-endian TIFF layer data
    if image.format == "ushort" and sys.byteorder == "little":
        samples = array("H")
        samples.frombytes(data)
        samples.byteswap()
        data = samples.tobytes()
    return data


def channels(image: pyvips.Image, encoder: Encoder) -> list[tuple[int, bytes]]:
    cmyk = mode(image) == MODE_CMYK
    bands = color_bands(image)
    result = []
    if image.hasalpha():
        result.append((-1, plane(image, bands, False, encoder)))
    for band in range(bands):
        result.append((band, plane(image, band, cmyk, encoder)))
    return result


def pascal_name(name: str) -> bytes:
    encoded = name.encode("latin-1", "replace")[:255]
    return pad(bytes([len(encoded)]) + encoded, 4)


def layer_info(layers: list[Layer], transparent: bool, encoder: Encoder) -> bytes:
    records = []
    data = []

    for layer in layers:
        image = layer.image
        encoded = [
            (channel_id, encoder.pack("H", COMPRESSION_ZIP) + zlib.compress(raw, 6))
            for channel_id, raw in channels(image, encoder)
        ]
        flags = FLAG_PS5 | (FLAG_PROTECT_TRANSPARENCY if layer.background else 0)
        extra = (
            encoder.pack("I", 0)
            + encoder.pack("I", len(BLEND_RANGES))
            + BLEND_RANGES
            + pascal_name(layer.name)
        )

        records.append(
            encoder.pack("iiii", 0, 0, image.height, image.width)
            + encoder.pack("H", len(encoded))
            + b"".join(encoder.pack("hI", cid, len(chunk)) for cid, chunk in encoded)
            + encoder.key(SIGNATURE)
            + encoder.key(b"norm")
            + bytes([layer.opacity, 0, flags, 0])
            + encoder.pack("I", len(extra))
            + extra
        )
        data.extend(chunk for _, chunk in encoded)

    count = -len(layers) if transparent else len(layers)
    return encoder.pack("h", count) + b"".join(records) + b"".join(data)


def tagged_block(key: bytes, data: bytes, encoder: Encoder) -> bytes:
    return (
        encoder.key(SIGNATURE)
        + encoder.key(key)
        + encoder.pack("I", len(data))
        + pad(data, 4)
    )


def layer_key(bits: int) -> bytes:
    return b"Layr" if bits == 8 else b"Lr16"


def image_resource(resource_id: int, data: bytes) -> bytes:
    return (
        SIGNATURE
        + struct.pack(">H", resource_id)
        + b"\0\0"
        + struct.pack(">I", len(data))
        + pad(data, 2)
    )


def fixed_dpi(pixels_per_mm: float) -> int:
    dpi = pixels_per_mm * MM_PER_INCH if pixels_per_mm > 1.0 else UNTAGGED_DPI
    return round(dpi * 65536)


def resources(image: pyvips.Image) -> bytes:
    resolution = struct.pack(
        ">IHHIHH", fixed_dpi(image.xres), 1, 1, fixed_dpi(image.yres), 1, 1
    )
    blocks = [image_resource(RESOURCE_RESOLUTION, resolution)]
    if image.get_typeof(ICC_PROFILE) != 0:
        blocks.append(image_resource(RESOURCE_ICC, image.get(ICC_PROFILE)))
    if image.get_typeof(PHOTOSHOP_DATA) != 0:
        blocks.append(bytes(image.get(PHOTOSHOP_DATA)))  # saved and clipping paths
    return b"".join(blocks)


def embed_jpeg_resources(path: Path, data: bytes) -> None:
    """Adds Photoshop resources (paths) to a JPEG as APP13 segments, like Photoshop."""
    jpeg = path.read_bytes()
    if jpeg[:2] != b"\xff\xd8":
        raise PsdError("not a JPEG file")

    # after SOI and the APPn segments (JFIF, Exif, XMP, ICC) that libvips wrote
    position = 2
    while jpeg[position] == 0xFF and 0xE0 <= jpeg[position + 1] <= 0xEF:
        (length,) = struct.unpack(">H", jpeg[position + 2 : position + 4])
        position += 2 + length

    chunk = JPEG_SEGMENT_MAX - len(JPEG_PHOTOSHOP)
    segments = b"".join(
        b"\xff\xed"
        + struct.pack(">H", 2 + len(JPEG_PHOTOSHOP) + len(part))
        + JPEG_PHOTOSHOP
        + part
        for part in (data[i : i + chunk] for i in range(0, len(data), chunk))
    )
    path.write_bytes(jpeg[:position] + segments + jpeg[position:])


def write_section(file: BinaryIO, data: bytes) -> None:
    file.write(struct.pack(">I", len(data)))
    file.write(data)


def matte_white(image: pyvips.Image) -> pyvips.Image:
    # Photoshop stores the color of a transparent composite blended with white.
    if not image.hasalpha():
        return image

    maximum = 255 if image.format == "uchar" else 65535
    bands = color_bands(image)
    white = 0 if image.interpretation == "cmyk" else maximum
    color = image.flatten(background=[white] * bands, max_alpha=maximum)
    return color.cast(image.format).bandjoin(image.extract_band(bands))


def save_psd(path: Path, composite: pyvips.Image, layers: list[Layer]) -> None:
    if composite.width > MAX_PSD_SIZE or composite.height > MAX_PSD_SIZE:
        raise PsdError(f"PSD is limited to {MAX_PSD_SIZE} pixels per side")

    bits = depth(composite)
    color_mode = mode(composite)
    encoder = Encoder(little_endian=False)

    layer_section = b""
    if layers:
        info = layer_info(layers, composite.hasalpha(), encoder)
        if bits == 8:
            layer_section = encoder.pack("I", len(pad(info, 4))) + pad(info, 4)
            layer_section += encoder.pack("I", 0)
        else:
            layer_section = encoder.pack("II", 0, 0)
            layer_section += tagged_block(layer_key(bits), info, encoder)

    with path.open("wb") as file:
        file.write(b"8BPS" + struct.pack(">H", 1) + b"\0" * 6)
        file.write(
            struct.pack(
                ">HIIHH",
                composite.bands,
                composite.height,
                composite.width,
                bits,
                color_mode,
            )
        )
        write_section(file, b"")
        write_section(file, resources(composite))
        write_section(file, layer_section)

        file.write(struct.pack(">H", COMPRESSION_RAW))
        merged = matte_white(composite)
        cmyk = color_mode == MODE_CMYK
        for band in range(merged.bands):
            invert = cmyk and band < color_bands(merged)
            file.write(plane(merged, band, invert, encoder))


def tiff_layer_data(layers: list[Layer], little_endian: bool) -> bytes:
    encoder = Encoder(little_endian)
    bits = depth(layers[0].image)
    info = layer_info(layers, False, encoder)
    return TIFF_LAYER_HEADER + tagged_block(layer_key(bits), info, encoder)


def embed_tiff_layers(path: Path, layers: list[Layer]) -> None:
    with path.open("r+b") as file:
        header = file.read(8)
        if header[:2] == b"II":
            order = "<"
        elif header[:2] == b"MM":
            order = ">"
        else:
            raise PsdError("not a TIFF file")

        magic, ifd_offset = struct.unpack(order + "HI", header[2:8])
        if magic != 42:
            raise PsdError("Photoshop layers cannot be added to a BigTIFF")

        file.seek(ifd_offset)
        (count,) = struct.unpack(order + "H", file.read(2))
        entries = [file.read(12) for _ in range(count)]
        next_ifd = file.read(4)
        entries = [
            e for e in entries if struct.unpack(order + "H", e[:2])[0] != TIFF_LAYER_TAG
        ]

        data = tiff_layer_data(layers, order == "<")

        file.seek(0, 2)
        file.write(b"\0" * (file.tell() % 2))
        data_offset = file.tell()
        file.write(data)
        file.write(b"\0" * (file.tell() % 2))
        new_ifd_offset = file.tell()
        if new_ifd_offset + 6 + 12 * (len(entries) + 1) > 0xFFFFFFFF:
            raise PsdError("TIFF is too large for Photoshop layers")

        entries.append(
            struct.pack(
                order + "HHII", TIFF_LAYER_TAG, TIFF_UNDEFINED, len(data), data_offset
            )
        )
        entries.sort(key=lambda e: struct.unpack(order + "H", e[:2])[0])
        file.write(struct.pack(order + "H", len(entries)))
        file.write(b"".join(entries))
        file.write(next_ifd)

        file.seek(4)
        file.write(struct.pack(order + "I", new_ifd_offset))
