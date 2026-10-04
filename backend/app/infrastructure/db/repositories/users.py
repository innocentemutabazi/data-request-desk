from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import User


class SqlUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_by_email(self, email: str) -> User | None:
        return (await self._s.execute(select(User).where(User.email == email.strip().lower()))).scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._s.get(User, user_id)

    async def list_page(self, limit: int = 200) -> list[User]:
        return list((await self._s.execute(select(User).order_by(User.created_at, User.email).limit(limit))).scalars())

    def add(self, user: User) -> None:
        self._s.add(user)

    async def insert_ignore(self, rows: Sequence[Mapping[str, object]]) -> int:
        """Idempotent seeding: existing emails are left untouched. Returns rows actually inserted."""
        if not rows:
            return 0
        stmt = pg_insert(User).on_conflict_do_nothing(index_elements=[User.email]).returning(User.id)
        result = await self._s.execute(stmt, [dict(r) for r in rows])
        return len(result.scalars().all())
