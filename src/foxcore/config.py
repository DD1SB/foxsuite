"""Typed TOML configuration; relative database paths follow the configuration file."""

import math
import string
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SerialConfig:
    port: str = ""
    baud_rate: int = 115200
    reconnect_interval_seconds: float = 2.0

    def __post_init__(self) -> None:
        if not isinstance(self.port, str) or type(self.baud_rate) is not int or self.baud_rate <= 0:
            raise ValueError("Serial port must be text and baud rate a positive integer")
        positive_interval(self.reconnect_interval_seconds, "Reconnect")


@dataclass(frozen=True)
class TimeSyncConfig:
    enabled: bool = True
    on_connect: bool = True
    interval_seconds: float = 60.0
    command_template: str = "TIME {unix}\n"

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool or type(self.on_connect) is not bool:
            raise ValueError("TimeSync enabled/on_connect must be booleans")
        if not isinstance(self.command_template, str):
            raise ValueError("Time command template must be text")
        fields = [
            name
            for _, name, _, _ in string.Formatter().parse(self.command_template)
            if name is not None
        ]
        if fields != ["unix"] or not self.command_template.endswith("\n"):
            raise ValueError("Time command must contain one {unix} and end with newline")
        self.command_template.format(unix=1).encode("ascii")
        positive_interval(self.interval_seconds, "TimeSync")


def positive_interval(value: float, name: str) -> None:
    if type(value) not in {int, float} or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} interval must be finite and positive")


@dataclass(frozen=True)
class Config:
    serial: SerialConfig = field(default_factory=SerialConfig)
    database_path: Path = Path("data/foxsuite.db")
    time_sync: TimeSyncConfig = field(default_factory=TimeSyncConfig)
    logging_level: str = "INFO"
    minimum_unix_timestamp: int | None = None

    def __post_init__(self) -> None:
        if self.logging_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("Invalid logging level")
        threshold = self.minimum_unix_timestamp
        if threshold is not None and (type(threshold) is not int or threshold < 0):
            raise ValueError("Timestamp threshold must be a nonnegative integer")


def load_config(path: Path) -> Config:
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    serial = SerialConfig(**data.get("serial", {}))
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
