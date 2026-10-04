"""Domain vocabulary. Plain enums with no framework dependencies."""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    CLIENT = "client"

    @property
    def is_staff(self) -> bool:
        return self in (UserRole.ADMIN, UserRole.OPERATOR)


class RequestStatus(StrEnum):
    SUBMITTED = "submitted"
    IN_PROGRESS = "in_progress"
    DELIVERED = "delivered"
    ACCEPTED = "accepted"
    REJECTED = "rejected"

    @property
    def is_terminal(self) -> bool:
        return self is RequestStatus.ACCEPTED


class Quality(StrEnum):
    GOOD = "good"
    USABLE = "usable"
    BAD = "bad"

    @property
    def rank(self) -> int:
        """Higher is better. Lets `min_quality=usable` mean 'usable or good'."""
        return {Quality.BAD: 0, Quality.USABLE: 1, Quality.GOOD: 2}[self]


def qualities_at_least(minimum: Quality | None) -> list[Quality]:
    if minimum is None:
        return list(Quality)
    return [q for q in Quality if q.rank >= minimum.rank]


class ExportStatus(StrEnum):
    NOT_STARTED = "not_started"
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def in_flight(self) -> bool:
        return self in (ExportStatus.PENDING, ExportStatus.RUNNING)
