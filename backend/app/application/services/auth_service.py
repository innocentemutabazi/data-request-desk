from __future__ import annotations

import time
from collections.abc import Callable

from app.application.dto import Actor
from app.application.ports import PasswordVerifier, TokenPort, UnitOfWork
from app.domain.errors import AuthenticationFailed
from app.domain.models import User


class AuthService:
    _FAILURE_WINDOW_SECONDS = 60.0
    _MAX_FAILURE_KEYS = 10_000

    def __init__(self, uow_factory: Callable[[], UnitOfWork], tokens: TokenPort, verify: PasswordVerifier) -> None:
        self._uow = uow_factory
        self._tokens = tokens
        self._verify = verify
        self._failures: dict[str, tuple[int, float, float]] = {}

    @property
    def expires_in_seconds(self) -> int:
        return self._tokens.expires_in_seconds

    async def login(self, email: str, password: str) -> tuple[User, str]:
        key = email.strip().lower()
        now = time.monotonic()
        failures, blocked_until, last_failure_at = self._failures.get(key, (0, 0.0, 0.0))
        if last_failure_at and now - last_failure_at >= self._FAILURE_WINDOW_SECONDS:
            failures = 0
            blocked_until = 0.0
        if blocked_until > now:
            raise AuthenticationFailed("Incorrect email or password.")
        async with self._uow() as uow:
            user = await uow.users.get_by_email(key)
        # Always verify (against a dummy hash if the user is unknown) -> uniform timing and message.
        ok = await self._verify(password, user.hashed_password if user else None)
        if not ok or user is None or not user.is_active:
            failures += 1
            self._failures[key] = (
                failures,
                now + self._FAILURE_WINDOW_SECONDS if failures >= 5 else 0.0,
                now,
            )
            if len(self._failures) > self._MAX_FAILURE_KEYS:
                oldest_key = min(self._failures, key=lambda candidate: self._failures[candidate][2])
                self._failures.pop(oldest_key, None)
            raise AuthenticationFailed("Incorrect email or password.")
        self._failures.pop(key, None)
        return user, self._tokens.issue(user)

    async def authenticate(self, token: str) -> Actor:
        claims = self._tokens.decode(token)
        async with self._uow() as uow:
            user = await uow.users.get_by_id(claims.user_id)
        if user is None or not user.is_active:
            raise AuthenticationFailed("Account not found or disabled.")
        # Authorization uses the role stored in the DB, not the one baked into the token.
        return Actor(id=user.id, role=user.role)

    async def get_user(self, actor: Actor) -> User:
        async with self._uow() as uow:
            user = await uow.users.get_by_id(actor.id)
        if user is None:
            raise AuthenticationFailed("Account not found or disabled.")
        return user
