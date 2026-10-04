"""Domain errors. The API layer maps these onto HTTP; the domain knows nothing about HTTP."""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    code = "domain_error"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFound(DomainError):
    code = "not_found"


class AuthenticationFailed(DomainError):
    code = "authentication_failed"


class PermissionDenied(DomainError):
    code = "permission_denied"


class Conflict(DomainError):
    code = "conflict"


class InvalidTransition(Conflict):
    code = "invalid_transition"


class InsufficientAssignedEpisodes(Conflict):
    code = "insufficient_assigned_episodes"


class EpisodesAlreadyAssigned(Conflict):
    code = "episodes_already_assigned"


class RequestNotAssignable(Conflict):
    code = "request_not_assignable"


class AssignmentExceedsRequest(Conflict):
    code = "assignment_exceeds_request"


class NoEpisodesAvailable(Conflict):
    code = "no_episodes_available"


class ExportNotRetryable(Conflict):
    code = "export_not_retryable"


class ValidationFailed(DomainError):
    code = "validation_failed"


class EpisodesNotFound(ValidationFailed):
    code = "episodes_not_found"


class EpisodeCriteriaMismatch(ValidationFailed):
    code = "episode_criteria_mismatch"


class InvalidCursor(ValidationFailed):
    code = "invalid_cursor"


class InvalidImportFile(ValidationFailed):
    code = "invalid_import_file"


class PayloadTooLarge(DomainError):
    code = "payload_too_large"


class ResourceBusy(DomainError):
    """A row lock could not be obtained in time or a deadlock was resolved by PostgreSQL."""

    code = "resource_busy"
