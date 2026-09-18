"""
Manual full-refresh pipeline: extract all 36 states → Snowflake → dbt full-refresh.

Schedule: None (trigger manually from Airflow UI or CLI).
Use when: re-extracting everything from scratch, or after a schema change.
dbt runs with --full-refresh to drop and recreate all incremental models.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

PROJECT_DIR = "/home/ubuntu/udhyam_msme_extractor"
VENV = f"{PROJECT_DIR}/.venv/bin/activate"

default_args = {
    "owner": "udyam",
    "retries": 0,
    "email_on_failure": False,
}

with DAG(
    dag_id="udyam_full_refresh_pipeline",
    default_args=default_args,
    description="Manual full-refresh: extract all states → Snowflake → dbt full-refresh",
    schedule_interval=None,
    start_date=datetime(2026, 9, 21),
    catchup=False,
    tags=["udyam", "msme", "full-refresh"],
) as dag:

    extract = BashOperator(
        task_id="extract",
        bash_command=(
            f"source {VENV} && "
            f"cd {PROJECT_DIR} && "
            "python3 run_udyam.py"
        ),
        execution_timeout=timedelta(hours=12),
    )

    load = BashOperator(
        task_id="load_to_snowflake",
        bash_command=(
            f"source {VENV} && "
            f"cd {PROJECT_DIR} && "
            "python3 scripts/load_to_snowflake.py"
        ),
        execution_timeout=timedelta(hours=6),
    )

    transform = BashOperator(
        task_id="dbt_full_refresh",
        bash_command=(
            f"source {VENV} && "
            f"cd {PROJECT_DIR}/udyam_dbt && "
            "dbt run --full-refresh"
        ),
        execution_timeout=timedelta(hours=4),
    )

    extract >> load >> transform
