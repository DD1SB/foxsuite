"""Source-derived FoxIdentServer line parser and normalization."""

from datetime import datetime
import json
import re
from typing import Any

from .events import (DiagnosticEvent, MalformedLineEvent, Message, Punch,
                     TagEvent, UnknownJsonEvent)


def normalize_uid(value: str) -> str:
    value = re.sub(r"[:\-\s]", "", value).upper()
    if not value or len(value) % 2 or re.fullmatch(r"[0-9A-F]+", value) is None:
        raise ValueError("UID must contain complete hexadecimal bytes")
    return value


def format_uid(value: str) -> str:
    uid = normalize_uid(value)
    return ":".join(uid[i:i + 2] for i in range(0, len(uid), 2))


def parse_line(raw: bytes) -> Message:
    try:
        text = raw.decode("utf-8").strip()
        if not text.startswith(("{", "[")):
            return Message("text", "text", {"text": text})
        # [BASE] is firmware text, not a JSON array.
        if text.startswith("[BASE]"):
            return Message("text", "text", {"text": text})
        payload: Any = json.loads(text)
        if not isinstance(payload, dict):
            return UnknownJsonEvent("unknown", "unknown", {"value": payload})
        kind = payload.get("type", "unknown")
        if not isinstance(kind, str):
            kind = "unknown"
        if kind == "tag":
            return TagEvent(kind, "parsed", payload)
        if kind in {"time", "sync", "time_request", "error"}:
            return DiagnosticEvent(kind, "parsed", payload)
        return UnknownJsonEvent(kind, "unknown", payload)
    except (UnicodeError, ValueError, RecursionError) as exc:
        return MalformedLineEvent("malformed", "malformed", {}, str(exc))


def integer(payload: dict[str, Any], name: str, maximum: int) -> int:
    value = payload[name]
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"Invalid {name}")
    return int(value)


def normalize(message: Message, raw_id: int, received: datetime, source: str,
              replayed: bool, scope: str) -> Punch | None:
    if not isinstance(message, TagEvent):
        return None
    p = message.payload
    uid = p["uid"]
    if not isinstance(uid, str):
        raise ValueError("UID must be text")
    callsign, rssi = p.get("callsign"), p.get("rssi")
    if callsign is not None and not isinstance(callsign, str):
        raise ValueError("Invalid callsign")
    if rssi is not None and type(rssi) is not int:
        raise ValueError("Invalid RSSI")
    return Punch(raw_id, received, integer(p, "station", 65535),
                 integer(p, "timestamp", 4294967295), integer(p, "sequence", 65535),
                 normalize_uid(uid), callsign, rssi, source, replayed, scope)
