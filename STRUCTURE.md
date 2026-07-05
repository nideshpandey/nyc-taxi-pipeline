# Project Structure Documentation

NYC Yellow Taxi Analytics Pipeline — what every folder and file does.

```
nyc-taxi-pipeline/
├── README.md
├── INSTRUCTIONS.md
├── STRUCTURE.md
├── requirements.txt
├── .gitignore
├── ingestion/
│   ├── ingest.py
│   └── load.py
├── orchestration/
│   ├── dags/
│   │   └── nyc_taxi_dag.py
│   └── requirements-airflow.txt
├── dbt/nyc_taxi/
│   ├── dbt_project.yml
│   ├── profiles.yml
│   ├── seeds/
│   │   ├── _schema.yml
│   │   └── taxi_zone_lookup.csv
│   └── models/
│       ├── staging/
│       │   ├── _sources.yml
│       │   ├── _schema.yml
│       │   └── stg_yellow_trips.sql
│       └── marts/
│           ├── _schema.yml
│           ├── fct_trip_summary.sql
│           └── fct_zone_metrics.sql
├── dashboard/
│   └── app.py
└── data/
    ├── raw/
    └── warehouse/
```

---

## Root files

| File | Purpose |
|---|---|
| `README.md` | The "why": architecture diagram, stack choices, incremental loading design, cleaning rules, possible extensions. Aimed at reviewers. |
| `INSTRUCTIONS.md` | The "how": step-by-step runbook — setup (uv or pip), download, load, transform, dashboard, monthly refresh, troubleshooting. Aimed at anyone running the project. |
| `STRUCTURE.md` | This file — a map of every folder and file. |
| `requirements.txt` | Python dependencies (duckdb, dbt-core, dbt-duckdb, requests, streamlit, pandas, altair). |
| `.gitignore` | Keeps large/generated files out of git: raw parquet, the .duckdb warehouse, `.venv/`, dbt's `target/`. |

---

## `ingestion/` — Extract & Load (Python)

| File | Purpose |
|---|---|
| `ingest.py` | Downloads monthly yellow-taxi parquet files from the TLC into `data/raw/`. Idempotent: a JSON manifest tracks completed months, re-runs skip them and pick up newly published months automatically. Partial downloads are written to `.part` files and renamed on success. |
| `load.py` | Loads raw parquet files into DuckDB (`raw.yellow_trips`). Incremental: a `meta.loaded_files` table records what's already loaded, so only new files are appended. Every row is tagged with its `source_file` for lineage and clean reloads. |

---

## `orchestration/` — Scheduling (Airflow)

| File | Purpose |
|---|---|
| `dags/nyc_taxi_dag.py` | Airflow DAG running the whole pipeline monthly: ingest → load → dbt seed → run → test → docs generate. Point Airflow's dags_folder at orchestration/dags/; the DAG auto-detects the project root from its own location. |
| `requirements-airflow.txt` | Dependencies for the separate Airflow environment (Airflow must not share the project venv). |
| `start_airflow.sh` | One-command launcher: sets AIRFLOW_HOME and dags_folder relative to the repo, then runs `airflow standalone`. |

---

## `dbt/nyc_taxi/` — Transform (dbt)

| File | Purpose |
|---|---|
| `dbt_project.yml` | Project settings: name, folder paths, default materializations (staging = incremental, marts = table). |
| `profiles.yml` | Connection config: points dbt at the local DuckDB file. Used via the `--profiles-dir` flag. |

### `seeds/`

| File | Purpose |
|---|---|
| `_schema.yml` | Seed documentation and tests (unique, not-null LocationID) — rendered in the dbt docs site. |
| `taxi_zone_lookup.csv` | 265-row crosswalk mapping TLC zone IDs to borough and neighborhood names. Loaded into the warehouse with `dbt seed`. Downloaded once (see INSTRUCTIONS step 3) — not shipped in the repo. |

### `models/staging/` — cleaning layer

| File | Purpose |
|---|---|
| `_sources.yml` | Declares the raw table (`raw.yellow_trips`) that Python created, so models can reference it with `source()`. |
| `_schema.yml` | Staging model documentation (every column described for dbt docs) and data quality tests: `trip_id` unique + not null, valid payment codes. Run with `dbt test`. |
| `stg_yellow_trips.sql` | The cleaning model: renames columns, casts types, computes `duration_min` / `pickup_date` / `trip_id`, filters garbage rows (negative fares, impossible distances, dropoff before pickup). Incremental — only processes rows from unseen source files. |

### `models/marts/` — presentation layer

| File | Purpose |
|---|---|
| `_schema.yml` | Mart documentation (model + column descriptions) and tests (non-null dates, valid payment labels). |
| `fct_trip_summary.sql` | Filterable summary cube: one row per (date, hour, weekday, borough, payment type) with sums/counts, so the dashboard can slice by any filter and recompute weighted averages. Incremental with a 7-day rebuild window. |
| `fct_zone_metrics.sql` | Zone-level mart at (date, zone) grain: pickups and revenue per neighborhood, joined to the zone lookup for names. Rebuilt fully each run (tiny table). |

---

## `dashboard/` — Serve (Streamlit)

| File | Purpose |
|---|---|
| `app.py` | The dashboard. Sidebar filters (date range, borough, payment type, pickup hour), six KPI cards, and Altair charts: daily trend with metric toggle, payment-type donut, hour×weekday demand heatmap, top pickup zones. Reads only the two mart tables, so it stays fast at any data volume. |

---

## `data/` — local storage (gitignored)

| Folder | Purpose |
|---|---|
| `raw/` | Downloaded monthly parquet files plus `_manifest.json` (the ingestion ledger). |
| `warehouse/` | `nyc_taxi.duckdb` — the single-file warehouse holding raw, staging, mart, and metadata tables. |

---

## How the pieces connect

```
ingest.py → data/raw/ → load.py → DuckDB raw schema
    → dbt staging (clean) → dbt marts (aggregate) → app.py (visualize)
```

Each layer reads only from the layer before it and never modifies
upstream data. Incrementality is tracked independently at the file level
(manifest), the load level (meta table), and the model level (dbt
incremental configs).
