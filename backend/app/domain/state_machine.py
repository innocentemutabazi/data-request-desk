"""The request lifecycle as data.

    submitted ──▶ in_progress ──▶ delivered ──▶ accepted
                           ▲          └───────▶ rejected
                           └────────────────────

* operators (and admins) drive submitted → in_progress → delivered
* ONLY clients may accept / reject, and only for their own request (ownership is enforced by the
  service layer, which owns the data; this module owns the *rules*).

Two distinct failure modes, deliberately different HTTP statuses:
  - the actor's role may never perform this move      → PermissionDenied (403)
  - the role may, but not from the current state       → InvalidTransition (409)
"""

from __future__ import annotations

from types import MappingProxyType

from app.domain.enums import RequestStatus, UserRole
from app.domain.errors import InvalidTransition, PermissionDenied

S = RequestStatus
R = UserRole

_STAFF = frozenset({R.ADMIN, R.OPERATOR})
_CLIENT = frozenset({R.CLIENT})

# (from, to) -> roles allowed to perform it. Anything absent is illegal. Immutable on purpose.
TRANSITIONS: MappingProxyType[tuple[RequestStatus, RequestStatus], frozenset[UserRole]] = MappingProxyType(
    {
        (S.SUBMITTED, S.IN_PROGRESS): _STAFF,
        (S.IN_PROGRESS, S.DELIVERED): _STAFF,
        (S.DELIVERED, S.ACCEPTED): _CLIENT,
        (S.DELIVERED, S.REJECTED): _CLIENT,
        (S.REJECTED, S.IN_PROGRESS): _STAFF,
    }
)


def roles_allowed_to_reach(target: RequestStatus) -> frozenset[UserRole]:
    allowed: set[UserRole] = set()
    for (_, to), roles in TRANSITIONS.items():
        if to == target:
            allowed |= roles
    return frozenset(allowed)


def authorize_transition(current: RequestStatus, target: RequestStatus, role: UserRole) -> None:
    """Raise unless `role` may move a request from `current` to `target`."""
    if role not in roles_allowed_to_reach(target):
        raise PermissionDenied(
            f"Role '{role}' is not permitted to move a request to '{target}'.",
            role=str(role),
            target=str(target),
        )
    if (current, target) not in TRANSITIONS:
        raise InvalidTransition(
            f"Cannot move a request from '{current}' to '{target}'.",
            current=str(current),
            target=str(target),
        )


def available_targets(current: RequestStatus, role: UserRole) -> list[RequestStatus]:
    """Statuses this role could move to right now (ignores data guards such as episode counts)."""
    return [to for (frm, to), roles in TRANSITIONS.items() if frm == current and role in roles]
