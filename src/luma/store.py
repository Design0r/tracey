import logging
import sqlite3
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


class ColorSpaceOp(Choice):
    CONVERT = 0, "Convert"
    ASSIGN = 1, "Assign"


class ImageFormat(Choice):
    JPEG = 0, "JPEG"
    PNG = 1, "PNG"
    TIFF = 2, "TIFF"


class BitDepth(Choice):
    BPC_8 = 0, "8-Bit"
    BPC_16 = 1, "16-Bit"
    BPC_32 = 2, "32-Bit Float"


class DpiOp(Choice):
    TAG_ONLY = 0, "Tag Only"
    RESAMPLE = 1, "Resample"


@dataclass
class ExportProfile:
    id: int = 0
    name: str = "New Profile"

    color_space_enabled: bool = False
    color_space: ColorSpace = ColorSpace.SRGB
    color_space_op: ColorSpaceOp = ColorSpaceOp.CONVERT
    embed: bool = True

    bit_depth_enabled: bool = False
    bit_depth: BitDepth = BitDepth.BPC_8
    keep_alpha: bool = True

    resolution_enabled: bool = False
    width: int = 2048
    height: int = 2048

    dpi_enabled: bool = False
    dpi: int = 300
    dpi_op: DpiOp = DpiOp.TAG_ONLY

    formats: list[ImageFormat] = field(default_factory=lambda: [ImageFormat.JPEG])

    def copy(self) -> "ExportProfile":
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
]

PROFILE_COLUMNS = (
    "name, "
    "color_space_enabled, color_space, color_space_op, color_space_embedd, "
    "bit_depth_enabled, bit_depth, keep_alpha, "
    "resolution_enabled, width, height, "
    "dpi_enabled, dpi, dpi_op"
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
        formats=[],
    )


class Store:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path)
        log.info("opened database")
        self.migrate()

    def close(self) -> None:
        self.conn.close()
        log.info("closed database")

    def migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version;").fetchone()[0]
        count = len(MIGRATIONS)
        if version >= count:
            log.info("database migrations up to date (%d/%d)", version, count)
            return

        for index in range(version, count):
            try:
                self.conn.executescript(MIGRATIONS[index])
            except sqlite3.Error as e:
                log.error("failed migration %d: %s", index + 1, e)
                return
            log.info("migration executed (%d/%d)", index + 1, count)

        self.conn.execute(f"PRAGMA user_version = {count};")

    def save_formats(self, p: ExportProfile) -> None:
        self.conn.execute("DELETE FROM export_format WHERE profile_id = ?;", (p.id,))
        self.conn.executemany(
            "INSERT OR IGNORE INTO export_format (profile_id, format) VALUES (?, ?);",
            [(p.id, int(fmt)) for fmt in p.formats],
        )

    def create_profile(self, p: ExportProfile) -> int:
        try:
            with self.conn:
                row = self.conn.execute(
                    f"INSERT INTO export_profile ({PROFILE_COLUMNS}) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id;",
                    profile_values(p),
                ).fetchone()
                created = replace(p, id=row[0])
                self.save_formats(created)
        except sqlite3.Error as e:
            log.error("failed to create profile: %s", e)
            return 0
        return created.id

    def update_profile(self, p: ExportProfile) -> bool:
        assignments = ", ".join(
            f"{column.strip()} = ?" for column in PROFILE_COLUMNS.split(",")
        )
        try:
            with self.conn:
                self.conn.execute(
                    f"UPDATE export_profile SET {assignments} WHERE id = ?;",
                    (*profile_values(p), p.id),
                )
                self.save_formats(p)
        except sqlite3.Error as e:
            log.error("failed to update profile %d: %s", p.id, e)
            return False
        return True

    def get_profiles(self) -> list[ExportProfile]:
        rows = self.conn.execute(
            f"SELECT id, {PROFILE_COLUMNS} FROM export_profile ORDER BY name;"
        ).fetchall()
        profiles = [profile_from_row(row) for row in rows]
        by_id = {p.id: p for p in profiles}

        for profile_id, fmt in self.conn.execute(
            "SELECT profile_id, format FROM export_format ORDER BY rowid;"
        ):
            if profile_id in by_id:
                by_id[profile_id].formats.append(ImageFormat(fmt))

        return profiles

    def delete_profile(self, p: ExportProfile) -> bool:
        try:
            with self.conn:
                self.conn.execute(
                    "DELETE FROM export_format WHERE profile_id = ?;", (p.id,)
                )
                self.conn.execute("DELETE FROM export_profile WHERE id = ?;", (p.id,))
        except sqlite3.Error as e:
            log.error("failed to delete profile %d: %s", p.id, e)
            return False
        return True
