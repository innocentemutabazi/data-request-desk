"""Turns one raw CSV record into either a clean episode or a *reasoned* rejection.

Pure functions, no I/O - so each decision below is unit-tested against the real dirty rows in
`seed/episodes.csv`. The guiding principle is "normalise what is unambiguous, quarantine what would
require a guess":

  NORMALISE (lossless / unambiguous)                QUARANTINE (reject + report; fix source, re-import)
  ---------------------------------------------     -----------------------------------------------------
  trim + collapse whitespace in every field         wrong column count (malformed record)
  lower-case robot_id, task_name, quality           missing/invalid episode_id
  upper-case episode_id (matches the source system) robot_id blank or not in the known fleet
  parse mixed date formats -> UTC instant           unparseable recorded_at
  '45.0' -> 45                                      duration blank / negative / zero / non-numeric / 45.5
  blank operator_name -> NULL (kept, warned)        quality blank or outside {good, usable, bad}
                                                    recorded_at in the future (> cutoff) - e.g. 2031
                                                    duration outside 1..24h (e.g. 999999s) - implausible

Why quality 'excellent' is rejected rather than mapped to 'good': it would be inventing data, and
quality decides what a client is sold. Why blank operator is kept: it is provenance metadata, not a
filter or billing dimension, so losing the whole episode for it would be disproportionate.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.enums import Quality
from app.domain.errors import InvalidImportFile

EXPECTED_COLUMNS: tuple[str, ...] = (
    "episode_id",
    "robot_id",
    "task_name",
    "recorded_at",
    "duration_seconds",
    "operator_name",
    "quality",
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_INT_RE = re.compile(r"^\+?(\d+)(?:\.0+)?$")  # "45" and "45.0" are whole numbers; "45.5" is not
_WS_RE = re.compile(r"\s+")

# Day-first, because the source data proves it: '14/08/2026' cannot be month-first. Month-first is
# intentionally unsupported - an ambiguous '03/04/2026' is better rejected than silently mis-dated.
_DAY_FIRST_FORMATS = (
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
)
_MIN_YEAR, _MAX_YEAR = 2000, 2100

_MAX_LEN = {"episode_id": 64, "robot_id": 64, "task_name": 200, "operator_name": 100}


@dataclass(frozen=True, slots=True)
class CleanEpisode:
    episode_id: str
    robot_id: str
    task_name: str
    recorded_at: datetime
    duration_seconds: int
    operator_name: str | None
    quality: Quality

    def as_row(self) -> dict[str, object]:
        return {
            "episode_id": self.episode_id,
            "robot_id": self.robot_id,
            "task_name": self.task_name,
            "recorded_at": self.recorded_at,
            "duration_seconds": self.duration_seconds,
            "operator_name": self.operator_name,
            "quality": self.quality,
        }

    def same_content_as(self, other: CleanEpisode) -> bool:
        return self == other


@dataclass(frozen=True, slots=True)
class Rejection:
    reason: str
    detail: str


@dataclass(slots=True)
class CleaningResult:
    episode: CleanEpisode | None = None
    rejection: Rejection | None = None
    normalizations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_header(header: Sequence[str]) -> dict[str, int]:
    """Map column name -> index, tolerating reordering, case and whitespace differences."""
    normalized = [name.strip().lower().lstrip("\ufeff") for name in header]
    duplicates = sorted({name for name in normalized if normalized.count(name) > 1})
    if duplicates:
        raise InvalidImportFile(
            f"CSV header contains duplicate column(s): {', '.join(duplicates)}.",
            duplicates=duplicates,
        )
    index = {name: i for i, name in enumerate(normalized)}
    missing = [c for c in EXPECTED_COLUMNS if c not in index]
    if missing:
        raise InvalidImportFile(
            f"CSV header is missing required column(s): {', '.join(missing)}.",
            expected=list(EXPECTED_COLUMNS),
            found=[h.strip() for h in header],
        )
    return index


def parse_timestamp(raw: str) -> tuple[datetime, bool, bool] | None:
    """Return (UTC datetime, was_non_canonical, tz_was_assumed) or None if unparseable.

    Naive timestamps carry no zone information; we treat them as UTC (documented assumption).
    """
    value = raw.strip()
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(value)  # 2026-08-14T09:12:00 | 2026-08-14 09:12:00 | ...Z | +02:00
    except ValueError:
        for fmt in _DAY_FIRST_FORMATS:
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None

    naive = parsed.tzinfo is None
    canonical = naive and "T" in value and value.count(":") == 2 and len(value) == 19
    parsed = parsed.replace(tzinfo=UTC) if naive else parsed.astimezone(UTC)
    if not (_MIN_YEAR <= parsed.year <= _MAX_YEAR):
        return None
    return parsed, not canonical, naive


def _tidy(value: str) -> str:
    """Trim and collapse internal runs of whitespace."""
    # Fast path: the overwhelming majority of values are already tidy, and a regex pass per field
    # per row is measurable at millions of rows.
    if value == value.strip() and "  " not in value and "\t" not in value and "\n" not in value:
        return value
    return _WS_RE.sub(" ", value).strip()


def clean_row(
    cells: Sequence[str],
    index: Mapping[str, int],
    width: int,
    known_robots: Collection[str],
    max_duration_seconds: int,
    latest_allowed: datetime,
) -> CleaningResult:
    """`latest_allowed` (tz-aware) is injected, not read from the clock, so this stays pure."""
    result = CleaningResult()

    if len(cells) != width:
        result.rejection = Rejection("malformed_row", f"expected {width} columns, found {len(cells)}")
        return result
    if any("\ufffd" in c for c in cells):
        result.rejection = Rejection("invalid_encoding", "row contains undecodable (non UTF-8) bytes")
        return result

    def raw(name: str) -> str:
        return cells[index[name]]

    def tidy(name: str) -> str:
        original = raw(name)
        cleaned = _tidy(original)
        if cleaned != original:
            result.normalizations.append("whitespace_trimmed")
        return cleaned

    def reject(reason: str, detail: str) -> CleaningResult:
        result.rejection = Rejection(reason, detail)
        result.normalizations.clear()
        result.warnings.clear()
        return result

    # -- episode_id ------------------------------------------------------------------------------
    episode_id = tidy("episode_id")
    if not episode_id:
        return reject("missing_episode_id", "episode_id is blank")
    if not _ID_RE.match(episode_id):
        return reject("invalid_episode_id", f"episode_id {episode_id!r} has illegal characters or length")
    if episode_id != episode_id.upper():
        result.normalizations.append("case_normalized")
    episode_id = episode_id.upper()

    # -- robot_id --------------------------------------------------------------------------------
    robot_id = tidy("robot_id")
    if not robot_id:
        return reject("unknown_robot", "robot_id is blank")
    if robot_id != robot_id.lower():
        result.normalizations.append("case_normalized")
    robot_id = robot_id.lower()
    if robot_id not in known_robots:
        return reject("unknown_robot", f"robot {robot_id!r} is not in the known fleet")

    # -- task_name -------------------------------------------------------------------------------
    task_name = tidy("task_name")
    if not task_name:
        return reject("missing_task_name", "task_name is blank")
    if task_name != task_name.lower():
        result.normalizations.append("case_normalized")
    task_name = task_name.lower()
    if len(task_name) > _MAX_LEN["task_name"]:
        return reject("value_too_long", f"task_name exceeds {_MAX_LEN['task_name']} characters")

    # -- recorded_at -----------------------------------------------------------------------------
    raw_ts = raw("recorded_at")
    if raw_ts != raw_ts.strip():
        result.normalizations.append("whitespace_trimmed")
    if not raw_ts.strip():
        return reject("invalid_recorded_at", "recorded_at is blank")
    parsed = parse_timestamp(raw_ts)
    if parsed is None:
        return reject("invalid_recorded_at", f"cannot parse {raw_ts.strip()!r} as a date/time")
    recorded_at, non_canonical, tz_assumed = parsed
    if recorded_at > latest_allowed:
        return reject(
            "future_recorded_at",
            f"recorded_at {recorded_at.isoformat()} is after the cutoff {latest_allowed.isoformat()}",
        )
    if non_canonical:
        result.normalizations.append("date_format_normalized")
    if tz_assumed:
        result.warnings.append("timestamps_assumed_utc")

    # -- duration_seconds ------------------------------------------------------------------------
    raw_dur = tidy("duration_seconds")
    if not raw_dur:
        return reject("invalid_duration", "duration_seconds is blank")
    match = _INT_RE.match(raw_dur)
    if not match:
        return reject("invalid_duration", f"{raw_dur!r} is not a positive whole number of seconds")
    duration = int(match.group(1))
    if duration <= 0 or duration > max_duration_seconds:
        return reject("invalid_duration", f"{duration} is outside 1..{max_duration_seconds} seconds")

    # -- quality ---------------------------------------------------------------------------------
    raw_quality = tidy("quality")
    if not raw_quality:
        return reject("invalid_quality", "quality is blank")
    if raw_quality != raw_quality.lower():
        result.normalizations.append("case_normalized")
    try:
        quality = Quality(raw_quality.lower())
    except ValueError:
        return reject("invalid_quality", f"{raw_quality!r} is not one of good/usable/bad")

    # -- operator_name (optional provenance) -----------------------------------------------------
    operator = tidy("operator_name") or None
    if operator is None:
        result.warnings.append("operator_name_missing")
    elif len(operator) > _MAX_LEN["operator_name"]:
        return reject("value_too_long", f"operator_name exceeds {_MAX_LEN['operator_name']} characters")

    result.episode = CleanEpisode(
        episode_id=episode_id,
        robot_id=robot_id,
        task_name=task_name,
        recorded_at=recorded_at,
        duration_seconds=duration,
        operator_name=operator,
        quality=quality,
    )
    return result
