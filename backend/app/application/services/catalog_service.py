"""Task catalogue for the request form, behind a small TTL cache.

`GROUP BY task_name` over millions of rows is an index-only scan - cheap, but not free - and the
answer changes only when an import lands. So: compute at most once per TTL, and make concurrent
callers share the in-flight computation instead of stampeding the database.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from app.application.ports import UnitOfWork


class CatalogService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], ttl_seconds: int) -> None:
        self._uow = uow_factory
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()
        self._expires = 0.0
        self._tasks: list[tuple[str, int]] = []

    def invalidate(self) -> None:
        self._expires = 0.0

    async def tasks(self) -> list[tuple[str, int]]:
        if time.monotonic() < self._expires:
            return self._tasks
        async with self._lock:
            if time.monotonic() >= self._expires:  # re-check: another caller may have refreshed it
                async with self._uow() as uow:
                    self._tasks = await uow.episodes.task_counts()
                self._expires = time.monotonic() + self._ttl
            return self._tasks
