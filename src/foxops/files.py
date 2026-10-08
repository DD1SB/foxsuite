"""Portable file-content flushing for completed operations staging files."""

import os
from pathlib import Path


def sync_file(path: Path) -> None:
    """Flush an existing file after its writer has closed, without changing its bytes.

    Windows' os.fsync uses _commit and needs a writable handle. r+b neither
    creates nor truncates the file. Close this handle before callers rename/replace
    the file; never suppress flush errors or try to fsync directory descriptors.
    This flushes file contents, not a subsequent directory-entry change.
    """
    with path.open("r+b") as stream:
        os.fsync(stream.fileno())
