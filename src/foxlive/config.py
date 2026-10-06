"""Local-only web configuration; core serial and DB configuration remain separate."""

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LiveConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    open_browser: bool = True
    operator: str = "local operator"

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host.strip():
            raise ValueError("Live host must be nonempty text")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("Live port must be in 1..65535")
        if type(self.open_browser) is not bool or not isinstance(self.operator, str):
            raise ValueError("Invalid browser/operator configuration")


def load_live_config(path: Path | None) -> LiveConfig:
    if path is None:
        return LiveConfig()
    with path.open("rb") as stream:
        return LiveConfig(**tomllib.load(stream).get("live", {}))
