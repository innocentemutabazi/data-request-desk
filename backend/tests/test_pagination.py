"""Keyset pagination: correctness under ties, tamper-resistance, and proof the indexes are usable."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from app.domain.enums import Quality
from tests.conftest import create_request


async def _walk(client, url, headers, params=None, limit=10):
    """Follow cursors to the end; return every item and the number of pages."""
    items, pages, cursor = [], 0, None
    while True:
        q = {**(params or {}), "limit": limit, **({"cursor": cursor} if cursor else {})}
        r = await client.get(url, headers=headers, params=q)
        assert r.status_code == 200, r.text
        body = r.json()
        items += body["items"]
        pages += 1
        cursor = body["next_cursor"]
        if not cursor:
            return items, pages
        assert pages < 1000


async def test_episode_paging_has_no_gaps_or_duplicates_even_with_identical_timestamps(client, world):
    # 105 episodes in 3 groups sharing the SAME recorded_at: the tie-breaker (episode_id) is what keeps
    # keyset pages stable. Naive "WHERE recorded_at < last" would skip rows here.
    same = datetime(2026, 8, 1, 12, tzinfo=UTC)
    all_ids = []
    for i in range(3):
        all_ids += await world.add_episodes(35, prefix=f"T{i}", recorded_at=same)  # distinct minute offsets...
    async with world.c.session_factory() as s:  # ...then force wholesale ties
        await s.execute(text("UPDATE episodes SET recorded_at = :t WHERE episode_id LIKE 'T0-%' OR episode_id LIKE 'T1-%'"), {"t": same})
        await s.commit()

    items, pages = await _walk(client, "/episodes", world.headers("ops1"), limit=10)
    ids = [i["episode_id"] for i in items]
    assert len(ids) == len(set(ids)) == 105 and set(ids) == set(all_ids)
    assert pages == 11  # ceil(105/10)
    keys = [(i["recorded_at"], i["episode_id"]) for i in items]
    assert keys == sorted(keys, reverse=True)  # strict (recorded_at DESC, episode_id DESC)


@pytest.mark.parametrize("limit", [1, 7, 50, 200])
async def test_paging_is_independent_of_page_size(client, world, limit):
    await world.add_episodes(60)
    items, _ = await _walk(client, "/episodes", world.headers("ops1"), limit=limit)
    assert len(items) == 60 and len({i["episode_id"] for i in items}) == 60


async def test_last_page_has_no_cursor_and_exact_multiples_do_not_emit_a_phantom_page(client, world):
    await world.add_episodes(20)
    r = await client.get("/episodes", headers=world.headers("ops1"), params={"limit": 20})
    assert len(r.json()["items"]) == 20 and r.json()["next_cursor"] is None  # we fetch limit+1 to know


async def test_filters_compose_with_cursors(client, world):
    await world.add_episodes(30, task="pick cup", quality=Quality.GOOD, prefix="A")
    await world.add_episodes(30, task="pick cup", quality=Quality.BAD, prefix="B")
    await world.add_episodes(30, task="fold towel", quality=Quality.GOOD, prefix="C")
    items, _ = await _walk(client, "/episodes", world.headers("ops1"), {"task_name": "Pick  CUP", "quality": "good"}, limit=8)
    assert len(items) == 30 and all(i["episode_id"].startswith("A-") for i in items)
    items, _ = await _walk(client, "/episodes", world.headers("ops1"), {"quality": ["good", "bad"]}, limit=8)
    assert len(items) == 90


async def test_availability_filter_uses_active_assignments(client, world):
    ids = await world.add_episodes(10)
    req = await create_request(client, world, episodes_requested=4)
    await client.post(f"/requests/{req['id']}/start", headers=world.headers("ops1"))
    await client.post(f"/requests/{req['id']}/assignments", json={"episode_ids": ids[:4]}, headers=world.headers("ops1"))
    avail, _ = await _walk(client, "/episodes", world.headers("ops1"), {"availability": "available"})
    taken, _ = await _walk(client, "/episodes", world.headers("ops1"), {"availability": "assigned"})
    assert len(avail) == 6 and {t["episode_id"] for t in taken} == set(ids[:4])
    assert all(t["assigned_request_id"] == req["id"] for t in taken)
    cands, _ = await _walk(client, f"/requests/{req['id']}/candidates", world.headers("ops1"))
    assert {c["episode_id"] for c in cands} == set(ids[4:])


async def test_request_listing_is_keyset_paginated_newest_first(client, world):
    await world.add_episodes(3)
    made = [(await create_request(client, world, "client_a", title=f"R{i}"))["id"] for i in range(23)]
    items, pages = await _walk(client, "/requests", world.headers("client_a"), limit=5)
    assert [i["id"] for i in items] == list(reversed(made)) and pages == 5
    only_submitted, _ = await _walk(client, "/requests", world.headers("ops1"), {"status": "submitted"}, limit=10)
    assert len(only_submitted) == 23


@pytest.mark.parametrize("bad", ["garbage", "", "e30", base64.urlsafe_b64encode(b'["only-one"]').decode(),
                                 base64.urlsafe_b64encode(b'["not-a-date","EP-1"]').decode(),
                                 base64.urlsafe_b64encode(b'{"a":1}').decode()])
async def test_tampered_cursors_are_a_clean_400(client, world, bad):
    r = await client.get("/episodes", headers=world.headers("ops1"), params={"cursor": bad or "x"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_cursor"


async def test_limit_is_bounded(client, world):
    assert (await client.get("/episodes", headers=world.headers("ops1"), params={"limit": 10_000})).status_code == 422
    assert (await client.get("/episodes", headers=world.headers("ops1"), params={"limit": 0})).status_code == 422


async def test_a_forged_cursor_cannot_widen_a_clients_scope(client, world):
    """Cursors carry position only; the caller's row-level filter is re-applied to every page."""
    await world.add_episodes(3)
    mine = await create_request(client, world, "client_a")
    theirs = await create_request(client, world, "client_b")
    forged = base64.urlsafe_b64encode(f'["2999-01-01T00:00:00+00:00","{theirs["id"]}"]'.encode()).decode().rstrip("=")
    r = await client.get("/requests", headers=world.headers("client_a"), params={"cursor": forged})
    assert [i["id"] for i in r.json()["items"]] == [mine["id"]]


# ------------------------------------------------------------------ the indexes can actually serve these queries
async def _plan(world, sql: str, drop: tuple[str, ...] = ()) -> str:
    """EXPLAIN inside a transaction that is always rolled back.

    * SET LOCAL scopes the planner overrides to this transaction (no leakage onto pooled connections).
    * DDL is transactional in PostgreSQL, so we can DROP competing indexes to ask the sharper
      question "CAN this index serve the query with no sort step?" - then roll the drop back.
    """
    async with world.c.session_factory() as s:
        await s.execute(text("SET LOCAL enable_seqscan = off"))  # tiny table => force the planner's hand
        await s.execute(text("SET LOCAL enable_bitmapscan = off"))
        for index in drop:
            await s.execute(text(f"DROP INDEX {index}"))
        plan = "\n".join(r[0] for r in await s.execute(text("EXPLAIN " + sql)))
        await s.rollback()
        return plan


async def test_keyset_queries_use_composite_indexes_with_no_sort_step(world):
    await world.add_episodes(50)
    # (1) task = ? AND quality = ?  ORDER BY recorded_at DESC  + keyset predicate -> the spec'd composite
    #     index, scanned backwards, no Sort node. Competing indexes dropped so it is the only candidate.
    plan = await _plan(
        world,
        """SELECT * FROM episodes WHERE task_name='pick cup' AND quality='good'
           AND (recorded_at, episode_id) < ('2026-09-01+00','EP-5')
           ORDER BY recorded_at DESC, episode_id DESC LIMIT 51""",
        drop=("ix_episodes_task_recorded_at", "ix_episodes_recorded_at_episode_id"),
    )
    assert "Index Scan Backward using ix_episodes_task_quality_recorded_at" in plan and "Sort" not in plan, plan

    # (2) task only (or quality IN (...)) -> (task, recorded_at, id): ordered without a Sort
    plan = await _plan(
        world,
        "SELECT * FROM episodes WHERE task_name='pick cup' ORDER BY recorded_at DESC, episode_id DESC LIMIT 51",
        drop=("ix_episodes_recorded_at_episode_id",),
    )
    assert "ix_episodes_task_recorded_at" in plan and "Sort" not in plan, plan

    # (3) unfiltered global feed
    plan = await _plan(world, "SELECT * FROM episodes ORDER BY recorded_at DESC, episode_id DESC LIMIT 51")
    assert "ix_episodes_recorded_at_episode_id" in plan and "Sort" not in plan, plan


async def test_one_active_assignment_per_episode_probe_uses_the_partial_index(world):
    await world.add_episodes(5)
    plan = await _plan(world, "SELECT 1 FROM assignments WHERE episode_id = 'EP-00001' AND released_at IS NULL")
    assert "uq_assignments_active_episode" in plan, plan


async def test_request_summary_counts_are_scoped_and_complete(client, world):
    await world.add_episodes(3)
    for owner in ("client_a", "client_a", "client_b"):
        await create_request(client, world, owner, episodes_requested=1)
    mine = (await client.get("/requests/summary", headers=world.headers("client_a"))).json()
    everyone = (await client.get("/requests/summary", headers=world.headers("ops1"))).json()
    assert mine == {"submitted": 2, "in_progress": 0, "delivered": 0, "accepted": 0, "rejected": 0}
    assert everyone["submitted"] == 3 and set(everyone) == {"submitted", "in_progress", "delivered", "accepted", "rejected"}
