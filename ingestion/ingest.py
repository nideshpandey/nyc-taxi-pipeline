"""
Idempotent downloader for NYC TLC yellow taxi trip data.

Incremental design:
- One parquet file per (service, year-month) partition.
- A manifest (data/raw/_manifest.json) records every file already
  downloaded, with size + timestamp. Re-runs skip completed partitions.
- New months are picked up automatically: the script computes the list
  of expected months between START and the latest published month
  (TLC publishes with a ~2 month lag) and downloads only what's missing.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date
from pathlib import Path

import requests

BASE_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data"
SERVICE = "yellow_tripdata"
START = date(2025, 6, 1)          # first month to ingest (adjust freely)
PUBLISH_LAG_MONTHS = 2            # TLC publishes ~2 months behind

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
MANIFEST_PATH = RAW_DIR / "_manifest.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ingest")


def month_range(start: date, end: date) -> list[str]:
    """Yield YYYY-MM strings from start to end inclusive."""
    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return months


def latest_published_month(today: date, lag: int) -> date:
    y, m = today.year, today.month - lag
    while m < 1:
        y, m = y - 1, m + 12
    return date(y, m, 1)


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text())
    return {}


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def download_month(month: str, manifest: dict) -> bool:
    """Download one monthly partition. Returns True if a new file was fetched."""
    filename = f"{SERVICE}_{month}.parquet"
    url = f"{BASE_URL}/{filename}"
    dest = RAW_DIR / filename

    if manifest.get(filename) and dest.exists():
        log.info("skip %s (already in manifest)", filename)
        return False

    log.info("downloading %s", url)
    resp = requests.get(url, stream=True, timeout=120)
    if resp.status_code == 403:
        # TLC returns 403 for months not yet published
        log.warning("%s not published yet, stopping here", month)
        return False
    resp.raise_for_status()

    tmp = dest.with_suffix(".parquet.part")
    with open(tmp, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    tmp.rename(dest)  # atomic-ish: no half-written files in raw/

    manifest[filename] = {
        "bytes": dest.stat().st_size,
        "downloaded_at": date.today().isoformat(),
        "url": url,
    }
    save_manifest(manifest)
    log.info("done %s (%.1f MB)", filename, dest.stat().st_size / 1e6)
    return True


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    end = latest_published_month(date.today(), PUBLISH_LAG_MONTHS)
    months = month_range(START, end)
    log.info("expected partitions: %s .. %s (%d months)", months[0], months[-1], len(months))

    new_files = sum(download_month(m, manifest) for m in months)
    log.info("finished: %d new file(s), %d total in manifest", new_files, len(manifest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
