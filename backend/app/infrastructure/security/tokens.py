"""Stateless JWT access tokens (PyJWT).

Hardening choices:
  * algorithm is pinned on decode (`algorithms=[...]`) - defeats the classic alg=none / alg-swap attacks
  * `exp`, `iat`, `sub`, `iss`, `aud` are all *required* and verified
  * the token identifies the user; the ROLE IS RE-READ FROM THE DATABASE on every request, so
    demoting/deactivating a user takes effect immediately instead of when their token expires
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.application.dto import TokenClaims
from app.core.config import Settings
from app.domain.errors import AuthenticationFailed
from app.domain.models import User


class TokenService:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    @property
    def expires_in_seconds(self) -> int:
        return self._s.access_token_expire_minutes * 60

    def issue(self, user: User, now: datetime | None = None) -> str:
        issued = now or datetime.now(UTC)
        payload = {
            "sub": str(user.id),
            "role": user.role.value,  # informational for clients; NOT trusted for authorization
            "iss": self._s.jwt_issuer,
            "aud": self._s.jwt_audience,
            "iat": issued,
            "exp": issued + timedelta(seconds=self.expires_in_seconds),
        }
        return jwt.encode(payload, self._s.jwt_secret, algorithm=self._s.jwt_algorithm)

    def decode(self, token: str) -> TokenClaims:
        try:
            data = jwt.decode(
                token,
                self._s.jwt_secret,
                algorithms=[self._s.jwt_algorithm],
                issuer=self._s.jwt_issuer,
                audience=self._s.jwt_audience,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
            return TokenClaims(user_id=uuid.UUID(data["sub"]), role=str(data.get("role", "")))
        except (jwt.PyJWTError, ValueError) as exc:
            raise AuthenticationFailed("Invalid or expired token.") from exc
