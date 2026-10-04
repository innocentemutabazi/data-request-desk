"""Episode import: cleaning rules, idempotency, duplicate handling, concurrency, RBAC."""

from __future__ import annotations

import asyncio
import io
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from app.application.episode_cleaning import clean_row, parse_header, parse_timestamp
from app.application.services.import_service import ImportService
from app.domain.errors import InvalidImportFile, PayloadTooLarge
from tests.conftest import SEED_DIR

HEADER = "episode_id,robot_id,task_name,recorded_at,duration_seconds,operator_name,quality\n"
ROBOTS = {"arm-01", "arm-02", "arm-03", "mobile-01", "humanoid-01"}
CUTOFF = datetime(2026, 9, 30, tzinfo=UTC)
IDX = parse_header(HEADER.strip().split(","))


def clean(line: str):
    import csv

    return clean_row(next(csv.reader([line])), IDX, 7, ROBOTS, 86_400, CUTOFF)


# ================================================================ cleaning rules (pure, no DB)
def test_whitespace_and_case_are_normalised():
    r = clean("ep-00006, ARM-01 ,  Pick   Cup ,2026-08-13T23:51:00,111,Eric,USABLE")
    e = r.episode
    assert (e.episode_id, e.robot_id, e.task_name, e.quality.value) == ("EP-00006", "arm-01", "pick cup", "usable")
    assert {"whitespace_trimmed", "case_normalized"} <= set(r.normalizations)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-08-14T09:12:00", "2026-08-14T09:12:00+00:00"),
        ("2026-08-14 09:12:00", "2026-08-14T09:12:00+00:00"),  # space separator
        ("2026-08-14T09:20:00Z", "2026-08-14T09:20:00+00:00"),  # explicit UTC
        ("2026-08-14T11:20:00+02:00", "2026-08-14T09:20:00+00:00"),  # offsets converted, not dropped
        ("14/08/2026 09:15", "2026-08-14T09:15:00+00:00"),  # day-first (14 cannot be a month)
        ("14/08/2026", "2026-08-14T00:00:00+00:00"),
    ],
)
def test_mixed_date_formats_all_become_the_same_utc_instant(raw, expected):
    parsed, _, _ = parse_timestamp(raw)
    assert parsed.isoformat() == expected


@pytest.mark.parametrize("raw", ["not a date", "", "31/02/2026 10:00", "2026-13-01T00:00:00", "08/14/2026 10:00"])
def test_unparseable_dates_return_none(raw):  # note: month-first '08/14/2026' is deliberately unsupported
    assert parse_timestamp(raw) is None


@pytest.mark.parametrize(
    "line,reason",
    [
        (",humanoid-01,fold towel,2026-08-13T06:59:00,82,Patrick,good", "missing_episode_id"),
        ("EP-1,arm-99,pick cup,2026-08-13T06:59:00,82,Patrick,good", "unknown_robot"),
        ("EP-1,,pick cup,2026-08-13T06:59:00,82,Patrick,good", "unknown_robot"),
        ("EP-1,arm-01,pick cup,not a date,82,Patrick,good", "invalid_recorded_at"),
        ("EP-1,arm-01,pick cup,2031-01-01T00:00:00,56,Jeanne,usable", "future_recorded_at"),
        ("EP-1,arm-01,pick cup,2026-08-13T06:59:00,45.5,Patrick,good", "invalid_duration"),
        ("EP-1,arm-01,pick cup,2026-08-13T06:59:00,,Patrick,good", "invalid_duration"),
        ("EP-1,arm-01,pick cup,2026-08-13T06:59:00,-5,Patrick,good", "invalid_duration"),
        ("EP-1,arm-01,pick cup,2026-08-13T06:59:00,0,Patrick,good", "invalid_duration"),
        ("EP-1,arm-01,pick cup,2026-08-13T06:59:00,N/A,Patrick,good", "invalid_duration"),
        ("EP-1,arm-01,pick cup,2026-08-13T06:59:00,999999,Patrick,good", "invalid_duration"),
        ("EP-1,arm-01,pick cup,2026-08-13T06:59:00,50,Patrick,excellent", "invalid_quality"),
        ("EP-1,arm-01,pick cup,2026-08-13T06:59:00,50,Patrick,", "invalid_quality"),
        ("EP-1,arm-01,,2026-08-13T06:59:00,50,Patrick,good", "missing_task_name"),
    ],
)
def test_rejections_carry_a_specific_reason(line, reason):
    r = clean(line)
    assert r.episode is None and r.rejection.reason == reason


def test_malformed_column_count_is_rejected():
    r = clean_row(["EP-90001", "arm-02", "open drawer", "2026-08-20T10:00:00", "30"], IDX, 7, ROBOTS, 86_400, CUTOFF)
    assert r.rejection.reason == "malformed_row" and "found 5" in r.rejection.detail


def test_whole_number_float_durations_are_accepted_but_fractions_are_not():
    assert clean("EP-1,arm-01,pick cup,2026-08-13T06:59:00,45.0,Eric,good").episode.duration_seconds == 45
    assert clean("EP-1,arm-01,pick cup,2026-08-13T06:59:00,45.5,Eric,good").rejection


def test_blank_operator_is_kept_as_null_with_a_warning():
    r = clean("EP-1,mobile-01,pour water,2026-08-22T09:15:00,30,,usable")
    assert r.episode.operator_name is None and "operator_name_missing" in r.warnings


def test_quoted_comma_in_task_name_does_not_shift_columns():
    r = clean('EP-1,arm-03,"pick cup, then place",2026-08-21T11:00:00,40,Eric,good')
    assert r.episode.task_name == "pick cup, then place" and r.episode.duration_seconds == 40


def test_header_is_validated_and_tolerates_reordering():
    with pytest.raises(InvalidImportFile, match="missing required column"):
        parse_header(["episode_id", "robot_id"])
    idx = parse_header(["Quality ", "EPISODE_ID", "robot_id", "task_name", "recorded_at", "duration_seconds", "operator_name"])
    r = clean_row(["good", "ep-1", "arm-01", "pick cup", "2026-08-01T00:00:00", "9", "Eric"], idx, 7, ROBOTS, 86_400, CUTOFF)
    assert r.episode.quality.value == "good" and r.episode.episode_id == "EP-1"


def test_duplicate_header_is_rejected_instead_of_overwriting_a_column():
    with pytest.raises(InvalidImportFile, match="duplicate column"):
        parse_header(["episode_id", "robot_id", "task_name", "recorded_at", "quality", "quality"])


# ================================================================ against the real seed file
SEED_CSV = (SEED_DIR / "episodes.csv").read_text(encoding="utf-8-sig")


async def _import(container, text_: str, name="episodes.csv", **settings_overrides):
    s = container.settings.model_copy(update=settings_overrides) if settings_overrides else container.settings
    svc = ImportService(container.uow, s)
    return await svc.import_csv(io.StringIO(text_, newline=""), name)


async def _count(container) -> int:
    async with container.session_factory() as s:
        return (await s.execute(text("SELECT count(*) FROM episodes"))).scalar_one()


async def test_seed_file_produces_the_documented_numbers(container):
    r = await _import(container, SEED_CSV)
    assert r.rows_read == 189 and r.blank_lines_skipped == 2
    assert r.inserted == 172
    assert (r.duplicates_identical, r.duplicates_conflicting) == (2, 2)
    assert r.rejected == 13
    assert r.rejected_by_reason == {
        "invalid_duration": 5, "unknown_robot": 2, "invalid_quality": 2, "missing_episode_id": 1,
        "invalid_recorded_at": 1, "future_recorded_at": 1, "malformed_row": 1,
    }
    # accounting identity: every record is inserted, a duplicate, or rejected - nothing silently lost
    assert r.rows_read == r.inserted + r.duplicates_identical + r.duplicates_conflicting + r.rejected
    assert await _count(container) == 172


async def test_conflicting_duplicates_keep_the_first_row_and_are_reported(container):
    r = await _import(container, SEED_CSV)
    conflicts = {d.episode_id: d for d in r.duplicate_samples if not d.identical}
    assert set(conflicts) == {"EP-00011", "EP-00003"}  # EP-00003 conflicts with 'ep-00003' (case-insensitive id)
    assert "quality" in conflicts["EP-00011"].note and "robot_id" in conflicts["EP-00003"].note
    async with container.session_factory() as s:
        rows = {r[0]: r[1:] for r in await s.execute(text("SELECT episode_id, robot_id, quality FROM episodes WHERE episode_id IN ('EP-00011','EP-00003')"))}
    assert rows["EP-00011"] == ("arm-03", "bad")  # the first occurrence won
    assert rows["EP-00003"] == ("humanoid-01", "good")


async def test_import_is_idempotent(container):
    first = await _import(container, SEED_CSV)
    snapshot = await _snapshot(container)
    for _ in range(3):
        again = await _import(container, SEED_CSV)
        assert again.inserted == 0
        assert again.rejected == first.rejected
    assert await _snapshot(container) == snapshot  # byte-identical table after re-imports
    assert await _count(container) == 172


async def test_import_endpoint_enforces_streaming_upload_limit(client, world):
    await world.add_episodes(1)
    container = client._transport.app.state.container
    original = container.settings.max_import_bytes
    container.settings.max_import_bytes = 32
    try:
        response = await client.post(
            "/episodes/import",
            files={"file": ("episodes.csv", HEADER + "EP-1,arm-01,pick cup,2026-08-13T06:59:00,30,Eric,good")},
            headers=world.headers("ops1"),
        )
    finally:
        container.settings.max_import_bytes = original
    assert response.status_code == 413
    assert response.json()["error"]["code"] == PayloadTooLarge.code


async def _snapshot(container):
    async with container.session_factory() as s:
        return (await s.execute(text("SELECT * FROM episodes ORDER BY episode_id"))).all()


@pytest.mark.parametrize("batch_size", [1, 7, 50, 4000])
async def test_result_does_not_depend_on_batch_size(container, batch_size):
    """Duplicates that straddle batch boundaries must be handled exactly like in-batch ones."""
    r = await _import(container, SEED_CSV, import_batch_size=batch_size)
    assert (r.inserted, r.duplicates_identical, r.duplicates_conflicting, r.rejected) == (172, 2, 2, 13)
    assert await _count(container) == 172


async def test_concurrent_imports_of_the_same_file_cannot_duplicate_or_crash(container):
    rows = "".join(f"EP-{i:06d},arm-01,pick cup,2026-08-01T00:00:00,30,Eric,good\n" for i in range(3000))
    reports = await asyncio.gather(*(_import(container, HEADER + rows, import_batch_size=250) for _ in range(4)))
    assert await _count(container) == 3000
    assert sum(r.inserted for r in reports) == 3000  # every row inserted by exactly one importer
    assert sum(r.duplicates_identical for r in reports) == 3 * 3000


async def test_bom_crlf_and_blank_lines_are_handled(container):
    data = "\ufeff" + HEADER.replace("\n", "\r\n") + "EP-1,arm-01,pick cup,2026-08-01T00:00:00,30,Eric,good\r\n\r\n   \r\n"
    r = await _import(container, data)
    assert (r.inserted, r.blank_lines_skipped, r.rejected) == (1, 2, 0)


async def test_empty_file_and_bad_header_are_400s(container):
    with pytest.raises(InvalidImportFile):
        await _import(container, "")
    with pytest.raises(InvalidImportFile):
        await _import(container, "a,b,c\n1,2,3\n")


async def test_reimport_of_a_corrected_file_adds_only_the_fixed_rows(container):
    """The intended workflow: quarantine -> fix source -> re-run. Only the fixed row is new."""
    bad = HEADER + "EP-1,arm-01,pick cup,2026-08-01T00:00:00,30,Eric,excellent\nEP-2,arm-01,pick cup,2026-08-01T00:00:00,30,Eric,good\n"
    fixed = bad.replace("excellent", "good")
    r1 = await _import(container, bad)
    assert (r1.inserted, r1.rejected) == (1, 1)
    r2 = await _import(container, fixed)
    assert (r2.inserted, r2.duplicates_identical, r2.rejected) == (1, 1, 0)


# ================================================================ through HTTP
async def test_import_endpoint_returns_full_report(client, world):
    r = await client.post("/episodes/import", headers=world.headers("admin"), files={"file": ("episodes.csv", SEED_CSV.encode(), "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inserted"] == 172 and body["rejected"] == 13
    assert body["rejected_samples"][0].keys() == {"line", "reason", "detail", "raw"}
    assert body["normalizations"]["date_format_normalized"] == 3
    # the catalogue cache is invalidated by an import
    tasks = (await client.get("/catalog/tasks", headers=world.headers("client_a"))).json()
    assert {t["task_name"] for t in tasks} >= {"pick cup", "pick cup, then place"}


async def test_import_endpoint_rejects_non_csv_and_bad_header(client, world):
    h = world.headers("admin")
    assert (await client.post("/episodes/import", headers=h, files={"file": ("x.pdf", b"%PDF", "application/pdf")})).status_code == 400
    r = await client.post("/episodes/import", headers=h, files={"file": ("e.csv", b"foo,bar\n1,2\n", "text/csv")})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_import_file"


async def test_non_utf8_bytes_become_row_rejections_not_a_crash(client, world):
    body = HEADER.encode() + b"EP-1,arm-01,pick \xff\xfe cup,2026-08-01T00:00:00,30,Eric,good\nEP-2,arm-01,pick cup,2026-08-01T00:00:00,30,Eric,good\n"
    r = await client.post("/episodes/import", headers=world.headers("admin"), files={"file": ("e.csv", body, "text/csv")})
    assert r.status_code == 200
    assert r.json()["inserted"] == 1 and r.json()["rejected_by_reason"] == {"invalid_encoding": 1}
