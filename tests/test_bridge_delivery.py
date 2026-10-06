import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from foxbridge.config import BridgeConfig, OutputConfig
from foxbridge.mapping import MappingRepository, Role
from foxbridge.output import FakeOutput
from foxbridge.persistence import DeliveryRepository
from foxbridge.service import BridgeService
from foxcore.config import TimeSyncConfig
from foxcore.events import ConnectionEvent
from foxcore.persistence import Store
from foxcore.replay import replay
from foxcore.serial import FakeTransport
from foxcore.service import IngestService
from foxcore.simulator import messages
from foxcore.timesync import TimeSyncService

STAMP = 1770000000
NOW = datetime.fromtimestamp(STAMP, UTC)
UID = "04A78319BCDE12"


def config() -> BridgeConfig:
    return BridgeConfig(
        enabled=True, output=OutputConfig(port="FAKE", reconnect_interval_seconds=0.001)
    )


def setup(
    store: Store, output: FakeOutput, allow_replay: bool = False
) -> tuple[BridgeService, IngestService]:
    mapping = MappingRepository(store)
    mapping.add_uid(UID, 912345)
    mapping.add_station(1, 31, Role.CONTROL)
    bridge = BridgeService(DeliveryRepository(store), config(), output, allow_replay)
    ingest = IngestService(store)
    ingest.subscribe(bridge.accept)
    return bridge, ingest


async def flush(bridge: BridgeService) -> None:
    task = asyncio.create_task(bridge.run())
    try:
        await asyncio.wait_for(bridge.drain(), 1)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def test_live_once_duplicate_restart_and_explicit_resend(tmp_path: Path) -> None:
    async def check() -> None:
        path = tmp_path / "once.db"
        store = Store(path)
        output = FakeOutput()
        bridge, ingest = setup(store, output)
        first = ingest.ingest(messages()[0], "base", NOW)
        duplicate = ingest.ingest(messages()[0], "base", NOW)
        assert first is not None and duplicate is not None
        bridge.accept(first)  # subscriber retried
        await flush(bridge)
        assert len(output.frames) == 1
        assert DeliveryRepository(store).status(config())["delivered"] == 1
        originals = store.raw_events()
        store.close()
        store = Store(path)
        bridge, _ = setup(store, output)
        bridge.accept(first)
        await flush(bridge)
        assert len(output.frames) == 1
        resent = bridge.enqueue(store.get_punch(first.id or 0), explicit=True)
        assert resent is not None and resent.status == "queued"
        await flush(bridge)
        assert len(output.frames) == 2 and output.frames[0] == output.frames[1]
        assert store.raw_events() == originals
        assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []
        store.close()

    asyncio.run(check())


@pytest.mark.parametrize("allow", [False, True])
def test_replay_guard(tmp_path: Path, allow: bool) -> None:
    async def check() -> None:
        store = Store(tmp_path / "replay.db")
        output = FakeOutput()
        bridge, ingest = setup(store, output, allow)
        ingest.ingest(messages()[0], "base", NOW)
        await flush(bridge)
        assert await replay(ingest) == 1
        await flush(bridge)
        assert len(output.frames) == (2 if allow else 1)
        row = store.db.execute(
            "SELECT status FROM bridge_deliveries ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row[0] == ("sent" if allow else "replay_blocked")
        store.close()

    asyncio.run(check())


def test_missing_mapping_does_not_stop_later_punch(tmp_path: Path) -> None:
    async def check() -> None:
        store = Store(tmp_path / "missing.db")
        output = FakeOutput()
        bridge, ingest = setup(store, output)
        missing = ingest.ingest(messages()[0].replace(UID.encode(), b"04AA"), "base", NOW)
        ingest.ingest(messages()[0], "base", NOW)
        await flush(bridge)
        assert len(output.frames) == 1
        status = DeliveryRepository(store).status(config())
        assert status["mapping_failures"] == 1 and status["unmapped_uids"] == ["04AA"]
        MappingRepository(store).add_uid("04AA", 912346)
        assert missing is not None
        bridge.enqueue(missing, explicit=True)
        await flush(bridge)
        assert len(output.frames) == 2
        store.close()

    asyncio.run(check())


def test_output_failures_and_reconnect_never_automatically_resend(tmp_path: Path) -> None:
    async def check() -> None:
        store = Store(tmp_path / "failure.db")
        output = FakeOutput()
        bridge, ingest = setup(store, output)
        output.fail_connect = True
        first = ingest.ingest(messages()[0], "base", NOW)
        await flush(bridge)
        assert DeliveryRepository(store).list_deliveries("fjww")[0]["status"] == "failed"
        output.fail_connect = False
        await asyncio.sleep(0.002)
        second = ingest.ingest(messages()[0].replace(b'"sequence":2', b'"sequence":3'), "base", NOW)
        await flush(bridge)
        assert len(output.frames) == 1
        assert first is not None and second is not None
        bridge.accept(first)
        output.fail_write = True
        third = ingest.ingest(messages()[0].replace(b'"sequence":2', b'"sequence":4'), "base", NOW)
        await flush(bridge)
        assert DeliveryRepository(store).list_deliveries("fjww")[0]["status"] == "uncertain"
        output.fail_write = False
        assert third is not None
        await asyncio.sleep(0.002)
        bridge.enqueue(third, explicit=True)
        await flush(bridge)
        assert len(output.frames) == 2
        store.close()

    asyncio.run(check())


def test_reservation_survives_restart_without_resend(tmp_path: Path) -> None:
    path = tmp_path / "reservation.db"
    store = Store(path)
    output = FakeOutput()
    bridge, ingest = setup(store, output)
    punch = ingest.ingest(messages()[0], "base", NOW)
    assert punch is not None
    delivery = DeliveryRepository(store).list_deliveries("fjww")[0]
    assert delivery["status"] == "queued"
    DeliveryRepository(store).claim(delivery["id"])  # simulate crash immediately before/after write
    store.close()
    store = Store(path)
    restarted, _ = setup(store, output)
    restarted.accept(punch)
    assert restarted.queue.empty() and output.frames == []
    assert DeliveryRepository(store).list_deliveries("fjww")[0]["status"] == "writing"
    store.close()


@pytest.mark.parametrize(
    "station,code,role", [(1, 31, Role.CONTROL), (2, 3, Role.START), (3, 4, Role.FINISH)]
)
def test_roles_and_original_timestamp_untouched(
    tmp_path: Path, station: int, code: int, role: Role
) -> None:
    async def check() -> None:
        store = Store(tmp_path / "role.db")
        maps = MappingRepository(store)
        maps.add_uid(UID, 912345)
        maps.add_station(station, code, role)
        output = FakeOutput()
        bridge = BridgeService(DeliveryRepository(store), config(), output)
        ingest = IngestService(store)
        ingest.subscribe(bridge.accept)
        punch = ingest.ingest(
            messages()[0].replace(b'"station":1', f'"station":{station}'.encode()), "base", NOW
        )
        assert punch is not None
        await flush(bridge)
        assert int.from_bytes(output.frames[0][3:5], "big") == code
        assert store.get_punch(punch.id or 0) == punch
        store.close()

    asyncio.run(check())


def test_invalid_timestamp_and_queue_overflow_are_audited(tmp_path: Path) -> None:
    store = Store(tmp_path / "limits.db")
    output = FakeOutput()
    bridge, ingest = setup(store, output)
    bad = ingest.ingest(messages()[0].replace(b"1770000000", b"100"), "base", NOW)
    assert bad is not None
    assert DeliveryRepository(store).status(config())["encoding_failures"] == 1
    tiny = BridgeService(DeliveryRepository(store), replace(config(), queue_capacity=1), output)
    for sequence in [3, 4]:
        # Standalone ingestion, then feed the bounded subscriber once.
        p = IngestService(store).ingest(
            messages()[0].replace(b'"sequence":2', f'"sequence":{sequence}'.encode()), "base", NOW
        )
        assert p is not None
        tiny.accept(p)
    assert DeliveryRepository(store).list_deliveries("fjww")[0]["status"] == "failed"
    store.close()


def test_internal_persistence_failure_is_fatal_and_raw_safe(tmp_path: Path) -> None:
    async def check() -> None:
        store = Store(tmp_path / "broken.db")
        bridge, ingest = setup(store, FakeOutput())
        with patch.object(bridge.repository, "prepare", side_effect=RuntimeError("ledger broken")):
            punch = ingest.ingest(messages()[0], "base", NOW)
        assert punch is not None and store.stats()["raw_events"] == 1
        with pytest.raises(RuntimeError, match="ledger broken"):
            await bridge.run(False)
        store.close()

    asyncio.run(check())


def test_resend_uses_frozen_mapping_history(tmp_path: Path) -> None:
    async def check() -> None:
        store = Store(tmp_path / "frozen.db")
        output = FakeOutput()
        bridge, ingest = setup(store, output)
        punch = ingest.ingest(messages()[0], "base", NOW)
        assert punch is not None
        await flush(bridge)
        maps = MappingRepository(store)
        maps.remove_uid(UID)
        maps.add_uid(UID, 912346)
        maps.remove_station(1)
        maps.add_station(1, 32, Role.CONTROL)
        bridge.enqueue(punch, explicit=True)
        await flush(bridge)
        assert output.frames[0] == output.frames[1]
        row = DeliveryRepository(store).list_deliveries("fjww")[0]
        assert row["card_number"] == 912345 and row["control_code"] == 31
        store.close()

    asyncio.run(check())


def test_end_to_end_fake_source_reconnect_and_independent_time_sync(tmp_path: Path) -> None:
    async def check() -> None:
        store = Store(tmp_path / "end-to-end.db")
        output = FakeOutput()
        bridge, ingest = setup(store, output)
        transport = FakeTransport()
        sync = TimeSyncService(
            transport,
            TimeSyncConfig(),
            lambda e: store.diagnostic("timesync", str(e)),
            clock=lambda: STAMP,
        )
        seen: list[int] = []
        ingest.subscribe(lambda p: seen.append(p.id or 0))

        async def line(raw: bytes) -> None:
            ingest.ingest(raw, "fake-base", NOW)
            await asyncio.sleep(0)

        for raw in messages():
            transport.input.put_nowait(raw)
        transport.input.put_nowait(ConnectionEvent(False, "USB unplug"))
        transport.input.put_nowait(ConnectionEvent(True, "USB replug"))
        transport.input.put_nowait(messages()[0].replace(b'"sequence":2', b'"sequence":4'))
        transport.input.put_nowait(None)
        worker = asyncio.create_task(bridge.run())
        try:
            await transport.run(line, sync.connection_changed)
            await asyncio.wait_for(bridge.drain(), 1)
            assert transport.commands == [b"TIME 1770000000\n"] * 2
            assert len(output.frames) == 2 and len(seen) == 3
            assert store.stats()["raw_events"] == 8
            assert store.stats()["duplicates"] == 1
            assert DeliveryRepository(store).status(config())["delivered"] == 2
        finally:
            worker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await worker
            await sync.stop()
            store.close()

    asyncio.run(check())


def test_continuous_output_reconnect_only_delivers_new_punches(tmp_path: Path) -> None:
    async def check() -> None:
        store = Store(tmp_path / "continuous.db")
        output = FakeOutput()
        bridge, ingest = setup(store, output)
        output.fail_connect = True
        worker = asyncio.create_task(bridge.run())
        try:
            ingest.ingest(messages()[0], "base", NOW)
            await asyncio.wait_for(bridge.drain(), 1)
            output.fail_connect = False
            async with asyncio.timeout(1):
                while not output.connected:
                    await asyncio.sleep(0.001)
            ingest.ingest(messages()[0].replace(b'"sequence":2', b'"sequence":3'), "base", NOW)
            await asyncio.wait_for(bridge.drain(), 1)
            assert len(output.frames) == 1
            assert DeliveryRepository(store).status(config())["status_counts"] == {
                "failed": 1,
                "sent": 1,
            }
        finally:
            worker.cancel()
            with pytest.raises(asyncio.CancelledError):
                await worker
            store.close()

    asyncio.run(check())


def test_failure_after_write_preserves_uncertain_reservation(tmp_path: Path) -> None:
    async def check() -> None:
        store = Store(tmp_path / "post-write.db")
        output = FakeOutput()
        bridge, ingest = setup(store, output)
        punch = ingest.ingest(messages()[0], "base", NOW)
        assert punch is not None
        with patch.object(bridge.repository, "finish", side_effect=RuntimeError("disk failure")):
            with pytest.raises(RuntimeError, match="disk failure"):
                await bridge.run()
        assert len(output.frames) == 1
        assert DeliveryRepository(store).list_deliveries("fjww")[0]["status"] == "writing"
        restarted, _ = setup(store, output)
        restarted.accept(punch)
        assert restarted.queue.empty()
        assert store.stats()["raw_events"] == 1
        store.close()

    asyncio.run(check())


def test_shutdown_during_write_is_uncertain_not_automatically_retried(tmp_path: Path) -> None:
    class WaitingOutput(FakeOutput):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()

        async def write(self, data: bytes) -> None:
            self.started.set()
            await asyncio.Future[None]()

    async def check() -> None:
        store = Store(tmp_path / "cancel.db")
        output = WaitingOutput()
        bridge, ingest = setup(store, output)
        punch = ingest.ingest(messages()[0], "base", NOW)
        assert punch is not None
        worker = asyncio.create_task(bridge.run())
        await asyncio.wait_for(output.started.wait(), 1)
        worker.cancel()
        with pytest.raises(asyncio.CancelledError):
            await worker
        assert not output.connected
        assert DeliveryRepository(store).list_deliveries("fjww")[0]["status"] == "uncertain"
        restarted, _ = setup(store, FakeOutput())
        restarted.accept(punch)
        assert restarted.queue.empty()
        store.close()

    asyncio.run(check())


@pytest.mark.parametrize("reason", ["skew", "offset", "missing_station"])
def test_validation_and_station_failures_are_visible(tmp_path: Path, reason: str) -> None:
    store = Store(tmp_path / "validation.db")
    bridge, ingest = setup(store, FakeOutput())
    if reason == "offset":
        with store.db:
            store.db.execute("INSERT INTO bridge_offsets VALUES ('fjww',31,16777216)")
    elif reason == "missing_station":
        MappingRepository(store).remove_station(1)
    receive = datetime.fromtimestamp(STAMP + 86401, UTC) if reason == "skew" else NOW
    ingest.ingest(messages()[0], "base", receive)
    row = DeliveryRepository(store).list_deliveries("fjww")[0]
    assert row["status"] == ("mapping_error" if reason == "missing_station" else "encoding_error")
    assert bridge.queue.empty() and row["encoded_frame"] is None
    if reason == "missing_station":
        assert DeliveryRepository(store).status(config())["unmapped_stations"] == [1]
    store.close()


def test_removed_output_close_failure_does_not_poison_ingest(tmp_path: Path) -> None:
    class RemovedOutput(FakeOutput):
        async def close(self) -> None:
            self.connected = False
            raise OSError("Device removed during close")

    async def check() -> None:
        store = Store(tmp_path / "close-error.db")
        output = RemovedOutput()
        bridge, ingest = setup(store, output)
        output.fail_write = True
        ingest.ingest(messages()[0], "base", NOW)
        await flush(bridge)
        output.fail_write = False
        await asyncio.sleep(0.002)
        ingest.ingest(messages()[0].replace(b'"sequence":2', b'"sequence":3'), "base", NOW)
        await flush(bridge)
        assert len(output.frames) == 1 and store.stats()["raw_events"] == 2
        assert DeliveryRepository(store).status(config())["status_counts"] == {
            "sent": 1,
            "uncertain": 1,
        }
        store.close()

    asyncio.run(check())
