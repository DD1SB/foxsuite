import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from foxcore.config import SerialConfig, TimeSyncConfig
from foxcore.events import ConnectionEvent, TimeSyncEvent
from foxcore.persistence import Store
from foxcore.replay import replay
from foxcore.serial import FakeTransport, SerialTransport
from foxcore.service import IngestService
from foxcore.simulator import messages
from foxcore.timesync import TimeSyncService


def test_time_sync() -> None:
    async def check() -> None:
        transport = FakeTransport()
        events: list[TimeSyncEvent] = []
        service = TimeSyncService(
            transport, TimeSyncConfig(interval_seconds=0.01), events.append, lambda: 1770000000
        )
        await transport.connect()
        await service.connection_changed(ConnectionEvent(True, "fake"))
        await asyncio.sleep(0.025)
        assert transport.commands[0] == b"TIME 1770000000\n"
        assert len(transport.commands) >= 2
        transport.fail_send = True
        assert not (await service.send_now()).success
        await service.connection_changed(ConnectionEvent(False, "disconnect"))
        transport.fail_send = False
        await service.connection_changed(ConnectionEvent(True, "reconnect"))
        await asyncio.sleep(0)
        assert events[-1].success
        await service.stop()
        disabled = TimeSyncService(
            transport, TimeSyncConfig(enabled=False), events.append, lambda: 1770000001
        )
        before = len(transport.commands)
        await disabled.connection_changed(ConnectionEvent(True, "fake"))
        await asyncio.sleep(0.015)
        assert len(transport.commands) == before
        assert (await disabled.send_now()).success
        await disabled.stop()
        alternate = TimeSyncService(
            transport, TimeSyncConfig(command_template="CLOCK {unix}\n"), events.append, lambda: 1
        )
        await alternate.send_now()
        assert transport.commands[-1] == b"CLOCK 1\n"

    asyncio.run(check())


def test_fake_transport_integration(tmp_path: Path) -> None:
    async def check() -> None:
        store = Store(tmp_path / "integration.db")
        ingest = IngestService(store)
        transport = FakeTransport()
        states: list[bool] = []
        received: list[str] = []
        ingest.subscribe(lambda p: received.append(p.uid))

        async def line(raw: bytes) -> None:
            ingest.ingest(raw, "fake")

        async def state(event: ConnectionEvent) -> None:
            states.append(event.connected)

        for raw in messages():
            transport.input.put_nowait(raw)
        transport.input.put_nowait(ConnectionEvent(False, "unplug"))
        transport.input.put_nowait(ConnectionEvent(True, "replug"))
        transport.input.put_nowait(messages()[0])
        transport.input.put_nowait(None)
        await transport.run(line, state)
        assert states == [True, False, True, False]
        assert len(received) == 3
        assert store.stats()["duplicates"] == 2
        assert store.stats()["raw_events"] == 8
        store.close()

    asyncio.run(check())


def test_replay(tmp_path: Path) -> None:
    store = Store(tmp_path / "replay.db")
    ingest = IngestService(store)
    now = datetime.now(UTC)
    ingest.ingest(messages()[3], "base", now + timedelta(seconds=2))
    ingest.ingest(messages()[0], "base", now)
    ingest.ingest(messages()[0], "base", now + timedelta(seconds=1))
    original = store.raw_events()
    seen: list[bool] = []
    ingest.subscribe(lambda p: seen.append(p.replayed))
    assert asyncio.run(replay(ingest)) == 3
    assert seen == [True, True]
    assert store.raw_events(live_only=True) == original
    assert store.stats()["duplicates"] == 2
    assert [r.received_at for r in store.raw_events() if r.replayed] == [
        r.received_at for r in original
    ]
    with patch("foxcore.replay.asyncio.sleep", new_callable=AsyncMock) as sleep:
        assert asyncio.run(replay(ingest, speed=10)) == 3
        assert [c.args[0] for c in sleep.call_args_list] == [0.1, 0.1]
    with pytest.raises(ValueError):
        asyncio.run(replay(ingest, -1))
    store.close()


def test_serial_reconnect_partial_and_commands() -> None:
    class Device:
        in_waiting = 1

        def __init__(self) -> None:
            self.chunks = [b"first\npart", b"ial\r\n", b"tail"]
            self.written: list[bytes] = []

        def read(self, size: int) -> bytes:
            if self.chunks:
                return self.chunks.pop(0)
            raise OSError("USB removed")

        def write(self, raw: bytes) -> int:
            self.written.append(raw)
            return len(raw)

        def close(self) -> None:
            pass

    async def check() -> None:
        transport = SerialTransport(SerialConfig("FAKE", reconnect_interval_seconds=0.001))
        device = Device()
        count = 0
        lines: list[bytes] = []

        async def line(raw: bytes) -> None:
            lines.append(raw)

        async def state(event: ConnectionEvent) -> None:
            nonlocal count
            if event.connected:
                count += 1
                await transport.send(b"TIME 1\n")
                if count == 2:
                    transport._stop.set()

        with patch("foxcore.serial.serial.Serial", return_value=device):
            await asyncio.wait_for(transport.run(line, state), timeout=1)
        assert lines == [b"first\n", b"partial\r\n", b"tail"]
        assert count == 2 and device.written == [b"TIME 1\n", b"TIME 1\n"]
        assert not transport.connected

    asyncio.run(check())
