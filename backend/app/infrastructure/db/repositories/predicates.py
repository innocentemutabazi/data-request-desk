"""Shared WHERE-clause builders, so list / candidate / analytics queries can never disagree."""

from __future__ import annotations

from sqlalchemy import ColumnElement, exists

from app.application.dto import EpisodeFilters
from app.domain.models import Assignment, Episode


def active_assignment_exists() -> ColumnElement[bool]:
    """Correlated NOT-EXISTS probe target; served by the partial unique index on assignments."""
    return exists().where(Assignment.episode_id == Episode.episode_id, Assignment.released_at.is_(None))


def episode_predicates(f: EpisodeFilters) -> list[ColumnElement[bool]]:
    preds: list[ColumnElement[bool]] = []
    if f.task_name:
        preds.append(Episode.task_name == f.task_name)
    if f.qualities:
        preds.append(Episode.quality.in_(f.qualities) if len(f.qualities) > 1 else Episode.quality == f.qualities[0])
    if f.robot_id:
        preds.append(Episode.robot_id == f.robot_id)
    if f.recorded_from:
        preds.append(Episode.recorded_at >= f.recorded_from)
    if f.recorded_to:
        preds.append(Episode.recorded_at < f.recorded_to)  # exclusive upper bound
    return preds
