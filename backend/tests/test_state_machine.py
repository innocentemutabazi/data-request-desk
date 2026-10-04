"""The request lifecycle: pure rules (exhaustive) + end-to-end behaviour through the API."""

from __future__ import annotations

import itertools

import pytest
from sqlalchemy import text

from app.domain.enums import Quality, RequestStatus, UserRole
from app.domain.errors import InvalidTransition, PermissionDenied
from app.domain.state_machine import TRANSITIONS, authorize_transition, available_targets
from tests.conftest import create_request

S = RequestStatus


# ============================================================================ pure rules (no DB)
LEGAL = {
    (S.SUBMITTED, S.IN_PROGRESS): {UserRole.ADMIN, UserRole.OPERATOR},
    (S.IN_PROGRESS, S.DELIVERED): {UserRole.ADMIN, UserRole.OPERATOR},
    (S.DELIVERED, S.ACCEPTED): {UserRole.CLIENT},
    (S.DELIVERED, S.REJECTED): {UserRole.CLIENT},
    (S.REJECTED, S.IN_PROGRESS): {UserRole.ADMIN, UserRole.OPERATOR},
}


def test_transition_table_matches_the_spec_exactly():
    assert {k: set(v) for k, v in TRANSITIONS.items()} == LEGAL


@pytest.mark.parametrize(
    "current,target,role", list(itertools.product(RequestStatus, RequestStatus, UserRole))
)
def test_every_possible_transition_for_every_role(current, target, role):
    """5 states x 5 states x 3 roles = 75 cases; nothing outside the table may ever succeed."""
    may_reach_target = any(to == target and role in roles for (_, to), roles in LEGAL.items())
    is_legal_edge = (current, target) in LEGAL and role in LEGAL[(current, target)]

    if is_legal_edge:
        authorize_transition(current, target, role)  # must not raise
    elif not may_reach_target:
        with pytest.raises(PermissionDenied):  # wrong ROLE for this destination -> 403
            authorize_transition(current, target, role)
    else:
        with pytest.raises(InvalidTransition):  # right role, wrong STATE -> 409
            authorize_transition(current, target, role)


def test_only_accepted_is_terminal():
    assert S.ACCEPTED.is_terminal
    assert not S.REJECTED.is_terminal
    assert available_targets(S.ACCEPTED, UserRole.OPERATOR) == []
    assert available_targets(S.REJECTED, UserRole.OPERATOR) == [S.IN_PROGRESS]


def test_only_clients_can_decide():
    assert available_targets(S.DELIVERED, UserRole.CLIENT) == [S.ACCEPTED, S.REJECTED]
    assert available_targets(S.DELIVERED, UserRole.OPERATOR) == []
    assert available_targets(S.DELIVERED, UserRole.ADMIN) == []


# ============================================================================ through the API
async def _ready_request(client, world, n=3, owner="client_a", staff="ops1"):
    """A started request that has been fully assigned."""
    await world.add_episodes(n + 2)
    req = await create_request(client, world, owner, episodes_requested=n)
    r = await client.post(f"/requests/{req['id']}/start", headers=world.headers(staff))
    assert r.status_code == 200, r.text
    r = await client.post(f"/requests/{req['id']}/assignments/auto", headers=world.headers(staff))
    assert r.status_code == 201, r.text
    return req["id"]


async def test_happy_path_submitted_to_accepted(client, world):
    await world.add_episodes(5)
    req = await create_request(client, world, episodes_requested=3)
    rid = req["id"]
    assert req["status"] == "submitted"
    assert req["available_transitions"] == []  # clients cannot move a submitted request

    r = await client.post(f"/requests/{rid}/start", headers=world.headers("ops1"))
    assert r.status_code == 200
    started = r.json()
    assert started["status"] == "in_progress" and started["started_at"] and started["operator_id"]

    r = await client.post(f"/requests/{rid}/assignments/auto", headers=world.headers("ops1"))
    assert r.status_code == 201 and r.json()["fully_assigned"] is True

    r = await client.post(f"/requests/{rid}/deliver", headers=world.headers("ops1"))
    assert r.status_code == 200 and r.json()["status"] == "delivered" and r.json()["delivered_at"]

    r = await client.post(f"/requests/{rid}/accept", headers=world.headers("client_a"))
    assert r.status_code == 200
    done = r.json()
    assert done["status"] == "accepted" and done["decided_at"] and done["assigned_count"] == 3
    assert done["available_transitions"] == []


async def test_admin_can_drive_operator_transitions(client, world):
    await world.add_episodes(3)
    req = await create_request(client, world, episodes_requested=2)
    assert (await client.post(f"/requests/{req['id']}/start", headers=world.headers("admin"))).status_code == 200
    assert (await client.post(f"/requests/{req['id']}/assignments/auto", headers=world.headers("admin"))).status_code == 201
    assert (await client.post(f"/requests/{req['id']}/deliver", headers=world.headers("admin"))).status_code == 200


@pytest.mark.parametrize("path", ["deliver", "accept", "reject"])
async def test_cannot_skip_ahead_from_submitted(client, world, path):
    await world.add_episodes(3)
    req = await create_request(client, world)
    who = "client_a" if path in ("accept", "reject") else "ops1"
    r = await client.post(f"/requests/{req['id']}/{path}", headers=world.headers(who))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "invalid_transition"


async def test_cannot_start_twice_or_move_backwards(client, world):
    rid = await _ready_request(client, world)
    r = await client.post(f"/requests/{rid}/start", headers=world.headers("ops1"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"


async def test_client_cannot_accept_before_delivery(client, world):
    rid = await _ready_request(client, world)  # in_progress, fully assigned, NOT delivered
    r = await client.post(f"/requests/{rid}/accept", headers=world.headers("client_a"))
    assert r.status_code == 409


@pytest.mark.parametrize("decision", ["accept", "reject"])
async def test_accepted_is_terminal_but_rejected_can_reenter_work(client, world, decision):
    rid = await _ready_request(client, world)
    await client.post(f"/requests/{rid}/deliver", headers=world.headers("ops1"))
    assert (await client.post(f"/requests/{rid}/{decision}", headers=world.headers("client_a"))).status_code == 200
    if decision == "accept":
        for again in ("accept", "reject"):
            r = await client.post(f"/requests/{rid}/{again}", headers=world.headers("client_a"))
            assert r.status_code == 409, f"{decision} then {again}"
    else:
        r = await client.post(f"/requests/{rid}/rework", headers=world.headers("ops1"))
        assert r.status_code == 200 and r.json()["status"] == "in_progress"
        assert [h["to_status"] for h in r.json()["status_history"]] == ["submitted", "in_progress", "delivered", "rejected", "in_progress"]


# ---------------------------------------------------------------- the delivery guard
async def test_cannot_deliver_without_enough_assigned_episodes(client, world):
    ids = await world.add_episodes(5)
    req = await create_request(client, world, episodes_requested=3)
    rid = req["id"]
    await client.post(f"/requests/{rid}/start", headers=world.headers("ops1"))

    # 0 of 3
    r = await client.post(f"/requests/{rid}/deliver", headers=world.headers("ops1"))
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "insufficient_assigned_episodes"
    assert err["details"] == {"assigned": 0, "requested": 3}

    # 2 of 3
    r = await client.post(f"/requests/{rid}/assignments", json={"episode_ids": ids[:2]}, headers=world.headers("ops1"))
    assert r.status_code == 201 and r.json()["fully_assigned"] is False
    r = await client.post(f"/requests/{rid}/deliver", headers=world.headers("ops1"))
    assert r.status_code == 409 and r.json()["error"]["details"] == {"assigned": 2, "requested": 3}

    # 3 of 3 -> allowed (assigned >= requested)
    await client.post(f"/requests/{rid}/assignments", json={"episode_ids": [ids[2]]}, headers=world.headers("ops1"))
    r = await client.post(f"/requests/{rid}/deliver", headers=world.headers("ops1"))
    assert r.status_code == 200 and r.json()["status"] == "delivered"


# ---------------------------------------------------------------- assignment rules
async def test_assignment_only_allowed_while_in_progress(client, world):
    ids = await world.add_episodes(3)
    req = await create_request(client, world)
    r = await client.post(f"/requests/{req['id']}/assignments", json={"episode_ids": ids[:1]}, headers=world.headers("ops1"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "request_not_assignable"


async def test_cannot_assign_more_than_requested(client, world):
    ids = await world.add_episodes(6)
    req = await create_request(client, world, episodes_requested=2)
    await client.post(f"/requests/{req['id']}/start", headers=world.headers("ops1"))
    r = await client.post(f"/requests/{req['id']}/assignments", json={"episode_ids": ids[:3]}, headers=world.headers("ops1"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "assignment_exceeds_request"


async def test_episodes_must_match_request_criteria(client, world):
    good = await world.add_episodes(2, task="pick cup", quality=Quality.GOOD)
    other_task = await world.add_episodes(1, task="fold towel", prefix="FT")
    bad_q = await world.add_episodes(1, task="pick cup", quality=Quality.BAD, prefix="BQ")
    req = await create_request(client, world, episodes_requested=3, min_quality="usable")
    await client.post(f"/requests/{req['id']}/start", headers=world.headers("ops1"))

    r = await client.post(
        f"/requests/{req['id']}/assignments", json={"episode_ids": [good[0], other_task[0], bad_q[0]]},
        headers=world.headers("ops1"),
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "episode_criteria_mismatch"
    assert sorted(r.json()["error"]["details"]["episode_ids"]) == sorted([other_task[0], bad_q[0]])


async def test_unknown_episode_ids_rejected(client, world):
    await world.add_episodes(3)
    req = await create_request(client, world)
    await client.post(f"/requests/{req['id']}/start", headers=world.headers("ops1"))
    r = await client.post(f"/requests/{req['id']}/assignments", json={"episode_ids": ["EP-99999"]}, headers=world.headers("ops1"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "episodes_not_found"


async def test_episode_cannot_belong_to_two_requests(client, world):
    ids = await world.add_episodes(3)
    r1 = await create_request(client, world, "client_a", episodes_requested=2)
    r2 = await create_request(client, world, "client_b", episodes_requested=2)
    for rid in (r1["id"], r2["id"]):
        await client.post(f"/requests/{rid}/start", headers=world.headers("ops1"))

    ok = await client.post(f"/requests/{r1['id']}/assignments", json={"episode_ids": ids[:2]}, headers=world.headers("ops1"))
    assert ok.status_code == 201
    clash = await client.post(f"/requests/{r2['id']}/assignments", json={"episode_ids": [ids[1], ids[2]]}, headers=world.headers("ops2"))
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "episodes_already_assigned"
    assert clash.json()["error"]["details"]["episode_ids"] == [ids[1]]


async def test_rejecting_releases_episodes_back_to_the_pool(client, world):
    ids = await world.add_episodes(3)
    r1 = await create_request(client, world, "client_a", episodes_requested=3)
    r2 = await create_request(client, world, "client_b", episodes_requested=3)
    for rid in (r1["id"], r2["id"]):
        await client.post(f"/requests/{rid}/start", headers=world.headers("ops1"))
    await client.post(f"/requests/{r1['id']}/assignments/auto", headers=world.headers("ops1"))

    # the pool is exhausted while r1 holds everything
    r = await client.post(f"/requests/{r2['id']}/assignments/auto", headers=world.headers("ops1"))
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_episodes_available"

    await client.post(f"/requests/{r1['id']}/deliver", headers=world.headers("ops1"))
    rej = await client.post(f"/requests/{r1['id']}/reject", json={"reason": "Wrong lighting"}, headers=world.headers("client_a"))
    assert rej.status_code == 200
    assert rej.json()["status"] == "rejected" and rej.json()["decision_reason"] == "Wrong lighting"
    assert rej.json()["assigned_count"] == 0  # released

    # ...and now they can be assigned to someone else ("at a time", not "ever")
    r = await client.post(f"/requests/{r2['id']}/assignments", json={"episode_ids": ids}, headers=world.headers("ops1"))
    assert r.status_code == 201

    # history is retained for audit: 3 released rows + 3 active rows
    async with world.c.session_factory() as s:
        rows = (await s.execute(text("SELECT count(*) FILTER (WHERE released_at IS NULL), count(*) FROM assignments"))).one()
    assert tuple(rows) == (3, 6)


async def test_accept_keeps_episodes_assigned(client, world):
    rid = await _ready_request(client, world)
    await client.post(f"/requests/{rid}/deliver", headers=world.headers("ops1"))
    await client.post(f"/requests/{rid}/accept", headers=world.headers("client_a"))
    r = await client.get(f"/requests/{rid}", headers=world.headers("client_a"))
    assert r.json()["assigned_count"] == 3


async def test_clients_see_episodes_only_after_delivery(client, world):
    rid = await _ready_request(client, world)
    r = await client.get(f"/requests/{rid}/assignments", headers=world.headers("client_a"))
    assert r.status_code == 403
    assert (await client.get(f"/requests/{rid}/assignments", headers=world.headers("ops1"))).status_code == 200
    await client.post(f"/requests/{rid}/deliver", headers=world.headers("ops1"))
    r = await client.get(f"/requests/{rid}/assignments", headers=world.headers("client_a"))
    assert r.status_code == 200 and len(r.json()["items"]) == 3


async def test_request_validation(client, world):
    await world.add_episodes(1)
    h = world.headers("client_a")
    assert (await client.post("/requests", json={"title": "x", "task_name": "pick cup", "episodes_requested": 0}, headers=h)).status_code == 422
    assert (await client.post("/requests", json={"title": "", "task_name": "pick cup", "episodes_requested": 1}, headers=h)).status_code == 422
    r = await client.post("/requests", json={"title": "x", "task_name": "juggle chainsaws", "episodes_requested": 1}, headers=h)
    assert r.status_code == 422 and "Unknown task" in r.json()["error"]["message"]
    r = await client.post(
        "/requests",
        json={"title": "x", "task_name": "  Pick   CUP ", "episodes_requested": 1,
              "recorded_after": "2026-09-01T00:00:00Z", "recorded_before": "2026-08-01T00:00:00Z"},
        headers=h,
    )
    assert r.status_code == 422  # inverted window
    r = await client.post("/requests", json={"title": "x", "task_name": "  Pick   CUP ", "episodes_requested": 1}, headers=h)
    assert r.status_code == 201 and r.json()["task_name"] == "pick cup"  # normalised like the import
