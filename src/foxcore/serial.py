"""Bidirectional serial transport without persistence or timing policy."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

import serial

from .config import SerialConfig
from .events import ConnectionEvent
from .logging import SafeLogger

LineHandler = Callable[[bytes], Awaitable[None]]
StateHandler = Callable[[ConnectionEvent], Awaitable[None]]
log = SafeLogger(__name__)


class Transport(Protocol):
    connected: bool

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def send(self, data: bytes) -> None: ...
    async def run(self, line: LineHandler, state: StateHandler) -> None: ...


class SerialTransport:
    def __init__(self, config: SerialConfig) -> None:
        self.config = config
        self.connected = False
        self._serial: serial.Serial | None = None
        self._writes = asyncio.Lock()
        self._stop = asyncio.Event()

    async def connect(self) -> None:
        if not self.config.port:
            raise ValueError("Configure a serial port")
        # Shield the worker: cancellation must not abandon an open device handle.
        task = asyncio.create_task(
            asyncio.to_thread(
                serial.Serial, self.config.port, self.config.baud_rate, timeout=0.1, write_timeout=1
            )
        )
        try:
            self._serial = await asyncio.shield(task)
        except asyncio.CancelledError:
            device = await task
            await asyncio.to_thread(device.close)
            raise
        self.connected = True

    async def disconnect(self) -> None:
        async with self._writes:
            device, self._serial = self._serial, None
            self.connected = False
            if device is not None:
                await asyncio.to_thread(device.close)

    async def send(self, data: bytes) -> None:
        async with self._writes:
            device = self._serial
            if not self.connected or device is None:
                raise ConnectionError("Serial disconnected")
            task = asyncio.create_task(asyncio.to_thread(device.write, data))
            try:
                count = await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise
            if count != len(data):
                raise OSError("Incomplete serial write")

    async def _read(self) -> bytes:
        device = self._serial
        assert device is not None
        task = asyncio.create_task(asyncio.to_thread(device.read, max(1, device.in_waiting)))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Deliver bytes returned by the bounded read before honoring shutdown.
            self._shutdown_bytes = await task
            raise

    async def run(self, line: LineHandler, state: StateHandler) -> None:
        self._shutdown_bytes = b""
        pending = bytearray()
        try:
            while not self._stop.is_set():
                try:
                    await self.connect()
                except (OSError, serial.SerialException) as exc:
                    log.info("Serial reconnect: %s", exc)
                    await state(ConnectionEvent(False, str(exc)))
                    await asyncio.sleep(self.config.reconnect_interval_seconds)
                    continue
                await state(ConnectionEvent(True, self.config.port))
                log.info("Serial connected port=%s", self.config.port)
                try:
                    while not self._stop.is_set():
                        # Catch only transport reads, never callback/database failures.
                        try:
                            chunk = await self._read()
                        except (OSError, serial.SerialException) as exc:
                            log.info("Serial disconnected: %s", exc)
                            break
                        pending.extend(chunk)
                        while b"\n" in pending:
                            end = pending.index(10) + 1
                            raw = bytes(pending[:end])
                            del pending[:end]
                            await line(raw)
                finally:
                    await self.disconnect()
                if pending:
                    fragment = bytes(pending)
                    pending.clear()
                    await line(fragment)
                await state(ConnectionEvent(False, self.config.port))
                if not self._stop.is_set():
                    await asyncio.sleep(self.config.reconnect_interval_seconds)
        finally:
            await self.disconnect()
            pending.extend(self._shutdown_bytes)
            # On read cancellation this may contain complete lines plus a fragment.
            while pending:
                end = pending.index(10) + 1 if 10 in pending else len(pending)
                await line(bytes(pending[:end]))
                del pending[:end]
            await state(ConnectionEvent(False, "shutdown"))


class FakeTransport:
    """Deterministic developer/test transport, supports reconnect and failure injection."""

    def __init__(self) -> None:
        self.connected = False
        self.commands: list[bytes] = []
        self.input: asyncio.Queue[bytes | ConnectionEvent | None] = asyncio.Queue()
        self.fail_send = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def send(self, data: bytes) -> None:
        if not self.connected or self.fail_send:
            raise ConnectionError("Fake transport unavailable")
        self.commands.append(data)

    async def run(self, line: LineHandler, state: StateHandler) -> None:
        await self.connect()
        await state(ConnectionEvent(True, "fake"))
        try:
            while (item := await self.input.get()) is not None:
                if isinstance(item, ConnectionEvent):
                    self.connected = item.connected
                    await state(item)
                else:
                    await line(item)
        finally:
            await self.disconnect()
            await state(ConnectionEvent(False, "fake shutdown"))
