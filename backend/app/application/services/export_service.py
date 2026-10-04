"""Background export orchestration.

State machine (column `requests.export_status`):

    not_started ─(fully assigned)→ pending ─(claim)→ running ─→ succeeded
                                      ↑                  │
                                      └──(retry)── failed ←┘  (after max attempts)

SAFETY: every transition is a single `UPDATE ... WHERE <expected status>` (compare-and-set).
  * Two workers racing for the same request: exactly one `claim` wins; the loser exits quietly.
  * No transaction is held open while "exporting" (the sleep happens between short transactions).
  * A worker that dies mid-export leaves status='running' with an aging heartbeat; the next claim
    attempt reclaims it once it is stale, so a crash never wedges a request forever.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable

from app.application.dto import Actor, RequestView
from app.application.ports import UnitOfWork
from app.core.config import Settings
from app.domain.enums import ExportStatus
from app.domain.errors import ExportNotRetryable, NotFound, PermissionDenied
from app.infrastructure.exports.simulator import ExportSimulationError, ExportSimulator

log = logging.getLogger(__name__)


class ExportService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], settings: Settings, simulator: ExportSimulator) -> None:
        self._uow = uow_factory
        self._s = settings
        self._sim = simulator

    async def run(self, request_id: uuid.UUID) -> ExportStatus | None:
        """Entry point for FastAPI BackgroundTasks. Never raises; returns the final status (or None
        if another worker owns the export)."""
        try:
            return await self._run(request_id)
        except asyncio.CancelledError:
            raise  # shutting down: leave 'running'; the stale-heartbeat reclaim will recover it
        except Exception:
            log.exception("export crashed for request %s", request_id)
            async with self._uow() as uow:
                # Generation 0 cannot match a claimed export. Unexpected failures inside _run
                # are handled there with the claim generation; this is only a pre-claim fallback.
                await uow.requests.finish_export(request_id, 0, status=ExportStatus.FAILED, error="Internal error")
                await uow.commit()
            return ExportStatus.FAILED

    async def _run(self, request_id: uuid.UUID) -> ExportStatus | None:
        async with self._uow() as uow:
            generation = await uow.requests.claim_export(request_id, self._s.export_stale_after_seconds)
            await uow.commit()
        if generation is None:
            log.info("export for %s already claimed/finished; skipping", request_id)
            return None

        max_attempts = self._s.export_max_attempts
        for attempt in range(1, max_attempts + 1):
            async with self._uow() as uow:
                number = await uow.requests.begin_export_attempt(request_id, generation)
                await uow.commit()
            if number is None:  # status changed under us (e.g. reclaimed elsewhere)
                return None
            try:
                await self._sim.run()
            except ExportSimulationError as exc:
                message = f"Attempt {attempt}/{max_attempts} failed: {exc}"
                log.warning("export %s: %s", request_id, message)
                async with self._uow() as uow:
                    if attempt >= max_attempts:
                        await uow.requests.finish_export(
                            request_id, generation, status=ExportStatus.FAILED, error=message
                        )
                    else:
                        await uow.requests.heartbeat_export(request_id, generation, error=message)
                    await uow.commit()
                if attempt >= max_attempts:
                    return ExportStatus.FAILED
                await self._sim.backoff(attempt)
                continue

            async with self._uow() as uow:
                await uow.requests.finish_export(request_id, generation, status=ExportStatus.SUCCEEDED, error=None)
                await uow.commit()
            return ExportStatus.SUCCEEDED
        return ExportStatus.FAILED  # unreachable; keeps type-checkers honest

    async def recover_in_flight(self) -> None:
        """Requeue durable export intent after a process restart."""
        while True:
            async with self._uow() as uow:
                ids = await uow.requests.pending_export_ids(
                    stale_after_seconds=self._s.export_stale_after_seconds
                )
                await uow.commit()
            for request_id in ids:
                await self.run(request_id)
            await asyncio.sleep(5)

    async def retry(self, actor: Actor, request_id: uuid.UUID) -> RequestView:
        """failed → pending. The caller then schedules `run` (see the router)."""
        if not actor.role.is_staff:
            raise PermissionDenied("Only operators and admins can retry exports.")
        async with self._uow() as uow:
            if await uow.requests.get_view(request_id) is None:
                raise NotFound("Request not found.")
            if not await uow.requests.reset_failed_export(request_id):
                raise ExportNotRetryable("Only a failed export can be retried.")
            await uow.commit()
            view = await uow.requests.get_view(request_id)
        assert view is not None
        return view
