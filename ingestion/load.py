"""
Incremental loader: raw parquet -> DuckDB.

Incremental design:
- A metadata table (meta.loaded_files) records every raw file already
  loaded into the warehouse.
- Each run diffs raw/ against that table and loads ONLY new partitions,
  appending into raw.yellow_trips.
- Reloading a revised month: delete its row from meta.loaded_files and
  its rows from raw.yellow_trips (filter on source_file), then re-run.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "warehouse" / "nyc_taxi.duckdb"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("load")


def main() -> None:
    con = duckdb.connect(str(DB_PATH))
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")
    con.execute("CREATE SCHEMA IF NOT EXISTS meta")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS meta.loaded_files (
            file_name   VARCHAR PRIMARY KEY,
            row_count   BIGINT,
            loaded_at   TIMESTAMP DEFAULT current_timestamp
        )
        """
    )

    already = {r[0] for r in con.execute("SELECT file_name FROM meta.loaded_files").fetchall()}
    candidates = sorted(p for p in RAW_DIR.glob("yellow_tripdata_*.parquet"))
    new_files = [p for p in candidates if p.name not in already]

    if not new_files:
        log.info("nothing to load — warehouse is up to date")
        return

    for path in new_files:
        log.info("loading %s", path.name)
        # source_file column = lineage + the delete-key for reloads
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS raw.yellow_trips AS
            SELECT *, ? AS source_file
            FROM read_parquet(?) LIMIT 0
            """,
            [path.name, str(path)],
        )
        con.execute(
            """
            INSERT INTO raw.yellow_trips
            SELECT *, ? AS source_file FROM read_parquet(?)
            """,
            [path.name, str(path)],
        )
        n = con.execute(
            "SELECT count(*) FROM raw.yellow_trips WHERE source_file = ?", [path.name]
        ).fetchone()[0]
        con.execute(
            "INSERT INTO meta.loaded_files (file_name, row_count) VALUES (?, ?)",
            [path.name, n],
        )
        log.info("loaded %s rows from %s", f"{n:,}", path.name)

    total = con.execute("SELECT count(*) FROM raw.yellow_trips").fetchone()[0]
    log.info("raw.yellow_trips now has %s rows", f"{total:,}")


if __name__ == "__main__":
    main()
