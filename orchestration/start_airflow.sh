#!/usr/bin/env bash
# Start a project-local Airflow that watches this repo's DAG folder.
# Usage:  ./orchestration/start_airflow.sh
#
# Why a script: AIRFLOW_HOME and dags_folder configure the Airflow
# process itself and must be set BEFORE it starts — they can't live
# inside a DAG file (Airflow reads them before parsing any DAGs).
# This script derives them from its own location, so no exports needed.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export AIRFLOW_HOME="$REPO_ROOT/.airflow"
export AIRFLOW__CORE__DAGS_FOLDER="$REPO_ROOT/orchestration/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES="False"   # hide Airflow's demo DAGs

AIRFLOW_BIN="$REPO_ROOT/.venv-airflow/bin/airflow"
if [[ ! -x "$AIRFLOW_BIN" ]]; then
    echo "Airflow env not found. Create it first:"
    echo "  uv venv .venv-airflow"
    echo "  VIRTUAL_ENV=.venv-airflow uv pip install -r orchestration/requirements-airflow.txt"
    exit 1
fi

echo "AIRFLOW_HOME = $AIRFLOW_HOME"
echo "dags_folder  = $AIRFLOW__CORE__DAGS_FOLDER"
exec "$AIRFLOW_BIN" standalone
