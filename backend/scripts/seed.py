"""Idempotent seed: users from users.json (passwords hashed with Argon2id) + episodes.csv import.

    python -m scripts.seed            # uses SEED_DIR (default: /seed in Docker, ../seed locally)

Safe to run on every container start: users use ON CONFLICT DO NOTHING on email and the episode
import is itself idempotent. Plain-text passwords from users.json are never stored.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from sqlalchemy import text

from app.composition import build_container
from app.core.config import get_settings
from app.infrastructure.security.passwords import hash_password

log = logging.getLogger("seed")


def _seed_dir() -> Path:
    for candidate in (os.environ.get("SEED_DIR"), "/seed", str(Path(__file__).resolve().parents[2] / "seed")):
        if candidate and (Path(candidate) / "users.json").exists():
            return Path(candidate)
    sys.exit("Seed directory not found (set SEED_DIR).")


async def _wait_for_db(container, attempts: int = 30) -> None:
    for i in range(1, attempts + 1):
        try:
            async with container.session_factory() as s:
                await s.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001
            log.info("waiting for database (%d/%d): %s", i, attempts, type(exc).__name__)
            await asyncio.sleep(1)
    sys.exit("Database never became available.")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    seed_dir = _seed_dir()
    container = build_container(get_settings())
    try:
        await _wait_for_db(container)

        users = json.loads((seed_dir / "users.json").read_text(encoding="utf-8"))
        rows = [
            {
                "email": u["email"].strip().lower(),
                "name": u["name"],
                "role": u["role"],
                "organisation": u.get("organisation"),
                # Argon2 is CPU-heavy: keep it off the event loop
                "hashed_password": await asyncio.to_thread(hash_password, u["password"]),
            }
            for u in users
        ]
        async with container.uow() as uow:
            created = await uow.users.insert_ignore(rows)
            await uow.commit()
        log.info("users: %d created, %d already present", created, len(rows) - created)

        csv_path = seed_dir / "episodes.csv"
        if csv_path.exists():
            with csv_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
                report = await container.imports.import_csv(fh, csv_path.name)
            log.info(
                "episodes: read=%d inserted=%d dup_identical=%d dup_conflicting=%d rejected=%d %s",
                report.rows_read, report.inserted, report.duplicates_identical,
                report.duplicates_conflicting, report.rejected, report.rejected_by_reason,
            )
    finally:
        await container.engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
