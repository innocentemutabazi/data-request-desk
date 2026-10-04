"""Analytics are pure SQL aggregates; verify the numbers against hand-computed values."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import insert

from app.domain.enums import Quality
from app.domain.models import Episode
from tests.conftest import create_request


async def _seed_known(world):
    """task A (arm-01): durations 10,20,30,40,50 | task B (arm-02): 100,200."""
    rows, n = [], 0
    for task, robot, durs, quality in [
        ("pick cup", "arm-01", [10, 20, 30, 40, 50], [Quality.GOOD, Quality.GOOD, Quality.USABLE, Quality.BAD, Quality.GOOD]),
        ("fold towel", "arm-02", [100, 200], [Quality.GOOD, Quality.USABLE]),
    ]:
        for d, q in zip(durs, quality, strict=True):
            n += 1
            rows.append({"episode_id": f"EP-{n:03d}", "robot_id": robot, "task_name": task,
                         "recorded_at": datetime(2026, 8, 1 + (n % 3), 10, tzinfo=UTC), "duration_seconds": d,
                         "operator_name": "Aline" if n % 2 else None, "quality": q})
    async with world.c.session_factory() as s:
        await s.execute(insert(Episode), rows)
        await s.commit()


async def test_analytics_rejects_inverted_date_range(client, world):
    response = await client.get(
        "/analytics/episodes/breakdown",
        params={"recorded_from": "2026-08-02T00:00:00Z", "recorded_to": "2026-08-01T00:00:00Z"},
        headers=world.headers("ops1"),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_failed"


async def test_breakdown_by_task_matches_hand_computed_statistics(client, world):
    await _seed_known(world)
    r = await client.get("/analytics/episodes/breakdown", params={"group_by": "task_name"}, headers=world.headers("ops1"))
    assert r.status_code == 200
    rows = {x["key"]: x for x in r.json()}
    cup = rows["pick cup"]
    assert cup["episodes"] == 5 and cup["total_duration_seconds"] == 150
    assert cup["avg_duration_seconds"] == 30.0 and cup["min_duration_seconds"] == 10 and cup["max_duration_seconds"] == 50
    # percentile_cont (linear interpolation): p50 = 30 ; p90 = 40 + .6*10 = 46 ; p95 = 40 + .8*10 = 48
    assert (cup["p50_duration_seconds"], cup["p90_duration_seconds"], cup["p95_duration_seconds"]) == (30.0, 46.0, 48.0)
    assert cup["quality"] == {"good": 3, "usable": 1, "bad": 1}
    towel = rows["fold towel"]
    assert towel["p50_duration_seconds"] == 150.0 and towel["p90_duration_seconds"] == 190.0  # interpolates between 100 & 200
    assert [x["key"] for x in r.json()] == ["pick cup", "fold towel"]  # ordered by volume


@pytest.mark.parametrize("group_by,expected", [
    ("robot_id", {"arm-01": 5, "arm-02": 2}),
    ("quality", {"good": 4, "usable": 2, "bad": 1}),
    ("operator_name", {"Aline": 4, None: 3}),  # blank operators are grouped, not dropped
])
async def test_other_groupings(client, world, group_by, expected):
    await _seed_known(world)
    r = await client.get("/analytics/episodes/breakdown", params={"group_by": group_by}, headers=world.headers("admin"))
    assert {x["key"]: x["episodes"] for x in r.json()} == expected


async def test_breakdown_filters(client, world):
    await _seed_known(world)
    r = await client.get("/analytics/episodes/breakdown", headers=world.headers("ops1"),
                         params={"group_by": "quality", "task_name": "pick cup", "robot_id": "ARM-01"})
    assert {x["key"]: x["episodes"] for x in r.json()} == {"good": 3, "usable": 1, "bad": 1}
    r = await client.get("/analytics/episodes/breakdown", headers=world.headers("ops1"),
                         params={"group_by": "task_name", "quality": "good"})
    assert {x["key"]: x["episodes"] for x in r.json()} == {"pick cup": 3, "fold towel": 1}


async def test_group_by_is_a_whitelist_not_an_injection_vector(client, world):
    for evil in ["episode_id", "quality; DROP TABLE episodes", "1) UNION SELECT hashed_password FROM users --"]:
        r = await client.get("/analytics/episodes/breakdown", params={"group_by": evil}, headers=world.headers("ops1"))
        assert r.status_code == 422
    r = await client.get("/analytics/episodes/timeseries", params={"bucket": "year'); --"}, headers=world.headers("ops1"))
    assert r.status_code == 422


async def test_timeseries_buckets_by_day_in_utc(client, world):
    await _seed_known(world)
    r = await client.get("/analytics/episodes/timeseries", params={"bucket": "day"}, headers=world.headers("ops1"))
    pts = r.json()
    assert sum(p["episodes"] for p in pts) == 7 and [p["bucket"] for p in pts] == sorted(p["bucket"] for p in pts)
    assert all(p["bucket"].startswith("2026-08-0") for p in pts)
    month = (await client.get("/analytics/episodes/timeseries", params={"bucket": "month"}, headers=world.headers("ops1"))).json()
    assert month == [{"bucket": "2026-08-01", "episodes": 7, "total_duration_seconds": 450}]


async def test_timeseries_can_return_daily_counts_per_robot(client, world):
    await _seed_known(world)
    r = await client.get(
        "/analytics/episodes/timeseries",
        params={"bucket": "day", "per_robot": "true"},
        headers=world.headers("ops1"),
    )
    assert r.status_code == 200
    assert {row["robot_id"] for row in r.json()} == {"arm-01", "arm-02"}
    assert sum(row["episodes"] for row in r.json()) == 7


async def test_overview_counts_assigned_vs_available_and_the_request_funnel(client, world):
    await _seed_known(world)
    req = await create_request(client, world, episodes_requested=2)
    await client.post(f"/requests/{req['id']}/start", headers=world.headers("ops1"))
    await client.post(f"/requests/{req['id']}/assignments/auto", headers=world.headers("ops1"))
    await client.post(f"/requests/{req['id']}/deliver", headers=world.headers("ops1"))
    await client.post(f"/requests/{req['id']}/accept", headers=world.headers("client_a"))

    o = (await client.get("/analytics/overview", headers=world.headers("ops1"))).json()
    assert o["episodes_total"] == 7 and o["episodes_assigned"] == 2 and o["episodes_available"] == 5
    assert o["total_duration_seconds"] == 450 and o["quality"] == {"good": 4, "usable": 2, "bad": 1}
    assert o["requests"]["by_status"]["accepted"] == 1 and o["requests"]["acceptance_rate"] == 1.0
    assert o["requests"]["turnaround_hours_p50"] is not None


async def test_empty_database_returns_empty_not_errors(client, world):
    assert (await client.get("/analytics/episodes/breakdown", headers=world.headers("ops1"))).json() == []
    o = (await client.get("/analytics/overview", headers=world.headers("ops1"))).json()
    assert o["episodes_total"] == 0 and o["avg_duration_seconds"] is None and o["requests"]["acceptance_rate"] is None


async def test_analytics_never_materialises_rows_in_python(world):
    """Structural guard: the repository must only ever issue aggregate statements."""
    import inspect

    from app.infrastructure.db.repositories import analytics

    src = inspect.getsource(analytics)
    assert "select(Episode)" not in src and ".scalars()" not in src  # no ORM entity loading
    assert src.count("func.percentile_cont") >= 2 and "group_by" in src
