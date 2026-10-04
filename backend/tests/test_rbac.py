"""Authentication + role-based access control, including object-level (row) security."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import text

from app.domain.enums import UserRole
from tests.conftest import create_request


# ----------------------------------------------------------------------------- authentication
async def test_login_success_and_me(client, world):
    r = await client.post("/auth/login", data={"username": "ops1@example.com", "password": "pw-for-tests"})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["user"]["role"] == "operator"
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == "ops1@example.com"
    assert "hashed_password" not in me.text


async def test_login_failures_are_indistinguishable(client, world):
    wrong_pw = await client.post("/auth/login", data={"username": "ops1@example.com", "password": "nope"})
    no_user = await client.post("/auth/login", data={"username": "ghost@example.com", "password": "nope"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json()["error"]["message"] == no_user.json()["error"]["message"]  # no user enumeration


async def test_inactive_user_cannot_log_in_or_use_token(client, world):
    await world.add_user("ghost", UserRole.CLIENT, is_active=False)
    r = await client.post("/auth/login", data={"username": "ghost@example.com", "password": "pw-for-tests"})
    assert r.status_code == 401
    assert (await client.get("/auth/me", headers=world.headers("ghost"))).status_code == 401


@pytest.mark.parametrize("path", ["/requests", "/auth/me", "/analytics/overview", "/episodes", "/catalog/tasks"])
async def test_endpoints_require_authentication(client, path):
    r = await client.get(path)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "authentication_failed"
    assert r.headers["www-authenticate"] == "Bearer"


async def test_garbage_tampered_and_expired_tokens_rejected(client, world, settings):
    good = world.headers("ops1")["Authorization"].split()[1]
    forged = jwt.encode({"sub": str(world.users["ops1"].id)}, "wrong-secret-wrong-secret-wrong-secret!!", algorithm="HS256")
    none_alg = jwt.encode(
        {"sub": str(world.users["admin"].id), "iss": settings.jwt_issuer, "aud": settings.jwt_audience,
         "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(hours=1)},
        key="", algorithm="none",
    )
    expired = world.tokens.issue(world.users["ops1"], now=datetime.now(UTC) - timedelta(hours=3))
    wrong_aud = jwt.encode(
        {"sub": str(world.users["ops1"].id), "iss": settings.jwt_issuer, "aud": "someone-else",
         "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(hours=1)},
        settings.jwt_secret, algorithm="HS256",
    )
    for bad in ["not-a-jwt", good[:-3] + "abc", forged, none_alg, expired, wrong_aud]:
        r = await client.get("/auth/me", headers={"Authorization": f"Bearer {bad}"})
        assert r.status_code == 401, bad


async def test_role_is_read_from_database_not_from_token(client, world, engine):
    """Demoting a user takes effect immediately, even though their token still claims 'operator'."""
    headers = world.headers("ops1")
    assert (await client.get("/analytics/overview", headers=headers)).status_code == 200
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE users SET role='client' WHERE email='ops1@example.com'"))
    assert (await client.get("/analytics/overview", headers=headers)).status_code == 403


# ----------------------------------------------------------------------------- role matrix
async def test_role_matrix_on_collection_endpoints(client, world):
    await world.add_episodes(2)
    csv_file = {"file": ("episodes.csv", io.BytesIO(b"episode_id,robot_id,task_name,recorded_at,duration_seconds,operator_name,quality\n"), "text/csv")}
    new_req = {"title": "t", "task_name": "pick cup", "episodes_requested": 1}

    expected = {
        ("GET", "/analytics/overview"): {"admin": 200, "ops1": 200, "client_a": 403},
        ("GET", "/analytics/episodes/breakdown"): {"admin": 200, "ops1": 200, "client_a": 403},
        ("GET", "/episodes"): {"admin": 200, "ops1": 200, "client_a": 403},
        ("GET", "/requests"): {"admin": 200, "ops1": 200, "client_a": 200},
        ("GET", "/catalog/tasks"): {"admin": 200, "ops1": 200, "client_a": 200},
        ("POST", "/requests"): {"admin": 403, "ops1": 403, "client_a": 201},
    }
    for (method, path), by_user in expected.items():
        for user, status in by_user.items():
            kwargs = {"json": new_req} if (method, path) == ("POST", "/requests") else {}
            r = await client.request(method, path, headers=world.headers(user), **kwargs)
            assert r.status_code == status, f"{user} {method} {path} -> {r.status_code} {r.text}"

    for user, status in {"admin": 200, "ops1": 200, "client_a": 403}.items():
        r = await client.post("/episodes/import", headers=world.headers(user), files={"file": ("e.csv", b"episode_id,robot_id,task_name,recorded_at,duration_seconds,operator_name,quality\n", "text/csv")})
        assert r.status_code == status, f"import as {user} -> {r.status_code}"
    del csv_file


async def test_lifecycle_endpoints_are_role_gated(client, world):
    await world.add_episodes(3)
    req = await create_request(client, world)
    rid = req["id"]
    # clients may not drive operator transitions or assign
    for path in (f"/requests/{rid}/start", f"/requests/{rid}/deliver", f"/requests/{rid}/assignments/auto"):
        r = await client.post(path, headers=world.headers("client_a"))
        assert r.status_code == 403, path
    r = await client.post(f"/requests/{rid}/assignments", json={"episode_ids": ["EP-1"]}, headers=world.headers("client_a"))
    assert r.status_code == 403
    # staff may not accept/reject - only clients decide
    for path in (f"/requests/{rid}/accept", f"/requests/{rid}/reject"):
        for staff in ("admin", "ops1"):
            r = await client.post(path, headers=world.headers(staff))
            assert r.status_code == 403, (staff, path)


# ----------------------------------------------------------------------------- row-level security
async def test_clients_only_see_their_own_requests(client, world):
    await world.add_episodes(3)
    a = await create_request(client, world, "client_a", title="A's request")
    b = await create_request(client, world, "client_b", title="B's request")

    a_list = (await client.get("/requests", headers=world.headers("client_a"))).json()["items"]
    assert [r["id"] for r in a_list] == [a["id"]]

    staff_list = (await client.get("/requests", headers=world.headers("ops1"))).json()["items"]
    assert {r["id"] for r in staff_list} == {a["id"], b["id"]}


async def test_cross_tenant_access_returns_404_not_403(client, world):
    """404 (not 403) so that request ids cannot be probed to learn what exists."""
    await world.add_episodes(3)
    b = await create_request(client, world, "client_b")
    hdr = world.headers("client_a")
    assert (await client.get(f"/requests/{b['id']}", headers=hdr)).status_code == 404
    assert (await client.post(f"/requests/{b['id']}/accept", headers=hdr)).status_code == 404
    assert (await client.post(f"/requests/{b['id']}/reject", headers=hdr)).status_code == 404
    assert (await client.get(f"/requests/{b['id']}/assignments", headers=hdr)).status_code == 404


async def test_export_details_hidden_from_clients(client, world):
    await world.add_episodes(1)
    req = await create_request(client, world, episodes_requested=1)
    as_client = (await client.get(f"/requests/{req['id']}", headers=world.headers("client_a"))).json()
    as_staff = (await client.get(f"/requests/{req['id']}", headers=world.headers("ops1"))).json()
    assert as_client["export"] is None
    assert as_staff["export"]["status"] == "not_started"


async def test_only_admins_can_manage_users(client, world):
    body = {"email": "new@example.com", "name": "New User", "password": "long-enough-password", "role": "client"}
    assert (await client.post("/users", json=body, headers=world.headers("ops1"))).status_code == 403
    created = await client.post("/users", json=body, headers=world.headers("admin"))
    assert created.status_code == 201
    user = created.json()
    assert user["is_active"] is True
    changed = await client.patch(
        f"/users/{user['id']}", json={"role": "operator", "is_active": False}, headers=world.headers("admin")
    )
    assert changed.status_code == 200
    assert changed.json()["role"] == "operator" and changed.json()["is_active"] is False
