"""Reuse the FoxLive presentation convention, with desktop-only catalogs."""

import json
from functools import lru_cache
from pathlib import Path

from foxlive.presentation import language

ERRORS = {
    "Explicit configuration is read-only in desktop settings": "error.override",
    "FoxSuite is restarting; wait for it to reconnect": "error.restarting",
    "Destination must contain an existing FoxSuite database": "error.existing",
    "Database integrity check failed": "error.integrity",
    "Database schema is unsupported": "error.schema",
    "Not a valid FoxSuite database": "error.database",
    "Destination database already exists; choose Use existing instead": "error.destination",
    "Choose an absolute data folder, not a drive root": "error.folder",
    "Choose a different data folder": "error.other_folder",
    "Confirm the data-location change": "error.confirm_data",
    "Confirm restore; current competition data will be replaced": "error.confirm_restore",
    "Backup is invalid": "error.backup",
    "Backup members are invalid": "error.members",
    "Backup is too large": "error.size",
    "Backup metadata is too large": "error.size",
    "Unsupported backup format": "error.format",
    "Backup database checksum failed": "error.checksum",
    "Backup settings checksum failed": "error.checksum",
    "Choose an existing FoxSuite backup": "error.select_backup",
    "Native folder selection is available in the Windows desktop app; otherwise enter an absolute folder path": "error.browse",
    "FoxSuite is already running for this user": "error.busy",
    "Select a FoxIdentServer port before finishing setup": "error.port",
}


@lru_cache(maxsize=2)
def catalog(lang: str) -> dict[str, str]:
    values: dict[str, str] = json.loads(
        (Path(__file__).parent / "static" / f"{language(lang)}.json").read_text(encoding="utf-8")
    )
    return values


def error_text(message: str, lang: str) -> str:
    key = ERRORS.get(message)
    if key is None:
        return message
    return catalog(lang).get(key, catalog("en")[key])
