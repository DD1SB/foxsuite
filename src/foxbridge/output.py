"""SPORTident sinks; shared FoxCore serial mechanics, no driver installation."""

import asyncio
import os
from pathlib import Path
from typing import BinaryIO, Protocol

from foxcore.config import SerialConfig
from foxcore.serial import SerialTransport

from .config import OutputConfig


class SportIdentOutput(Protocol):
    @property
    def connected(self) -> bool: ...

    async def connect(self) -> None: ...
    async def write(self, data: bytes) -> None: ...
    async def close(self) -> None: ...


class SerialOutput:
    def __init__(self, config: OutputConfig) -> None:
        self.transport = SerialTransport(
            SerialConfig(config.port, config.baud_rate, config.reconnect_interval_seconds)
        )

    @property
    def connected(self) -> bool:
        return self.transport.connected

    async def connect(self) -> None:
        if not self.transport.connected:
            await self.transport.connect()

    async def write(self, data: bytes) -> None:
        await self.transport.send(data)

    async def close(self) -> None:
        await self.transport.disconnect()


class FileOutput:
    """Append-only binary capture with fsync; never a claim of Fjw delivery."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.connected = False
        self._file: BinaryIO | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("ab", buffering=0)
        self.connected = True

    def _write(self, data: bytes) -> None:
        assert self._file is not None
        count = self._file.write(data)
        if count != len(data):
            raise OSError("Incomplete capture file write")
        os.fsync(self._file.fileno())

    async def write(self, data: bytes) -> None:
        if not self.connected:
            raise ConnectionError("Capture file is closed")
        task = asyncio.create_task(asyncio.to_thread(self._write, data))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
        self.connected = False


class FakeOutput:
    def __init__(self) -> None:
        self.connected = False
        self.frames: list[bytes] = []
        self.fail_connect = False
        self.fail_write = False

    async def connect(self) -> None:
        if self.fail_connect:
            raise OSError("Fake output port unavailable")
        self.connected = True

    async def write(self, data: bytes) -> None:
        if not self.connected or self.fail_write:
            raise OSError("Fake output write failed")
        self.frames.append(data)

    async def close(self) -> None:
        self.connected = False


def create_output(config: OutputConfig) -> SportIdentOutput:
    return SerialOutput(config) if config.type == "serial" else FileOutput(config.path)
