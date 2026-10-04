"""Test harness. Runs against a REAL PostgreSQL - row locks, partial indexes and ON CONFLICT cannot be
meaningfully tested on SQLite or mocks.

    TEST_DATABASE_URL=postgresql+asyncpg://desk:desk@localhost:5432/desk_test pytest
"""

from __future__ import annotations

import os
import random
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

# Must happen BEFORE the app (and its cached settings) is imported.
_TEST_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://desk:desk@localhost:5432/desk_test")
if not _TEST_URL.rsplit("/", 1)[-1].endswith("_test"):
    raise RuntimeError(f"Refusing to run tests against non-test database: {_TEST_URL}")
os.environ["DATABASE_URL"] = _TEST_URL
os.environ["ENVIRONMENT"] = "test"

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import insert, text  # noqa: E402

from alembic import command  # noqa: E402
from app.composition import Container, build_container  # noqa: E402
from app.core.config import Settings, get_settings  # noqa: E402
from app.domain.enums import Quality, UserRole  # noqa: E402
from app.domain.models import Episode, User  # noqa: E402
from app.infrastructure.db.session import build_engine  # noqa: E402
from app.infrastructure.exports.simulator import ExportSimulator  # noqa: E402
from app.infrastructure.security.passwords import hash_password  # noqa: E402
from app.infrastructure.security.tokens import TokenService  # noqa: E402
from app.main import create_app  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
SEED_DIR = BACKEND_DIR.parent / "seed"
_PW_HASH = hash_password("pw-for-tests")  # hash once; Argon2 is deliberately slow


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Build the schema through the REAL Alembic migration (also proves downgrade/upgrade round-trips)."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def settings() -> Settings:
    s = get_settings()
    assert s.database_url == _TEST_URL
    return s


@pytest_asyncio.fixture(scope="session")
async def engine(settings):
    eng = build_engine(settings)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean_tables(engine) -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE assignments, requests, episodes, users RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def simulator(settings) -> ExportSimulator:
    async def no_sleep(_: float) -> None:  # instant "exports"
        return None

    return ExportSimulator(settings, rng=random.Random(1234), sleep=no_sleep)


@pytest.fixture
def container(settings, engine, simulator) -> Container:
    # Deterministic exports by default: never fail unless a test opts in.
    original = settings.export_failure_rate
    settings.export_failure_rate = 0.0
    yield build_container(settings, engine=engine, simulator=simulator)
    settings.export_failure_rate = original


@pytest_asyncio.fixture
async def client(container) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(container)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------------------- data helpers
class World:
    """Users + helpers for building scenarios quickly."""

    def __init__(self, container: Container) -> None:
        self.c = container
        self.tokens = TokenService(container.settings)
        self.users: dict[str, User] = {}

    async def add_user(self, key: str, role: UserRole, **kw) -> User:
        user = User(
            id=uuid.uuid4(), email=f"{key}@example.com", name=kw.get("name", key.title()),
            organisation=kw.get("organisation"), role=role, hashed_password=_PW_HASH,
            is_active=kw.get("is_active", True),
        )
        async with self.c.session_factory() as s:
            s.add(user)
            await s.commit()
        self.users[key] = user
        return user

    def headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tokens.issue(self.users[key])}"}

    def actor(self, key: str):
        from app.application.dto import Actor

        u = self.users[key]
        return Actor(id=u.id, role=u.role)

    async def add_episodes(
        self, n: int, *, task: str = "pick cup", quality: Quality = Quality.GOOD, prefix: str = "EP", start: int = 1,
        recorded_at=None, duration: int = 30,
    ) -> list[str]:
        from datetime import UTC, datetime, timedelta

        base = recorded_at or datetime(2026, 8, 1, tzinfo=UTC)
        rows = [
            {
                "episode_id": f"{prefix}-{start + i:05d}", "robot_id": "arm-01", "task_name": task,
                "recorded_at": base + timedelta(minutes=i), "duration_seconds": duration,
                "operator_name": "Aline", "quality": quality,
            }
            for i in range(n)
        ]
        async with self.c.session_factory() as s:
            await s.execute(insert(Episode), rows)
            await s.commit()
        return [r["episode_id"] for r in rows]


@pytest_asyncio.fixture
async def world(container) -> World:
    w = World(container)
    await w.add_user("admin", UserRole.ADMIN, name="Ada Admin")
    await w.add_user("ops1", UserRole.OPERATOR, name="Olu Operator")
    await w.add_user("ops2", UserRole.OPERATOR, name="Odile Operator")
    await w.add_user("client_a", UserRole.CLIENT, name="Acme Robotics", organisation="Acme Robotics")
    await w.add_user("client_b", UserRole.CLIENT, name="Beta Labs", organisation="Beta Labs")
    return w


async def create_request(client: httpx.AsyncClient, world: World, owner: str = "client_a", **overrides) -> dict:
    body = {"title": "Cup picking set", "task_name": "pick cup", "episodes_requested": 3} | overrides
    r = await client.post("/requests", json=body, headers=world.headers(owner))
    assert r.status_code == 201, r.text
    return r.json()
