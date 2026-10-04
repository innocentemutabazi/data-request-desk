"""Race conditions on assignment & state transitions, against real PostgreSQL row locks.

Two layers of defence are tested SEPARATELY so neither can mask a regression in the other:
  1. pessimistic locks (FOR UPDATE / SKIP LOCKED): correct, queued, *clean* behaviour
  2. the partial UNIQUE index: correctness even if every lock were bypassed
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.application.dto import NewRequest
from app.composition import build_container
from app.domain.enums import ExportStatus, RequestStatus
from app.domain.errors import (
    EpisodesAlreadyAssigned,
    InsufficientAssignedEpisodes,
    InvalidTransition,
    NoEpisodesAvailable,
    ResourceBusy,
)
from app.domain.models import Assignment
from app.infrastructure.db.session import build_engine
from app.main import create_app


async def _new_request(world, owner="client_a", n=5, task="pick cup", start_by="ops1") -> uuid.UUID:
    view = await world.c.requests.create(world.actor(owner), NewRequest(title="r", task_name=task, episodes_requested=n))
    if start_by:
        await world.c.requests.start(world.actor(start_by), view.request.id)
    return view.request.id


async def _active_rows(world) -> list[tuple[str, uuid.UUID]]:
    async with world.c.session_factory() as s:
        rows = await s.execute(text("SELECT episode_id, request_id FROM assignments WHERE released_at IS NULL"))
        return [(r[0], r[1]) for r in rows]


# ==================================================================================== the race itself
@pytest.mark.parametrize("round_", range(8))  # repeat: races are probabilistic; do it many times
async def test_two_operators_cannot_double_assign_the_same_episodes(world, round_):
    ids = await world.add_episodes(5)
    r1 = await _new_request(world, "client_a")
    r2 = await _new_request(world, "client_b")

    results = await asyncio.gather(
        world.c.requests.assign_episodes(world.actor("ops1"), r1, ids),
        world.c.requests.assign_episodes(world.actor("ops2"), r2, ids),
        return_exceptions=True,
    )

    winners = [r for r in results if not isinstance(r, BaseException)]
    losers = [r for r in results if isinstance(r, BaseException)]
    assert len(winners) == 1 and len(losers) == 1, results
    # The loser got the CLEAN domain error with the offending ids - which only the lock-protected
    # check produces (a raw unique-index violation carries no episode_ids).
    assert isinstance(losers[0], EpisodesAlreadyAssigned)
    assert sorted(losers[0].details["episode_ids"]) == sorted(ids)

    rows = await _active_rows(world)
    assert sorted(e for e, _ in rows) == sorted(ids)  # exactly 5 active rows...
    assert len({rid for _, rid in rows}) == 1  # ...all owned by a single request


async def test_row_lock_on_episodes_really_blocks_a_second_assigner(world):
    """Prove FOR UPDATE is doing work: while someone holds the episode rows, an assigner must WAIT."""
    ids = await world.add_episodes(3)
    rid = await _new_request(world, n=3)

    async with world.c.uow() as holder:
        await holder.episodes.lock_many(ids)  # transaction A takes the row locks and sits on them

        blocked = asyncio.create_task(world.c.requests.assign_episodes(world.actor("ops1"), rid, ids))
        await asyncio.sleep(0.4)
        assert not blocked.done(), "assigner did not block on the episode row locks"

        await holder.rollback()  # A lets go without assigning anything
    result = await asyncio.wait_for(blocked, timeout=5)  # B now proceeds and succeeds
    assert sorted(result.assigned_episode_ids) == sorted(ids)


async def test_request_row_lock_serialises_deliver_against_assignment(world):
    ids = await world.add_episodes(2)
    rid = await _new_request(world, n=2)
    await world.c.requests.assign_episodes(world.actor("ops1"), rid, ids)  # fully assigned

    async with world.c.uow() as holder:
        await holder.requests.get_for_update(rid)  # someone is mid-operation on this request
        deliver = asyncio.create_task(world.c.requests.deliver(world.actor("ops2"), rid))
        await asyncio.sleep(0.4)
        assert not deliver.done(), "deliver did not wait for the request lock"
        await holder.rollback()
    view = await asyncio.wait_for(deliver, timeout=5)
    assert view.request.status is RequestStatus.DELIVERED


@pytest.mark.parametrize("round_", range(5))
async def test_deliver_never_succeeds_while_under_assigned_even_when_racing_assignment(world, round_):
    """Request needs 3, has 2. One operator assigns the 3rd while another tries to deliver."""
    ids = await world.add_episodes(3)
    rid = await _new_request(world, n=3)
    await world.c.requests.assign_episodes(world.actor("ops1"), rid, ids[:2])

    deliver, assign = await asyncio.gather(
        world.c.requests.deliver(world.actor("ops2"), rid),
        world.c.requests.assign_episodes(world.actor("ops1"), rid, ids[2:]),
        return_exceptions=True,
    )
    assert not isinstance(assign, BaseException)  # the assignment always lands
    async with world.c.session_factory() as s:
        assigned = (await s.execute(text("SELECT count(*) FROM assignments WHERE released_at IS NULL"))).scalar_one()
    if isinstance(deliver, BaseException):  # deliver ran first, saw 2 < 3, was refused
        assert isinstance(deliver, InsufficientAssignedEpisodes)
    else:  # deliver ran after, saw 3 >= 3
        assert deliver.request.status is RequestStatus.DELIVERED
        assert assigned >= 3  # THE INVARIANT: never delivered with fewer than requested


# ==================================================================================== SKIP LOCKED
async def test_concurrent_auto_assign_hands_out_disjoint_sets(world):
    """10 requests (5 each = 50 wanted) fight over a pool of 40: nobody gets a duplicate, pool fully used."""
    await world.add_episodes(40)
    request_ids = [await _new_request(world, "client_a" if i % 2 else "client_b", n=5) for i in range(10)]

    results = await asyncio.gather(
        *(world.c.requests.auto_assign(world.actor("ops1" if i % 2 else "ops2"), rid) for i, rid in enumerate(request_ids)),
        return_exceptions=True,
    )
    ok = [r for r in results if not isinstance(r, BaseException)]
    failed = [r for r in results if isinstance(r, BaseException)]
    assert all(isinstance(f, NoEpisodesAvailable) for f in failed), failed  # only "pool empty" is acceptable

    rows = await _active_rows(world)
    ids = [e for e, _ in rows]
    assert len(ids) == len(set(ids)), "an episode was handed out twice"
    assert len(ids) == 40, f"pool should be fully distributed, got {len(ids)}"
    per_request = {}
    for _, rid in rows:
        per_request[rid] = per_request.get(rid, 0) + 1
    assert all(n <= 5 for n in per_request.values())
    assert sum(len(r.assigned_episode_ids) for r in ok) == 40


async def test_auto_assign_prefers_best_quality_and_newest(world):
    from datetime import UTC, datetime

    from app.domain.enums import Quality

    bad = await world.add_episodes(3, quality=Quality.BAD, prefix="B")
    usable = await world.add_episodes(3, quality=Quality.USABLE, prefix="U")
    good = await world.add_episodes(3, quality=Quality.GOOD, prefix="G", recorded_at=datetime(2026, 7, 1, tzinfo=UTC))
    rid = await _new_request(world, n=4)
    result = await world.c.requests.auto_assign(world.actor("ops1"), rid)
    # 3 good first (even though older), then the newest usable one
    assert set(good) <= set(result.assigned_episode_ids)
    assert len(set(result.assigned_episode_ids) & set(usable)) == 1 and not set(result.assigned_episode_ids) & set(bad)


# ==================================================================================== state transitions
async def test_only_one_of_many_concurrent_starts_wins(world):
    await world.add_episodes(1)
    rid = await _new_request(world, n=1, start_by=None)
    actors = [world.actor("ops1"), world.actor("ops2"), world.actor("admin")] * 2
    results = await asyncio.gather(*(world.c.requests.start(a, rid) for a in actors), return_exceptions=True)
    assert sum(not isinstance(r, BaseException) for r in results) == 1
    assert all(isinstance(r, InvalidTransition) for r in results if isinstance(r, BaseException))


async def test_accept_and_reject_race_has_exactly_one_winner(world):
    ids = await world.add_episodes(2)
    rid = await _new_request(world, n=2)
    await world.c.requests.assign_episodes(world.actor("ops1"), rid, ids)
    await world.c.requests.deliver(world.actor("ops1"), rid)

    results = await asyncio.gather(
        world.c.requests.accept(world.actor("client_a"), rid),
        world.c.requests.reject(world.actor("client_a"), rid, "nope"),
        return_exceptions=True,
    )
    assert sum(not isinstance(r, BaseException) for r in results) == 1
    final = (await world.c.requests.get(world.actor("ops1"), rid)).request.status
    assert final in (RequestStatus.ACCEPTED, RequestStatus.REJECTED)
    # consistency between the two tables: accepted keeps episodes, rejected releases them
    active = len(await _active_rows(world))
    assert active == (2 if final is RequestStatus.ACCEPTED else 0)


async def test_export_is_armed_exactly_once_when_final_assignments_race(world):
    ids = await world.add_episodes(4)
    rid = await _new_request(world, n=4)
    a, b = await asyncio.gather(
        world.c.requests.assign_episodes(world.actor("ops1"), rid, ids[:2]),
        world.c.requests.assign_episodes(world.actor("ops2"), rid, ids[2:]),
    )
    assert [a.export_scheduled, b.export_scheduled].count(True) == 1
    assert [a.fully_assigned, b.fully_assigned].count(True) == 1
    view = await world.c.requests.get(world.actor("ops1"), rid)
    assert view.request.export_status is ExportStatus.PENDING and view.assigned_count == 4


# ==================================================================================== layer 2: the constraint
async def test_unique_index_blocks_double_assignment_even_with_no_locking_at_all(world):
    """Bypass every service/lock and write rows directly: PostgreSQL itself must refuse."""
    (episode,) = await world.add_episodes(1)
    r1 = await _new_request(world, "client_a", n=1, start_by=None)
    r2 = await _new_request(world, "client_b", n=1, start_by=None)
    op = world.users["ops1"].id

    async with world.c.session_factory() as s:
        s.add(Assignment(request_id=r1, episode_id=episode, assigned_by_id=op))
        await s.commit()
    async with world.c.session_factory() as s:
        s.add(Assignment(request_id=r2, episode_id=episode, assigned_by_id=op))
        with pytest.raises(IntegrityError, match="uq_assignments_active_episode"):
            await s.commit()


async def test_unique_index_catches_two_unlocked_writers_racing(world):
    """Two raw transactions insert the same active claim concurrently: one commits, one is refused."""
    (episode,) = await world.add_episodes(1)
    r1 = await _new_request(world, "client_a", n=1, start_by=None)
    r2 = await _new_request(world, "client_b", n=1, start_by=None)
    op = world.users["ops1"].id

    async def raw_claim(rid):
        async with world.c.session_factory() as s:
            s.add(Assignment(request_id=rid, episode_id=episode, assigned_by_id=op))
            await s.commit()

    results = await asyncio.gather(raw_claim(r1), raw_claim(r2), return_exceptions=True)
    assert sum(isinstance(r, IntegrityError) for r in results) == 1
    assert len(await _active_rows(world)) == 1


# ==================================================================================== failing fast
async def test_lock_timeout_surfaces_as_503_not_a_hang(world, settings):
    """A stuck lock holder must not queue every other operator forever."""
    await world.add_episodes(1)
    rid = await _new_request(world, n=1, start_by=None)

    impatient_settings = settings.model_copy(update={"db_lock_timeout_ms": 300})
    engine = build_engine(impatient_settings)
    impatient = build_container(impatient_settings, engine=engine)
    try:
        async with world.c.uow() as holder:
            await holder.requests.get_for_update(rid)  # hold the row lock "forever"

            with pytest.raises(ResourceBusy):
                await impatient.requests.start(world.actor("ops1"), rid)

            app = create_app(impatient)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
                r = await c.post(f"/requests/{rid}/start", headers=world.headers("ops1"))
            assert r.status_code == 503
            assert r.headers["retry-after"] == "1"
            assert r.json()["error"]["code"] == "resource_busy"
    finally:
        await engine.dispose()
