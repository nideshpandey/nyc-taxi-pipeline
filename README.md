# NYC Yellow Taxi Analytics Pipeline

End-to-end, fully local, fully free data pipeline on the NYC TLC trip record
dataset: **Python ingestion → DuckDB warehouse → dbt transformations →
Streamlit dashboard**, with incremental loading at every layer.

## Architecture

```
TLC CloudFront (parquet, monthly)
        │  ingestion/ingest.py      idempotent download, manifest-tracked
        ▼
data/raw/*.parquet
        │  ingestion/load.py        loads ONLY new files (meta.loaded_files)
        ▼
DuckDB  raw.yellow_trips
        │  dbt (duckdb adapter)     incremental staging + marts, tests
        ▼
DuckDB  marts: fct_trip_summary, fct_zone_metrics
        │
        ▼
Streamlit dashboard (reads marts only)
```

**Orchestration:** an Airflow DAG (`orchestration/dags/nyc_taxi_dag.py`)
runs the full chain monthly: ingest → load → dbt seed/run/test → docs
generate. Setup in INSTRUCTIONS.md section 9.

**Documentation:** every source, seed, model and column is described in
dbt yml files; `dbt docs generate && dbt docs serve` renders a browsable
site with a lineage graph (INSTRUCTIONS.md section 10).

## Incremental loading design

Incrementality is enforced at three independent layers, so any layer can be
re-run safely and cheaply:

1. **Ingestion (file level).** `ingest.py` keeps a JSON manifest of
   downloaded partitions. Re-runs skip existing months and automatically
   pick up newly published months (TLC publishes ~2 months behind).
   Downloads write to a `.part` temp file and rename on success, so a
   killed run never leaves a corrupt partition.
2. **Warehouse load (partition level).** `load.py` diffs `data/raw/`
   against the `meta.loaded_files` table and appends only unseen files,
   tagging every row with `source_file` for lineage. To reprocess a
   revised month, delete its rows by `source_file` and its manifest row.
3. **dbt (model level).** `stg_yellow_trips` is an incremental model that
   processes only rows from source files not yet present in the model.
   `fct_trip_summary` uses `delete+insert` on `pickup_date` with a 7-day
   lookback window to handle late-arriving or revised data.

## Tested scale & disk space

This pipeline has been tested end-to-end with 12 months of yellow taxi
data (~40M rows). Note on disk usage: the staging build is a heavy
operation — deduplicating on the hashed `trip_id` across the full
dataset — and on a full refresh DuckDB may spill intermediate state to
a temporary directory (`nyc_taxi.duckdb.tmp`). Plan for roughly **10 GB
of free disk** during a full rebuild; the space is released
automatically when the run completes. Routine incremental runs process
one month at a time and stay far below this.

## Quickstart

Recommended setup uses [uv](https://docs.astral.sh/uv/) (fast Python
package manager). Full setup options — including generating a
`pyproject.toml` yourself — are in INSTRUCTIONS.md.

```bash
# 0. Environment
uv venv
uv pip install -r requirements.txt

# 1. Download raw data (idempotent, re-run anytime)
uv run python ingestion/ingest.py

# 2. Load new files into DuckDB
uv run python ingestion/load.py

# 3. Get the zone lookup seed (once)
curl -o dbt/nyc_taxi/seeds/taxi_zone_lookup.csv \
  https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv

# 4. Transform + test (run from project root)
uv run dbt seed --project-dir dbt/nyc_taxi --profiles-dir dbt/nyc_taxi
uv run dbt run  --project-dir dbt/nyc_taxi --profiles-dir dbt/nyc_taxi
uv run dbt test --project-dir dbt/nyc_taxi --profiles-dir dbt/nyc_taxi

# 5. Dashboard
uv run streamlit run dashboard/app.py
```

Running steps 1–4 again after a new month is published loads **only** the
new partition end-to-end — that's the incremental story.

## Data cleaning rules (staging)

Trips are excluded when: dropoff ≤ pickup, distance ≤ 0 or ≥ 200 mi,
total_amount ≤ 0 or ≥ $1,000, passenger_count outside 1–8. Rules are
documented in `stg_yellow_trips.sql`.

## Design note: the zone crosswalk is treated as static

The taxi zone lookup is fetched once (the DAG's `fetch_zone_lookup`
task skips the download if the file already exists) and never
refreshed. This is a deliberate stability-vs-freshness trade-off: the
265-zone crosswalk is a quasi-static dimension, unchanged in practice
since 2016, and never re-downloading keeps builds reproducible with no
extra external failure mode per run. If the source did change, impact
is contained — marts use a LEFT JOIN with `coalesce(..., 'Unknown')`,
so unmatched zone IDs surface visibly as "Unknown" rather than
dropping rows. For a faster-changing dimension I would refresh via
HTTP conditional GET (`curl -z`, re-download only if modified) or
track history with dbt snapshots (slowly changing dimensions, type 2).

## Possible extensions

- Schedule the Airflow DAG on a server or swap in GitHub Actions for a
  lightweight serverless alternative.
- Add green taxi / HVFHV (Uber & Lyft) sources.
- Deploy to Streamlit Community Cloud with a small aggregated `.duckdb`
  file committed to the repo.