import logging
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from enum import IntEnum
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class Choice(IntEnum):
    label: str

    def __new__(cls, value: int, label: str):
        member = int.__new__(cls, value)
        member._value_ = value
        member.label = label
        return member


class ColorSpace(Choice):
    SRGB = 0, "sRGB"
    CMYK = 1, "CMYK"
    ECI_RGB = 2, "eciRGB v2"
    ISO_COATED = 3, "ISO Coated v2 300%"

    @property
    def is_cmyk(self) -> bool:
        return self in (ColorSpace.CMYK, ColorSpace.ISO_COATED)


class ColorSpaceOp(Choice):
    CONVERT = 0, "Convert"
    ASSIGN = 1, "Assign"


class RenderingIntent(Choice):
    PERCEPTUAL = 0, "Perceptual"
    RELATIVE = 1, "Relative Colorimetric"


class ImageFormat(Choice):
    TIFF = 0, "TIFF"
    PSD = 1, "PSD"
    JPEG = 2, "JPEG"
    PNG = 3, "PNG"


class TiffCompression(Choice):
    NONE = 0, "None"
    LZW = 1, "LZW"


class BitDepth(Choice):
    BPC_8 = 0, "8-Bit"
    BPC_16 = 1, "16-Bit"
    BPC_32 = 2, "32-Bit Float"


class DpiOp(Choice):
    TAG_ONLY = 0, "Tag Only"
    RESAMPLE = 1, "Resample"


class BackgroundOp(Choice):
    LAYER = 0, "Separate Layer"
    MERGE = 1, "Merge to Background"


class ShadowOp(Choice):
    LAYER = 0, "Separate Layer"
    MERGE = 1, "Merge into Image"


class PathSource(Choice):
    ALPHA = 0, "Alpha Channel"
    MASK_FILE = 1, "Mask File"


@dataclass
class ExportProfile:
    id: int = 0
    name: str = "New Profile"

    color_space_enabled: bool = False
    color_space: ColorSpace = ColorSpace.SRGB
    color_space_op: ColorSpaceOp = ColorSpaceOp.CONVERT
    embed: bool = True
    intent: RenderingIntent = RenderingIntent.PERCEPTUAL
    bpc: bool = True  # black point compensation

    bit_depth_enabled: bool = False
    bit_depth: BitDepth = BitDepth.BPC_8
    keep_alpha: bool = True

    resolution_enabled: bool = False
    width: int = 2048
    height: int = 2048

    dpi_enabled: bool = False
    dpi: int = 300
    dpi_op: DpiOp = DpiOp.TAG_ONLY

    background_enabled: bool = False
    background_color: str = "#ffffff"
    background_op: BackgroundOp = BackgroundOp.LAYER

    tiff_compression: TiffCompression = TiffCompression.LZW

    path_enabled: bool = False
    path_source: PathSource = PathSource.ALPHA
    path_blacklevel: int = 50
    path_smoothness: float = 0.5
    path_simplify: float = 0.2
    path_speckle_size: int = 2
    path_offset: float = 0.0
    path_invert: bool = False
    path_clipping: bool = False
    path_svg: bool = False
    path_name: str = ""

    shadow_enabled: bool = False
    shadow_opacity: int = 100
    shadow_op: ShadowOp = ShadowOp.LAYER
    shadow_k_only: bool = False
    shadow_grade_k: bool = False

    formats: list[ImageFormat] = field(default_factory=list[ImageFormat])

    def copy(self) -> ExportProfile:
        return replace(self, formats=list(self.formats))


MIGRATIONS = [
    """
    CREATE TABLE export_profile (
        id                    INTEGER PRIMARY KEY,
        name                  TEXT    NOT NULL,

        color_space_enabled   BOOLEAN NOT NULL,
        color_space           INTEGER NOT NULL,
        color_space_op        INTEGER NOT NULL,
        color_space_embedd    BOOLEAN NOT NULL,

        bit_depth_enabled     BOOLEAN NOT NULL,
        bit_depth             INTEGER NOT NULL,
        keep_alpha            BOOLEAN NOT NULL,

        resolution_enabled    BOOLEAN NOT NULL,
        width                 INTEGER NOT NULL,
        height                INTEGER NOT NULL,

        dpi_enabled           BOOLEAN NOT NULL,
        dpi                   INTEGER NOT NULL,
        dpi_op                INTEGER NOT NULL
    );

    CREATE TABLE export_format (
        profile_id  INTEGER NOT NULL REFERENCES export_profile(id) ON DELETE CASCADE,
        format      INTEGER NOT NULL,
        PRIMARY KEY (profile_id, format)
    );
    """,
    """
    ALTER TABLE export_profile ADD COLUMN background_enabled BOOLEAN NOT NULL DEFAULT 0;
    ALTER TABLE export_profile ADD COLUMN background_color   TEXT    NOT NULL DEFAULT '#ffffff';
    ALTER TABLE export_profile ADD COLUMN background_op      INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE export_profile ADD COLUMN tiff_compression   INTEGER NOT NULL DEFAULT 1;
    """,
    """
    ALTER TABLE export_profile ADD COLUMN path_blacklevel    INTEGER NOT NULL DEFAULT 50;
    ALTER TABLE export_profile ADD COLUMN path_smoothness    REAL    NOT NULL DEFAULT 0.5;
    ALTER TABLE export_profile ADD COLUMN path_simplify      REAL    NOT NULL DEFAULT 0.2;
    ALTER TABLE export_profile ADD COLUMN path_speckle_size  INTEGER NOT NULL DEFAULT 2;
    ALTER TABLE export_profile ADD COLUMN path_offset        REAL    NOT NULL DEFAULT 0;
    ALTER TABLE export_profile ADD COLUMN path_invert        BOOLEAN NOT NULL DEFAULT 0;
    ALTER TABLE export_profile ADD COLUMN path_clipping      BOOLEAN NOT NULL DEFAULT 0;
    ALTER TABLE export_profile ADD COLUMN path_svg           BOOLEAN NOT NULL DEFAULT 0;
    ALTER TABLE export_profile ADD COLUMN path_compression   INTEGER NOT NULL DEFAULT 1;
    """,
    """
    ALTER TABLE export_profile ADD COLUMN path_enabled       BOOLEAN NOT NULL DEFAULT 0;
    ALTER TABLE export_profile ADD COLUMN path_source        INTEGER NOT NULL DEFAULT 0;
    """,
    """
    ALTER TABLE export_profile ADD COLUMN path_name          TEXT    NOT NULL DEFAULT '';
    """,
    """
    ALTER TABLE export_profile ADD COLUMN shadow_enabled     BOOLEAN NOT NULL DEFAULT 0;
    ALTER TABLE export_profile ADD COLUMN shadow_opacity     INTEGER NOT NULL DEFAULT 100;
    """,
    """
    ALTER TABLE export_profile ADD COLUMN shadow_op          INTEGER NOT NULL DEFAULT 0;
    """,
    """
    ALTER TABLE export_profile ADD COLUMN shadow_k_only      BOOLEAN NOT NULL DEFAULT 0;
    """,
    """
    ALTER TABLE export_profile ADD COLUMN shadow_grade_k     BOOLEAN NOT NULL DEFAULT 0;
    """,
    """
    ALTER TABLE export_profile ADD COLUMN bpc                BOOLEAN NOT NULL DEFAULT 1;
    """,
    """
    ALTER TABLE export_profile ADD COLUMN intent             INTEGER NOT NULL DEFAULT 0;
    """,
]

PROFILE_COLUMNS = (
    "name, "
    "color_space_enabled, color_space, color_space_op, color_space_embedd, "
    "bit_depth_enabled, bit_depth, keep_alpha, "
    "resolution_enabled, width, height, "
    "dpi_enabled, dpi, dpi_op, "
    "background_enabled, background_color, background_op, "
    "tiff_compression, "
    "path_blacklevel, path_smoothness, path_simplify, path_speckle_size, "
    "path_offset, path_invert, path_clipping, path_svg, "
    "path_enabled, path_source, path_name, "
    "shadow_enabled, shadow_opacity, shadow_op, shadow_k_only, shadow_grade_k, "
    "bpc, intent"
)


def profile_values(p: ExportProfile) -> tuple[Any, ...]:
    return (
        p.name,
        int(p.color_space_enabled),
        int(p.color_space),
        int(p.color_space_op),
        int(p.embed),
        int(p.bit_depth_enabled),
        int(p.bit_depth),
        int(p.keep_alpha),
        int(p.resolution_enabled),
        p.width,
        p.height,
        int(p.dpi_enabled),
        p.dpi,
        int(p.dpi_op),
        int(p.background_enabled),
        p.background_color,
        int(p.background_op),
        int(p.tiff_compression),
        p.path_blacklevel,
        p.path_smoothness,
        p.path_simplify,
        p.path_speckle_size,
        p.path_offset,
        int(p.path_invert),
        int(p.path_clipping),
        int(p.path_svg),
        int(p.path_enabled),
        int(p.path_source),
        p.path_name,
        int(p.shadow_enabled),
        p.shadow_opacity,
        int(p.shadow_op),
        int(p.shadow_k_only),
        int(p.shadow_grade_k),
        int(p.bpc),
        int(p.intent),
    )


def profile_from_row(row: tuple[Any, ...]) -> ExportProfile:
    return ExportProfile(
        id=row[0],
        name=row[1],
        color_space_enabled=bool(row[2]),
        color_space=ColorSpace(row[3]),
        color_space_op=ColorSpaceOp(row[4]),
        embed=bool(row[5]),
        bit_depth_enabled=bool(row[6]),
        bit_depth=BitDepth(row[7]),
        keep_alpha=bool(row[8]),
        resolution_enabled=bool(row[9]),
        width=row[10],
        height=row[11],
        dpi_enabled=bool(row[12]),
        dpi=row[13],
        dpi_op=DpiOp(row[14]),
        background_enabled=bool(row[15]),
        background_color=row[16],
        background_op=BackgroundOp(row[17]),
        tiff_compression=TiffCompression(row[18]),
        path_blacklevel=row[19],
        path_smoothness=row[20],
        path_simplify=row[21],
        path_speckle_size=row[22],
        path_offset=row[23],
        path_invert=bool(row[24]),
        path_clipping=bool(row[25]),
        path_svg=bool(row[26]),
        path_enabled=bool(row[27]),
        path_source=PathSource(row[28]),
        path_name=row[29],
        shadow_enabled=bool(row[30]),
        shadow_opacity=row[31],
        shadow_op=ShadowOp(row[32]),
        shadow_k_only=bool(row[33]),
        shadow_grade_k=bool(row[34]),
        bpc=bool(row[35]),
        intent=RenderingIntent(row[36]),
        formats=[],
    )


@contextmanager
def connection(path: Path) -> Generator[sqlite3.Connection]:
    conn = sqlite3.connect(path)
    log.info("opened database")

    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise

    finally:
        conn.close()
        log.info("closed database")


class Store:
    def __init__(self, path: Path):
        self.db_path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    def migrate(self) -> None:
        with connection(self.db_path) as db:
            version = db.execute("PRAGMA user_version;").fetchone()[0]
            count = len(MIGRATIONS)
            if version >= count:
                log.info(f"database migrations up to date ({version}/{count})")
                return

            for index in range(version, count):
                script = (
                    "BEGIN;\n"
                    f"{MIGRATIONS[index]}\n"
                    f"PRAGMA user_version = {index + 1};\n"
                    "COMMIT;"
                )
                try:
                    db.executescript(script)
                except sqlite3.Error:
                    log.exception("failed migration %d/%d", index + 1, count)
                    raise
                log.info("migration executed (%d/%d)", index + 1, count)

    def save_formats(self, db: sqlite3.Connection, p: ExportProfile) -> None:
        """Runs on the caller's connection, so it commits along with the profile."""
        db.execute("DELETE FROM export_format WHERE profile_id = ?;", (p.id,))
        db.executemany(
            "INSERT OR IGNORE INTO export_format (profile_id, format) VALUES (?, ?);",
            [(p.id, int(fmt)) for fmt in p.formats],
        )

    def create_profile(self, p: ExportProfile) -> int:
        try:
            with connection(self.db_path) as db:
                row = db.execute(
                    f"INSERT INTO export_profile ({PROFILE_COLUMNS}) "
                    f"VALUES ({', '.join('?' * len(profile_values(p)))}) RETURNING id;",
                    profile_values(p),
                ).fetchone()
                created = replace(p, id=row[0])
                self.save_formats(db, created)
        except sqlite3.Error:
            log.error("failed to create profile")
            return 0

        return created.id

    def update_profile(self, p: ExportProfile) -> bool:
        assignments = ", ".join(
            f"{column.strip()} = ?" for column in PROFILE_COLUMNS.split(",")
        )
        try:
            with connection(self.db_path) as db:
                db.execute(
                    f"UPDATE export_profile SET {assignments} WHERE id = ?;",
                    (*profile_values(p), p.id),
                )
                self.save_formats(db, p)
        except sqlite3.Error:
            log.error(f"failed to update profile {p.id}")
            return False
        return True

    def get_profiles(self) -> list[ExportProfile]:
        with connection(self.db_path) as db:
            rows = db.execute(
                f"SELECT id, {PROFILE_COLUMNS} FROM export_profile ORDER BY name;"
            ).fetchall()
            profiles = [profile_from_row(row) for row in rows]
            by_id = {p.id: p for p in profiles}

            for profile_id, fmt in db.execute(
                "SELECT profile_id, format FROM export_format ORDER BY rowid;"
            ):
                if profile_id in by_id:
                    by_id[profile_id].formats.append(ImageFormat(fmt))

            return profiles

    def delete_profile(self, p: ExportProfile) -> bool:
        try:
            with connection(self.db_path) as db:
                db.execute("DELETE FROM export_format WHERE profile_id = ?;", (p.id,))
                db.execute("DELETE FROM export_profile WHERE id = ?;", (p.id,))
        except sqlite3.Error:
            log.error(f"failed to delete profile {p.id}")
            return False

        return True
