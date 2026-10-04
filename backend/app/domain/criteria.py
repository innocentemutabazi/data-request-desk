"""Selection criteria: what makes an episode eligible for a request."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.enums import Quality, qualities_at_least
from app.domain.models import Episode, Request


@dataclass(frozen=True, slots=True)
class EpisodeCriteria:
    """Window semantics: `recorded_after` inclusive, `recorded_before` exclusive."""

    task_name: str
    min_quality: Quality | None = None
    recorded_after: datetime | None = None
    recorded_before: datetime | None = None

    @classmethod
    def from_request(cls, request: Request) -> EpisodeCriteria:
        return cls(request.task_name, request.min_quality, request.recorded_after, request.recorded_before)

    @property
    def qualities(self) -> list[Quality]:
        return qualities_at_least(self.min_quality)

    def matches(self, episode: Episode) -> bool:
        """Python-side mirror of the SQL predicate built in the episode repository."""
        if episode.task_name != self.task_name:
            return False
        if episode.quality not in self.qualities:
            return False
        if self.recorded_after and episode.recorded_at < self.recorded_after:
            return False
        if self.recorded_before and episode.recorded_at >= self.recorded_before:
            return False
        return True
