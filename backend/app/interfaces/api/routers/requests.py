from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.application.dto import Actor, NewRequest
from app.composition import Container
from app.domain.enums import ExportStatus, RequestStatus, UserRole
from app.interfaces.api.deps import STAFF, current_actor, get_container, require_roles
from app.interfaces.api.schemas import (
    AssignIn,
    AssignmentOut,
    AutoAssignIn,
    EpisodeOut,
    PageOut,
    RejectIn,
    RequestCreate,
    RequestOut,
    to_episode_out,
    to_request_out,
)

router = APIRouter(prefix="/requests", tags=["requests"])

_staff = require_roles(*STAFF)
_client = require_roles(UserRole.CLIENT)


def _out(view, actor: Actor, c: Container) -> RequestOut:
    return to_request_out(view, actor.role, c.settings)


def _assignment_out(result, actor: Actor, c: Container) -> AssignmentOut:
    return AssignmentOut(
        request=_out(result.view, actor, c),
        assigned_episode_ids=result.assigned_episode_ids,
        fully_assigned=result.fully_assigned,
        export_scheduled=result.export_scheduled,
    )


# ------------------------------------------------------------------ create / read
@router.post("", response_model=RequestOut, status_code=201)
async def create_request(body: RequestCreate, actor: Actor = Depends(_client), c: Container = Depends(get_container)):
    view = await c.requests.create(actor, NewRequest(**body.model_dump()))
    return _out(view, actor, c)


@router.get("", response_model=PageOut[RequestOut])
async def list_requests(
    status: list[RequestStatus] | None = Query(None),
    export_status: list[ExportStatus] | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    cursor: str | None = Query(None, description="Opaque keyset cursor from a previous page."),
    actor: Actor = Depends(current_actor),
    c: Container = Depends(get_container),
):
    """Newest first, keyset-paginated. Clients automatically see only their own requests."""
    page = await c.requests.list(actor, status=status, export_status=export_status, limit=limit, cursor=cursor)
    return PageOut[RequestOut](items=[_out(v, actor, c) for v in page.items], next_cursor=page.next_cursor)


@router.get("/summary", response_model=dict[str, int])
async def requests_summary(actor: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    """Count per status (accurate regardless of pagination). Declared BEFORE /{request_id}."""
    return await c.requests.summary(actor)


@router.get("/{request_id}", response_model=RequestOut)
async def get_request(request_id: uuid.UUID, actor: Actor = Depends(current_actor), c: Container = Depends(get_container)):
    return _out(await c.requests.get(actor, request_id), actor, c)


# ------------------------------------------------------------------ lifecycle
@router.post("/{request_id}/start", response_model=RequestOut)
async def start_request(request_id: uuid.UUID, actor: Actor = Depends(_staff), c: Container = Depends(get_container)):
    return _out(await c.requests.start(actor, request_id), actor, c)


@router.post("/{request_id}/deliver", response_model=RequestOut)
async def deliver_request(request_id: uuid.UUID, actor: Actor = Depends(_staff), c: Container = Depends(get_container)):
    return _out(await c.requests.deliver(actor, request_id), actor, c)


@router.post("/{request_id}/rework", response_model=RequestOut)
async def rework_request(request_id: uuid.UUID, actor: Actor = Depends(_staff), c: Container = Depends(get_container)):
    return _out(await c.requests.rework(actor, request_id), actor, c)


@router.post("/{request_id}/accept", response_model=RequestOut)
async def accept_request(request_id: uuid.UUID, actor: Actor = Depends(_client), c: Container = Depends(get_container)):
    return _out(await c.requests.accept(actor, request_id), actor, c)


@router.post("/{request_id}/reject", response_model=RequestOut)
async def reject_request(
    request_id: uuid.UUID,
    body: RejectIn | None = None,
    actor: Actor = Depends(_client),
    c: Container = Depends(get_container),
):
    return _out(await c.requests.reject(actor, request_id, body.reason if body else None), actor, c)


# ------------------------------------------------------------------ assignment (+ background export)
@router.post("/{request_id}/assignments", response_model=AssignmentOut, status_code=201)
async def assign_episodes(
    request_id: uuid.UUID,
    body: AssignIn,
    background: BackgroundTasks,
    actor: Actor = Depends(_staff),
    c: Container = Depends(get_container),
):
    """Assign hand-picked episodes (pessimistic row locks). Completing the set arms the export."""
    result = await c.requests.assign_episodes(actor, request_id, body.episode_ids)
    if result.export_scheduled:
        background.add_task(c.exports.run, request_id)
    return _assignment_out(result, actor, c)


@router.post("/{request_id}/assignments/auto", response_model=AssignmentOut, status_code=201)
async def auto_assign_episodes(
    request_id: uuid.UUID,
    background: BackgroundTasks,
    body: AutoAssignIn | None = None,
    actor: Actor = Depends(_staff),
    c: Container = Depends(get_container),
):
    """Let the system pick the best unassigned matches (FOR UPDATE SKIP LOCKED)."""
    result = await c.requests.auto_assign(actor, request_id, body.count if body else None)
    if result.export_scheduled:
        background.add_task(c.exports.run, request_id)
    return _assignment_out(result, actor, c)


@router.get("/{request_id}/assignments", response_model=PageOut[EpisodeOut])
async def list_assigned_episodes(
    request_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    actor: Actor = Depends(current_actor),
    c: Container = Depends(get_container),
):
    page = await c.requests.list_assigned_episodes(actor, request_id, limit=limit, cursor=cursor)
    return PageOut[EpisodeOut](
        items=[to_episode_out(v.episode, v.assigned_request_id) for v in page.items], next_cursor=page.next_cursor
    )


@router.get("/{request_id}/candidates", response_model=PageOut[EpisodeOut])
async def list_candidates(
    request_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    actor: Actor = Depends(_staff),
    c: Container = Depends(get_container),
):
    page = await c.requests.list_candidates(actor, request_id, limit=limit, cursor=cursor)
    return PageOut[EpisodeOut](
        items=[to_episode_out(v.episode, v.assigned_request_id) for v in page.items], next_cursor=page.next_cursor
    )


@router.post("/{request_id}/export/retry", response_model=RequestOut, status_code=202)
async def retry_export(
    request_id: uuid.UUID,
    background: BackgroundTasks,
    actor: Actor = Depends(_staff),
    c: Container = Depends(get_container),
):
    view = await c.exports.retry(actor, request_id)
    background.add_task(c.exports.run, request_id)
    return _out(view, actor, c)
