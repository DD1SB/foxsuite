"""Absolute per-user locations and atomic desktop preferences."""

import json
import os
import sys
import tempfile
import tomllib
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Literal

from foxcore.config import Config, load_config
from foxlive.config import LiveConfig, load_live_config


def user_root() -> Path:
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            raise ValueError("Windows LOCALAPPDATA is unavailable")
        return Path(local).resolve() / "FoxSuite"
    return (
        Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))).resolve()
        / "FoxSuite"
    )


@dataclass(frozen=True)
class Locations:
    root: Path

    def __post_init__(self) -> None:
        if not self.root.is_absolute():
            raise ValueError("FoxSuite user directory must be absolute")

    @property
    def settings(self) -> Path:
        return self.root / "config/settings.toml"

    @property
    def database(self) -> Path:
        return self.root / "data/foxsuite.db"

    @property
    def backups(self) -> Path:
        return self.root / "backups"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def create(self) -> None:
        for directory in (self.settings.parent, self.database.parent, self.backups, self.logs):
            directory.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Device:
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None
    description: str = ""
    manufacturer: str | None = None
    product: str | None = None


@dataclass(frozen=True)
class Settings:
    core: Config
    live: LiveConfig = field(default_factory=LiveConfig)
    completed: bool = False
    language: Literal["en", "de"] = "en"
    device: Device = field(default_factory=Device)
    override: bool = False

    def __post_init__(self) -> None:
        if type(self.completed) is not bool or type(self.override) is not bool:
            raise ValueError("Desktop completed/override flags must be booleans")
        if not self.core.database_path.is_absolute():
            raise ValueError("Desktop database path must be absolute")
        if self.completed and not self.core.serial.port:
            raise ValueError("Select a FoxIdentServer port before finishing setup")
        if self.live.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Desktop operations must bind localhost; use the advanced CLI for LAN")
        if self.language not in {"en", "de"}:
            raise ValueError("Choose English or Deutsch")


def load(locations: Locations, override: Path | None = None) -> Settings:
    settings = Settings(Config(database_path=locations.database))
    if locations.settings.exists():
        with locations.settings.open("rb") as stream:
            saved = tomllib.load(stream)
        desk = saved.get("desktop", {})
        settings = Settings(
            load_config(locations.settings),
            load_live_config(locations.settings),
            desk.get("completed", False),
            desk.get("language", "en"),
            Device(**saved.get("device", {})),
        )
    if override is not None:
        settings = replace(
            settings,
            core=load_config(override),
            live=load_live_config(override),
            completed=True,
            override=True,
        )
    return settings


def encode(settings: Settings) -> bytes:
    sections = {
        "desktop": {"completed": settings.completed, "language": settings.language},
        "serial": asdict(settings.core.serial),
        "database": {"path": str(settings.core.database_path)},
        "time_sync": asdict(settings.core.time_sync),
        "logging": {"level": settings.core.logging_level},
        "validation": {"minimum_unix_timestamp": settings.core.minimum_unix_timestamp},
        "live": asdict(settings.live),
        "device": asdict(settings.device),
    }
    # JSON string escaping is a valid subset of TOML basic-string escaping for these values.
    return "\n".join(
        f"[{section}]\n"
        + "\n".join(
            f"{key} = {json.dumps(value, ensure_ascii=False)}"
            for key, value in values.items()
            if value is not None
        )
        + "\n"
        for section, values in sections.items()
    ).encode("utf-8")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".foxsuite-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save(locations: Locations, settings: Settings) -> None:
    if settings.override:
        raise ValueError("Explicit configuration is read-only in desktop settings")
    atomic_write(locations.settings, encode(settings))


def update(
    settings: Settings,
    *,
    port: str,
    language: Literal["en", "de"],
    http_port: int,
    baud_rate: int,
    time_sync: bool,
    time_sync_interval: float,
    reconnect_interval: float,
    logging_level: str,
    device: Device,
) -> Settings:
    return replace(
        settings,
        completed=True,
        language=language,
        device=device,
        core=replace(
            settings.core,
            serial=replace(
                settings.core.serial,
                port=port.strip(),
                baud_rate=baud_rate,
                reconnect_interval_seconds=reconnect_interval,
            ),
            time_sync=replace(
                settings.core.time_sync, enabled=time_sync, interval_seconds=time_sync_interval
            ),
            logging_level=logging_level,
        ),
        live=replace(settings.live, port=http_port),
    )
