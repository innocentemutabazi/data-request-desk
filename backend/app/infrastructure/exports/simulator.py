"""Simulated dataset export: takes 2-5 s and fails ~20% of the time.

`rng` and `sleep` are injectable so tests can force success/failure with zero wall-clock delay.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

from app.core.config import Settings

_FAILURES = (
    "Storage gateway timed out while packaging the dataset",
    "Checksum mismatch detected on a shard; upload aborted",
    "Object store returned 503 (SlowDown)",
    "Transient network error during multipart upload",
)


class ExportSimulationError(Exception):
    """A (simulated) transient export failure."""


class ExportSimulator:
    def __init__(
        self,
        settings: Settings,
        rng: random.Random | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._s = settings
        self._rng = rng or random.Random()
        self._sleep = sleep

    async def run(self) -> None:
        await self._sleep(self._rng.uniform(self._s.export_min_seconds, self._s.export_max_seconds))
        if self._rng.random() < self._s.export_failure_rate:
            raise ExportSimulationError(self._rng.choice(_FAILURES))

    async def backoff(self, attempt: int) -> None:
        # exponential backoff with +-25% jitter so retries from many requests don't synchronise
        base = self._s.export_retry_backoff_seconds * (2 ** (attempt - 1))
        await self._sleep(base * self._rng.uniform(0.75, 1.25))
