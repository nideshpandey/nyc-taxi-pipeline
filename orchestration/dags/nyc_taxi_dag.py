"""
Airflow DAG for the NYC Taxi pipeline.

Monthly schedule (TLC publishes monthly, ~2 months behind). Every task is
a thin wrapper around the same commands you run by hand — the scripts are
idempotent, so retries and re-runs are always safe.

    ingest -> load -> dbt_seed -> dbt_run -> dbt_test -> dbt_docs

Setup (see INSTRUCTIONS.md section 9): run ./orchestration/start_airflow.sh,
which points Airflow's dags_folder at this repo. The DAG derives the
project root from its own file location — no configuration needed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

try:  # Airflow 3.x
    from airflow.providers.standard.operators.bash import BashOperator
except ImportError:  # Airflow 2.x
    from airflow.operators.bash import BashOperator

from airflow import DAG

# Project root derived from this file's location: orchestration/dags/ -> root.
# Requires the DAG file to stay inside the repo (dags_folder points here).
PROJECT_DIR = str(Path(__file__).resolve().parents[2])
DBT = "uv run dbt {cmd} --project-dir dbt/nyc_taxi --profiles-dir dbt/nyc_taxi"

default_args = {
    "owner": "data-eng",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
}

with DAG(
    dag_id="nyc_taxi_pipeline",
    description="TLC yellow taxi: ingest -> DuckDB -> dbt -> docs",
    schedule="@monthly",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["nyc-taxi", "duckdb", "dbt"],
) as dag:

    ingest = BashOperator(
        task_id="ingest_raw_files",
        bash_command="uv run python ingestion/ingest.py",
        cwd=PROJECT_DIR,
    )

    load = BashOperator(
        task_id="load_to_duckdb",
        bash_command="uv run python ingestion/load.py",
        cwd=PROJECT_DIR,
    )

    dbt_seed = BashOperator(
        task_id="dbt_seed",
        bash_command=DBT.format(cmd="seed"),
        cwd=PROJECT_DIR,
    )

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=DBT.format(cmd="run"),
        cwd=PROJECT_DIR,
    )

    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=DBT.format(cmd="test"),
        cwd=PROJECT_DIR,
    )

    dbt_docs = BashOperator(
        task_id="dbt_docs_generate",
        bash_command=DBT.format(cmd="docs generate"),
        cwd=PROJECT_DIR,
    )

    ingest >> load >> dbt_seed >> dbt_run >> dbt_test >> dbt_docs
