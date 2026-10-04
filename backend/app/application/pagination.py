"""Opaque keyset cursors.

A cursor is base64url(JSON([...sort-key values...])). It carries *position*, never authority: every
page query re-applies the caller's scope filters, so a forged cursor can only move the window.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime

from app.domain.errors import InvalidCursor

MAX_LIMIT = 200


def encode_cursor(*values: str) -> str:
    raw = json.dumps(list(values), separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, arity: int) -> list[str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        values = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except Exception as exc:  # noqa: BLE001 - any decoding failure is just "bad cursor"
        raise InvalidCursor("Malformed pagination cursor.") from exc
    if not isinstance(values, list) or len(values) != arity or not all(isinstance(v, str) for v in values):
        raise InvalidCursor("Malformed pagination cursor.")
    return values


def parse_dt(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidCursor("Malformed pagination cursor.") from exc
    if dt.tzinfo is None:
        raise InvalidCursor("Malformed pagination cursor.")
    return dt


def parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise InvalidCursor("Malformed pagination cursor.") from exc


def clamp_limit(limit: int, default: int = 50) -> int:
    if limit is None:
        return default
    return max(1, min(int(limit), MAX_LIMIT))
