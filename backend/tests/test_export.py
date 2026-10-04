"""Background export: tracking, retries, and safety under concurrency / crashes."""

from __future__ import annotations

import asyncio
import random
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.application.dto import NewRequest
from app.application.services.export_service import ExportService
from app.domain.enums import ExportStatus
from app.infrastructure.exports.simulator import ExportSimulator
from tests.conftest import create_request


async def _status(world, rid):
    return (await world.c.requests.get(world.actor("ops1"), rid)).request


async def _fully_assigned_request(client, world, n=2):
    await world.add_episodes(n)
    req = await create_request(client, world, episodes_requested=n)
    await client.post(f"/requests/{req['id']}/start", headers=world.headers("ops1"))
    return req["id"]


async def test_recovery_queries_pending_and_stale_exports(settings, simulator, monkeypatch):
    requests = SimpleNamespace(pending_export_ids=AsyncMock(return_value=[]))

    class RecoveryUow:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def commit(self):
            return None

    uow = RecoveryUow()
    uow.requests = requests

    async def stop(_: float) -> None:
        raise asyncio.CancelledError

    service = ExportService(lambda: uow, settings, simulator)
    monkeypatch.setattr("app.application.services.export_service.asyncio.sleep", stop)

    with pytest.raises(asyncio.CancelledError):
        await service.recover_in_flight()

    requests.pending_export_ids.assert_awaited_once_with(
        stale_after_seconds=settings.export_stale_after_seconds
    )


async def test_no_export_until_the_request_is_fully_assigned(client, world):
    ids = await world.add_episodes(3)
    req = await create_request(client, world, episodes_requested=3)
    await client.post(f"/requests/{req['id']}/start", headers=world.headers("ops1"))
    r = await client.post(f"/requests/{req['id']}/assignments", json={"episode_ids": ids[:2]}, headers=world.headers("ops1"))
    assert r.json()["export_scheduled"] is False and r.json()["request"]["export"]["status"] == "not_started"


async def test_assignment_triggers_background_export_that_succeeds(client, world):
    rid = await _fully_assigned_request(client, world)
    r = await client.post(f"/requests/{rid}/assignments/auto", headers=world.headers("ops1"))
    assert r.json()["export_scheduled"] is True
    assert r.json()["request"]["export"]["status"] == "pending"  # response is immediate; work happens after
    # httpx's ASGI transport waits for the background task, so by now it has run (instantly, in tests)
    exp = (await client.get(f"/requests/{rid}", headers=world.headers("ops1"))).json()["export"]
    assert exp["status"] == "succeeded" and exp["attempts"] == 1 and exp["error"] is None and exp["max_attempts"] == 3


async def test_failing_export_retries_then_fails_and_records_why(client, world, settings):
    settings.export_failure_rate = 1.0  # every attempt fails
    rid = await _fully_assigned_request(client, world)
    await client.post(f"/requests/{rid}/assignments/auto", headers=world.headers("ops1"))
    exp = (await client.get(f"/requests/{rid}", headers=world.headers("ops1"))).json()["export"]
    assert exp["status"] == "failed" and exp["attempts"] == 3
    assert exp["error"].startswith("Attempt 3/3 failed")
    # the failure of the export does NOT block the business workflow
    assert (await client.post(f"/requests/{rid}/deliver", headers=world.headers("ops1"))).status_code == 200


async def test_flaky_export_succeeds_after_a_retry(client, world, settings, container):
    """~20% failure with automatic retries: first attempt fails, second succeeds."""
    outcomes = iter([True, False])  # fail, then succeed

    class Scripted(random.Random):
        def uniform(self, a, b):  # type: ignore[override]
            return 0.0  # sleep-duration/jitter draws must not consume the scripted outcomes

        def choice(self, seq):  # type: ignore[override]
            return seq[0]  # (CPython's choice() would otherwise call our overridden random())

        def random(self):  # type: ignore[override]
            return 0.0 if next(outcomes) else 0.99  # < failure_rate => fail

    async def no_sleep(_):
        return None

    container.exports._sim = ExportSimulator(settings, rng=Scripted(), sleep=no_sleep)
    settings.export_failure_rate = 0.2
    rid = await _fully_assigned_request(client, world)
    await client.post(f"/requests/{rid}/assignments/auto", headers=world.headers("ops1"))
    exp = (await client.get(f"/requests/{rid}", headers=world.headers("ops1"))).json()["export"]
    assert exp["status"] == "succeeded" and exp["attempts"] == 2
    # a success clears the error; attempts == 2 is what tells the UI "this needed a retry"
    assert exp["error"] is None


async def test_manual_retry_resets_and_reruns_a_failed_export(client, world, settings):
    settings.export_failure_rate = 1.0
    rid = await _fully_assigned_request(client, world)
    await client.post(f"/requests/{rid}/assignments/auto", headers=world.headers("ops1"))
    assert (await _status(world, rid)).export_status is ExportStatus.FAILED

    settings.export_failure_rate = 0.0
    r = await client.post(f"/requests/{rid}/export/retry", headers=world.headers("ops2"))
    assert r.status_code == 202 and r.json()["export"]["status"] == "pending" and r.json()["export"]["attempts"] == 0
    exp = (await client.get(f"/requests/{rid}", headers=world.headers("ops1"))).json()["export"]
    assert exp["status"] == "succeeded" and exp["attempts"] == 1 and exp["error"] is None


async def test_only_failed_exports_can_be_retried_and_only_by_staff(client, world):
    rid = await _fully_assigned_request(client, world)
    await client.post(f"/requests/{rid}/assignments/auto", headers=world.headers("ops1"))  # succeeds
    r = await client.post(f"/requests/{rid}/export/retry", headers=world.headers("ops1"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "export_not_retryable"
    assert (await client.post(f"/requests/{rid}/export/retry", headers=world.headers("client_a"))).status_code == 403


# ------------------------------------------------------------------------ concurrency / crash safety
def _slow_service(container, settings, seconds=0.2) -> ExportService:
    async def real_sleep(_):
        await asyncio.sleep(seconds)

    return ExportService(container.uow, settings, ExportSimulator(settings, rng=random.Random(0), sleep=real_sleep))


async def _pending_request(world, container):
    await world.add_episodes(1)
    view = await container.requests.create(world.actor("client_a"), NewRequest(title="t", task_name="pick cup", episodes_requested=1))
    rid = view.request.id
    await container.requests.start(world.actor("ops1"), rid)
    await container.requests.assign_episodes(world.actor("ops1"), rid, ["EP-00001"])
    assert (await _status(world, rid)).export_status is ExportStatus.PENDING
    return rid


async def test_two_workers_racing_for_one_export_exactly_one_runs_it(world, container, settings):
    rid = await _pending_request(world, container)
    svc = _slow_service(container, settings)
    results = await asyncio.gather(*(svc.run(rid) for _ in range(5)))
    assert results.count(ExportStatus.SUCCEEDED) == 1 and results.count(None) == 4
    assert (await _status(world, rid)).export_attempts == 1  # work was done once, not five times


async def test_finished_exports_are_never_re_run(world, container, settings):
    rid = await _pending_request(world, container)
    svc = _slow_service(container, settings, 0)
    assert await svc.run(rid) is ExportStatus.SUCCEEDED
    assert await svc.run(rid) is None  # claim only matches 'pending' (or stale 'running')


async def test_orphaned_running_export_is_recovered_only_after_its_heartbeat_goes_stale(world, container, settings, engine):
    rid = await _pending_request(world, container)
    svc = _slow_service(container, settings, 0)
    async with engine.begin() as c:  # simulate a worker that crashed mid-export just now
        await c.execute(text("UPDATE requests SET export_status='running', export_attempts=1, export_updated_at=now()"))
    assert await svc.run(rid) is None  # fresh heartbeat => presumed alive, hands off
    async with engine.begin() as c:  # ...and the same row once the heartbeat is old
        await c.execute(text("UPDATE requests SET export_updated_at = now() - interval '10 minutes'"))
    assert await svc.run(rid) is ExportStatus.SUCCEEDED  # reclaimed


async def test_reclaimed_worker_cannot_finish_a_new_export_generation(world, container, settings, engine):
    rid = await _pending_request(world, container)
    async with container.uow() as uow:
        old_generation = await uow.requests.claim_export(rid, settings.export_stale_after_seconds)
        await uow.commit()
    assert old_generation is not None
    async with engine.begin() as c:
        await c.execute(text("UPDATE requests SET export_updated_at = now() - interval '10 minutes'"))
    async with container.uow() as uow:
        new_generation = await uow.requests.claim_export(rid, settings.export_stale_after_seconds)
        await uow.commit()
    assert new_generation is not None and new_generation != old_generation

    async with container.uow() as uow:
        assert not await uow.requests.finish_export(
            rid, old_generation, status=ExportStatus.SUCCEEDED, error=None
        )
        await uow.commit()
    async with container.uow() as uow:
        assert await uow.requests.finish_export(
            rid, new_generation, status=ExportStatus.SUCCEEDED, error=None
        )
        await uow.commit()
    assert (await _status(world, rid)).export_status is ExportStatus.SUCCEEDED


async def test_rework_starts_a_fresh_export_cycle(client, world, settings):
    rid = await _fully_assigned_request(client, world)
    await client.post(f"/requests/{rid}/assignments/auto", headers=world.headers("ops1"))
    assert (await _status(world, rid)).export_status is ExportStatus.SUCCEEDED
    await client.post(f"/requests/{rid}/deliver", headers=world.headers("ops1"))
    await client.post(f"/requests/{rid}/reject", json={"reason": "Needs a different sample"}, headers=world.headers("client_a"))
    reworked = await client.post(f"/requests/{rid}/rework", headers=world.headers("ops1"))
    assert reworked.status_code == 200 and reworked.json()["export"]["status"] == "not_started"
    assigned = await client.post(f"/requests/{rid}/assignments/auto", headers=world.headers("ops1"))
    assert assigned.status_code == 201 and assigned.json()["export_scheduled"] is True
    assert (await _status(world, rid)).export_status is ExportStatus.SUCCEEDED


async def test_export_runs_without_holding_a_database_transaction(world, container, settings, engine):
    """The 2-5s 'work' must not pin a connection / row lock, or exports would starve the pool."""
    rid = await _pending_request(world, container)
    svc = _slow_service(container, settings, 0.5)
    task = asyncio.create_task(svc.run(rid))
    await asyncio.sleep(0.2)  # mid-"export"
    async with engine.connect() as c:
        idle_in_tx = (await c.execute(text(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND state = 'idle in transaction'"
        ))).scalar_one()
        status = (await c.execute(text("SELECT export_status FROM requests"))).scalar_one()
    assert status == "running" and idle_in_tx == 0
    # and the request is freely lockable by operators meanwhile
    await asyncio.wait_for(container.requests.deliver(world.actor("ops1"), rid), timeout=2)
    assert await task is ExportStatus.SUCCEEDED
