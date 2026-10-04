"""Request lifecycle + episode assignment.

CONCURRENCY MODEL (read this first)
-----------------------------------
Every mutating operation follows one protocol, inside one transaction:

    1. SELECT ... FOR UPDATE the request row          (serialises everything touching this request)
    2. re-read state *after* acquiring the lock       (so decisions are made on committed truth)
    3. SELECT ... FOR UPDATE the episode rows, sorted (serialises claims on the same episodes)
    4. re-verify availability with a *fresh* query    (READ COMMITTED: new statement => new snapshot)
    5. INSERT assignments, COMMIT                      (locks released)

Lock order is always request → episodes(sorted by id), so lock graphs are acyclic: no deadlocks.
Layered underneath as a safety net, a partial UNIQUE index makes a double-assignment impossible even
if some future code path forgot to lock. Locking gives good behaviour (queueing, clean 409s); the
constraint gives correctness.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from app.application.dto import (
    Actor,
    AssignmentResult,
    EpisodeFilters,
    EpisodeView,
    NewRequest,
    Page,
    RequestFilters,
    RequestView,
)
from app.application.pagination import clamp_limit
from app.application.ports import UnitOfWork
from app.domain.criteria import EpisodeCriteria
from app.domain.enums import ExportStatus, RequestStatus, UserRole
from app.domain.errors import (
    AssignmentExceedsRequest,
    EpisodeCriteriaMismatch,
    EpisodesAlreadyAssigned,
    EpisodesNotFound,
    InsufficientAssignedEpisodes,
    NoEpisodesAvailable,
    NotFound,
    PermissionDenied,
    RequestNotAssignable,
    ValidationFailed,
)
from app.domain.models import Request
from app.domain.state_machine import authorize_transition

log = logging.getLogger(__name__)

# SKIP LOCKED can momentarily hide rows held by a concurrent operator; a couple of rounds lets us
# top up once those locks resolve, without ever spinning.
_MAX_FILL_ROUNDS = 3
MAX_EPISODES_PER_REQUEST = 100_000
MAX_EXPLICIT_IDS = 1_000


def _now() -> datetime:
    return datetime.now(UTC)


class RequestService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow = uow_factory

    # ------------------------------------------------------------------ guards
    @staticmethod
    def _require_staff(actor: Actor) -> None:
        if not actor.role.is_staff:
            raise PermissionDenied("Only operators and admins can perform this action.")

    @staticmethod
    def _assert_visible(actor: Actor, request: Request) -> None:
        """Row-level security. A client asking for someone else's request gets a 404, not a 403,
        so request ids cannot be probed to discover what exists (IDOR / enumeration)."""
        if actor.role is UserRole.CLIENT and request.client_id != actor.id:
            raise NotFound("Request not found.")

    async def _lock(self, uow: UnitOfWork, actor: Actor, request_id) -> Request:
        request = await uow.requests.get_for_update(request_id)
        if request is None:
            raise NotFound("Request not found.")
        self._assert_visible(actor, request)
        return request

    # ------------------------------------------------------------------ create / read
    async def create(self, actor: Actor, data: NewRequest) -> RequestView:
        if actor.role is not UserRole.CLIENT:
            raise PermissionDenied("Only clients can create dataset requests.")
        title = data.title.strip()
        task_name = " ".join(data.task_name.split()).lower()
        if not title or not task_name:
            raise ValidationFailed("Title and task are required.")
        if not 1 <= data.episodes_requested <= MAX_EPISODES_PER_REQUEST:
            raise ValidationFailed(f"episodes_requested must be between 1 and {MAX_EPISODES_PER_REQUEST}.")
        if data.deadline < datetime.now(UTC).date():
            raise ValidationFailed("deadline must be today or later.")
        if data.recorded_after and data.recorded_before and data.recorded_after >= data.recorded_before:
            raise ValidationFailed("recorded_after must be earlier than recorded_before.")

        async with self._uow() as uow:
            if not await uow.episodes.task_exists(task_name):
                raise ValidationFailed(f"Unknown task '{task_name}': no episodes have been recorded for it.")
            request = Request(
                client_id=actor.id,
                title=title,
                deadline=data.deadline,
                notes=data.notes.strip() if data.notes else None,
                task_name=task_name,
                min_quality=data.min_quality,
                recorded_after=data.recorded_after,
                recorded_before=data.recorded_before,
                episodes_requested=data.episodes_requested,
            )
            uow.requests.add(request)
            await uow.requests.flush()
            await uow.requests.add_status_history(request.id, None, RequestStatus.SUBMITTED, actor.id)
            await uow.commit()
            view = await uow.requests.get_view(request.id)
        assert view is not None
        return view

    async def get(self, actor: Actor, request_id) -> RequestView:
        async with self._uow() as uow:
            view = await uow.requests.get_view(request_id)
        if view is None:
            raise NotFound("Request not found.")
        self._assert_visible(actor, view.request)
        return view

    async def list(
        self,
        actor: Actor,
        *,
        status: list[RequestStatus] | None,
        export_status: list[ExportStatus] | None,
        limit: int,
        cursor: str | None,
    ) -> Page[RequestView]:
        filters = RequestFilters(
            status=status,
            export_status=export_status,
            # Row-level security is applied HERE, not left to the caller.
            client_id=actor.id if actor.role is UserRole.CLIENT else None,
        )
        async with self._uow() as uow:
            return await uow.requests.list_page(filters, clamp_limit(limit, 20), cursor)

    async def summary(self, actor: Actor) -> dict[str, int]:
        """Requests per status, scoped like `list`: clients only ever count their own."""
        async with self._uow() as uow:
            return await uow.requests.status_counts(actor.id if actor.role is UserRole.CLIENT else None)

    async def list_assigned_episodes(
        self, actor: Actor, request_id, *, limit: int, cursor: str | None
    ) -> Page[EpisodeView]:
        async with self._uow() as uow:
            view = await uow.requests.get_view(request_id)
            if view is None:
                raise NotFound("Request not found.")
            self._assert_visible(actor, view.request)
            if actor.role is UserRole.CLIENT and view.request.status not in (
                RequestStatus.DELIVERED,
                RequestStatus.ACCEPTED,
            ):
                raise PermissionDenied("Episodes become visible once the request has been delivered.")
            return await uow.assignments.list_episodes_page(request_id, clamp_limit(limit), cursor)

    async def list_candidates(self, actor: Actor, request_id, *, limit: int, cursor: str | None) -> Page[EpisodeView]:
        """Unassigned episodes that satisfy the request's criteria (the operator's picking list)."""
        self._require_staff(actor)
        async with self._uow() as uow:
            view = await uow.requests.get_view(request_id)
            if view is None:
                raise NotFound("Request not found.")
            c = EpisodeCriteria.from_request(view.request)
            filters = EpisodeFilters(
                task_name=c.task_name,
                qualities=c.qualities,
                recorded_from=c.recorded_after,
                recorded_to=c.recorded_before,
                availability="available",
            )
            return await uow.episodes.list_page(filters, clamp_limit(limit), cursor)

    # ------------------------------------------------------------------ state transitions
    async def start(self, actor: Actor, request_id) -> RequestView:
        """submitted → in_progress"""
        async with self._uow() as uow:
            request = await self._lock(uow, actor, request_id)
            authorize_transition(request.status, RequestStatus.IN_PROGRESS, actor.role)
            previous = request.status
            request.status = RequestStatus.IN_PROGRESS
            request.operator_id = actor.id
            request.started_at = _now()
            await uow.requests.add_status_history(request.id, previous, request.status, actor.id)
            await uow.commit()
            return await self._view(uow, request_id)

    async def deliver(self, actor: Actor, request_id) -> RequestView:
        """in_progress → delivered, only once assigned_episodes >= episodes_requested."""
        async with self._uow() as uow:
            request = await self._lock(uow, actor, request_id)
            authorize_transition(request.status, RequestStatus.DELIVERED, actor.role)

            # We hold the request lock, and assignment also takes it first => this count cannot
            # change underneath us between the check and the status update.
            assigned = await uow.assignments.count_active(request.id)
            if assigned < request.episodes_requested:
                raise InsufficientAssignedEpisodes(
                    f"Cannot deliver: {assigned} of {request.episodes_requested} episodes assigned.",
                    assigned=assigned,
                    requested=request.episodes_requested,
                )
            request.status = RequestStatus.DELIVERED
            request.delivered_at = _now()
            await uow.requests.add_status_history(request.id, RequestStatus.IN_PROGRESS, request.status, actor.id)
            await uow.commit()
            return await self._view(uow, request_id)

    async def accept(self, actor: Actor, request_id) -> RequestView:
        """delivered → accepted (owning client only). Terminal."""
        async with self._uow() as uow:
            request = await self._lock(uow, actor, request_id)
            authorize_transition(request.status, RequestStatus.ACCEPTED, actor.role)
            request.status = RequestStatus.ACCEPTED
            request.decided_at = _now()
            await uow.requests.add_status_history(request.id, RequestStatus.DELIVERED, request.status, actor.id)
            await uow.commit()
            return await self._view(uow, request_id)

    async def reject(self, actor: Actor, request_id, reason: str | None) -> RequestView:
        """delivered → rejected (owning client only). Terminal; episodes go back into the pool."""
        async with self._uow() as uow:
            request = await self._lock(uow, actor, request_id)
            authorize_transition(request.status, RequestStatus.REJECTED, actor.role)
            now = _now()
            request.status = RequestStatus.REJECTED
            request.decided_at = now
            request.decision_reason = (reason or "").strip() or None
            released = await uow.assignments.release_all(request.id, now)
            log.info("request %s rejected; released %d episodes", request.id, released)
            await uow.requests.add_status_history(
                request.id, RequestStatus.DELIVERED, request.status, actor.id, request.decision_reason
            )
            await uow.commit()
            return await self._view(uow, request_id)

    async def rework(self, actor: Actor, request_id) -> RequestView:
        """rejected -> in_progress, allowing staff to fulfil client feedback."""
        self._require_staff(actor)
        async with self._uow() as uow:
            request = await self._lock(uow, actor, request_id)
            authorize_transition(request.status, RequestStatus.IN_PROGRESS, actor.role)
            request.status = RequestStatus.IN_PROGRESS
            request.operator_id = actor.id
            request.started_at = _now()
            # Rework is a new fulfillment cycle: prior assignments were released on rejection,
            # and any old export worker must be fenced from the next cycle.
            request.export_status = ExportStatus.NOT_STARTED
            request.export_attempts = 0
            request.export_error = None
            request.export_updated_at = None
            request.export_generation += 1
            await uow.requests.add_status_history(request.id, RequestStatus.REJECTED, request.status, actor.id)
            await uow.commit()
            return await self._view(uow, request_id)

    # ------------------------------------------------------------------ assignment
    async def assign_episodes(self, actor: Actor, request_id, episode_ids: list[str]) -> AssignmentResult:
        """Operator hand-picks specific episodes."""
        self._require_staff(actor)
        ids = sorted({i.strip().upper() for i in episode_ids if i and i.strip()})
        if not ids:
            raise ValidationFailed("Provide at least one episode id.")
        if len(ids) > MAX_EXPLICIT_IDS:
            raise ValidationFailed(f"At most {MAX_EXPLICIT_IDS} episodes can be assigned per call.")

        async with self._uow() as uow:
            # 1. lock the request, 2. re-read state under the lock
            request = await self._lock(uow, actor, request_id)
            current = await self._assert_assignable(uow, request)
            remaining = request.episodes_requested - current
            if len(ids) > remaining:
                raise AssignmentExceedsRequest(
                    f"Only {remaining} more episode(s) can be assigned to this request; got {len(ids)}.",
                    remaining=remaining,
                )

            # 3. lock the episode rows (sorted => no lock-order deadlocks)
            episodes = await uow.episodes.lock_many(ids)
            found = {e.episode_id for e in episodes}
            if missing := [i for i in ids if i not in found]:
                raise EpisodesNotFound(f"{len(missing)} episode(s) do not exist.", episode_ids=missing)

            criteria = EpisodeCriteria.from_request(request)
            if mismatched := [e.episode_id for e in episodes if not criteria.matches(e)]:
                raise EpisodeCriteriaMismatch(
                    "Some episodes do not satisfy this request's task/quality/date criteria.",
                    episode_ids=mismatched,
                )

            # 4. fresh availability check - we now hold the locks, so this answer cannot go stale
            if taken := await uow.assignments.active_episode_ids(ids):
                raise EpisodesAlreadyAssigned(
                    f"{len(taken)} episode(s) are already assigned to a request.", episode_ids=sorted(taken)
                )

            # 5. write + commit
            await uow.assignments.add_many(request.id, ids, actor.id)
            return await self._finish_assignment(uow, request, ids, current + len(ids))

    async def auto_assign(self, actor: Actor, request_id, count: int | None = None) -> AssignmentResult:
        """System picks the best unassigned matching episodes (FOR UPDATE SKIP LOCKED).

        Two operators auto-assigning for different requests from the same pool get *disjoint*
        episodes without waiting on each other.
        """
        self._require_staff(actor)
        if count is not None and count < 1:
            raise ValidationFailed("count must be at least 1.")

        async with self._uow() as uow:
            request = await self._lock(uow, actor, request_id)
            current = await self._assert_assignable(uow, request)
            want = request.episodes_requested - current
            if count is not None:
                want = min(want, count)

            criteria = EpisodeCriteria.from_request(request)
            chosen: list[str] = []
            skip: set[str] = set()
            for _ in range(_MAX_FILL_ROUNDS):
                need = want - len(chosen)
                if need <= 0:
                    break
                batch = await uow.episodes.lock_available_matching(criteria, need, exclude=skip)
                if not batch:
                    break
                ids = [e.episode_id for e in batch]
                skip.update(ids)
                # Re-verify with a fresh snapshot: the SKIP LOCKED scan may have started before a
                # concurrent commit that assigned one of these rows and released its lock.
                taken = await uow.assignments.active_episode_ids(ids)
                chosen.extend(i for i in ids if i not in taken)

            if not chosen:
                raise NoEpisodesAvailable(
                    "No unassigned episodes currently match this request's criteria.",
                    requested=want,
                )
            chosen.sort()
            await uow.assignments.add_many(request.id, chosen, actor.id)
            return await self._finish_assignment(uow, request, chosen, current + len(chosen))

    # ------------------------------------------------------------------ helpers
    @staticmethod
    async def _assert_assignable(uow: UnitOfWork, request: Request) -> int:
        if request.status is not RequestStatus.IN_PROGRESS:
            raise RequestNotAssignable(
                f"Episodes can only be assigned while a request is in progress (currently '{request.status}').",
                status=str(request.status),
            )
        current = await uow.assignments.count_active(request.id)
        if current >= request.episodes_requested:
            raise AssignmentExceedsRequest("This request already has all of its episodes assigned.", remaining=0)
        return current

    async def _finish_assignment(
        self, uow: UnitOfWork, request: Request, new_ids: list[str], total_assigned: int
    ) -> AssignmentResult:
        fully_assigned = total_assigned >= request.episodes_requested
        export_scheduled = False
        # Becoming fully assigned arms the background export exactly once. The status flip to
        # 'pending' is committed atomically with the assignments, so it survives a crash before the
        # background task is scheduled (operators can retry / a sweeper can pick it up).
        if fully_assigned and request.export_status is ExportStatus.NOT_STARTED:
            request.export_status = ExportStatus.PENDING
            request.export_attempts = 0
            request.export_updated_at = _now()
            export_scheduled = True
        await uow.commit()
        view = await self._view(uow, request.id)
        return AssignmentResult(
            view=view,
            assigned_episode_ids=new_ids,
            fully_assigned=fully_assigned,
            export_scheduled=export_scheduled,
        )

    @staticmethod
    async def _view(uow: UnitOfWork, request_id) -> RequestView:
        view = await uow.requests.get_view(request_id)
        assert view is not None
        return view
