from pathlib import Path
from unittest.mock import patch

import pytest

from foxbridge.mapping import MappingRepository, Role
from foxcore.persistence import MIGRATIONS, Store
from foxcore.service import IngestService
from foxcore.simulator import messages


def test_uid_mapping_unique_persistent_explicit(tmp_path: Path) -> None:
    path = tmp_path / "mapping.db"
    store = Store(path)
    maps = MappingRepository(store)
    mapped = maps.add_uid("04:aa", 912345)
    assert maps.uid("04AA") == mapped
    assert maps.uid("00") is None
    assert maps.add_uid("04aa", 912345) == mapped
    with pytest.raises(ValueError, match="already has"):
        maps.add_uid("04BB", 912345)
    with pytest.raises(ValueError, match="already maps"):
        maps.add_uid("04AA", 912346)
    maps.remove_uid("04AA")
    assert maps.uid("04AA") is None
    changed = maps.add_uid("04AA", 912346)
    assert changed.id != mapped.id
    assert store.db.execute("SELECT COUNT(*) FROM bridge_uid_maps").fetchone()[0] == 2
    store.close()
    store = Store(path)
    assert MappingRepository(store).uid("04aa") == changed
    store.close()


@pytest.mark.parametrize(
    "station,code,role",
    [(1, 20, Role.CONTROL), (2, 254, Role.CONTROL), (3, 3, Role.START), (4, 4, Role.FINISH)],
)
def test_station_mapping(tmp_path: Path, station: int, code: int, role: Role) -> None:
    store = Store(tmp_path / "station.db")
    maps = MappingRepository(store)
    mapped = maps.add_station(station, code, role)
    assert maps.station(station) == mapped
    assert maps.add_station(station, code, role) == mapped
    assert maps.station(7) is None
    maps.remove_station(station)
    assert maps.station(station) is None
    store.close()


@pytest.mark.parametrize(
    "code,role",
    [
        (19, Role.CONTROL),
        (255, Role.CONTROL),
        (0, Role.CONTROL),
        (1024, Role.CONTROL),
        (31, Role.START),
        (3, Role.FINISH),
    ],
)
def test_invalid_station_code(tmp_path: Path, code: int, role: Role) -> None:
    store = Store(tmp_path / "invalid.db")
    with pytest.raises(ValueError):
        MappingRepository(store).add_station(1, code, role)
    store.close()


def test_csv_atomic_import(tmp_path: Path) -> None:
    store = Store(tmp_path / "import.db")
    maps = MappingRepository(store)
    path = tmp_path / "uids.csv"
    path.write_text("uid,card_number\n04AA,912345\n04BB,912345\n")
    with pytest.raises(ValueError):
        maps.import_csv(path, "uid")
    assert maps.list_uids() == []
    path.write_text("uid,card_number\n04AA,912345\n04BB,912346\n")
    assert maps.import_csv(path, "uid") == 2
    path.write_text("station_id,control_code,role\n1,31,CONTROL\n2,3,START\n")
    assert maps.import_csv(path, "station") == 2
    assert len(maps.list_stations()) == 2
    store.close()


def test_v1_database_upgrades_without_source_changes(tmp_path: Path) -> None:
    path = tmp_path / "m1.db"
    with patch("foxcore.persistence.MIGRATIONS", MIGRATIONS[:1]):
        store = Store(path)
        punch = IngestService(store).ingest(messages()[0], "source")
        assert punch is not None
        original = store.raw_events()
        assert store.version == 1
        store.close()
    store = Store(path)
    assert store.version == 2 and store.raw_events() == original
    assert store.get_punch(punch.id or 0) == punch
    assert store.db.execute("PRAGMA foreign_key_check").fetchall() == []
    store.close()


def test_import_rejects_wrong_empty_header_and_kind(tmp_path: Path) -> None:
    store = Store(tmp_path / "empty.db")
    path = tmp_path / "empty.csv"
    path.write_text("wrong,header\n")
    with pytest.raises(ValueError, match="CSV headers"):
        MappingRepository(store).import_csv(path, "uid")
    with pytest.raises(ValueError, match="import kind"):
        MappingRepository(store).import_csv(path, "invalid")
    store.close()
