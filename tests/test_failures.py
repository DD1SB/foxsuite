import asyncio
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from foxcore.config import SerialConfig, TimeSyncConfig
from foxcore.events import ConnectionEvent
from foxcore.persistence import MIGRATIONS, Store
from foxcore.serial import FakeTransport, SerialTransport
from foxcore.service import IngestService
from foxcore.simulator import messages
from foxcore.timesync import TimeSyncService


def test_logging_failure_isolated(tmp_path: Path) -> None:
    class BrokenHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            raise RuntimeError("logging failure")

    logger = logging.getLogger("foxcore.service")
    handler = BrokenHandler()
    logger.addHandler(handler)
    store = Store(tmp_path / "logging.db")
    try:
        service = IngestService(store)
        service.ingest(messages()[3], "test")
        assert service.ingest(messages()[0], "test") is not None
        assert store.stats()["raw_events"] == 2
    finally:
        logger.removeHandler(handler)
        store.close()


def test_raw_failure_explicit(tmp_path: Path) -> None:
    store = Store(tmp_path / "full.db")
    store.db.execute(
        "CREATE TRIGGER fail_raw BEFORE INSERT ON raw_events "
        "BEGIN SELECT RAISE(ABORT,'disk unavailable'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="disk unavailable"):
        IngestService(store).ingest(messages()[0], "test")
    assert store.stats()["punches"] == 0
    store.close()


def test_future_migration_rejected(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    store = Store(path)
    with store.db:
        store.db.execute("INSERT INTO schema_migrations VALUES (?)", (len(MIGRATIONS) + 1,))
    store.close()
    with pytest.raises(ValueError, match="schema version"):
        Store(path)


def test_naive_receive_time_rejected(tmp_path: Path) -> None:
    store = Store(tmp_path / "naive.db")
    with pytest.raises(ValueError, match="timezone"):
        store.insert_raw(b"data", datetime(2026, 1, 1), "test")
    store.close()


def test_time_without_on_connect_and_diagnostic_failure() -> None:
    async def check() -> None:
        transport = FakeTransport()
        await transport.connect()

        def broken(_: object) -> None:
            raise RuntimeError("diagnostics database failed")

        service = TimeSyncService(
            transport,
            TimeSyncConfig(on_connect=False, interval_seconds=0.01),
            broken,
            lambda: 1770000000,
        )
        await service.connection_changed(ConnectionEvent(True, "fake"))
        await asyncio.sleep(0)
        assert transport.commands == []
        await asyncio.sleep(0.02)
        with pytest.raises(RuntimeError, match="diagnostics database failed"):
            await service.wait_failure()
        with pytest.raises(RuntimeError):
            await service.stop()

    asyncio.run(check())


def test_serial_callback_failure_never_reconnects() -> None:
    class Device:
        in_waiting = 1

        def read(self, count: int) -> bytes:
            return b"line\n"

        def close(self) -> None:
            pass

    async def check() -> None:
        transport = SerialTransport(SerialConfig("FAKE"))
        calls = 0

        async def line(raw: bytes) -> None:
            nonlocal calls
            calls += 1
            raise OSError("database failed")

        async def state(event: ConnectionEvent) -> None:
            pass

        with patch("foxcore.serial.serial.Serial", return_value=Device()) as constructor:
            with pytest.raises(OSError, match="database failed"):
                await asyncio.wait_for(transport.run(line, state), 1)
            assert constructor.call_count == 1
        assert calls == 1 and not transport.connected

    asyncio.run(check())


def test_serial_failed_open_then_connect_and_cancel() -> None:
    class Device:
        in_waiting = 1

        def read(self, count: int) -> bytes:
            return b"fragment"

        def close(self) -> None:
            pass

    async def check() -> None:
        transport = SerialTransport(SerialConfig("FAKE", reconnect_interval_seconds=0.001))
        states: list[bool] = []
        received: list[bytes] = []
        ready = asyncio.Event()

        async def line(raw: bytes) -> None:
            received.append(raw)

        async def state(event: ConnectionEvent) -> None:
            states.append(event.connected)
            if event.connected:
                ready.set()

        with patch("foxcore.serial.serial.Serial", side_effect=[OSError("missing"), Device()]):
            task = asyncio.create_task(transport.run(line, state))
            await asyncio.wait_for(ready.wait(), 1)
            await asyncio.sleep(0.005)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert states[:2] == [False, True]
        assert not transport.connected
        assert received and received[0].startswith(b"fragment")

    asyncio.run(check())
