"""Streaming, idempotent CSV import.

* Streams the file: memory is O(batch), not O(file) - a 5M-row file costs the same RAM as 5k rows.
* Each batch is `INSERT ... ON CONFLICT DO NOTHING RETURNING episode_id` in its OWN transaction.
  - idempotent: re-importing the same file inserts nothing and changes nothing
  - resumable: if the process dies at row 3,000,000, just run it again
  - concurrency-safe: two simultaneous imports cannot create duplicates or raise errors
* "First occurrence wins" is deterministic, and conflicts (same id, different content) are *reported*,
  never silently merged.
"""

from __future__ import annotations

import csv
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TextIO

from app.application.dto import ImportReport
from app.application.episode_cleaning import CleanEpisode, clean_row, parse_header
from app.application.ports import UnitOfWork
from app.core.config import Settings
from app.domain.errors import InvalidImportFile
from app.domain.models import Episode

log = logging.getLogger(__name__)

_COMPARED_FIELDS = ("robot_id", "task_name", "recorded_at", "duration_seconds", "operator_name", "quality")


def _differing_fields(existing: Episode, new: CleanEpisode) -> list[str]:
    return [f for f in _COMPARED_FIELDS if getattr(existing, f) != getattr(new, f)]


class ImportService:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        settings: Settings,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow = uow_factory
        self._s = settings
        self._clock = clock

    async def import_csv(self, stream: TextIO, filename: str | None = None) -> ImportReport:
        started = time.perf_counter()
        report = ImportReport(filename=filename)
        reader = csv.reader(stream)  # real CSV parsing: quoted commas/newlines are handled correctly

        try:
            header = next(reader)
        except StopIteration:
            raise InvalidImportFile("The file is empty.") from None
        except csv.Error as exc:
            raise InvalidImportFile(f"Cannot parse CSV header: {exc}") from exc
        index = parse_header(header)
        width = len(header)
        latest_allowed = self._clock() + timedelta(hours=self._s.import_max_future_skew_hours)
        known_robots = frozenset(r.lower() for r in self._s.known_robots)

        batch: list[tuple[int, CleanEpisode]] = []
        try:
            for cells in reader:
                if not cells or not any(c.strip() for c in cells):
                    report.blank_lines_skipped += 1
                    continue
                report.rows_read += 1
                result = clean_row(
                    cells, index, width, known_robots, self._s.max_episode_duration_seconds, latest_allowed
                )
                for key in set(result.normalizations):
                    report.bump("normalizations", key)
                for key in set(result.warnings):
                    report.bump("warnings", key)
                if result.rejection or result.episode is None:
                    rej = result.rejection
                    assert rej is not None
                    report.reject(reader.line_num, rej.reason, rej.detail, ",".join(cells))
                    continue
                batch.append((reader.line_num, result.episode))
                if len(batch) >= self._s.import_batch_size:
                    await self._flush(batch, report)
                    batch = []
        except csv.Error as exc:
            raise InvalidImportFile(f"CSV parse error near line {reader.line_num}: {exc}") from exc

        if batch:
            await self._flush(batch, report)
        report.duration_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "import %s: read=%d inserted=%d dup_identical=%d dup_conflict=%d rejected=%d in %dms",
            filename, report.rows_read, report.inserted, report.duplicates_identical,
            report.duplicates_conflicting, report.rejected, report.duration_ms,
        )
        return report

    async def _flush(self, batch: list[tuple[int, CleanEpisode]], report: ImportReport) -> None:
        # (a) duplicates *inside* this batch: keep the first, classify the rest without touching the DB
        first: dict[str, tuple[int, CleanEpisode]] = {}
        for line, ep in batch:
            kept = first.get(ep.episode_id)
            if kept is None:
                first[ep.episode_id] = (line, ep)
            else:
                same = kept[1].same_content_as(ep)
                report.duplicate(
                    line, ep.episode_id, same,
                    f"repeat of line {kept[0]} (kept the earlier row)" if same
                    else f"conflicts with line {kept[0]} on {_diff_names(kept[1], ep)}; kept the earlier row",
                )

        async with self._uow() as uow:
            inserted = await uow.episodes.insert_ignore([ep.as_row() for _, ep in first.values()])
            await uow.commit()
            report.inserted += len(inserted)

            # (b) ids that already existed (earlier batch, earlier import, or a concurrent import)
            skipped = {i: pair for i, pair in first.items() if i not in inserted}
            if skipped:
                existing = {e.episode_id: e for e in await uow.episodes.get_many(list(skipped))}
                for episode_id, (line, ep) in skipped.items():
                    current = existing.get(episode_id)
                    diff = _differing_fields(current, ep) if current else []
                    report.duplicate(
                        line, episode_id, not diff,
                        "already imported (identical)" if not diff
                        else f"already exists with different {', '.join(diff)}; kept the existing row",
                    )


def _diff_names(a: CleanEpisode, b: CleanEpisode) -> str:
    return ", ".join(f for f in _COMPARED_FIELDS if getattr(a, f) != getattr(b, f))
