"""Consistent backups and explicit data moves. No source-row interpretation or edits."""

import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from foxcore.logging import SafeLogger
from foxcore.persistence import MIGRATIONS, Store

from .settings import Locations, Settings, encode, save

MAX_ARCHIVE_BYTES = 8 * 1024**3
MEMBERS = {"foxsuite.db", "settings.toml", "manifest.json"}


def validate_database(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("Destination must contain an existing FoxSuite database")
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Database integrity check failed")
            versions = [
                row[0]
                for row in db.execute("SELECT version FROM schema_migrations ORDER BY version")
            ]
            if (
                not versions
                or any(type(version) is not int for version in versions)
                or versions != list(range(1, len(versions) + 1))
                or versions[-1] > len(MIGRATIONS)
            ):
                raise ValueError("Database schema is unsupported")
            # These source tables must exist even in the original M1 database.
            db.execute("SELECT id FROM raw_events LIMIT 0")
            db.execute("SELECT id FROM punches LIMIT 0")
            expected_tables = {
                statement.split()[2]
                for migration in MIGRATIONS[: versions[-1]]
                for statement in migration
                if statement.startswith("CREATE TABLE ")
            }
            actual_tables = {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not expected_tables <= actual_tables:
                raise ValueError("Not a valid FoxSuite database")
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("Database integrity check failed")
    except sqlite3.DatabaseError as exc:
        raise ValueError("Not a valid FoxSuite database") from exc


def snapshot(store: Store, target: Path) -> None:
    if target.exists():
        raise ValueError("Destination database already exists; choose Use existing instead")
    with closing(sqlite3.connect(target)) as db:
        store.db.backup(db)
    validate_database(target)


def backup(store: Store, locations: Locations, settings: Settings) -> Path:
    locations.backups.mkdir(parents=True, exist_ok=True)
    name = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8] + ".foxbackup"
    target = locations.backups / name
    with tempfile.TemporaryDirectory(prefix=".backup-", dir=locations.backups) as folder:
        database = Path(folder) / "foxsuite.db"
        snapshot(store, database)
        config = encode(settings)
        manifest = {
            "format": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "schema": store.version,
            "sha256": {
                "foxsuite.db": digest(database),
                "settings.toml": hashlib.sha256(config).hexdigest(),
            },
        }
        temporary = Path(folder) / "archive"
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(database, "foxsuite.db")
            archive.writestr("settings.toml", config)
            archive.writestr("manifest.json", json.dumps(manifest))
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        temporary.replace(target)
    return target


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def unpack(archive: Path, destination: Path) -> None:
    """Only our three fixed members; no arbitrary paths or ZIP extraction."""
    try:
        with zipfile.ZipFile(archive) as source:
            items = source.infolist()
            if len(items) != 3 or {item.filename for item in items} != MEMBERS:
                raise ValueError("Backup members are invalid")
            if sum(item.file_size for item in items) > MAX_ARCHIVE_BYTES:
                raise ValueError("Backup is too large")
            if (
                source.getinfo("manifest.json").file_size > 65536
                or source.getinfo("settings.toml").file_size > 65536
            ):
                raise ValueError("Backup metadata is too large")
            manifest = json.loads(source.read("manifest.json"))
            if manifest["format"] != 1:
                raise ValueError("Unsupported backup format")
            config = source.read("settings.toml")
            if hashlib.sha256(config).hexdigest() != manifest["sha256"]["settings.toml"]:
                raise ValueError("Backup settings checksum failed")
            with source.open("foxsuite.db") as reader, destination.open("xb") as writer:
                while block := reader.read(1024 * 1024):
                    writer.write(block)
            if digest(destination) != manifest["sha256"]["foxsuite.db"]:
                raise ValueError("Backup database checksum failed")
        validate_database(destination)
    except (zipfile.BadZipFile, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Backup is invalid") from exc


def change_location(
    locations: Locations,
    settings: Settings,
    directory: Path,
    mode: Literal["copy", "move", "existing"],
) -> Settings:
    """Called only after HTTP lifespan closes Store/serial. Never overwrite destination."""
    if settings.override:
        raise ValueError("Explicit configuration is read-only in desktop settings")
    if not directory.is_absolute() or directory == Path(directory.anchor):
        raise ValueError("Choose an absolute data folder, not a drive root")
    if mode not in {"copy", "move", "existing"}:
        raise ValueError("Choose Copy, Move or Use existing")
    directory = directory.resolve()
    target = directory / "foxsuite.db"
    original = settings.core.database_path.resolve()
    if target == original:
        raise ValueError("Choose a different data folder")
    if mode == "existing":
        validate_database(target)
    elif target.exists():
        raise ValueError("Destination database already exists; choose Use existing instead")
    directory.mkdir(parents=True, exist_ok=True)
    with closing(Store(original)) as store:
        backup(store, locations, settings)
        if mode != "existing":
            # Temporary file stays on the destination volume; publication is atomic.
            with tempfile.TemporaryDirectory(prefix=".foxsuite-", dir=directory) as folder:
                temporary = Path(folder) / "foxsuite.db"
                snapshot(store, temporary)
                temporary.replace(target)
        if store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] != 0:
            raise ValueError("Database is in use; close other FoxSuite/CLI processes")
    updated = replace(settings, core=replace(settings.core, database_path=target))
    # Publish settings while the original still exists: even a power loss cannot make the old
    # configured path disappear before the new configuration is durable.
    save(locations, updated)
    # Move deliberately retains the original as a recovery copy. No recursive deletion.
    if mode == "move":
        recovery = original.with_name("foxsuite-moved-" + uuid4().hex[:8] + ".db")
        try:
            original.replace(recovery)
        except OSError as exc:
            # The new configuration/data are already committed. Do not pretend the old path is
            # still active; keep its original filename if Windows cannot rename the safety copy.
            SafeLogger(__name__).warning(
                "Data location changed; recovery copy remains at %s: %s", original, exc
            )
    return updated


def restore(locations: Locations, settings: Settings, archive: Path) -> None:
    if settings.override:
        raise ValueError("Explicit configuration is read-only in desktop settings")
    path = settings.core.database_path
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=path.parent) as folder:
        temporary = Path(folder) / "foxsuite.db"
        unpack(archive, temporary)  # Validate completely before touching the current database.
        with closing(Store(path)) as store:
            backup(store, locations, settings)
            if store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] != 0:
                raise ValueError("Database is in use; close other FoxSuite/CLI processes")
        # Owned Store is closed; no other writers are allowed during this operation.
        for suffix in ("-wal", "-shm"):
            path.with_name(path.name + suffix).unlink(missing_ok=True)
        temporary.replace(path)
