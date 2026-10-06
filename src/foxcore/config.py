"""Typed TOML configuration; relative database paths follow the configuration file."""

import string
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SerialConfig:
    port: str = ""
    baud_rate: int = 115200
    reconnect_interval_seconds: float = 2.0


@dataclass(frozen=True)
class TimeSyncConfig:
    enabled: bool = True
    on_connect: bool = True
    interval_seconds: float = 60.0
    command_template: str = "TIME {unix}\n"

    def __post_init__(self) -> None:
        fields = [
            name
            for _, name, _, _ in string.Formatter().parse(self.command_template)
            if name is not None
        ]
        if fields != ["unix"] or not self.command_template.endswith("\n"):
            raise ValueError("Time command must contain one {unix} and end with newline")
        self.command_template.format(unix=1).encode("ascii")
        if self.interval_seconds <= 0:
            raise ValueError("TimeSync interval must be positive")


@dataclass(frozen=True)
class Config:
    serial: SerialConfig = field(default_factory=SerialConfig)
    database_path: Path = Path("data/foxsuite.db")
    time_sync: TimeSyncConfig = field(default_factory=TimeSyncConfig)
    logging_level: str = "INFO"
    minimum_unix_timestamp: int | None = None


def load_config(path: Path) -> Config:
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    serial = SerialConfig(**data.get("serial", {}))
    if serial.baud_rate <= 0 or serial.reconnect_interval_seconds <= 0:
        raise ValueError("Serial baud/reconnect interval must be positive")
    db = Path(data.get("database", {}).get("path", "data/foxsuite.db"))
    if not db.is_absolute():
        db = path.resolve().parent / db
    level = data.get("logging", {}).get("level", "INFO").upper()
    if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ValueError("Invalid logging level")
    return Config(
        serial,
        db,
        TimeSyncConfig(**data.get("time_sync", {})),
        level,
        data.get("validation", {}).get("minimum_unix_timestamp"),
    )
