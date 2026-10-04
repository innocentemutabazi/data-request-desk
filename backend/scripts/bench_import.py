"""Throughput check for the streaming import:  python -m scripts.bench_import path/to/big.csv"""

from __future__ import annotations

import asyncio
import resource
import sys
import time

from app.composition import build_container
from app.core.config import get_settings


async def main(path: str) -> None:
    container = build_container(get_settings())
    try:
        t0 = time.perf_counter()
        with open(path, encoding="utf-8-sig", newline="") as fh:
            report = await container.imports.import_csv(fh, path)
        dt = time.perf_counter() - t0
        rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        print(f"read={report.rows_read:,} inserted={report.inserted:,} dup={report.duplicates_identical:,} "
              f"rejected={report.rejected:,} | {dt:.1f}s = {report.rows_read / dt:,.0f} rows/s | peak RSS {rss_mb:.0f} MB")
    finally:
        await container.engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
