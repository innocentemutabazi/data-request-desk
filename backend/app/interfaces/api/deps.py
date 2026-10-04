"""FastAPI dependencies: authentication and RBAC."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer

from app.application.dto import Actor
from app.composition import Container
from app.domain.enums import UserRole
from app.domain.errors import AuthenticationFailed, PermissionDenied

# auto_error=False so a missing header flows through OUR 401 envelope instead of FastAPI's default.
_oauth2 = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


def get_container(request: Request) -> Container:
    return request.app.state.container


async def current_actor(
    request: Request,
    token: str | None = Depends(_oauth2), container: Container = Depends(get_container)
) -> Actor:
    if not token:
        raise AuthenticationFailed("Not authenticated.")
    actor = await container.auth.authenticate(token)
    # Middleware uses this only for request logging; authorization still happens here.
    request.state.user_id = str(actor.id)
    return actor


def require_roles(*roles: UserRole) -> Callable[..., Actor]:
    """Coarse-grained RBAC at the edge. Object-level rules (e.g. 'a client sees only their own
    requests') are enforced again in the service layer, so they hold for every caller."""

    allowed = frozenset(roles)

    async def dependency(actor: Actor = Depends(current_actor)) -> Actor:
        if actor.role not in allowed:
            raise PermissionDenied(
                "Your role is not allowed to perform this action.",
                required=sorted(r.value for r in allowed),
                actual=actor.role.value,
            )
        return actor

    return dependency


STAFF = (UserRole.ADMIN, UserRole.OPERATOR)
