import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from tracey import APP_NAME

CONFIG_FILENAME = "config.json"
DATABASE_FILENAME = "tracey.db"

log = logging.getLogger(__name__)


def config_dir() -> Path:
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = (
            Path(local_app_data)
            if local_app_data
            else Path.home() / "AppData" / "Local"
        )
        return base / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def config_path() -> Path:
    return config_dir() / CONFIG_FILENAME


def user_database_path() -> Path:
    return config_dir() / DATABASE_FILENAME


def default_database_path() -> Path:
    cwd = Path.cwd()
    if os.access(cwd, os.W_OK):
        return cwd / DATABASE_FILENAME
    return user_database_path()


@dataclass
class Config:
    database: Path | None = None

    def database_path(self) -> Path:
        return self.database or default_database_path()


def load_config() -> Config:
    path = config_path()
    if not path.exists():
        return Config()

    try:
        data: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        log.exception("failed to read config %s, using defaults", path)
        return Config()

    config = Config()
    database = data.get("database")
    if isinstance(database, str) and database.strip():
        config.database = Path(database.strip()).expanduser()
    return config


def save_config(config: Config) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"database": str(config.database) if config.database else None}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    log.info("saved config to %s", path)
