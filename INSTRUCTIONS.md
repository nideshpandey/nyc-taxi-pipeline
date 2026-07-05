# INSTRUCTIONS — Running the NYC Taxi Pipeline

Follow these steps in order the first time. After setup, day-to-day use is
just steps 4 → 5 → 6 → 7.

---

## 0. Prerequisites

- Python 3.10 or newer (`python --version`)
- ~5–10 GB free disk space (12 months of yellow taxi data)
- Internet connection (only needed for steps 3 and 4)
- Recommended: [uv](https://docs.astral.sh/uv/), a fast Python package
  and environment manager. Install it once with:

  ```bash
  # macOS / Linux
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # Windows (PowerShell)
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

  (uv can even install Python for you if it's missing: `uv python install 3.12`)

---

## 1. One-time setup

From the project root (`nyc-taxi-pipeline/`), pick ONE option:

### Option A — uv (recommended)

```bash
uv venv                              # creates .venv/
uv pip install -r requirements.txt  # installs deps (seconds, not minutes)
```

With uv you never need to activate the venv: prefix commands with
`uv run` (e.g. `uv run python ingestion/ingest.py`) and it automatically
uses the project environment. All commands below are shown in this style.

#### Optional upgrade: generate a pyproject.toml

The repo intentionally ships only `requirements.txt`. If you want the
modern project layout (single-command setup, lockfile, reproducible
builds), generate it yourself in two commands:

```bash
uv init --bare --name nyc-taxi-pipeline   # creates a minimal pyproject.toml
uv add -r requirements.txt                # moves deps into it + creates uv.lock
```

This writes the dependencies from `requirements.txt` into
`pyproject.toml` and pins exact versions of everything (including
transitive dependencies) in `uv.lock`. From then on:

- setup on any machine is just `uv sync`
- commit both `pyproject.toml` and `uv.lock` — the lockfile is what
  makes builds byte-for-byte reproducible, a nice detail to mention
  in the README
- you can then delete `requirements.txt`, or keep it in sync for
  pip users with: `uv export --format requirements-txt > requirements.txt`

### Option B — classic venv + pip

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

If you use this option, activate the venv in every new terminal and drop
the `uv run` prefix from all commands below.

### Verify the install

```bash
uv run python -c "import duckdb, streamlit, requests; print('ok')"
uv run dbt --version
```

---

## 2. Configure the date range (optional)

Open `ingestion/ingest.py` and edit:

```python
START = date(2025, 6, 1)   # first month to download
```

The end month is discovered automatically (latest published month, since
TLC publishes ~2 months behind today's date). For a faster first test run,
set START to just 1–2 months back.

---

## 3. Download the taxi zone lookup (one time)

This small CSV maps zone IDs to borough/neighborhood names. It lives in
dbt's `seeds/` folder:

```bash
curl -o dbt/nyc_taxi/seeds/taxi_zone_lookup.csv \
  https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv
```

(If you don't have curl, just open the URL in a browser and save the file
to `dbt/nyc_taxi/seeds/taxi_zone_lookup.csv`.)

---

## 4. Download trip data

```bash
uv run python ingestion/ingest.py
```

What it does:
- Downloads one parquet file per month into `data/raw/`
- Records each completed download in `data/raw/_manifest.json`
- **Safe to re-run anytime** — already-downloaded months are skipped,
  newly published months are picked up automatically
- If a month isn't published yet (HTTP 403), it logs a warning and stops

Each monthly file is roughly 50–60 MB, so expect a few minutes for a
full year on a normal connection.

---

## 5. Load into DuckDB

```bash
uv run python ingestion/load.py
```

What it does:
- Creates `data/warehouse/nyc_taxi.duckdb` if it doesn't exist
- Compares `data/raw/` against the `meta.loaded_files` table and appends
  **only new files** into `raw.yellow_trips`
- Tags every row with its `source_file` for lineage
- Re-running with no new files prints "nothing to load" and exits

To force a reload of one month (e.g. TLC revised the file):

```bash
uv run python - <<'EOF'
import duckdb
con = duckdb.connect("data/warehouse/nyc_taxi.duckdb")
f = "yellow_tripdata_2025-06.parquet"
con.execute("DELETE FROM raw.yellow_trips WHERE source_file = ?", [f])
con.execute("DELETE FROM meta.loaded_files WHERE file_name = ?", [f])
EOF
# then delete the file from data/raw/, remove its entry from
# data/raw/_manifest.json, and re-run steps 4 and 5
```

---

## 6. Run dbt transformations

Run these from the project root (no need to cd):

```bash
uv run dbt seed --project-dir dbt/nyc_taxi --profiles-dir dbt/nyc_taxi   # zone lookup (first time only)
uv run dbt run  --project-dir dbt/nyc_taxi --profiles-dir dbt/nyc_taxi   # builds staging + marts
uv run dbt test --project-dir dbt/nyc_taxi --profiles-dir dbt/nyc_taxi   # data quality tests
```

Notes:
- `--project-dir` points dbt at the dbt project; `--profiles-dir` points
  it at our local `profiles.yml` instead of `~/.dbt/`. Running from the
  root also keeps `uv run` working (it finds `.venv/` in the current
  directory).
- Without a pyproject.toml, run `uv run` from the project root where
  `.venv/` lives. (If you did the optional pyproject.toml upgrade in
  step 1, `uv run` works from any subdirectory.)
- `dbt run` is incremental: on repeat runs it only processes rows from
  source files not yet in the staging model
- To rebuild everything from scratch: `uv run dbt run --full-refresh --project-dir dbt/nyc_taxi --profiles-dir dbt/nyc_taxi`

Check which schemas were created (needed for step 7):

```bash
uv run python -c "import duckdb; print(duckdb.connect('data/warehouse/nyc_taxi.duckdb').execute('SHOW ALL TABLES').fetchdf())"
```

If the mart tables are NOT in a schema called `main_marts` (dbt-duckdb
prefixes schema names by default), update the schema name in the three
queries inside `dashboard/app.py` to match what you see.

---

## 7. Launch the dashboard

```bash
uv run streamlit run dashboard/app.py
```

Opens at http://localhost:8501. The app reads only the small mart tables,
so it stays fast regardless of how many months you've loaded.

**Important:** close any other process holding the DuckDB file (e.g. a
dbt run or a Python shell) before starting Streamlit — DuckDB allows only
one writer, and the app opens the file read-only but can't while a write
lock is held.

---

## 8. Monthly refresh (the incremental story)

When TLC publishes a new month, the entire update is:

```bash
uv run python ingestion/ingest.py          # fetches only the new month
uv run python ingestion/load.py            # loads only the new file
uv run dbt run  --project-dir dbt/nyc_taxi --profiles-dir dbt/nyc_taxi
uv run dbt test --project-dir dbt/nyc_taxi --profiles-dir dbt/nyc_taxi
```

Then refresh the dashboard in your browser. Only the new partition is
processed at every layer.

---

## 9. Orchestration with Airflow (optional)

The DAG at `orchestration/dags/nyc_taxi_dag.py` runs the whole pipeline
monthly: `ingest → load → dbt seed → dbt run → dbt test → dbt docs`.

**Important:** Airflow gets its OWN environment — it pins many packages
and will conflict with the project env.

```bash
# 1. Separate env for Airflow (from the project root)
uv venv .venv-airflow
VIRTUAL_ENV=.venv-airflow uv pip install -r orchestration/requirements-airflow.txt

# 2. Launch (sets AIRFLOW_HOME + dags_folder itself — nothing to export)
./orchestration/start_airflow.sh
```

The script points Airflow's home at `.airflow/` inside the repo and its
DAG folder at `orchestration/dags/`, then runs `airflow standalone`
(webserver + scheduler + auto-created user). Those two settings
configure the Airflow *process* and must exist before it starts, which
is why they can't live inside the DAG file — the script is what makes
them one-command instead of per-terminal exports.

Open http://localhost:8080 (credentials are printed in the terminal),
find the `nyc_taxi_pipeline` DAG, unpause it, and hit ▶ to trigger a run.

How the DAG finds the project: the file derives the project root from
its own location (`orchestration/dags/` → two levels up), so as long as
the DAG file lives inside the repo, zero configuration is needed. Keep
the file in place — if you ever deploy by *copying* it into a shared
Airflow dags folder, it loses that anchor; prefer a symlink (which
resolves back to the repo), or reintroduce a configurable path then.

Notes:
- Tasks call the exact same commands as the manual steps above, via
  `uv run`, so the project env is still what executes the pipeline.
- Because every layer is idempotent/incremental, retries and manual
  re-runs are always safe — that's the property that makes these
  scripts "orchestration-ready".
- The DAG is scheduled `@monthly` with `catchup=False`; adjust in the
  DAG file if you want a different cadence.
- Add `.venv-airflow/` and `.airflow/` to .gitignore if you commit from
  this machine (already done in this repo).

---

## 10. dbt documentation site

Every source, seed, model and column is documented in the `_schema.yml`
and `_sources.yml` files. dbt can render this into a browsable website
with a clickable lineage graph:

```bash
uv run dbt docs generate --project-dir dbt/nyc_taxi --profiles-dir dbt/nyc_taxi
uv run dbt docs serve    --project-dir dbt/nyc_taxi --profiles-dir dbt/nyc_taxi --port 8081
```

Open http://localhost:8081. Click any model to see its description,
columns, tests and compiled SQL; the graph button (bottom right) shows
the full DAG: raw source → staging → marts, with the seed joining in.

The generated site lives in `dbt/nyc_taxi/target/` (gitignored). The
Airflow DAG regenerates it on every run, so docs never drift from code.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `uv: command not found` | Install uv (step 0) and restart the terminal, or use Option B (pip) |
| `403` on download | That month isn't published yet — normal, wait for TLC |
| `IO Error: database is locked` | Another process has the .duckdb file open — close it |
| dbt: `Profile nyc_taxi not found` | You forgot the `--profiles-dir dbt/nyc_taxi` flag |
| Streamlit: table not found | Schema name mismatch — see the check in step 6 |
| Download interrupted mid-file | Just re-run `ingest.py`; partial `.part` files are ignored |
| Want to start over completely | Delete `data/raw/*` and `data/warehouse/*`, re-run steps 4–6 |
