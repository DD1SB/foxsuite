"""Logging handlers are diagnostics, never prerequisites for ingest."""

import logging
from typing import Any


class SafeLogger:
    def __init__(self, name: str) -> None:
        self.logger = logging.getLogger(name)

    def _emit(self, level: int, message: str, *args: Any, exc_info: bool = False) -> None:
        try:
            self.logger.log(level, message, *args, exc_info=exc_info)
        except Exception:
            # Broken custom handlers must not prevent durable input recording.
            pass

    def info(self, message: str, *args: Any) -> None:
        self._emit(logging.INFO, message, *args)

    def debug(self, message: str, *args: Any) -> None:
        self._emit(logging.DEBUG, message, *args)

    def warning(self, message: str, *args: Any) -> None:
        self._emit(logging.WARNING, message, *args)

    def exception(self, message: str, *args: Any) -> None:
        self._emit(logging.ERROR, message, *args, exc_info=True)
