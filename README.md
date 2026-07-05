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

## Possible extensions

- Schedule the Airflow DAG on a server or swap in GitHub Actions for a
  lightweight serverless alternative.
- Add green taxi / HVFHV (Uber & Lyft) sources.
- Deploy to Streamlit Community Cloud with a small aggregated `.duckdb`
  file committed to the repo.
