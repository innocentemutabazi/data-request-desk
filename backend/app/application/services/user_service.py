from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError

from app.application.dto import Actor
from app.application.ports import UnitOfWork
from app.domain.enums import UserRole
from app.domain.errors import NotFound, PermissionDenied, ValidationFailed
from app.domain.models import User
from app.infrastructure.security.passwords import hash_password


class UserService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow = uow_factory

    @staticmethod
    def _admin(actor: Actor) -> None:
        if actor.role is not UserRole.ADMIN:
            raise PermissionDenied("Only admins can manage users.")

    async def list(self, actor: Actor) -> list[User]:
        self._admin(actor)
        async with self._uow() as uow:
            return await uow.users.list_page()

    async def create(
        self, actor: Actor, *, email: str, name: str, password: str,
        role: UserRole, organisation: str | None,
    ) -> User:
        self._admin(actor)
        normalized_email = email.strip().lower()
        normalized_name = " ".join(name.split())
        if not normalized_email or not normalized_name or len(password) < 8:
            raise ValidationFailed("Email, name, and a password of at least 8 characters are required.")
        async with self._uow() as uow:
            if await uow.users.get_by_email(normalized_email):
                raise ValidationFailed("A user with that email already exists.")
            user = User(
                email=normalized_email, name=normalized_name, organisation=organisation,
                role=role, hashed_password=await asyncio.to_thread(hash_password, password),
            )
            uow.users.add(user)
            try:
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                if "uq_users_email" in str(exc.orig):
                    raise ValidationFailed("A user with that email already exists.") from None
                raise
            return user

    async def update(
        self, actor: Actor, user_id: uuid.UUID, *, role: UserRole | None, is_active: bool | None
    ) -> User:
        self._admin(actor)
        async with self._uow() as uow:
            user = await uow.users.get_by_id(user_id)
            if user is None:
                raise NotFound("User not found.")
            if user.id == actor.id and is_active is False:
                raise ValidationFailed("You cannot deactivate your own account.")
            if role is not None:
                user.role = role
            if is_active is not None:
                user.is_active = is_active
            await uow.commit()
            return user