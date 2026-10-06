"""FoxBridge policy/configuration; source serial/TimeSync remain FoxCore settings."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from foxcore.config import positive_interval

from .sportident import bounded_integer


@dataclass(frozen=True)
class OutputConfig:
    type: str = "serial"
    port: str = ""
    baud_rate: int = 38400
    reconnect_interval_seconds: float = 2.0
    path: Path = Path("data/bridge-capture.bin")

    def __post_init__(self) -> None:
        if self.type not in {"serial", "file"}:
            raise ValueError("Bridge output type must be serial or file")
        if not isinstance(self.port, str):
            raise ValueError("Bridge output port must be text")
        bounded_integer(self.baud_rate, 1, 4000000, "Output baud rate")
        positive_interval(self.reconnect_interval_seconds, "Output reconnect")

    @property
    def endpoint(self) -> str:
        return f"serial:{self.port}" if self.type == "serial" else f"file:{self.path.resolve()}"


@dataclass(frozen=True)
class SportIdentConfig:
    timezone: str = "UTC"
    week_counter: int = 0
    minimum_unix_timestamp: int = 1577836800
    maximum_receive_skew_seconds: float = 86400.0

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise ValueError(f"Unknown event timezone {self.timezone!r}; install tzdata") from exc
        bounded_integer(self.week_counter, 0, 3, "Week counter")
        bounded_integer(self.minimum_unix_timestamp, 1, 4294967295, "Minimum timestamp")
        positive_interval(self.maximum_receive_skew_seconds, "Maximum timestamp skew")


@dataclass(frozen=True)
class BridgeConfig:
    enabled: bool = False
    target: str = "fjww"
    queue_capacity: int = 1024
    output: OutputConfig = field(default_factory=OutputConfig)
    sportident: SportIdentConfig = field(default_factory=SportIdentConfig)

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("Bridge enabled must be a boolean")
        if not isinstance(self.target, str) or not self.target.strip():
            raise ValueError("Bridge target must be a nonempty stable name")
        bounded_integer(self.queue_capacity, 1, 100000, "Bridge queue capacity")


def load_bridge_config(path: Path | None) -> BridgeConfig:
    if path is None:
        return BridgeConfig()
    with path.open("rb") as stream:
        section = tomllib.load(stream).get("bridge", {})
    output = dict(section.get("output", {}))
    if "path" in output:
        capture = Path(output["path"])
        output["path"] = capture if capture.is_absolute() else path.resolve().parent / capture
    if section.get("mapping", {}).get("auto_allocate_si_numbers", False) is not False:
        raise ValueError("Automatic SI allocation is unsupported; provide explicit UID mappings")
    return BridgeConfig(
        enabled=section.get("enabled", False),
        target=section.get("target", "fjww"),
        queue_capacity=section.get("queue_capacity", 1024),
        output=OutputConfig(**output),
        sportident=SportIdentConfig(**section.get("sportident", {})),
    )
