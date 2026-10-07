import os
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__

from tracey import APP_NAME

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "src"
PACKAGE = SOURCE / "tracey"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
ICONS = {"win32": "tracey.ico", "darwin": "tracey.icns"}  # the executable's icon


def data(source: Path, target: str) -> str:
    return f"{source}{os.pathsep}{target}"


def main() -> None:
    shutil.rmtree(BUILD, ignore_errors=True)
    shutil.rmtree(DIST / APP_NAME, ignore_errors=True)
    (DIST / f"{APP_NAME}.exe").unlink(missing_ok=True)

    options = [
        str(PACKAGE / "__main__.py"),
        "--name",
        APP_NAME,
        "--paths",
        str(SOURCE),
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD),
        "--specpath",
        str(BUILD),
        "--add-data",
        data(PACKAGE / "icons", "tracey/icons"),
        "--add-data",
        data(PACKAGE / "profiles", "tracey/profiles"),
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--icon",
        str(PACKAGE / "icons" / ICONS.get(sys.platform, "icon.png")),
    ]

    PyInstaller.__main__.run(options)


if __name__ == "__main__":
    main()
